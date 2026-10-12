"""Per-frame scene description: every rounded rectangle to draw at a given time."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from look_music.keyboard import HIGHEST_PITCH, LOWEST_PITCH, KeyboardLayout
from look_music.midi import Song
from look_music.preset import Preset

INSTANCE_COLUMNS = 9  # x, y, w, h, r, g, b, a, radius

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


def prepare_notes(song: Song) -> NoteArrays:
    """Flatten a song into arrays sorted by start time, dropping notes off the 88 keys."""
    notes = [n for n in song.notes if LOWEST_PITCH <= n.pitch <= HIGHEST_PITCH]
    notes.sort(key=lambda n: n.start)
    return NoteArrays(
        start=np.array([n.start for n in notes], dtype=np.float64),
        end=np.array([n.end for n in notes], dtype=np.float64),
        pitch=np.array([n.pitch for n in notes], dtype=np.int16),
        velocity=np.array([n.velocity for n in notes], dtype=np.int16),
        track=np.array([n.track for n in notes], dtype=np.int16),
    )


def _rows(x, y, w, h, color, radius) -> np.ndarray:
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
    return out


def build_instances(
    notes: NoteArrays,
    t: float,
    width: int,
    height: int,
    layout: KeyboardLayout,
    preset: Preset,
) -> np.ndarray:
    """Return float32 array shape (N, 9). Rows are drawn in order (later rows on top)."""
    scale = height / 1080
    keyboard_top = height * (1 - preset.keyboard_height)
    keyboard_h = height - keyboard_top
    speed = keyboard_top / preset.seconds_visible
    gap = preset.note_gap * scale

    visible = (notes.start < t + preset.seconds_visible) & (notes.end > t)
    idx = np.flatnonzero(visible)
    start, end, pitch = notes.start[idx], notes.end[idx], notes.pitch[idx].astype(np.intp)

    palette = np.asarray(preset.track_colors, dtype=np.float64)
    colors = palette[notes.track[idx].astype(np.intp) % len(palette)]
    low = preset.min_velocity_brightness
    brightness = low + (1 - low) * notes.velocity[idx] / 127
    brightness = np.where(layout.black[pitch], brightness * preset.black_note_darkness, brightness)
    colors = colors * brightness[:, None]

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
    )

    edge_h = EDGE_HEIGHT * scale
    edge_row = _rows(
        0.0, keyboard_top - edge_h, float(width), edge_h, preset.keyboard_edge, 0.0
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
    return np.concatenate([note_rows, edge_row, white_rows, black_rows])
