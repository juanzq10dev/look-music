"""Playback transport with the audio device as the master clock (wall clock when silent)."""

from __future__ import annotations

import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a PCM WAV; return float32 samples, shape (n,) for mono or (n, ch), and the rate."""
    with wave.open(str(path), "rb") as wf:
        channels, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = (ints << 8) >> 8  # sign-extend 24 -> 32 bits
        data = ints.astype(np.float32) / 8388608.0
    elif width == 4:
        data = (np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0).astype(
            np.float32
        )
    else:
        raise ValueError(f"unsupported sample width: {width} bytes")
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate


class Player:
    """Play/pause/seek over [0, duration]; position follows the audio device when there is audio."""

    def __init__(
        self,
        duration: float,
        samples: np.ndarray | None = None,
        sample_rate: int = 44100,
        stream_factory: Callable[..., Any] | None = None,
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.duration = float(duration)
        self._stream_factory = stream_factory
        self._time_fn = time_fn
        self._lock = threading.RLock()
        self._playing = False
        self._pos = 0.0  # position while paused (wall-clock mode: position at last anchor)
        self._floor = 0.0  # audio position never reads below the last seek/play point
        self._cursor = 0  # next audio frame to hand to the device
        self._t0 = 0.0  # wall-clock mode: time_fn() at the last anchor
        self._samples: np.ndarray | None = None
        self._sample_rate = sample_rate
        self._channels = 1
        self._stream: Any = None
        self._stream_key: tuple[int, int] | None = None
        self._set_samples(samples, sample_rate)

    def _set_samples(self, samples: np.ndarray | None, sample_rate: int) -> None:
        if samples is not None:
            samples = np.asarray(samples, dtype=np.float32)
            if samples.ndim == 1:
                samples = samples[:, None]
            self._channels = samples.shape[1]
        self._samples = samples
        self._sample_rate = sample_rate

    @property
    def playing(self) -> bool:
        with self._lock:
            self.position()  # settles a wall-clock run that reached the end
            return self._playing

    def position(self) -> float:
        """Current time in seconds, clamped to [0, duration]."""
        with self._lock:
            if not self._playing:
                return self._pos
            if self._samples is None:
                pos = self._pos + self._time_fn() - self._t0
                if pos >= self.duration:
                    self._playing = False
                    self._pos = self.duration
                    return self.duration
            else:
                latency = getattr(self._stream, "latency", 0.0)
                if not isinstance(latency, (int, float)):
                    latency = 0.0
                pos = max(self._cursor / self._sample_rate - float(latency), self._floor)
            return min(max(pos, 0.0), self.duration)

    def play(self) -> None:
        """Start from the current position; at the end, restart from 0."""
        with self._lock:
            if self.playing:
                return
            pos = self._pos
            self._anchor(0.0 if pos >= self.duration else pos)
            self._playing = True
            if self._samples is not None:
                self._ensure_stream()

    def pause(self) -> None:
        with self._lock:
            pos = self.position()
            self._playing = False
            self._pos = pos

    def toggle(self) -> None:
        with self._lock:
            if self.playing:
                self.pause()
            else:
                self.play()

    def seek(self, t: float) -> None:
        """Jump to `t` (clamped); keeps the playing state."""
        with self._lock:
            self._anchor(min(max(float(t), 0.0), self.duration))

    def set_audio(self, samples: np.ndarray | None, sample_rate: int) -> None:
        """Swap the audio (e.g. after changing SoundFont), keeping the position."""
        with self._lock:
            pos = self.position()
            self._set_samples(samples, sample_rate)
            self._anchor(pos)
            if self._samples is None:
                self._close_stream()
            elif self._playing:
                self._ensure_stream()

    def close(self) -> None:
        with self._lock:
            self.pause()
            self._close_stream()

    def _anchor(self, pos: float) -> None:
        self._pos = self._floor = pos
        self._cursor = int(round(pos * self._sample_rate))
        self._t0 = self._time_fn()

    # The stream stays open while paused and just emits silence without advancing the
    # cursor, so resuming is instant (no device restart latency).
    def _ensure_stream(self) -> None:
        key = (self._sample_rate, self._channels)
        if self._stream is not None and self._stream_key == key:
            return
        self._close_stream()
        factory = self._stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.OutputStream
        stream = factory(
            samplerate=self._sample_rate, channels=self._channels, dtype="float32",
            callback=self._callback,
        )
        stream.start()
        self._stream, self._stream_key = stream, key

    def _close_stream(self) -> None:
        stream, self._stream, self._stream_key = self._stream, None, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        try:
            outdata[:] = 0
            if not self._lock.acquire(timeout=0.005):
                return
            try:
                samples = self._samples
                if not self._playing or samples is None or samples.shape[1] != outdata.shape[1]:
                    return
                end = int(np.ceil(self.duration * self._sample_rate))
                lo = self._cursor
                hi = min(lo + frames, len(samples), end)
                if hi > lo:
                    outdata[: hi - lo] = samples[lo:hi]
                self._cursor = lo + frames
                if self._cursor >= end:
                    self._playing = False
                    self._pos = self.duration
            finally:
                self._lock.release()
        except Exception:
            pass
