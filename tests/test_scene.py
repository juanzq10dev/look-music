from __future__ import annotations

import numpy as np

from look_music.keyboard import key_layout
from look_music.midi import Note, Song
from look_music.preset import Preset
from look_music.render.scene import INSTANCE_COLUMNS, build_instances, prepare_notes

W, H = 1920, 1080
PRESET = Preset()
LAYOUT = key_layout(W)
KEYBOARD_TOP = H * (1 - PRESET.keyboard_height)
KEY_ROWS = 52 + 36 + 1


def note(start, end, pitch=60, velocity=100, track=0):
    return Note(start, end, end, pitch, velocity, track)


def build(notes, t):
    song = Song(notes=tuple(notes), duration=max((n.end for n in notes), default=0.0))
    return build_instances(prepare_notes(song), t, W, H, LAYOUT, PRESET)


def test_empty_has_only_keyboard_rows():
    out = build([], 0.0)
    assert out.dtype == np.float32
    assert out.shape == (KEY_ROWS, INSTANCE_COLUMNS)


def test_note_starting_now_sits_on_keyboard():
    out = build([note(1.0, 2.0)], 1.0)
    assert out.shape == (KEY_ROWS + 1, INSTANCE_COLUMNS)
    x, y, w, h = out[0, :4]
    assert np.isclose(y + h, KEYBOARD_TOP)


def test_future_note_not_present():
    assert build([note(5.0, 6.0)], 1.0).shape[0] == KEY_ROWS


def test_ended_note_not_present():
    assert build([note(0.0, 1.0)], 2.0).shape[0] == KEY_ROWS


def test_falling_note_position():
    out = build([note(2.0, 3.0)], 1.0)
    speed = KEYBOARD_TOP / PRESET.seconds_visible
    assert np.isclose(out[0, 1] + out[0, 3], KEYBOARD_TOP - speed, rtol=1e-4)
    assert np.isclose(out[0, 3], speed, rtol=1e-4)


def test_sounding_key_changes_color():
    idle = build([], 0.0)
    out = build([note(0.0, 2.0, pitch=60)], 1.0)
    keys = out[1 + 1 :]  # skip note and edge rows
    idle_keys = idle[1:]
    assert not np.allclose(keys[:, 4:7], idle_keys[:, 4:7])


def test_pitches_outside_piano_dropped():
    song = Song(notes=(note(0, 1, pitch=10), note(0, 1, pitch=120), note(0, 1, pitch=60)), duration=1)
    assert len(prepare_notes(song).pitch) == 1
    out = build([note(0, 1, pitch=10), note(0, 1, pitch=120)], 0.5)
    assert out.shape[0] == KEY_ROWS
