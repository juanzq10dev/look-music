"""Turn live MIDI events into a Song or a MIDI file."""

from __future__ import annotations

from pathlib import Path

import mido

from look_music.live.events import NOTE_OFF, NOTE_ON, SUSTAIN, MidiEvent
from look_music.midi import SUSTAIN_CC, SUSTAIN_THRESHOLD, Note, Song

TICKS_PER_BEAT = 480
TEMPO_US = 500_000  # 120 BPM -> 1 tick = 1/960 s
_TICKS_PER_SECOND = TICKS_PER_BEAT * 1_000_000 / TEMPO_US
_MIN_DURATION = 0.05

_Raw = tuple[float, float, int, int]  # start, end, pitch, velocity


def _pair_notes(events: list[MidiEvent], end_time: float | None) -> list[_Raw]:
    """Pair note_on/note_off events into (start, end, pitch, velocity) tuples."""
    open_notes: dict[int, tuple[float, int]] = {}
    notes: list[_Raw] = []
    last = 0.0
    for ev in sorted(events, key=lambda e: e.time):
        last = ev.time
        if ev.kind == NOTE_ON:
            if ev.pitch in open_notes:
                start, vel = open_notes.pop(ev.pitch)
                notes.append((start, ev.time, ev.pitch, vel))
            open_notes[ev.pitch] = (ev.time, ev.velocity)
        elif ev.kind == NOTE_OFF and ev.pitch in open_notes:
            start, vel = open_notes.pop(ev.pitch)
            notes.append((start, ev.time, ev.pitch, vel))
    close = end_time if end_time is not None else last
    for pitch, (start, vel) in open_notes.items():
        notes.append((start, close if close > start else start + _MIN_DURATION, pitch, vel))
    return [n for n in notes if n[1] > n[0]]


def _pedal_intervals(events: list[MidiEvent]) -> list[tuple[float, float]]:
    """Pedal-down intervals as (down, up) pairs in seconds."""
    intervals = []
    down_at = None
    for ev in sorted(events, key=lambda e: e.time):
        if ev.kind != SUSTAIN:
            continue
        if ev.velocity >= SUSTAIN_THRESHOLD and down_at is None:
            down_at = ev.time
        elif ev.velocity < SUSTAIN_THRESHOLD and down_at is not None:
            intervals.append((down_at, ev.time))
            down_at = None
    if down_at is not None:
        intervals.append((down_at, float("inf")))
    return intervals


def events_to_song(events: list[MidiEvent], end_time: float | None = None) -> Song:
    """Pair live events into a Song (same semantics as midi.load_midi)."""
    intervals = _pedal_intervals(events)
    notes = []
    for start, end, pitch, vel in _pair_notes(events, end_time):
        sound_end = end
        for down, up in intervals:
            if down <= end < up:
                sound_end = end if up == float("inf") else up
                break
        notes.append(Note(start, end, sound_end, pitch, vel, 0))
    notes.sort(key=lambda n: (n.start, n.pitch))
    duration = max((n.sound_end for n in notes), default=0.0)
    return Song(notes=tuple(notes), duration=duration)


def save_midi(events: list[MidiEvent], path: str | Path, end_time: float | None = None) -> None:
    """Write a type-0 MIDI file (one track, channel 0) with tempo 120 BPM, 480 PPQ."""
    # (tick, order, message); note_off sorts before pedal before note_on at equal ticks
    timed: list[tuple[int, int, dict]] = []

    def tick(t: float) -> int:
        return round(max(t, 0.0) * _TICKS_PER_SECOND)

    for start, end, pitch, vel in _pair_notes(events, end_time):
        timed.append((tick(start), 2, dict(type="note_on", note=pitch, velocity=vel)))
        timed.append((tick(end), 0, dict(type="note_off", note=pitch, velocity=0)))
    for ev in events:
        if ev.kind == SUSTAIN:
            msg = dict(type="control_change", control=SUSTAIN_CC, value=ev.velocity)
            timed.append((tick(ev.time), 1, msg))
    timed.sort(key=lambda x: (x[0], x[1]))

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="look-music live take", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=TEMPO_US, time=0))
    prev = 0
    for t, _, msg in timed:
        track.append(mido.Message(channel=0, time=t - prev, **msg))
        prev = t
    track.append(mido.MetaMessage("end_of_track", time=0))
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    mid.tracks.append(track)
    mid.save(str(path))
