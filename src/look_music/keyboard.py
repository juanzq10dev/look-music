"""Geometry of an 88-key piano keyboard."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LOWEST_PITCH = 21  # A0
HIGHEST_PITCH = 108  # C8
BLACK_PITCH_CLASSES = frozenset({1, 3, 6, 8, 10})
BLACK_KEY_WIDTH_RATIO = 0.6


def is_black(pitch: int) -> bool:
    return pitch % 12 in BLACK_PITCH_CLASSES


@dataclass(frozen=True)
class KeyboardLayout:
    """Horizontal position of every key, indexed by MIDI pitch (0-127)."""

    x: np.ndarray  # left edge in pixels
    width: np.ndarray  # width in pixels
    black: np.ndarray  # bool
    white_key_width: float


def key_layout(total_width: float) -> KeyboardLayout:
    pitches = range(LOWEST_PITCH, HIGHEST_PITCH + 1)
    white_count = sum(1 for p in pitches if not is_black(p))
    white_w = total_width / white_count
    black_w = white_w * BLACK_KEY_WIDTH_RATIO

    x = np.zeros(128, dtype=np.float32)
    width = np.zeros(128, dtype=np.float32)
    black = np.zeros(128, dtype=bool)
    whites_before = 0
    for p in pitches:
        if is_black(p):
            # Black keys sit centred on the boundary between their neighbours.
            x[p] = whites_before * white_w - black_w / 2
            width[p] = black_w
            black[p] = True
        else:
            x[p] = whites_before * white_w
            width[p] = white_w
            whites_before += 1
    return KeyboardLayout(x=x, width=width, black=black, white_key_width=white_w)
