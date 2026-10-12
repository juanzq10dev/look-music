from __future__ import annotations

from look_music.live.events import MidiEvent
from look_music.live.state import LiveNote, LiveState


def on(t, p=60, v=100):
    return MidiEvent(t, "note_on", p, v)


def off(t, p=60):
    return MidiEvent(t, "note_off", p, 0)


def test_on_off_pairing():
    s = LiveState()
    s.apply([on(1.0)])
    assert s.visible_notes(1.5, 5) == [LiveNote(60, 100, 1.0, None)]
    s.apply([off(2.0)])
    assert s.visible_notes(2.5, 5) == [LiveNote(60, 100, 1.0, 2.0)]


def test_restrike_closes_previous():
    s = LiveState()
    s.apply([on(1.0, v=50), on(2.0, v=90)])
    notes = s.visible_notes(2.5, 5)
    assert LiveNote(60, 50, 1.0, 2.0) in notes
    assert LiveNote(60, 90, 2.0, None) in notes
    assert len(notes) == 2


def test_unmatched_off_ignored():
    s = LiveState()
    s.apply([off(1.0)])
    assert s.visible_notes(1.0, 5) == []
    assert len(s.events) == 1


def test_sustain_flag():
    s = LiveState()
    s.apply([MidiEvent(0.1, "sustain", 64, 127)])
    assert s.sustain
    s.apply([MidiEvent(0.2, "sustain", 64, 63)])
    assert not s.sustain


def test_visible_prunes_old_but_events_kept():
    s = LiveState()
    s.apply([on(0.0, 60), off(1.0, 60), on(5.0, 62), off(6.0, 62), on(7.0, 64)])
    assert {n.pitch for n in s.visible_notes(8.0, 3.0)} == {62, 64}
    assert len(s.events) == 5
    assert {n.pitch for n in s.visible_notes(8.0, 100.0)} == {62, 64}  # pruned for good


def test_held_pitches():
    s = LiveState()
    s.apply([on(0, 60), on(0, 64), off(1, 60)])
    assert s.held_pitches() == {64}


def test_clear():
    s = LiveState()
    s.apply([on(0), MidiEvent(0, "sustain", 64, 127)])
    s.clear()
    assert s.events == [] and not s.sustain and s.held_pitches() == set()
    assert s.visible_notes(0, 10) == []
