from __future__ import annotations

import wave

import numpy as np
import pytest

from look_music.live.audio_capture import AudioRecorder, list_input_devices

RATE, BLOCK = 8000, 400


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


class FakeInputStream:
    def __init__(self, latency: float = 0.0, **kwargs) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.latency = latency
        self.running = False
        self.closed = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.closed = True

    def feed(self, block: np.ndarray, status=None) -> None:
        self.callback(block, len(block), None, status)


def _make(tmp_path, now: float, latency: float = 0.0, channels: int = 2):
    holder = {}

    def factory(**kwargs):
        holder["stream"] = FakeInputStream(latency=latency, **kwargs)
        return holder["stream"]

    rec = AudioRecorder(
        tmp_path / "a.wav", FakeClock(now), sample_rate=RATE, channels=channels,
        stream_factory=factory,
    )
    return rec, holder


def _block(value: float, channels: int = 2) -> np.ndarray:
    return np.full((BLOCK, channels), value, dtype=np.float32)


def _read(path):
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return w.getnchannels(), w.getframerate(), w.getsampwidth(), data.reshape(-1, w.getnchannels())


def test_basic_recording(tmp_path):
    rec, h = _make(tmp_path, now=BLOCK / RATE)  # offset exactly 0
    rec.start()
    for _ in range(5):
        h["stream"].feed(_block(0.5))
    duration = rec.stop()
    ch, rate, width, data = _read(tmp_path / "a.wav")
    assert (ch, rate, width) == (2, RATE, 2)
    assert len(data) == 5 * BLOCK
    assert duration == pytest.approx(5 * BLOCK / RATE)
    assert rec.start_offset == pytest.approx(0.0)
    assert h["stream"].kwargs["dtype"] == "float32"
    assert h["stream"].closed


def test_positive_offset_pads_silence(tmp_path):
    rec, h = _make(tmp_path, now=0.5 + BLOCK / RATE)
    rec.start()
    h["stream"].feed(_block(0.5))
    rec.stop()
    _, _, _, data = _read(tmp_path / "a.wav")
    pad = round(0.5 * RATE)
    assert len(data) == pad + BLOCK
    assert not data[:pad].any()
    assert data[pad:].all()
    assert rec.start_offset == pytest.approx(0.5)


def test_negative_offset_drops_samples(tmp_path):
    drop = 100
    rec, h = _make(tmp_path, now=(BLOCK - drop) / RATE)
    rec.start()
    h["stream"].feed(_block(0.5))
    h["stream"].feed(_block(0.25))
    rec.stop()
    _, _, _, data = _read(tmp_path / "a.wav")
    assert len(data) == 2 * BLOCK - drop


def test_negative_offset_spans_blocks(tmp_path):
    rec, h = _make(tmp_path, now=-0.1)  # offset = -0.1 - 0.05 -> drop 1200 samples
    rec.start()
    for _ in range(5):
        h["stream"].feed(_block(0.5))
    rec.stop()
    _, _, _, data = _read(tmp_path / "a.wav")
    assert len(data) == 5 * BLOCK - round(0.15 * RATE)


def test_latency_shifts_offset(tmp_path):
    rec, h = _make(tmp_path, now=BLOCK / RATE + 0.25, latency=0.25)
    rec.start()
    h["stream"].feed(_block(0.1))
    rec.stop()
    assert rec.start_offset == pytest.approx(0.0)
    assert len(_read(tmp_path / "a.wav")[3]) == BLOCK


def test_level_and_overflows(tmp_path):
    rec, h = _make(tmp_path, now=BLOCK / RATE)
    rec.start()
    assert rec.level() == 0.0
    blk = _block(0.1)
    blk[10, 0] = -0.75
    h["stream"].feed(blk)
    assert rec.level() == pytest.approx(0.75)
    h["stream"].feed(_block(0.2), status=type("S", (), {"input_overflow": True})())
    assert rec.level() == pytest.approx(0.2)
    assert rec.overflows == 1
    rec.stop()


def test_many_blocks_and_context_manager(tmp_path):
    rec, h = _make(tmp_path, now=BLOCK / RATE, channels=1)
    with rec:
        for _ in range(2000):
            h["stream"].feed(_block(0.3, 1))
    ch, _, _, data = _read(tmp_path / "a.wav")
    assert ch == 1
    assert len(data) == 2000 * BLOCK


def test_list_input_devices():
    devices = list_input_devices()
    assert isinstance(devices, list)
    assert all(isinstance(i, int) and isinstance(n, str) for i, n in devices)
