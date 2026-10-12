"""Record a live audio input to a WAV file, aligned to the shared session clock."""

from __future__ import annotations

import queue
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from look_music.live.clock import SessionClock

_STOP = object()


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) for every audio device that has input channels."""
    import sounddevice as sd

    return [
        (i, str(d["name"]))
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


class AudioRecorder:
    """Stream an input device into a 16-bit PCM WAV whose sample 0 is session time 0."""

    def __init__(
        self,
        path: str | Path,
        clock: SessionClock,
        device: int | str | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream_factory = stream_factory
        self.start_offset: float | None = None
        self.overflows = 0
        self._level = 0.0
        self._lock = threading.Lock()
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stream: Any = None
        self._writer: threading.Thread | None = None
        self._error: BaseException | None = None
        self._frames_written = 0
        self._drop = 0  # leading samples still to discard (negative start offset)
        self._first = True

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("AudioRecorder already started")
        factory = self._stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.InputStream
            info = sd.query_devices(self.device, "input")
            self.channels = max(1, min(self.channels, int(info["max_input_channels"])))
        self._wav = wave.open(str(self.path), "wb")
        self._wav.setnchannels(self.channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.sample_rate)
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()
        try:
            self._stream = factory(
                samplerate=self.sample_rate, channels=self.channels, dtype="float32",
                device=self.device, callback=self._callback, blocksize=0,
            )
            self._stream.start()
        except BaseException:
            self._queue.put(_STOP)
            self._writer.join()
            self._wav.close()
            self._stream = None
            raise

    def stop(self) -> float:
        """Stop capturing, finish the WAV, and return the recorded duration in seconds."""
        if self._stream is None:
            return self._frames_written / self.sample_rate
        stream, self._stream = self._stream, None
        stream.stop()
        stream.close()
        self._queue.put(_STOP)
        assert self._writer is not None
        self._writer.join()
        self._wav.close()
        if self._error is not None:
            raise RuntimeError(f"audio writer failed: {self._error}") from self._error
        return self._frames_written / self.sample_rate

    def level(self) -> float:
        """Peak absolute level (0..1) of the most recent block."""
        with self._lock:
            return self._level

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status and getattr(status, "input_overflow", False):
            self.overflows += 1
        block = np.array(indata, dtype=np.float32, copy=True)
        with self._lock:
            self._level = float(np.max(np.abs(block))) if block.size else 0.0
        if self._first:
            self._first = False
            # Align: WAV sample 0 must be session time 0. The first block's first sample
            # was captured at now - block length - input latency; pad or trim the gap.
            latency = getattr(self._stream, "latency", 0)
            if not isinstance(latency, (int, float)):
                latency = 0
            self.start_offset = self.clock.now() - frames / self.sample_rate - float(latency)
            pad = round(self.start_offset * self.sample_rate)
            if pad > 0:
                self._queue.put(np.zeros((pad, block.shape[1]), dtype=np.float32))
            elif pad < 0:
                self._drop = -pad
        # TODO: long-take drift correction could re-anchor on the audio sample count.
        if self._drop:
            cut = min(self._drop, len(block))
            self._drop -= cut
            block = block[cut:]
        if len(block):
            self._queue.put(block)

    def _write_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if self._error is not None:
                continue
            try:
                pcm = (np.clip(item, -1.0, 1.0) * 32767.0).astype("<i2")
                self._wav.writeframes(pcm.tobytes())
                self._frames_written += len(item)
            except BaseException as exc:
                self._error = exc

    def __enter__(self) -> AudioRecorder:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
