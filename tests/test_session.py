from __future__ import annotations

import threading
import time
import wave

import numpy as np
import pytest

from look_music.live.session import record_take
from look_music.midi import load_midi

RATE, BLOCK = 8000, 400


class FakeMidiIn:
    def __init__(self, ports=("Digital Piano",)):
        self.ports = list(ports)
        self.callback = None
        self.closed = False

    def get_ports(self):
        return self.ports

    def open_port(self, i):
        pass

    def set_callback(self, fn):
        self.callback = fn

    def ignore_types(self, **kw):
        pass

    def cancel_callback(self):
        self.callback = None

    def close_port(self):
        self.closed = True

    def send(self, *msg):
        self.callback((list(msg), 0.0), None)


class FakeInputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.latency = 0.0
        self.closed = False

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def feed(self, block):
        self.callback(block, len(block), None, None)


def _setup():
    backend = FakeMidiIn()
    streams = []

    def factory(**kwargs):
        s = FakeInputStream(**kwargs)
        streams.append(s)
        return s

    return backend, streams, factory


def _inject(backend, streams, done: threading.Event) -> threading.Thread:
    """Background thread playing two notes and feeding audio blocks."""

    def run():
        while not streams or backend.callback is None:
            if done.is_set():
                return
            time.sleep(0.005)
        stream = streams[0]
        script = [(0x90, 60, 90), None, (0x90, 64, 70), None, (0x80, 60, 0), (0x80, 64, 0)]
        for step in script:
            if done.is_set():
                return
            stream.feed(np.full((BLOCK, 2), 0.3, dtype=np.float32))
            if step:
                backend.send(*step)
            time.sleep(0.03)
        while not done.is_set():
            stream.feed(np.full((BLOCK, 2), 0.1, dtype=np.float32))
            time.sleep(0.03)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_record_take_saves_midi_and_audio(tmp_path):
    backend, streams, factory = _setup()
    done = threading.Event()
    t = _inject(backend, streams, done)
    statuses = []
    result = record_take(
        tmp_path / "t.mid", midi_port=0, audio_path=tmp_path / "t.wav", sample_rate=RATE,
        duration=0.5, on_status=lambda *a: statuses.append(a),
        midi_backend=backend, audio_stream_factory=factory, poll_interval=0.01,
    )
    done.set()
    t.join()
    assert result.midi_path.exists() and result.audio_path.exists()
    assert result.duration >= 0.5
    assert result.note_count == 2
    assert result.audio_start_offset is not None
    assert result.audio_overflows == 0
    song = load_midi(tmp_path / "t.mid")
    assert sorted((n.pitch, n.velocity) for n in song.notes) == [(60, 90), (64, 70)]
    starts = [n.start for n in song.notes]
    assert starts == sorted(starts) and starts[0] < starts[1]
    with wave.open(str(tmp_path / "t.wav"), "rb") as w:
        assert w.getnframes() > 0 and w.getframerate() == RATE
    assert statuses and statuses[-1][1] == 2 and statuses[-1][2] > 0
    assert backend.closed and streams[0].closed


def test_midi_only(tmp_path):
    backend, _, _ = _setup()
    result = record_take(
        tmp_path / "t.mid", midi_port="piano", duration=0.1,
        midi_backend=backend, poll_interval=0.01,
    )
    assert result.audio_path is None and result.audio_start_offset is None
    assert result.note_count == 0
    assert (tmp_path / "t.mid").exists()


def test_stop_event_stops_early(tmp_path):
    backend, _, _ = _setup()
    stop = threading.Event()
    timer = threading.Timer(0.1, stop.set)
    timer.start()
    result = record_take(
        tmp_path / "t.mid", midi_port=0, stop_event=stop, duration=30,
        midi_backend=backend, poll_interval=0.01,
    )
    timer.join()
    assert result.duration < 5


def test_keyboard_interrupt_still_saves(tmp_path):
    backend, streams, factory = _setup()
    done = threading.Event()
    t = _inject(backend, streams, done)

    def on_status(elapsed, notes, level):
        if notes >= 2:
            raise KeyboardInterrupt

    result = record_take(
        tmp_path / "t.mid", midi_port=0, audio_path=tmp_path / "t.wav", sample_rate=RATE,
        duration=30, on_status=on_status,
        midi_backend=backend, audio_stream_factory=factory, poll_interval=0.01,
    )
    done.set()
    t.join()
    assert result.duration < 10
    assert result.note_count == 2
    assert len(load_midi(tmp_path / "t.mid").notes) == 2
    assert streams[0].closed


def test_bad_port_closes_audio(tmp_path):
    backend, streams, factory = _setup()
    with pytest.raises(ValueError):
        record_take(
            tmp_path / "t.mid", midi_port="nope", audio_path=tmp_path / "t.wav",
            sample_rate=RATE, duration=1, midi_backend=backend, audio_stream_factory=factory,
        )
    assert streams[0].closed
