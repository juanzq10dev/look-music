"""Widget that shows RGB24 preview frames scaled to fit."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class PreviewWidget(QWidget):
    """Shows RGB24 frames scaled to fit (aspect preserved, letterboxed on black)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._data: bytes | None = None
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, data: bytes, width: int, height: int) -> None:
        self._data = data  # QImage does not copy the buffer, so keep it alive
        self._image = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888)
        self.update()

    def current_image(self) -> QImage | None:
        return self._image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image is not None:
            size = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(0, 0, size.width(), size.height())
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self._image)
        painter.end()
