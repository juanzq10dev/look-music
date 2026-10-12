"""Background video export for the GUI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from look_music.audio import render_soundfont, synthesize, write_wav
from look_music.cli import render
from look_music.midi import load_midi
from look_music.preset import Preset


class _Cancelled(Exception):
    pass


class ExportWorker(QObject):
    """Renders a video via cli.render; run it in a QThread (or call run() directly)."""

    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)
    stage = Signal(str)

    def __init__(
        self,
        midi_path: Path,
        output: Path,
        preset: Preset,
        *,
        width: int,
        height: int,
        fps: int,
        soundfont: Path | None = None,
        audio_file: Path | None = None,
        audio: bool = True,
        lead_in: float = 1.0,
        tail: float = 1.0,
    ) -> None:
        super().__init__()
        self.midi_path = Path(midi_path)
        self.output = Path(output)
        self.preset = preset
        self.width, self.height, self.fps = width, height, fps
        self.soundfont = soundfont
        self.audio_file = audio_file
        self.audio = audio
        self.lead_in, self.tail = lead_in, tail
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        def on_progress(done: int, total: int) -> None:
            if self._cancelled:
                raise _Cancelled
            self.progress.emit(done, total)

        try:
            self._check_cancelled()
            with tempfile.TemporaryDirectory() as tmp:
                audio_file = self.audio_file
                if audio_file is None and self.audio:
                    self.stage.emit("Preparing audio…")
                    audio_file = self._prepare_audio(Path(tmp) / "audio.wav")
                    self._check_cancelled()
                self.stage.emit("Rendering frames…")
                render(
                    self.midi_path, self.output,
                    width=self.width, height=self.height, fps=self.fps, preset=self.preset,
                    lead_in=self.lead_in, tail=self.tail, crf=18, audio=audio_file is not None,
                    audio_file=audio_file, progress=on_progress,
                )
        except _Cancelled:
            self._remove_partial()
            self.failed.emit("Export cancelled")
        except Exception as exc:
            self._remove_partial()
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.finished.emit(str(self.output))

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise _Cancelled

    def _prepare_audio(self, wav_path: Path) -> Path:
        """Synthesize from the unshifted song: render() delays an audio file by lead_in itself."""
        song = load_midi(self.midi_path)
        samples = (
            render_soundfont(song, self.soundfont, tail=self.tail)
            if self.soundfont
            else synthesize(song, tail=self.tail)
        )
        write_wav(wav_path, samples)
        return wav_path

    def _remove_partial(self) -> None:
        try:
            if self.output.exists():
                os.remove(self.output)
        except OSError:
            pass
