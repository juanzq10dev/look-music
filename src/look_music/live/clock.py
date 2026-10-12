"""Session clock shared by MIDI and audio capture."""

from __future__ import annotations

import time


class SessionClock:
    """Shared monotonic clock for MIDI and audio capture (time.perf_counter based)."""

    def __init__(self) -> None:
        self.t0: float | None = None

    def start(self) -> None:
        self.t0 = time.perf_counter()

    def now(self) -> float:
        return self.to_session(time.perf_counter())

    def to_session(self, perf_time: float) -> float:
        if self.t0 is None:
            raise RuntimeError("SessionClock not started")
        return perf_time - self.t0
