from __future__ import annotations

import pretty_midi

from look_music.midi import load_midi


def _write(tmp_path, instruments, name="t.mid"):
    pm = pretty_midi.PrettyMIDI()
    pm.instruments.extend(instruments)
    path = tmp_path / name
    pm.write(str(path))
    return path


def _inst(notes, is_drum=False, pedal=()):
    inst = pretty_midi.Instrument(program=0, is_drum=is_drum)
    for pitch, start, end in notes:
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end))
    for number, value, time in pedal:
        inst.control_changes.append(pretty_midi.ControlChange(number, value, time))
    return inst


def test_notes_sorted_by_start(tmp_path):
    path = _write(tmp_path, [_inst([(64, 1.0, 1.5), (60, 0.0, 0.5), (62, 0.5, 1.0)])])
    song = load_midi(path)
    assert [n.pitch for n in song.notes] == [60, 62, 64]


def test_drums_skipped(tmp_path):
    path = _write(tmp_path, [_inst([(36, 0.0, 0.5)], is_drum=True), _inst([(60, 0.0, 0.5)])])
    assert [n.pitch for n in load_midi(path).notes] == [60]


def test_track_is_instrument_index(tmp_path):
    path = _write(tmp_path, [_inst([(60, 0.0, 0.5)]), _inst([(72, 0.0, 0.5)])])
    song = load_midi(path)
    assert {n.pitch: n.track for n in song.notes} == {60: 0, 72: 1}


def test_sustain_extends_sound_end(tmp_path):
    pedal = [(64, 127, 0.5), (64, 0, 2.0)]
    path = _write(tmp_path, [_inst([(60, 0.0, 1.0)], pedal=pedal)])
    (note,) = load_midi(path).notes
    assert abs(note.end - 1.0) < 1e-2
    assert abs(note.sound_end - 2.0) < 1e-2


def test_note_outside_pedal_keeps_end(tmp_path):
    pedal = [(64, 127, 0.5), (64, 0, 2.0)]
    path = _write(tmp_path, [_inst([(60, 2.5, 3.0)], pedal=pedal)])
    (note,) = load_midi(path).notes
    assert note.sound_end == note.end


def test_unreleased_pedal_keeps_end(tmp_path):
    path = _write(tmp_path, [_inst([(60, 0.0, 1.0)], pedal=[(64, 127, 0.5)])])
    (note,) = load_midi(path).notes
    assert note.sound_end == note.end


def test_shifted(tmp_path):
    pedal = [(64, 127, 0.5), (64, 0, 2.0)]
    song = load_midi(_write(tmp_path, [_inst([(60, 0.0, 1.0)], pedal=pedal)]))
    moved = song.shifted(1.5)
    (a,), (b,) = song.notes, moved.notes
    assert b.start == a.start + 1.5
    assert b.end == a.end + 1.5
    assert b.sound_end == a.sound_end + 1.5
    assert moved.duration == song.duration + 1.5


def test_empty_midi(tmp_path):
    song = load_midi(_write(tmp_path, []))
    assert song.notes == ()
    assert song.duration == 0
