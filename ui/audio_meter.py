# ui/audio_meter.py
"""
AudioMeter: a custom QWidget that draws a horizontal RMS level bar.

Features
--------
- Smooth decay animation (independent timer, 50 ms tick)
- Colour gradient: green → yellow → red
- Peak hold indicator (white tick)
- Thread-safe: set_level() can be called from any thread via
  a queued connection on the `level_changed` signal
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class AudioMeter(QWidget):
    """Horizontal level meter with smooth decay and peak hold."""

    # Internal signal: allows safe cross-thread updates
    level_changed = pyqtSignal(float)

    # Visual colours
    _COLOR_BG = QColor(22, 22, 28)
    _COLOR_BORDER = QColor(55, 55, 65)
    _COLOR_PEAK = QColor(240, 240, 240, 210)

    # Decay / peak parameters
    _DECAY_FACTOR = 0.82        # Multiply level by this each tick (50 ms)
    _PEAK_DECAY = 0.018         # Subtract this from peak each tick
    _PEAK_HOLD_TICKS = 14       # Ticks to hold peak before it starts falling

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(180, 18)
        self.setMaximumHeight(22)

        self._level: float = 0.0
        self._peak: float = 0.0
        self._peak_hold: int = 0  # Remaining ticks before peak decays
        self._active: bool = False  # Dims the meter when not recording
        self._threshold: float = 0.0  # silence threshold mark (0 = none)

        # Decay timer
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._decay_tick)
        self._timer.start()

        # Connect signal to slot so cross-thread calls are safely queued
        self.level_changed.connect(self._apply_level, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_level(self, rms: float) -> None:
        """Thread-safe: emit signal so the update happens in the UI thread."""
        self.level_changed.emit(float(rms))

    def set_threshold(self, level: float) -> None:
        """Draw a mark where sound stops counting as silence (0..1)."""
        self._threshold = min(1.0, max(0.0, level))
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._level = 0.0
            self._peak = 0.0
        self.update()

    # ------------------------------------------------------------------
    # Qt slots
    # ------------------------------------------------------------------

    @pyqtSlot(float)
    def _apply_level(self, level: float) -> None:
        self._level = min(1.0, max(0.0, level))
        if self._level > self._peak:
            self._peak = self._level
            self._peak_hold = self._PEAK_HOLD_TICKS
        self.update()

    @pyqtSlot()
    def _decay_tick(self) -> None:
        changed = False

        if self._level > 0.001:
            self._level *= self._DECAY_FACTOR
            changed = True

        if self._peak_hold > 0:
            self._peak_hold -= 1
        elif self._peak > 0.001:
            self._peak -= self._PEAK_DECAY
            changed = True

        if changed:
            self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w = self.width()
        h = self.height()
        r = 3  # corner radius

        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._COLOR_BG)
        painter.drawRoundedRect(0, 0, w, h, r, r)

        alpha = 255 if self._active else 80

        if self._level > 0.002:
            fill_w = max(r * 2, int(w * self._level))
            gradient = QLinearGradient(0, 0, w, 0)
            gradient.setColorAt(0.0, QColor(46, 213, 115, alpha))
            gradient.setColorAt(0.55, QColor(253, 203, 64, alpha))
            gradient.setColorAt(1.0, QColor(220, 53, 69, alpha))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(0, 0, fill_w, h, r, r)

        # Peak hold marker
        if self._peak > 0.01:
            px = int(w * self._peak)
            pen = QPen(self._COLOR_PEAK)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(px, 1, px, h - 1)

        # Silence threshold: a dashed mark
        if self._threshold > 0:
            tx = int(w * self._threshold)
            pen = QPen(QColor(255, 255, 255, 150), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(tx, 0, tx, h)

        # Border
        painter.setPen(QPen(self._COLOR_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, w - 1, h - 1, r, r)
