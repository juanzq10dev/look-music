from __future__ import annotations

import numpy as np

from look_music.keyboard import key_layout
from look_music.midi import Note, Song
from look_music.preset import Preset, hex_to_rgb
from look_music.live.state import LiveNote
from look_music.render.scene import (
    INSTANCE_COLUMNS,
    build_instances,
    build_live_instances,
    prepare_notes,
)

W, H = 1920, 1080
PRESET = Preset()
LAYOUT = key_layout(W)
KEYBOARD_TOP = H * (1 - PRESET.keyboard_height)
KEY_ROWS = 52 + 36 + 1


def note(start, end, pitch=60, velocity=100, track=0):
    return Note(start, end, end, pitch, velocity, track)


def build(notes, t, preset=PRESET):
    song = Song(notes=tuple(notes), duration=max((n.end for n in notes), default=0.0))
    return build_instances(prepare_notes(song, preset), t, W, H, LAYOUT, preset)


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
    assert len(prepare_notes(song, PRESET).pitch) == 1
    out = build([note(0, 1, pitch=10), note(0, 1, pitch=120)], 0.5)
    assert out.shape[0] == KEY_ROWS


def song_of(notes):
    return Song(notes=tuple(notes), duration=max(n.end for n in notes))


def test_hand_mode_splits_at_hand_split():
    preset = Preset(color_mode="hand", hand_split=60)
    nb = prepare_notes(song_of([note(0, 1, pitch=59), note(0.1, 1, pitch=60)]), preset)
    assert np.allclose(nb.base_color[0], preset.left_hand_color, atol=1e-6)
    assert np.allclose(nb.base_color[1], preset.right_hand_color, atol=1e-6)


def test_pitch_mode_uses_pitch_class():
    preset = Preset(color_mode="pitch")
    nb = prepare_notes(song_of([note(0, 1, pitch=61), note(0.1, 1, pitch=73)]), preset)
    assert np.allclose(nb.base_color, [preset.pitch_colors[1]] * 2, atol=1e-6)


def test_auto_mode_resolves_by_track_count():
    single = prepare_notes(song_of([note(0, 1, pitch=50), note(0, 1, pitch=70)]), PRESET)
    assert np.allclose(single.base_color[0], PRESET.left_hand_color, atol=1e-6)
    assert np.allclose(single.base_color[1], PRESET.right_hand_color, atol=1e-6)
    multi = prepare_notes(
        song_of([note(0, 1, pitch=50, track=0), note(0.1, 1, pitch=70, track=1)]), PRESET
    )
    assert np.allclose(multi.base_color[0], PRESET.track_color(0), atol=1e-6)
    assert np.allclose(multi.base_color[1], PRESET.track_color(1), atol=1e-6)


def test_glow_column():
    out = build([note(0.0, 2.0, pitch=60)], 1.0)
    assert out[0, 9] == 1.0  # note
    assert out[1, 9] == 0.0  # edge
    keys = out[2:]
    lit = np.isclose(keys[:, 0], LAYOUT.x[60])
    assert lit.sum() == 1
    assert keys[lit, 9][0] == 1.0
    assert np.all(keys[~lit, 9] == 0.0)


def test_hand_mode_note_color_in_instances():
    notes = [note(0, 2, pitch=40, velocity=127)]
    out = build(notes, 0.0, Preset(color_mode="hand"))
    assert np.allclose(out[0, 4:7], hex_to_rgb("#F06292"), atol=1e-5)


def live(notes, t, preset=PRESET):
    return build_live_instances(notes, t, W, H, LAYOUT, preset)


SPEED = KEYBOARD_TOP / PRESET.seconds_visible


def test_live_empty_has_only_keyboard_rows():
    out = live([], 0.0)
    assert out.dtype == np.float32
    assert out.shape == (KEY_ROWS, INSTANCE_COLUMNS)


def test_live_held_note_grows_from_keyboard():
    n = LiveNote(60, 100, 1.0, None)
    a, b = live([n], 1.5)[0], live([n], 2.0)[0]
    assert np.isclose(a[1] + a[3], KEYBOARD_TOP)
    assert np.isclose(b[1] + b[3], KEYBOARD_TOP)
    assert np.isclose(a[3], 0.5 * SPEED, rtol=1e-4)
    assert np.isclose(b[3], 1.0 * SPEED, rtol=1e-4)


def test_live_released_note_floats_up():
    out = live([LiveNote(60, 100, 1.0, 2.0)], 3.0)
    assert out.shape[0] == KEY_ROWS + 1
    assert np.isclose(out[0, 1] + out[0, 3], KEYBOARD_TOP - 1.0 * SPEED, rtol=1e-4)
    assert np.isclose(out[0, 3], 1.0 * SPEED, rtol=1e-4)


def test_live_offscreen_notes_omitted():
    n = LiveNote(60, 100, 0.0, 1.0)
    assert live([n], 1.0 + PRESET.seconds_visible + 0.1).shape[0] == KEY_ROWS


def test_live_auto_color_is_hand_split():
    out = live([LiveNote(40, 127, 0.0, None), LiveNote(79, 127, 0.0, None)], 1.0)
    by_x = {round(float(r[0]), 2): r[4:7] for r in out[:2]}
    left = by_x[round(float(LAYOUT.x[40] + PRESET.note_gap), 2)]
    right = by_x[round(float(LAYOUT.x[79] + PRESET.note_gap), 2)]
    assert np.allclose(left, PRESET.left_hand_color, atol=1e-5)
    assert np.allclose(right, PRESET.right_hand_color, atol=1e-5)


def test_live_held_key_lit_with_glow():
    out = live([LiveNote(60, 100, 0.0, None)], 1.0)
    assert out[0, 9] == 1.0
    keys = out[2:]
    lit = np.isclose(keys[:, 0], LAYOUT.x[60])
    assert lit.sum() == 1 and keys[lit, 9][0] == 1.0
    assert np.all(keys[~lit, 9] == 0.0)


def test_live_released_key_not_lit():
    out = live([LiveNote(60, 100, 0.0, 0.5)], 1.0)
    assert np.all(out[2:, 9] == 0.0)
