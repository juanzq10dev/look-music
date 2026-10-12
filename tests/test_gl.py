from __future__ import annotations

import numpy as np
import pytest

from look_music.render.gl import BloomSettings, Renderer

W, H = 64, 48
BG = (0.1, 0.2, 0.3)
BG_BYTES = np.round(np.array(BG) * 255)


@pytest.fixture
def renderer():
    try:
        r = Renderer(W, H, BG)
    except Exception as exc:
        pytest.skip(f"no GL context: {exc}")
    yield r
    r.release()


@pytest.fixture
def bloom_renderer():
    try:
        r = Renderer(W, H, BG, BloomSettings(intensity=1.0, radius=24.0))
    except Exception as exc:
        pytest.skip(f"no GL context: {exc}")
    yield r
    r.release()


def frame(r: Renderer, rows: list[list[float]]) -> np.ndarray:
    arr = np.array(rows, dtype="f4").reshape(-1, 10)
    data = r.render(arr)
    assert len(data) == W * H * 3
    return np.frombuffer(data, dtype=np.uint8).reshape(H, W, 3)


def test_empty_is_background(renderer):
    img = frame(renderer, [])
    assert np.abs(img.astype(float) - BG_BYTES).max() <= 1


def test_orientation_top_left(renderer):
    img = frame(renderer, [[10, 5, 20, 10, 1, 0, 0, 1, 0, 0]])
    assert tuple(img[10, 20]) == (255, 0, 0)
    assert np.abs(img[40, 60].astype(float) - BG_BYTES).max() <= 1
    assert np.abs(img[2, 20].astype(float) - BG_BYTES).max() <= 1


def test_later_rows_on_top(renderer):
    a = [10, 10, 20, 20, 1, 0, 0, 1, 0, 0]
    b = [20, 20, 20, 20, 0, 1, 0, 1, 0, 0]
    assert tuple(frame(renderer, [a, b])[25, 25]) == (0, 255, 0)
    assert tuple(frame(renderer, [b, a])[25, 25]) == (255, 0, 0)


def test_growth_and_varying_n(renderer):
    rows = [[i % 60, i % 40, 2, 2, 1, 1, 1, 1, 0, 0] for i in range(5000)]
    img = frame(renderer, rows)
    assert img.max() == 255
    img = frame(renderer, rows[:3])
    assert img.shape == (H, W, 3)
    assert np.abs(frame(renderer, [])[0, 0].astype(float) - BG_BYTES).max() <= 1


def _dist_from_bg(img: np.ndarray) -> np.ndarray:
    return np.abs(img.astype(float) - BG_BYTES).max(axis=2)


def test_bloom_glow_lights_outside(bloom_renderer):
    rect = [28, 20, 8, 8, 1, 1, 1, 1, 0, 1]
    img = frame(bloom_renderer, [rect])
    assert tuple(img[24, 32]) == (255, 255, 255)
    # just outside the left edge and above the top edge
    assert _dist_from_bg(img)[24, 25] > 5
    assert _dist_from_bg(img)[17, 32] > 5


def test_bloom_no_glow_column_zero(bloom_renderer):
    rect = [28, 20, 8, 8, 1, 1, 1, 1, 0, 0]
    img = frame(bloom_renderer, [rect])
    assert tuple(img[24, 32]) == (255, 255, 255)
    assert _dist_from_bg(img)[24, 25] <= 1
    assert _dist_from_bg(img)[17, 32] <= 1


def test_no_bloom_leaves_outside_background(renderer):
    img = frame(renderer, [[28, 20, 8, 8, 1, 1, 1, 1, 0, 1]])
    assert _dist_from_bg(img)[24, 25] <= 1


def test_bloom_orientation_and_length(bloom_renderer):
    img = frame(bloom_renderer, [[10, 5, 20, 10, 1, 0, 0, 1, 0, 1]])
    assert tuple(img[10, 20]) == (255, 0, 0)
    # glow appears near the rect (top-left), not at the opposite corner
    assert img[3, 20, 0] > img[44, 20, 0] + 5
    assert np.abs(img[44, 62].astype(float) - BG_BYTES).max() <= 3


def test_bloom_empty_and_growth(bloom_renderer):
    img = frame(bloom_renderer, [])
    assert np.abs(img.astype(float) - BG_BYTES).max() <= 1
    frame(bloom_renderer, [[1, 1, 5, 5, 1, 1, 1, 1, 0, 1]] * 3000)
