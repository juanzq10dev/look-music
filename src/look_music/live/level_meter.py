"""Input level monitor: peak of the most recent audio block, without recording anything."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import numpy as np


class LevelMeter:
    """Opens an input stream and tracks the peak level (0..1) of the latest block."""

    def __init__(
        self,
        device: int | str | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream_factory = stream_factory
        self._stream: Any = None
        self._level = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._stream is not None:
            return
        factory = self._stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.InputStream
            info = sd.query_devices(self.device, "input")
            self.channels = max(1, min(self.channels, int(info["max_input_channels"])))
        stream = factory(
            samplerate=self.sample_rate, channels=self.channels, dtype="float32",
            device=self.device, callback=self._callback, blocksize=0,
        )
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        try:
            stream.stop()
        finally:
            stream.close()
        with self._lock:
            self._level = 0.0

    def level(self) -> float:
        """Peak absolute level (0..1) of the most recent block."""
        with self._lock:
            return self._level

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        peak = float(np.max(np.abs(indata))) if np.size(indata) else 0.0
        with self._lock:
            self._level = peak
