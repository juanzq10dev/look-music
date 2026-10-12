"""Visual presets: colours and sizes, optionally loaded from JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

RGB = tuple[float, float, float]


def hex_to_rgb(value: str) -> RGB:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected a #RRGGBB colour, got {value!r}")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


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

    def track_color(self, track: int) -> RGB:
        return self.track_colors[track % len(self.track_colors)]


_COLOR_FIELDS = {"background", "white_key", "black_key", "keyboard_edge"}


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
    return Preset(**data)
