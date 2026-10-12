from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import time  # noqa: E402

import moderngl  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from look_music.gui.live_tab import NO_AUDIO, LiveTab  # noqa: E402
from look_music.midi import load_midi  # noqa: E402


def _gl_available() -> bool:
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _gl_available(), reason="no GL context")


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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Rig:
    def __init__(self, tmp_path, ports=("Digital Piano",)):
        self.midi = FakeMidiIn(ports)
        self.streams: list[FakeInputStream] = []

        def stream_factory(**kw):
            s = FakeInputStream(**kw)
            self.streams.append(s)
            return s

        self.tab = LiveTab(
            midi_backend_factory=lambda: self.midi,
            audio_stream_factory=stream_factory,
            list_midi_ports=lambda: list(ports),
            list_audio_inputs=lambda: [(0, "Speakers In"), (3, "Microphone (Realtek(R) Audio)")],
            save_dir=tmp_path,
        )
        self.saved: list[tuple] = []
        self.tab.take_saved.connect(lambda m, w: self.saved.append((m, w)))

    def frame(self) -> bytes:
        img = self.tab.preview.current_image()
        assert img is not None
        return bytes(img.constBits())


@pytest.fixture
def rig(app, tmp_path):
    r = Rig(tmp_path)
    yield r
    r.tab.shutdown()


def test_no_ports(app, tmp_path):
    r = Rig(tmp_path, ports=())
    assert "connect the piano" in r.tab.status_label.text()
    r.tab.live_button.click()
    assert not r.tab.is_live
    assert "connect the piano" in r.tab.status_label.text()
    r.tab.shutdown()


def test_defaults_prefer_microphone(rig):
    assert "Microphone" in rig.tab.audio_combo.currentText()
    assert rig.tab.audio_combo.itemText(0) == NO_AUDIO


def test_live_renders_notes(rig):
    rig.tab.start_live()
    assert rig.tab.is_live and rig.tab.record_button.isEnabled()
    rig.tab.tick()
    before = rig.frame()
    rig.midi.send(0x90, 60, 100)
    rig.tab.tick()
    held = rig.frame()
    assert held != before
    assert "1 notes" in rig.tab.status_label.text()
    rig.midi.send(0x80, 60, 0)
    time.sleep(0.05)
    rig.tab.tick()
    assert rig.frame() != held


def test_record_with_audio(rig, tmp_path):
    rig.tab.start_live()
    rig.tab.start_recording()
    assert rig.tab.is_recording
    rig.midi.send(0x90, 60, 90)
    rig.streams[-1].feed(np.full((400, 2), 0.3, dtype=np.float32))
    time.sleep(0.03)
    rig.midi.send(0x80, 60, 0)
    rig.tab.tick()
    assert rig.tab.meter.value() > 0
    assert rig.tab.status_label.text().startswith("Recording")
    rig.tab.stop_recording()
    assert len(rig.saved) == 1
    midi_path, wav_path = rig.saved[0]
    assert midi_path.exists() and wav_path.exists()
    assert midi_path.parent == tmp_path
    assert [n.pitch for n in load_midi(midi_path).notes] == [60]
    assert rig.tab.is_live
    assert all(st.closed for st in rig.streams[:-1])
    assert not rig.streams[-1].closed  # level meter restarted after the take


def test_record_without_audio(rig):
    rig.tab.audio_combo.setCurrentIndex(0)
    rig.tab.start_live()
    rig.tab.start_recording()
    rig.midi.send(0x90, 62, 80)
    time.sleep(0.02)
    rig.midi.send(0x80, 62, 0)
    rig.tab.stop_recording()
    midi_path, wav_path = rig.saved[0]
    assert wav_path is None and not rig.streams
    assert [n.pitch for n in load_midi(midi_path).notes] == [62]


def test_stop_live_saves_active_take(rig):
    rig.tab.start_live()
    rig.tab.start_recording()
    rig.midi.send(0x90, 64, 80)
    time.sleep(0.02)
    rig.midi.send(0x80, 64, 0)
    rig.tab.live_button.click()
    assert not rig.tab.is_live and not rig.tab.is_recording
    assert len(rig.saved) == 1 and rig.saved[0][0].exists()
    assert rig.midi.closed


def test_shutdown_closes_port(rig):
    rig.tab.start_live()
    rig.tab.shutdown()
    assert rig.midi.closed
    assert not rig.tab.is_live


def _open(rig):
    return [s for s in rig.streams if not s.closed]


def test_meter_follows_audio_while_live(rig):
    rig.tab.start_live()
    assert len(_open(rig)) == 1
    rig.streams[-1].feed(np.full((400, 2), 0.5, dtype=np.float32))
    rig.tab.tick()
    assert rig.tab.meter.value() == 50


def test_record_swaps_meter_for_recorder(rig):
    rig.tab.start_live()
    rig.tab.start_recording()
    assert len(_open(rig)) == 1 and len(rig.streams) == 2
    rig.tab.stop_recording()
    assert len(_open(rig)) == 1 and len(rig.streams) == 3


def test_no_audio_stops_meter(rig):
    rig.tab.start_live()
    rig.tab.audio_combo.setCurrentIndex(0)
    assert not _open(rig)
    rig.tab.audio_combo.setCurrentIndex(2)
    assert len(_open(rig)) == 1
    rig.tab.stop_live()
    assert not _open(rig)


def test_meter_open_error_keeps_live(app, tmp_path):
    r = Rig(tmp_path)

    def boom(**kw):
        raise OSError("device busy")

    r.tab._audio_stream_factory = boom
    r.tab.start_live()
    r.tab.tick()
    assert r.tab.is_live
    assert "device busy" in r.tab.status_label.text()
    assert not r.tab.meter.isVisibleTo(r.tab)
    r.tab.shutdown()


def test_peak_hold_decay_and_clip():
    from look_music.gui.live_tab import PeakHold

    h = PeakHold()
    assert h.update(0.8, 0.0) == (80, False)
    assert h.update(0.0, 1.0) == (60, False)
    assert h.update(0.0, 10.0) == (0, False)
    assert h.update(1.0, 11.0) == (100, True)
    assert h.update(0.0, 11.5)[1] is True
    assert h.update(0.0, 12.1)[1] is False
