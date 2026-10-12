"""GUI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from look_music.gui.main_window import MainWindow


def main(argv: list[str] | None = None, midi: Path | None = None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    window = MainWindow()
    window.show()
    if midi is not None:
        window.open_midi(midi)
    return app.exec()
