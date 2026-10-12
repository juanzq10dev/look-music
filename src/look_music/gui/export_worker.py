"""Background video export for the GUI."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from look_music.cli import render
from look_music.preset import Preset


class _Cancelled(Exception):
    pass


class ExportWorker(QObject):
    """Renders a video via cli.render; run it in a QThread (or call run() directly)."""

    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

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
            if self._cancelled:
                raise _Cancelled
            render(
                self.midi_path, self.output,
                width=self.width, height=self.height, fps=self.fps, preset=self.preset,
                lead_in=self.lead_in, tail=self.tail, crf=18, audio=self.audio,
                soundfont=self.soundfont, audio_file=self.audio_file, progress=on_progress,
            )
        except _Cancelled:
            self._remove_partial()
            self.failed.emit("Export cancelled")
        except Exception as exc:
            self._remove_partial()
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.finished.emit(str(self.output))

    def _remove_partial(self) -> None:
        try:
            if self.output.exists():
                os.remove(self.output)
        except OSError:
            pass
