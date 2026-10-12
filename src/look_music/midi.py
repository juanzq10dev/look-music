"""Load MIDI files into a flat, time-sorted list of notes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pretty_midi

SUSTAIN_CC = 64
SUSTAIN_THRESHOLD = 64


@dataclass(frozen=True)
class Note:
    start: float  # seconds
    end: float  # seconds, key released
    sound_end: float  # seconds, end extended by the sustain pedal
    pitch: int  # MIDI note number
    velocity: int  # 1-127
    track: int  # index of the source instrument


@dataclass(frozen=True)
class Song:
    notes: tuple[Note, ...]
    duration: float  # seconds, last sound_end

    def shifted(self, offset: float) -> Song:
        """Return a copy with every note moved later by `offset` seconds."""
        notes = tuple(
            replace(n, start=n.start + offset, end=n.end + offset, sound_end=n.sound_end + offset)
            for n in self.notes
        )
        return Song(notes=notes, duration=self.duration + offset)


def _sustain_intervals(instrument: pretty_midi.Instrument) -> list[tuple[float, float]]:
    """Pedal-down intervals from CC64 events, as (down, up) pairs in seconds."""
    intervals = []
    down_at = None
    for cc in sorted(instrument.control_changes, key=lambda c: c.time):
        if cc.number != SUSTAIN_CC:
            continue
        if cc.value >= SUSTAIN_THRESHOLD and down_at is None:
            down_at = cc.time
        elif cc.value < SUSTAIN_THRESHOLD and down_at is not None:
            intervals.append((down_at, cc.time))
            down_at = None
    if down_at is not None:
        intervals.append((down_at, float("inf")))
    return intervals


def _sound_end(end: float, intervals: list[tuple[float, float]]) -> float:
    for down, up in intervals:
        if down <= end < up:
            return up
    return end


def load_midi(path: str | Path) -> Song:
    pm = pretty_midi.PrettyMIDI(str(path))
    notes = []
    for track, instrument in enumerate(pm.instruments):
        if instrument.is_drum:
            continue
        intervals = _sustain_intervals(instrument)
        for n in instrument.notes:
            if n.end <= n.start:
                continue
            sound_end = _sound_end(n.end, intervals)
            if sound_end == float("inf"):
                sound_end = n.end
            notes.append(Note(n.start, n.end, sound_end, n.pitch, n.velocity, track))
    notes.sort(key=lambda n: (n.start, n.pitch))
    duration = max((n.sound_end for n in notes), default=0.0)
    return Song(notes=tuple(notes), duration=duration)
