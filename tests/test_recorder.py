from __future__ import annotations

import pytest

from look_music.live.events import MidiEvent
from look_music.live.recorder import events_to_song, save_midi
from look_music.midi import load_midi

TOL = 1 / 960 + 1e-6


def on(t, pitch, vel=80):
    return MidiEvent(t, "note_on", pitch, vel)


def off(t, pitch):
    return MidiEvent(t, "note_off", pitch, 0)


def pedal(t, value):
    return MidiEvent(t, "sustain", 64, value)


def test_simple_pair():
    song = events_to_song([on(1.0, 60, 90), off(2.5, 60)])
    (n,) = song.notes
    assert (n.start, n.end, n.sound_end, n.pitch, n.velocity, n.track) == (1.0, 2.5, 2.5, 60, 90, 0)
    assert song.duration == 2.5


def test_restrike_before_release():
    song = events_to_song([on(0.0, 60, 70), on(1.0, 60, 90), off(2.0, 60)])
    assert [(n.start, n.end, n.velocity) for n in song.notes] == [(0.0, 1.0, 70), (1.0, 2.0, 90)]


def test_hanging_note_closes_at_end_time():
    song = events_to_song([on(0.0, 60), on(1.0, 64), off(2.0, 64)], end_time=5.0)
    by_pitch = {n.pitch: n for n in song.notes}
    assert by_pitch[60].end == 5.0
    assert by_pitch[64].end == 2.0


def test_hanging_note_closes_at_last_event():
    song = events_to_song([on(0.0, 60), on(1.0, 64), off(2.0, 64)])
    assert {n.pitch: n.end for n in song.notes}[60] == 2.0


def test_hanging_note_minimal_duration():
    (n,) = events_to_song([on(1.0, 60)]).notes
    assert n.end == pytest.approx(1.05)


def test_sustain_extends_sound_end():
    song = events_to_song([pedal(0.0, 127), on(0.5, 60), off(1.0, 60), pedal(3.0, 0)])
    (n,) = song.notes
    assert n.end == 1.0 and n.sound_end == 3.0
    assert song.duration == 3.0


def test_pedal_never_released():
    song = events_to_song([pedal(0.0, 100), on(0.5, 60), off(1.0, 60)])
    (n,) = song.notes
    assert n.sound_end == n.end == 1.0


def test_round_trip(tmp_path):
    events = [
        pedal(0.0, 127),
        on(0.1, 60, 80),
        off(0.9, 60),
        on(0.5, 64, 100),
        on(1.3, 64, 50),
        off(2.0, 64),
        pedal(2.5, 0),
        on(3.0, 67, 33),
        off(3.4, 67),
    ]
    path = tmp_path / "take.mid"
    save_midi(events, path)
    expected = events_to_song(events)
    got = load_midi(path)
    assert len(got.notes) == len(expected.notes) == 4
    for a, b in zip(got.notes, expected.notes):
        assert (a.pitch, a.velocity) == (b.pitch, b.velocity)
        assert a.start == pytest.approx(b.start, abs=TOL)
        assert a.end == pytest.approx(b.end, abs=TOL)
        assert a.sound_end == pytest.approx(b.sound_end, abs=TOL)


def test_empty(tmp_path):
    song = events_to_song([])
    assert song.notes == () and song.duration == 0.0
    path = tmp_path / "empty.mid"
    save_midi([], path)
    assert load_midi(path).notes == ()
