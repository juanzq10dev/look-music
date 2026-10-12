"""Visual presets: colours and sizes, optionally loaded from JSON."""

from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass, field, fields
from pathlib import Path

from look_music.render.gl import BloomSettings

RGB = tuple[float, float, float]


def hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected a #RRGGBB colour, got {value!r}")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


COLOR_MODES = ("track", "hand", "pitch", "auto")


def _hue_wheel(n: int = 12, saturation: float = 0.65, value: float = 0.95) -> tuple[RGB, ...]:
    return tuple(colorsys.hsv_to_rgb(i / n, saturation, value) for i in range(n))


def _check_color_mode(mode: str) -> None:
    if mode not in COLOR_MODES:
        raise ValueError(f"invalid color_mode {mode!r}; valid modes: {', '.join(COLOR_MODES)}")


@dataclass(frozen=True)
class Preset:
    background: RGB = hex_to_rgb("#0B0B10")
    track_colors: tuple[RGB, ...] = field(
        default_factory=lambda: tuple(
            hex_to_rgb(c) for c in ("#4FC3F7", "#F06292", "#81C784", "#FFB74D", "#BA68C8")
        )
    )
    white_key: RGB = hex_to_rgb("#F2F2F2")
    black_key: RGB = hex_to_rgb("#161616")
    keyboard_edge: RGB = hex_to_rgb("#8B1A1A")
    keyboard_height: float = 0.16  # fraction of frame height
    seconds_visible: float = 3.0  # time a note takes to fall from the top to the keys
    note_radius: float = 6.0  # pixels at 1080p, scaled with frame height
    note_gap: float = 2.0  # horizontal pixels at 1080p trimmed from each side of a note
    black_note_darkness: float = 0.75  # brightness multiplier for notes on black keys
    min_velocity_brightness: float = 0.6  # brightness at velocity 0; velocity 127 is 1.0

    color_mode: str = "auto"  # track | hand | pitch | auto (track if 2+ tracks, else hand)
    hand_split: int = 60  # pitches below this are left hand
    left_hand_color: RGB = hex_to_rgb("#F06292")
    right_hand_color: RGB = hex_to_rgb("#4FC3F7")
    pitch_colors: tuple[RGB, ...] = field(default_factory=_hue_wheel)  # by pitch class, C=0

    bloom: bool = True
    bloom_intensity: float = 0.9  # strength of the glow added back over the scene
    bloom_radius: float = 24.0  # blur radius in pixels at 1080p, scaled with frame height

    def __post_init__(self) -> None:
        _check_color_mode(self.color_mode)
        if len(self.pitch_colors) != 12:
            raise ValueError("pitch_colors must have exactly 12 colours")
        if self.bloom_intensity < 0:
            raise ValueError(f"bloom_intensity must not be negative, got {self.bloom_intensity}")
        if self.bloom_radius <= 0:
            raise ValueError(f"bloom_radius must be greater than 0, got {self.bloom_radius}")

    def track_color(self, track: int) -> RGB:
        return self.track_colors[track % len(self.track_colors)]

    def bloom_settings(self) -> BloomSettings | None:
        if not self.bloom:
            return None
        return BloomSettings(intensity=self.bloom_intensity, radius=self.bloom_radius)


_COLOR_FIELDS = {
    "background", "white_key", "black_key", "keyboard_edge", "left_hand_color", "right_hand_color"
}


def load_preset(path: str | Path) -> Preset:
    """Load a JSON preset; any field left out keeps its default."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {f.name for f in fields(Preset)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown preset fields: {', '.join(sorted(unknown))}")
    for name in _COLOR_FIELDS & set(data):
        data[name] = hex_to_rgb(data[name])
    if "track_colors" in data:
        data["track_colors"] = tuple(hex_to_rgb(c) for c in data["track_colors"])
    if "pitch_colors" in data:
        if len(data["pitch_colors"]) != 12:
            raise ValueError("pitch_colors must list exactly 12 colours (C to B)")
        data["pitch_colors"] = tuple(hex_to_rgb(c) for c in data["pitch_colors"])
    if "color_mode" in data:
        _check_color_mode(data["color_mode"])
    return Preset(**data)
