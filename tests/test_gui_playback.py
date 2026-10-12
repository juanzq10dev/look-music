from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import dataclasses

import pretty_midi
import pytest

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication

from look_music.cli import main as cli_main
from look_music.gui.export_worker import ExportWorker
from look_music.gui.main_window import MainWindow
from look_music.gui.preview_widget import PreviewWidget
from look_music.gui.settings_panel import SettingsPanel
from look_music.preset import Preset


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    try:
        import moderngl

        moderngl.create_standalone_context(require=330).release()
    except Exception as exc:
        pytest.skip(f"no OpenGL context: {exc}")
    return app


@pytest.fixture
def midi_path(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=1.0))
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=67, start=0.5, end=1.5))
    pm.instruments.append(inst)
    path = tmp_path / "song.mid"
    pm.write(str(path))
    return path


@pytest.fixture
def window(qapp, midi_path):
    w = MainWindow(audio_enabled=False)
    w.playback_tab.open_midi(midi_path)
    yield w
    w.close()


def test_preview_widget_set_frame(qapp):
    widget = PreviewWidget()
    assert widget.current_image() is None
    widget.set_frame(bytes(64 * 36 * 3), 64, 36)
    image = widget.current_image()
    assert (image.width(), image.height()) == (64, 36)


def test_tick_and_seek_change_frame(window):
    tab = window.playback_tab
    tab.tick()
    image = tab.preview.current_image()
    assert (image.width(), image.height()) == (1280, 720)
    first = bytes(image.constBits())
    tab.seek(1.5)  # a note is falling / sounding here
    assert bytes(tab.preview.current_image().constBits()) != first
    assert tab.time_label.text().startswith("0:01")


def test_settings_panel_emits_on_change(qapp):
    panel = SettingsPanel(Preset())
    seen: list[Preset] = []
    panel.preset_changed.connect(seen.append)
    panel.color_mode.setCurrentText("pitch")
    assert seen[-1].color_mode == "pitch"
    panel.bloom.setChecked(False)
    assert seen[-1].bloom is False
    assert seen[-1].color_mode == "pitch"
    count = len(seen)
    panel.set_preset(dataclasses.replace(Preset(), color_mode="hand", bloom=True))
    assert len(seen) == count
    assert panel.color_mode.currentText() == "hand" and panel.bloom.isChecked()


def test_panel_change_updates_rendered_frame(window):
    tab = window.playback_tab

    def corner_pixel() -> tuple[int, int, int]:
        c = tab.preview.current_image().pixelColor(2, 2)
        return (c.red(), c.green(), c.blue())

    before = corner_pixel()
    window.settings.background.set_rgb((1.0, 0.0, 0.0))
    window.settings.background.changed.emit((1.0, 0.0, 0.0))
    assert window.preset.background == (1.0, 0.0, 0.0)
    assert corner_pixel() != before
    assert corner_pixel()[0] > 200


def test_export_worker_writes_mp4(window, tmp_path):
    out = tmp_path / "out.mp4"
    worker = window.playback_tab.start_export(out, 640, 360, 10, threaded=False)
    done: list[str] = []
    worker.finished.connect(done.append)
    worker.run()
    assert done == [str(out)]
    assert out.stat().st_size > 0


def test_export_cancel_removes_output(midi_path, tmp_path):
    out = tmp_path / "cancelled.mp4"
    worker = ExportWorker(midi_path, out, Preset(), width=640, height=360, fps=10)
    errors: list[str] = []
    worker.failed.connect(errors.append)
    worker.cancel()
    worker.run()
    assert errors == ["Export cancelled"]
    assert not out.exists()


def test_cli_gui_help():
    with pytest.raises(SystemExit) as exc:
        cli_main(["gui", "--help"])
    assert exc.value.code == 0


# --- threaded export regressions -------------------------------------------------------------

import subprocess
import time

import numpy as np
from PySide6.QtCore import QEventLoop, QThread, QTimer, Slot
import imageio_ffmpeg

from look_music.cli import render as cli_render
from look_music.gui import export_worker, playback_tab as pt


def _wait_until(cond, timeout=60.0):
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    deadline = time.monotonic() + timeout
    poll.timeout.connect(lambda: loop.quit() if cond() or time.monotonic() > deadline else None)
    poll.start()
    loop.exec()
    poll.stop()
    return cond()


@pytest.fixture
def short_midi(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=64, start=0.2, end=1.2))
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=71, start=1.0, end=2.0))
    pm.instruments.append(inst)
    path = tmp_path / "short.mid"
    pm.write(str(path))
    return path


@pytest.fixture
def tab_window(qapp, short_midi):
    w = MainWindow(audio_enabled=False)
    w.playback_tab.open_midi(short_midi)
    yield w
    w.close()


def _decode_audio(path):
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    raw = subprocess.run(
        [exe, "-v", "error", "-i", str(path), "-vn", "-af", "aresample=async=1:first_pts=0", "-f", "s16le", "-ac", "1", "-ar", "44100", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2")


class _SpyDialog:
    """Stands in for QProgressDialog and records the thread each call runs on."""

    def __init__(self, app):
        self.app = app
        self.calls: list[tuple[str, bool]] = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, QThread.currentThread() is self.app.thread()))
        return call


def test_threaded_export_slots_run_in_gui_thread(qapp, tab_window, tmp_path):
    tab = tab_window.playback_tab
    spy = _SpyDialog(qapp)
    tab._export_progress = spy
    out = tmp_path / "t.mp4"
    tab.start_export(out, 320, 180, 10)
    assert _wait_until(lambda: tab._export_thread is None)
    assert out.stat().st_size > 0
    names = {n for n, _ in spy.calls}
    assert {"setLabelText", "setMaximum", "setValue", "close"} <= names
    assert all(in_gui for _, in_gui in spy.calls)
    assert tab._export_progress is None
    assert tab._timer.isActive()


def test_threaded_export_closes_real_dialog(qapp, tab_window, tmp_path):
    tab = tab_window.playback_tab
    out = tmp_path / "d.mp4"
    tab.run_export(out, 320, 180, 10)
    assert tab._export_progress is not None
    assert _wait_until(lambda: tab._export_thread is None)
    assert tab._export_progress is None
    assert out.stat().st_size > 0


def test_export_audio_alignment_matches_cli(tab_window, short_midi, tmp_path):
    out = tmp_path / "gui.mp4"
    worker = tab_window.playback_tab.start_export(out, 320, 180, 10, threaded=False)
    worker.audio = True
    worker.run()
    ref = tmp_path / "cli.mp4"
    cli_render(
        short_midi, ref, width=320, height=180, fps=10, preset=Preset(),
        lead_in=1.0, tail=1.0, crf=18, audio=True,
    )
    a, b = _decode_audio(out), _decode_audio(ref)
    first = lambda x: int(np.argmax(np.abs(x) > 200))
    assert abs(first(a) - first(b)) < 4410  # within one frame
    assert abs(len(a) - len(b)) < 4410
    assert first(a) > 44100  # lead-in respected


def test_cancel_during_audio_prep(tab_window, tmp_path, monkeypatch):
    out = tmp_path / "c.mp4"
    tab = tab_window.playback_tab
    worker = tab.start_export(out, 320, 180, 10, threaded=False)
    worker.audio = True
    real = export_worker.synthesize

    def slow(*args, **kwargs):
        worker.cancel()
        return real(*args, **kwargs)

    monkeypatch.setattr(export_worker, "synthesize", slow)
    errors: list[str] = []
    stages: list[str] = []
    worker.failed.connect(errors.append)
    worker.stage.connect(stages.append)
    worker.run()
    assert errors == ["Export cancelled"]
    assert stages == ["Preparing audio…"]
    assert not out.exists()


def test_shutdown_during_running_export(qapp, short_midi, tmp_path):
    w = MainWindow(audio_enabled=False)
    tab = w.playback_tab
    tab.open_midi(short_midi)
    out = tmp_path / "s.mp4"
    tab.run_export(out, 640, 360, 30)
    assert tab._export_thread.isRunning()
    w.close()
    assert tab._export_thread is None
    assert not out.exists()
