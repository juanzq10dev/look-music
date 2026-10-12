from __future__ import annotations

import pytest

from look_music.live.clock import SessionClock


def test_now_before_start_raises():
    with pytest.raises(RuntimeError):
        SessionClock().now()


def test_now_increases():
    clock = SessionClock()
    clock.start()
    a = clock.now()
    b = clock.now()
    assert 0 <= a <= b


def test_to_session():
    clock = SessionClock()
    clock.start()
    assert clock.to_session(clock.t0 + 2.5) == pytest.approx(2.5)
