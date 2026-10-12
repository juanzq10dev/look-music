"""Playback tab: preview a MIDI file with audio, scrub, and export to video."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from look_music.audio import SAMPLE_RATE, render_soundfont, synthesize
from look_music.gui.export_worker import ExportWorker
from look_music.gui.preview_widget import PreviewWidget
from look_music.midi import Song, load_midi
from look_music.preset import Preset
from look_music.preview.frames import FrameSource
from look_music.preview.player import Player, load_wav

LEAD_IN = 1.0  # seconds of silence before the first note, as in the exported video
TAIL = 1.0
PREVIEW_SIZE = (1280, 720)
TICK_MS = 16
RESOLUTIONS = {"1280x720": (1280, 720), "1920x1080": (1920, 1080), "3840x2160": (3840, 2160)}
FPS_CHOICES = (30, 60)

SYNTH, SOUNDFONT, AUDIO_FILE = "Built-in synth", "SoundFont…", "Audio file…"


def _format_time(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


class _AudioSignals(QObject):
    ready = Signal(int, object, int)  # token, samples, sample rate
    failed = Signal(int, str)


class _AudioJob(QRunnable):
    """Prepares playback audio off the GUI thread."""

    def __init__(self, token: int, make: Callable[[], tuple[np.ndarray, int]]) -> None:
        super().__init__()
        self.token = token
        self.make = make
        self.signals = _AudioSignals()

    def run(self) -> None:
        try:
            samples, rate = self.make()
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc) or type(exc).__name__)
        else:
            self.signals.ready.emit(self.token, samples, rate)


def _delayed(samples: np.ndarray, rate: int, delay: float) -> np.ndarray:
    pad = np.zeros((int(round(delay * rate)), *samples.shape[1:]), dtype=np.float32)
    return np.concatenate([pad, samples])


class PlaybackTab(QWidget):
    """Preview, transport and export for one MIDI file."""

    export_running = Signal(bool)

    def __init__(
        self, parent: QWidget | None = None, preset: Preset | None = None,
        audio_enabled: bool = True,
    ) -> None:
        super().__init__(parent)
        self.preset = preset or Preset()
        self.audio_enabled = audio_enabled
        self.midi_path: Path | None = None
        self.song: Song | None = None
        self.frame_source: FrameSource | None = None
        self.player: Player | None = None
        self.soundfont: Path | None = (
            Path(os.environ["LOOK_MUSIC_SOUNDFONT"]) if os.environ.get("LOOK_MUSIC_SOUNDFONT") else None
        )
        self.audio_file: Path | None = None
        self._audio_token = 0
        self._pool = QThreadPool(self)
        self._pending_jobs: set[_AudioJob] = set()
        self._updating = False
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None

        self.preview = PreviewWidget()
        self.play_button = QPushButton("Play")
        self.play_button.setEnabled(False)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.time_label = QLabel("0:00 / 0:00")
        self.audio_source = QComboBox()
        self.audio_source.addItems([SYNTH, SOUNDFONT, AUDIO_FILE])
        self.status = QLabel("Open a MIDI file to start (File > Open MIDI…)")

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Audio:"))
        source_row.addWidget(self.audio_source)
        source_row.addWidget(self.status, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.preview, 1)
        layout.addLayout(controls)
        layout.addLayout(source_row)

        self.play_button.clicked.connect(self.toggle_play)
        self.slider.valueChanged.connect(self._on_slider)
        self.audio_source.activated.connect(self._on_audio_source)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_play)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    def open_midi(self, path: str | Path, audio_file: Path | None = None) -> None:
        """Load a MIDI file (and optionally a matching recording) for preview."""
        path = Path(path)
        song = load_midi(path).shifted(LEAD_IN)
        self._release()
        self.midi_path, self.song = path, song
        self.frame_source = FrameSource(song, self.preset, *PREVIEW_SIZE)
        self.player = Player(song.duration + TAIL)
        self.slider.setRange(0, round(self.player.duration * 1000))
        self.play_button.setEnabled(True)
        self.play_button.setText("Play")
        self.audio_file = Path(audio_file) if audio_file else None
        if self.audio_file is not None:
            self._set_source(AUDIO_FILE)
        elif self.audio_source.currentText() == AUDIO_FILE:
            self._set_source(SYNTH)
        self.status.setText(path.name)
        self._prepare_audio()
        self.tick()

    def set_preset(self, preset: Preset) -> None:
        self.preset = preset
        if self.frame_source is not None:
            self.frame_source.set_preset(preset)
            self.tick()

    def toggle_play(self) -> None:
        if self.player is None:
            return
        self.player.toggle()
        self.play_button.setText("Pause" if self.player.playing else "Play")

    def tick(self) -> None:
        """Render the frame for the current position and sync the transport widgets."""
        if self.player is None or self.frame_source is None:
            return
        t = self.player.position()
        fs = self.frame_source
        self.preview.set_frame(fs.frame(t), fs.width, fs.height)
        self._updating = True
        try:
            self.slider.setValue(round(t * 1000))
        finally:
            self._updating = False
        self.time_label.setText(f"{_format_time(t)} / {_format_time(self.player.duration)}")
        if not self.player.playing and self.play_button.text() == "Pause":
            self.play_button.setText("Play")

    def seek(self, t: float) -> None:
        if self.player is not None:
            self.player.seek(t)
            self.tick()

    def _on_slider(self, value: int) -> None:
        if not self._updating:
            self.seek(value / 1000)

    def _set_source(self, name: str) -> None:
        self.audio_source.setCurrentText(name)

    def _on_audio_source(self, _index: int) -> None:
        name = self.audio_source.currentText()
        if name == SOUNDFONT:
            start = str(self.soundfont or "")
            path, _ = QFileDialog.getOpenFileName(self, "Choose SoundFont", start, "SoundFont (*.sf2)")
            if not path:
                self._set_source(SYNTH)
                return
            self.soundfont = Path(path)
        elif name == AUDIO_FILE:
            path, _ = QFileDialog.getOpenFileName(self, "Choose audio file", "", "WAV audio (*.wav)")
            if not path:
                self._set_source(SYNTH if self.audio_file is None else AUDIO_FILE)
                return
            self.audio_file = Path(path)
        self._prepare_audio()

    def _audio_job(self) -> Callable[[], tuple[np.ndarray, int]]:
        song, source = self.song, self.audio_source.currentText()
        soundfont, audio_file = self.soundfont, self.audio_file

        def make() -> tuple[np.ndarray, int]:
            if source == AUDIO_FILE and audio_file is not None:
                samples, rate = load_wav(audio_file)
                return _delayed(samples, rate, LEAD_IN), rate
            if source == SOUNDFONT and soundfont is not None:
                return render_soundfont(song, soundfont, tail=TAIL), SAMPLE_RATE
            return synthesize(song, tail=TAIL), SAMPLE_RATE

        return make

    def _prepare_audio(self) -> None:
        self._audio_token += 1
        if not self.audio_enabled or self.song is None or self.player is None:
            return
        job = _AudioJob(self._audio_token, self._audio_job())
        job.setAutoDelete(False)
        queued = Qt.ConnectionType.QueuedConnection
        job.signals.ready.connect(self._on_audio_ready, queued)
        job.signals.failed.connect(self._on_audio_failed, queued)
        self._pending_jobs.add(job)
        self.player.set_audio(None, SAMPLE_RATE)
        self.status.setText("Preparing audio…")
        self._pool.start(job)

    @Slot(int, object, int)
    def _on_audio_ready(self, token: int, samples: object, rate: int) -> None:
        if token != self._audio_token or self.player is None:
            return
        self.player.set_audio(samples, rate)
        self.status.setText(self.midi_path.name if self.midi_path else "")

    @Slot(int, str)
    def _on_audio_failed(self, token: int, message: str) -> None:
        if token != self._audio_token:
            return
        self.status.setText(f"Audio unavailable: {message}")

    def _release(self) -> None:
        if self.player is not None:
            self.player.close()
            self.player = None
        if self.frame_source is not None:
            self.frame_source.close()
            self.frame_source = None

    def shutdown(self) -> None:
        self._stop_export()
        self._timer.stop()
        self._audio_token += 1
        self._pool.waitForDone(5000)
        self._release()

    def export_video(self) -> None:
        if self.midi_path is None:
            QMessageBox.information(self, "Export video", "Open a MIDI file first.")
            return
        dialog = _ExportDialog(self.midi_path.with_suffix(".mp4"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.run_export(*dialog.values())

    def run_export(self, output: Path, width: int, height: int, fps: int) -> ExportWorker:
        """Start a threaded export with a modal progress dialog."""
        progress = QProgressDialog("Preparing audio…", "Cancel", 0, 0, self)
        progress.setWindowTitle("Export video")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        self._export_progress = progress
        worker = self.start_export(output, width, height, fps)
        progress.canceled.connect(worker.cancel)
        progress.show()
        return worker

    @Slot(str)
    def _on_export_stage(self, text: str) -> None:
        if self._export_progress is not None:
            self._export_progress.setLabelText(text)

    @Slot(int, int)
    def _on_export_progress(self, done: int, total: int) -> None:
        if self._export_progress is not None:
            self._export_progress.setMaximum(total)
            self._export_progress.setValue(done)

    @Slot(str)
    def _on_export_finished(self, path: str) -> None:
        self._export_done(f"Saved {path}")

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self._export_done(message)

    def _export_done(self, message: str) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
            self._export_progress.deleteLater()
            self._export_progress = None
        self._join_export_thread(10000)
        self._export_worker = None
        self._timer.start()
        self.export_running.emit(False)
        self.status.setText(message)

    def _join_export_thread(self, timeout_ms: int) -> None:
        thread = self._export_thread
        if thread is None:
            return
        thread.quit()
        thread.wait(timeout_ms)
        thread.deleteLater()
        self._export_thread = None

    def _stop_export(self) -> None:
        """Cancel a running export and wait for its thread before resources go away."""
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._export_progress is not None:
            self._export_progress.close()
            self._export_progress = None
        self._join_export_thread(120000)
        self._export_worker = None

    def start_export(
        self, output: str | Path, width: int, height: int, fps: int, threaded: bool = True
    ) -> ExportWorker:
        """Build an export worker for the current song and, if `threaded`, start it on a QThread."""
        if self.midi_path is None:
            raise RuntimeError("no MIDI file is open")
        source = self.audio_source.currentText()
        worker = ExportWorker(
            self.midi_path, Path(output), self.preset, width=width, height=height, fps=fps,
            soundfont=self.soundfont if source == SOUNDFONT else None,
            audio_file=self.audio_file if source == AUDIO_FILE else None,
            lead_in=LEAD_IN, tail=TAIL,
        )
        if not threaded:
            return worker
        if self.player is not None:
            self.player.pause()
            self.play_button.setText("Play")
        self._timer.stop()
        self.export_running.emit(True)
        thread = QThread(self)
        worker.moveToThread(thread)
        queued = Qt.ConnectionType.QueuedConnection
        worker.stage.connect(self._on_export_stage, queued)
        worker.progress.connect(self._on_export_progress, queued)
        worker.finished.connect(self._on_export_finished, queued)
        worker.failed.connect(self._on_export_failed, queued)
        thread.started.connect(worker.run)
        self._export_thread = thread
        self._export_worker = worker
        thread.start()
        return worker


class _ExportDialog(QDialog):
    def __init__(self, default_output: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export video")
        self.output = QLineEdit(str(default_output))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.output, 1)
        row.addWidget(browse)
        self.resolution = QComboBox()
        self.resolution.addItems(list(RESOLUTIONS))
        self.fps = QComboBox()
        self.fps.addItems([str(f) for f in FPS_CHOICES])
        self.fps.setCurrentText("60")
        form = QFormLayout()
        form.addRow("Output", row)
        form.addRow("Resolution", self.resolution)
        form.addRow("Frame rate", self.fps)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export video", self.output.text(), "MP4 video (*.mp4)")
        if path:
            self.output.setText(path)

    def values(self) -> tuple[Path, int, int, int]:
        width, height = RESOLUTIONS[self.resolution.currentText()]
        return Path(self.output.text()), width, height, int(self.fps.currentText())
