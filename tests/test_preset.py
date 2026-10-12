from __future__ import annotations

import json

import pytest

from look_music.preset import Preset, hex_to_rgb, load_preset


def write(tmp_path, data):
    path = tmp_path / "p.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_defaults_valid():
    p = Preset()
    assert p.color_mode == "auto"
    assert p.hand_split == 60
    assert len(p.pitch_colors) == 12
    assert p.pitch_colors[0][0] == pytest.approx(0.95)


def test_load_parses_color_fields(tmp_path):
    colors = [f"#{i * 20:02X}00FF" for i in range(12)]
    p = load_preset(
        write(
            tmp_path,
            {
                "color_mode": "pitch",
                "hand_split": 64,
                "left_hand_color": "#112233",
                "right_hand_color": "#445566",
                "pitch_colors": colors,
            },
        )
    )
    assert p.color_mode == "pitch"
    assert p.hand_split == 64
    assert p.left_hand_color == hex_to_rgb("#112233")
    assert p.right_hand_color == hex_to_rgb("#445566")
    assert p.pitch_colors == tuple(hex_to_rgb(c) for c in colors)


def test_invalid_color_mode(tmp_path):
    with pytest.raises(ValueError, match="track"):
        load_preset(write(tmp_path, {"color_mode": "rainbow"}))
    with pytest.raises(ValueError):
        Preset(color_mode="rainbow")


def test_wrong_pitch_colors_length(tmp_path):
    with pytest.raises(ValueError):
        load_preset(write(tmp_path, {"pitch_colors": ["#FFFFFF"] * 11}))


def test_unknown_field(tmp_path):
    with pytest.raises(ValueError):
        load_preset(write(tmp_path, {"nope": 1}))


def test_bloom_defaults():
    p = Preset()
    assert p.bloom is True
    assert p.bloom_intensity == pytest.approx(0.9)
    assert p.bloom_radius == pytest.approx(24.0)
    settings = p.bloom_settings()
    assert settings is not None
    assert settings.intensity == pytest.approx(0.9)
    assert settings.radius == pytest.approx(24.0)


def test_bloom_settings_none_when_disabled():
    assert Preset(bloom=False).bloom_settings() is None


def test_invalid_bloom_values_rejected():
    with pytest.raises(ValueError, match="bloom_intensity"):
        Preset(bloom_intensity=-0.1)
    with pytest.raises(ValueError, match="bloom_radius"):
        Preset(bloom_radius=0)
    with pytest.raises(ValueError, match="bloom_radius"):
        Preset(bloom_radius=-3.0)
    Preset(bloom_intensity=0.0)  # zero intensity is allowed


def test_load_accepts_bloom_fields(tmp_path):
    p = load_preset(write(tmp_path, {"bloom": False, "bloom_intensity": 1.5, "bloom_radius": 12}))
    assert p.bloom is False
    assert p.bloom_intensity == pytest.approx(1.5)
    assert p.bloom_radius == pytest.approx(12.0)
    assert p.bloom_settings() is None


def test_load_rejects_invalid_bloom_fields(tmp_path):
    with pytest.raises(ValueError, match="bloom_radius"):
        load_preset(write(tmp_path, {"bloom_radius": 0}))
