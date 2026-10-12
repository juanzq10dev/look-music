"""Shared preset controls."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QPushButton,
    QSlider,
    QWidget,
)

from look_music.preset import COLOR_MODES, RGB, Preset

SLIDER_STEPS = 1000


def _to_qcolor(rgb: RGB) -> QColor:
    return QColor.fromRgbF(*rgb)


def _from_qcolor(color: QColor) -> RGB:
    return (color.redF(), color.greenF(), color.blueF())


class _ColorButton(QPushButton):
    """Button showing a colour; clicking opens a QColorDialog."""

    changed = Signal(object)

    def __init__(self, rgb: RGB) -> None:
        super().__init__()
        self.rgb = rgb
        self._refresh()
        self.clicked.connect(self._pick)

    def set_rgb(self, rgb: RGB) -> None:
        self.rgb = rgb
        self._refresh()

    def _refresh(self) -> None:
        color = _to_qcolor(self.rgb)
        self.setText(color.name().upper())
        fg = "black" if color.lightnessF() > 0.5 else "white"
        self.setStyleSheet(f"background-color: {color.name()}; color: {fg};")

    def _pick(self) -> None:
        color = QColorDialog.getColor(_to_qcolor(self.rgb), self)
        if color.isValid():
            self.set_rgb(_from_qcolor(color))
            self.changed.emit(self.rgb)


class _RangeSlider(QSlider):
    """Horizontal slider over a float range."""

    def __init__(self, low: float, high: float) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._low, self._high = low, high
        self.setRange(0, SLIDER_STEPS)

    def value_f(self) -> float:
        return self._low + (self._high - self._low) * self.value() / SLIDER_STEPS

    def set_value_f(self, value: float) -> None:
        frac = (value - self._low) / (self._high - self._low)
        self.setValue(round(min(max(frac, 0.0), 1.0) * SLIDER_STEPS))


class SettingsPanel(QWidget):
    """Edits the visual preset; emits a new Preset on every change."""

    preset_changed = Signal(object)

    def __init__(self, preset: Preset | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preset = preset or Preset()
        self._loading = False

        self.color_mode = QComboBox()
        self.color_mode.addItems(["auto", "track", "hand", "pitch"])
        self.left_color = _ColorButton(self._preset.left_hand_color)
        self.right_color = _ColorButton(self._preset.right_hand_color)
        self.background = _ColorButton(self._preset.background)
        self.seconds_visible = _RangeSlider(1.0, 8.0)
        self.keyboard_height = _RangeSlider(0.10, 0.30)
        self.bloom = QCheckBox("Enabled")
        self.bloom_intensity = _RangeSlider(0.0, 2.0)
        self.bloom_radius = _RangeSlider(4.0, 64.0)

        form = QFormLayout(self)
        form.addRow("Color mode", self.color_mode)
        form.addRow("Left hand", self.left_color)
        form.addRow("Right hand", self.right_color)
        form.addRow("Background", self.background)
        form.addRow("Fall time (s)", self.seconds_visible)
        form.addRow("Keyboard height", self.keyboard_height)
        form.addRow("Bloom", self.bloom)
        form.addRow("Bloom intensity", self.bloom_intensity)
        form.addRow("Bloom radius", self.bloom_radius)

        self.color_mode.currentTextChanged.connect(self._on_change)
        self.bloom.toggled.connect(self._on_change)
        for slider in (
            self.seconds_visible, self.keyboard_height, self.bloom_intensity, self.bloom_radius
        ):
            slider.valueChanged.connect(self._on_change)
        for button in (self.left_color, self.right_color, self.background):
            button.changed.connect(self._on_change)
        self.set_preset(self._preset)

    @property
    def preset(self) -> Preset:
        return self._preset

    def set_preset(self, preset: Preset) -> None:
        """Show `preset` in the controls without emitting."""
        self._loading = True
        try:
            self._preset = preset
            self.color_mode.setCurrentText(preset.color_mode)
            self.left_color.set_rgb(preset.left_hand_color)
            self.right_color.set_rgb(preset.right_hand_color)
            self.background.set_rgb(preset.background)
            self.seconds_visible.set_value_f(preset.seconds_visible)
            self.keyboard_height.set_value_f(preset.keyboard_height)
            self.bloom.setChecked(preset.bloom)
            self.bloom_intensity.set_value_f(preset.bloom_intensity)
            self.bloom_radius.set_value_f(preset.bloom_radius)
        finally:
            self._loading = False

    def _on_change(self, *_: object) -> None:
        if self._loading:
            return
        self._preset = dataclasses.replace(
            self._preset,
            color_mode=self.color_mode.currentText(),
            left_hand_color=self.left_color.rgb,
            right_hand_color=self.right_color.rgb,
            background=self.background.rgb,
            seconds_visible=self.seconds_visible.value_f(),
            keyboard_height=self.keyboard_height.value_f(),
            bloom=self.bloom.isChecked(),
            bloom_intensity=self.bloom_intensity.value_f(),
            bloom_radius=self.bloom_radius.value_f(),
        )
        self.preset_changed.emit(self._preset)
