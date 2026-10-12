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
