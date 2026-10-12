from __future__ import annotations

import numpy as np
import pytest

from look_music.audio import write_wav
from look_music.preview.player import Player, load_wav

SR = 1000


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class FakeOutputStream:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def pull(self, frames: int) -> np.ndarray:
        out = np.full((frames, self.kwargs["channels"]), 9.0, dtype=np.float32)
        self.callback(out, frames, None, None)
        return out


def make_audio_player(duration=1.0, samples=None):
    streams: list[FakeOutputStream] = []

    def factory(**kwargs):
        streams.append(FakeOutputStream(**kwargs))
        return streams[-1]

    if samples is None:
        samples = np.arange(2000, dtype=np.float32) / 2000
    return Player(duration, samples, SR, stream_factory=factory), streams


def test_wall_clock_play_pause_seek():
    clock = FakeClock()
    p = Player(10.0, time_fn=clock)
    assert not p.playing and p.position() == 0.0
    p.play()
    clock.t += 2.5
    assert p.position() == pytest.approx(2.5)
    p.pause()
    clock.t += 5
    assert p.position() == pytest.approx(2.5)
    p.seek(7.0)
    assert not p.playing and p.position() == 7.0
    p.play()
    clock.t += 1
    p.seek(1.0)
    assert p.playing
    clock.t += 1
    assert p.position() == pytest.approx(2.0)
    p.toggle()
    assert not p.playing
    p.toggle()
    assert p.playing


def test_wall_clock_clamping_and_auto_pause():
    clock = FakeClock()
    p = Player(3.0, time_fn=clock)
    p.seek(-5)
    assert p.position() == 0.0
    p.seek(99)
    assert p.position() == 3.0
    p.seek(2.0)
    p.play()
    clock.t += 10
    assert p.position() == 3.0
    assert not p.playing


def test_play_at_end_restarts():
    clock = FakeClock()
    p = Player(3.0, time_fn=clock)
    p.seek(3.0)
    p.play()
    assert p.playing and p.position() == 0.0
    clock.t += 1
    assert p.position() == pytest.approx(1.0)
    clock.t += 10
    assert not p.playing
    p.play()
    assert p.position() == 0.0


def test_audio_stream_opened_lazily():
    p, streams = make_audio_player()
    assert streams == []
    p.play()
    assert len(streams) == 1 and streams[0].started
    assert streams[0].kwargs["samplerate"] == SR
    assert streams[0].kwargs["channels"] == 1
    assert streams[0].kwargs["dtype"] == "float32"


def test_audio_position_follows_callback():
    p, streams = make_audio_player(duration=1.5)
    p.play()
    out = streams[0].pull(100)
    np.testing.assert_allclose(out[:, 0], np.arange(100) / 2000)
    assert p.position() == pytest.approx(0.1)
    streams[0].pull(250)
    assert p.position() == pytest.approx(0.35)


def test_audio_position_subtracts_latency():
    p, streams = make_audio_player(duration=1.5)
    p.play()
    streams[0].latency = 0.05
    streams[0].pull(300)
    assert p.position() == pytest.approx(0.25)
    p.seek(0.5)
    assert p.position() == pytest.approx(0.5)  # never below the seek point


def test_audio_seek_moves_cursor():
    p, streams = make_audio_player(duration=1.5)
    p.play()
    streams[0].pull(100)
    p.seek(1.0)
    out = streams[0].pull(10)
    np.testing.assert_allclose(out[:, 0], np.arange(1000, 1010) / 2000)
    assert p.position() == pytest.approx(1.01)
    assert p.playing


def test_audio_end_zero_fills_and_pauses():
    samples = np.ones(1000, dtype=np.float32)
    p, streams = make_audio_player(duration=1.0, samples=samples)
    p.seek(0.9)
    p.play()
    out = streams[0].pull(300)
    assert np.all(out[:100] == 1.0) and np.all(out[100:] == 0.0)
    assert not p.playing
    assert p.position() == 1.0
    assert np.all(streams[0].pull(50) == 0.0)
    p.play()  # at end -> restart
    assert p.position() == 0.0
    assert np.all(streams[0].pull(10) == 1.0)


def test_audio_pause_stops_advancing():
    p, streams = make_audio_player(duration=1.5)
    p.play()
    streams[0].pull(200)
    p.pause()
    pos = p.position()
    assert pos == pytest.approx(0.2)
    assert np.all(streams[0].pull(200) == 0.0)
    assert p.position() == pos
    p.play()
    out = streams[0].pull(5)
    np.testing.assert_allclose(out[:, 0], np.arange(200, 205) / 2000)
    assert len(streams) == 1


def test_set_audio_keeps_position():
    p, streams = make_audio_player(duration=1.5)
    p.play()
    streams[0].pull(400)
    p.set_audio(np.full(2000, 0.5, dtype=np.float32), SR)
    assert p.position() == pytest.approx(0.4)
    out = streams[0].pull(10)
    assert np.all(out == 0.5)
    assert p.position() == pytest.approx(0.41)


def test_set_audio_to_none_uses_wall_clock():
    clock = FakeClock()
    p = Player(5.0, np.zeros(5000, dtype=np.float32), SR,
               stream_factory=lambda **kw: FakeOutputStream(**kw), time_fn=clock)
    p.seek(1.0)
    p.play()
    p.set_audio(None, SR)
    clock.t += 2
    assert p.position() == pytest.approx(3.0)


def test_stereo_output():
    samples = np.stack([np.full(1000, 0.25), np.full(1000, -0.5)], axis=1).astype(np.float32)
    p, streams = make_audio_player(duration=1.0, samples=samples)
    p.play()
    assert streams[0].kwargs["channels"] == 2
    out = streams[0].pull(20)
    assert out.shape == (20, 2)
    assert np.all(out[:, 0] == 0.25) and np.all(out[:, 1] == -0.5)


def test_load_wav_round_trip(tmp_path):
    samples = np.sin(np.linspace(0, 20, 500)).astype(np.float32) * 0.8
    path = tmp_path / "a.wav"
    write_wav(path, samples, 22050)
    data, rate = load_wav(path)
    assert rate == 22050
    assert data.shape == (500,) and data.dtype == np.float32
    np.testing.assert_allclose(data, samples, atol=1e-4)
