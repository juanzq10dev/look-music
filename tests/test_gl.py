from __future__ import annotations

import numpy as np
import pytest

from look_music.render.gl import Renderer

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


def frame(r: Renderer, rows: list[list[float]]) -> np.ndarray:
    arr = np.array(rows, dtype="f4").reshape(-1, 9)
    data = r.render(arr)
    assert len(data) == W * H * 3
    return np.frombuffer(data, dtype=np.uint8).reshape(H, W, 3)


def test_empty_is_background(renderer):
    img = frame(renderer, [])
    assert np.abs(img.astype(float) - BG_BYTES).max() <= 1


def test_orientation_top_left(renderer):
    img = frame(renderer, [[10, 5, 20, 10, 1, 0, 0, 1, 0]])
    assert tuple(img[10, 20]) == (255, 0, 0)
    assert np.abs(img[40, 60].astype(float) - BG_BYTES).max() <= 1
    assert np.abs(img[2, 20].astype(float) - BG_BYTES).max() <= 1


def test_later_rows_on_top(renderer):
    a = [10, 10, 20, 20, 1, 0, 0, 1, 0]
    b = [20, 20, 20, 20, 0, 1, 0, 1, 0]
    assert tuple(frame(renderer, [a, b])[25, 25]) == (0, 255, 0)
    assert tuple(frame(renderer, [b, a])[25, 25]) == (255, 0, 0)


def test_growth_and_varying_n(renderer):
    rows = [[i % 60, i % 40, 2, 2, 1, 1, 1, 1, 0] for i in range(5000)]
    img = frame(renderer, rows)
    assert img.max() == 255
    img = frame(renderer, rows[:3])
    assert img.shape == (H, W, 3)
    assert np.abs(frame(renderer, [])[0, 0].astype(float) - BG_BYTES).max() <= 1
