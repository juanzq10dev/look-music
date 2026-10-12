from __future__ import annotations

import dataclasses

import pytest

import look_music.render.scene as scene
from look_music.midi import Note, Song
from look_music.preview.frames import FrameSource
from look_music.preset import Preset

W, H = 128, 96


def song() -> Song:
    notes = tuple(
        Note(start=s, end=s + 0.5, sound_end=s + 0.5, pitch=p, velocity=90, track=0)
        for s, p in [(0.5, 60), (1.0, 64), (1.5, 67)]
    )
    return Song(notes=notes, duration=2.0)


@pytest.fixture
def source():
    try:
        fs = FrameSource(song(), Preset(), W, H)
    except Exception as exc:
        pytest.skip(f"no GL context: {exc}")
    yield fs
    fs.close()


def test_frame_size(source):
    assert len(source.frame(1.0)) == W * H * 3


def test_frames_differ_over_time(source):
    assert source.frame(0.0) != source.frame(1.2)


def test_set_preset_background(source):
    before = source.frame(0.0)[:3]
    source.set_preset(dataclasses.replace(Preset(), background=(1.0, 0.0, 0.0), bloom=False))
    after = source.frame(0.0)[:3]
    assert before != after
    assert after == bytes([255, 0, 0])


def test_set_preset_colors_only(source):
    renderer = source._renderer
    source.set_preset(dataclasses.replace(Preset(), left_hand_color=(0.0, 1.0, 0.0)))
    assert source._renderer is renderer


def test_resize(source):
    source.resize(64, 48)
    assert len(source.frame(1.0)) == 64 * 48 * 3


def test_empty_song():
    try:
        fs = FrameSource(Song(notes=(), duration=0.0), Preset(), W, H)
    except Exception as exc:
        pytest.skip(f"no GL context: {exc}")
    with fs:
        assert len(fs.frame(0.0)) == W * H * 3


@pytest.mark.skipif(not hasattr(scene, "build_live_instances"), reason="live scene not available")
def test_live_frame(source):
    from look_music.live.state import LiveNote

    empty = source.live_frame([], 1.0)
    assert len(empty) == W * H * 3
    held = source.live_frame([LiveNote(60, 100, 0.5, None)], 1.0)
    assert held != empty
