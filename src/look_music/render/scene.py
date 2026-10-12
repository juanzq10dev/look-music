"""Per-frame scene description: every rounded rectangle to draw at a given time."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from look_music.keyboard import HIGHEST_PITCH, LOWEST_PITCH, KeyboardLayout
from look_music.live.state import LiveNote
from look_music.midi import Song
from look_music.preset import Preset

INSTANCE_COLUMNS = 10  # x, y, w, h, r, g, b, a, radius, glow

EDGE_HEIGHT = 4.0  # px at 1080p
KEY_GAP = 1.0
WHITE_KEY_RADIUS = 3.0
BLACK_KEY_RADIUS = 2.0
BLACK_KEY_HEIGHT_RATIO = 0.62
WHITE_KEY_NOTE_MIX = 0.7
BLACK_KEY_NOTE_MIX = 0.8


@dataclass(frozen=True)
class NoteArrays:
    start: np.ndarray  # float64 seconds
    end: np.ndarray  # float64 seconds, key release
    pitch: np.ndarray  # int16
    velocity: np.ndarray  # int16
    track: np.ndarray  # int16
    base_color: np.ndarray  # float32 (n, 3), before velocity/black-key brightness


def _base_colors(pitch: np.ndarray, track: np.ndarray, preset: Preset) -> np.ndarray:
    mode = preset.color_mode
    if mode == "auto":
        mode = "track" if len(np.unique(track)) >= 2 else "hand"
    if mode == "track":
        palette = np.asarray(preset.track_colors, dtype=np.float32)
        return palette[track.astype(np.intp) % len(palette)]
    if mode == "pitch":
        palette = np.asarray(preset.pitch_colors, dtype=np.float32)
        return palette[pitch.astype(np.intp) % 12]
    left = np.asarray(preset.left_hand_color, dtype=np.float32)
    right = np.asarray(preset.right_hand_color, dtype=np.float32)
    return np.where((pitch < preset.hand_split)[:, None], left, right).astype(np.float32)


def prepare_notes(song: Song, preset: Preset) -> NoteArrays:
    """Flatten a song into arrays sorted by start time, dropping notes off the 88 keys."""
    notes = [n for n in song.notes if LOWEST_PITCH <= n.pitch <= HIGHEST_PITCH]
    notes.sort(key=lambda n: n.start)
    pitch = np.array([n.pitch for n in notes], dtype=np.int16)
    track = np.array([n.track for n in notes], dtype=np.int16)
    return NoteArrays(
        start=np.array([n.start for n in notes], dtype=np.float64),
        end=np.array([n.end for n in notes], dtype=np.float64),
        pitch=pitch,
        velocity=np.array([n.velocity for n in notes], dtype=np.int16),
        track=track,
        base_color=_base_colors(pitch, track, preset),
    )


def _rows(x, y, w, h, color, radius, glow) -> np.ndarray:
    """Stack columns into instance rows; scalars broadcast to the longest column."""
    n = np.broadcast(x, y, w, h).size
    out = np.empty((n, INSTANCE_COLUMNS), dtype=np.float32)
    out[:, 0] = x
    out[:, 1] = y
    out[:, 2] = w
    out[:, 3] = h
    out[:, 4:7] = color
    out[:, 7] = 1.0
    out[:, 8] = radius
    out[:, 9] = glow
    return out


def build_instances(
    notes: NoteArrays,
    t: float,
    width: int,
    height: int,
    layout: KeyboardLayout,
    preset: Preset,
) -> np.ndarray:
    """Return float32 array shape (N, 10). Rows are drawn in order (later rows on top)."""
    scale = height / 1080
    keyboard_top = height * (1 - preset.keyboard_height)
    keyboard_h = height - keyboard_top
    speed = keyboard_top / preset.seconds_visible
    gap = preset.note_gap * scale

    visible = (notes.start < t + preset.seconds_visible) & (notes.end > t)
    idx = np.flatnonzero(visible)
    start, end, pitch = notes.start[idx], notes.end[idx], notes.pitch[idx].astype(np.intp)

    colors = _note_colors(notes.base_color[idx], notes.velocity[idx], pitch, layout, preset)

    # Per-pitch colour of the most recently started sounding note (notes are start-sorted).
    sounding = (start <= t) & (t < end)
    sound_color = np.zeros((128, 3))
    is_sounding = np.zeros(128, dtype=bool)
    sound_color[pitch[sounding]] = colors[sounding]
    is_sounding[pitch[sounding]] = True

    bottom = np.minimum(keyboard_top - (start - t) * speed, keyboard_top)
    top = keyboard_top - (end - t) * speed
    keep = (bottom - top) >= 1
    order = np.argsort(layout.black[pitch[keep]], kind="stable")  # white notes first
    sel = np.flatnonzero(keep)[order]
    note_rows = _rows(
        layout.x[pitch[sel]] + gap,
        top[sel],
        layout.width[pitch[sel]] - 2 * gap,
        bottom[sel] - top[sel],
        colors[sel],
        preset.note_radius * scale,
        1.0,
    )

    key_rows = _keyboard_rows(
        width, height, keyboard_top, layout, preset, sound_color, is_sounding
    )
    return np.concatenate([note_rows, key_rows])


def _note_colors(
    base: np.ndarray,
    velocity: np.ndarray,
    pitch: np.ndarray,
    layout: KeyboardLayout,
    preset: Preset,
) -> np.ndarray:
    """Apply velocity brightness and black-key darkness to base colours (float64, (n, 3))."""
    low = preset.min_velocity_brightness
    brightness = low + (1 - low) * velocity / 127
    brightness = np.where(layout.black[pitch], brightness * preset.black_note_darkness, brightness)
    return base.astype(np.float64) * brightness[:, None]


def _keyboard_rows(
    width: int,
    height: int,
    keyboard_top: float,
    layout: KeyboardLayout,
    preset: Preset,
    sound_color: np.ndarray,
    is_sounding: np.ndarray,
) -> np.ndarray:
    """Edge strip, white keys, then black keys; sounding keys mix in the note colour."""
    scale = height / 1080
    keyboard_h = height - keyboard_top
    edge_h = EDGE_HEIGHT * scale
    edge_row = _rows(
        0.0, keyboard_top - edge_h, float(width), edge_h, preset.keyboard_edge, 0.0, 0.0
    )

    def key_rows(pitches, base, mix, key_h, radius, trim):
        base = np.asarray(base, dtype=np.float64)
        col = np.broadcast_to(base, (len(pitches), 3)).copy()
        s = is_sounding[pitches]
        col[s] = mix * sound_color[pitches[s]] + (1 - mix) * base
        return _rows(
            layout.x[pitches],
            keyboard_top,
            layout.width[pitches] - trim,
            key_h,
            col,
            radius,
            s.astype(np.float32),
        )

    all_pitches = np.arange(LOWEST_PITCH, HIGHEST_PITCH + 1)
    black = layout.black[all_pitches]
    white_rows = key_rows(
        all_pitches[~black], preset.white_key, WHITE_KEY_NOTE_MIX, keyboard_h,
        WHITE_KEY_RADIUS * scale, KEY_GAP * scale,
    )
    black_rows = key_rows(
        all_pitches[black],
        preset.black_key,
        BLACK_KEY_NOTE_MIX,
        BLACK_KEY_HEIGHT_RATIO * keyboard_h,
        BLACK_KEY_RADIUS * scale,
        0.0,
    )
    return np.concatenate([edge_row, white_rows, black_rows])


def build_live_instances(
    notes: Sequence[LiveNote],
    t: float,
    width: int,
    height: int,
    layout: KeyboardLayout,
    preset: Preset,
) -> np.ndarray:
    """Instances (N, 10) for live mode: notes rise from the keyboard; lit keys for held notes."""
    scale = height / 1080
    keyboard_top = height * (1 - preset.keyboard_height)
    speed = keyboard_top / preset.seconds_visible
    gap = preset.note_gap * scale

    notes = [n for n in notes if LOWEST_PITCH <= n.pitch <= HIGHEST_PITCH]
    pitch = np.array([n.pitch for n in notes], dtype=np.intp)
    velocity = np.array([n.velocity for n in notes], dtype=np.int16)
    start = np.array([n.start for n in notes], dtype=np.float64)
    held = np.array([n.end is None for n in notes], dtype=bool)
    end = np.array([t if n.end is None else n.end for n in notes], dtype=np.float64)

    live_preset = replace(preset, color_mode="hand") if preset.color_mode == "auto" else preset
    base = _base_colors(pitch, np.zeros(len(notes), dtype=np.int16), live_preset)
    colors = _note_colors(base, velocity, pitch, layout, preset)

    # Per-pitch colour of the most recently started held note.
    sound_color = np.zeros((128, 3))
    is_sounding = np.zeros(128, dtype=bool)
    order = np.argsort(start, kind="stable")
    hp = order[held[order]]
    sound_color[pitch[hp]] = colors[hp]
    is_sounding[pitch[hp]] = True

    bottom = keyboard_top - (t - end) * speed
    top = keyboard_top - (t - start) * speed
    sel = np.flatnonzero((bottom > 0) & ((bottom - top) >= 1))
    sel = sel[np.argsort(layout.black[pitch[sel]], kind="stable")]  # white notes first
    note_rows = _rows(
        layout.x[pitch[sel]] + gap,
        top[sel],
        layout.width[pitch[sel]] - 2 * gap,
        bottom[sel] - top[sel],
        colors[sel],
        preset.note_radius * scale,
        1.0,
    )
    key_rows = _keyboard_rows(
        width, height, keyboard_top, layout, preset, sound_color, is_sounding
    )
    return np.concatenate([note_rows, key_rows])
