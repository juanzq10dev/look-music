"""Main window: Playback and Live tabs sharing one preset and settings panel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from look_music.gui.playback_tab import PlaybackTab
from look_music.gui.settings_panel import SettingsPanel
from look_music.preset import Preset, load_preset


def _preset_to_json(preset: Preset) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, value in vars(preset).items():
        if isinstance(value, tuple) and value and isinstance(value[0], tuple):
            data[name] = [_hex(c) for c in value]
        elif isinstance(value, tuple):
            data[name] = _hex(value)
        else:
            data[name] = value
    return data


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb)


class MainWindow(QMainWindow):
    def __init__(
        self,
        audio_enabled: bool = True,
        live_tab_kwargs: dict | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("look-music")
        self.resize(1280, 800)
        self.preset = Preset()

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.playback_tab = PlaybackTab(preset=self.preset, audio_enabled=audio_enabled)
        self.tabs.addTab(self.playback_tab, "Playback")
        self.live_tab: Any = None
        try:
            from look_music.gui.live_tab import LiveTab

            self.live_tab = LiveTab(None, **(live_tab_kwargs or {}))
            self.live_tab.set_preset(self.preset)
            self.live_tab.take_saved.connect(self._open_take)
            self.tabs.addTab(self.live_tab, "Live")
        except ImportError:
            placeholder = QLabel("Live recording is not available.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabs.addTab(placeholder, "Live")

        self.settings = SettingsPanel(self.preset)
        self.settings.preset_changed.connect(self._on_preset_changed)
        dock = QDockWidget("Settings", self)
        dock.setWidget(self.settings)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        for text, slot, shortcut in (
            ("&Open MIDI…", self.open_midi_dialog, QKeySequence.StandardKey.Open),
            ("&Load preset…", self.load_preset_dialog, None),
            ("&Save preset…", self.save_preset_dialog, QKeySequence.StandardKey.Save),
            ("&Export video…", self.playback_tab.export_video, None),
            ("&Quit", self.close, QKeySequence.StandardKey.Quit),
        ):
            action = QAction(text, self)
            if shortcut is not None:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            menu.addAction(action)
            if text == "&Save preset…" or text == "&Export video…":
                menu.addSeparator()

    def set_preset(self, preset: Preset) -> None:
        """Apply `preset` to the panel and both tabs."""
        self.settings.set_preset(preset)
        self._on_preset_changed(preset)

    def _on_preset_changed(self, preset: Preset) -> None:
        self.preset = preset
        self.playback_tab.set_preset(preset)
        if self.live_tab is not None:
            self.live_tab.set_preset(preset)

    def open_midi(self, path: str | Path, audio_file: Path | None = None) -> None:
        try:
            self.playback_tab.open_midi(path, audio_file)
        except Exception as exc:
            QMessageBox.warning(self, "Open MIDI", f"Cannot open {path}:\n{exc}")
            return
        self.tabs.setCurrentWidget(self.playback_tab)

    def _open_take(self, midi_path: Path, wav_path: Path | None) -> None:
        self.open_midi(midi_path, wav_path)

    def open_midi_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open MIDI", "", "MIDI files (*.mid *.midi)")
        if path:
            self.open_midi(path)

    def load_preset_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON preset (*.json)")
        if not path:
            return
        try:
            preset = load_preset(path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Load preset", f"Invalid preset:\n{exc}")
            return
        self.set_preset(preset)

    def save_preset_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save preset", "preset.json", "JSON preset (*.json)")
        if path:
            Path(path).write_text(json.dumps(_preset_to_json(self.preset), indent=2), encoding="utf-8")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.playback_tab.shutdown()
        if self.live_tab is not None and hasattr(self.live_tab, "shutdown"):
            self.live_tab.shutdown()
        super().closeEvent(event)
