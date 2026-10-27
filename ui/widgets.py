# ui/widgets.py
"""
Custom widgets for Typra.
CheckBox: draws a real checkmark glyph when checked.
HotkeyRecorder: click to record a key combination.
"""
from __future__ import annotations
import sys
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QToolTip, QWidget

from input.hotkey import is_safe_hotkey


def _is_dark() -> bool:
    if sys.platform != "win32": return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k); return v == 0
    except Exception: return True


# ── CheckBox ───────────────────────────────────────────────────────────────────

class CheckBox(QAbstractButton):
    """
    Custom checkbox:
    - Unchecked: empty square outline
    - Checked:   same outline + bold white checkmark glyph
    No background fill — purely stroke-based.
    """

    stateChanged = pyqtSignal(int)   # 0 = unchecked, 2 = checked (Qt compat)

    _BOX   = 18   # px
    _GAP   = 8    # between box and label

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(lambda checked: self.stateChanged.emit(2 if checked else 0))

    def isChecked(self) -> bool:
        return self.isDown() or super().isChecked()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self.update()

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w  = self._BOX + self._GAP + fm.horizontalAdvance(self.text()) + 4
        return QSize(w, 28)

    def paintEvent(self, _) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        dark = _is_dark()
        border_color  = QColor("#3a3a50") if dark else QColor("#b0b0c0")
        check_color   = QColor("#5a8aff")
        text_color    = QColor("#e0e0e8") if dark else QColor("#1a1a2e")
        accent_border = QColor("#5a8aff")

        # Box dimensions
        bx = 0
        by = (self.height() - self._BOX) // 2
        bw = bh = self._BOX
        r  = 3

        # Box background — always transparent
        p.setPen(QPen(accent_border if self.isChecked() else border_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(bx + 1, by + 1, bw - 2, bh - 2, r, r)

        # Checkmark — only when checked
        if self.isChecked():
            pen = QPen(check_color, 2.5, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Tick: \ shape from lower-left to centre, then / up to top-right
            x0 = bx + 4; y0 = by + bh // 2
            xm = bx + 7; ym = by + bh - 5
            x1 = bx + bw - 4; y1 = by + 4
            p.drawLine(x0, y0, xm, ym)
            p.drawLine(xm, ym, x1, y1)

        # Label text
        p.setPen(QPen(text_color))
        p.setFont(self.font())
        text_x = bx + bw + self._GAP
        p.drawText(text_x, 0, self.width() - text_x, self.height(),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())


# ── HotkeyRecorder ─────────────────────────────────────────────────────────────

class HotkeyRecorder(QWidget):
    """
    Click to start recording. Press desired key combo. Click again or
    press Enter/Escape to finish. Emits hotkey_recorded(str) on save.
    Format: "ctrl+shift+space", "ctrl+alt+r", etc.
    """

    hotkey_recorded = pyqtSignal(str)

    _MODIFIER_MAP = {
        Qt.Key.Key_Control: "ctrl",
        Qt.Key.Key_Shift:   "shift",
        Qt.Key.Key_Alt:     "alt",
        Qt.Key.Key_Meta:    "win",
    }
    _KEY_NAMES = {
        Qt.Key.Key_Space:  "space",
        Qt.Key.Key_Tab:    "tab",
        Qt.Key.Key_Return: "enter",
        Qt.Key.Key_Escape: "escape",
        **{getattr(Qt.Key, f"Key_F{i}"): f"f{i}" for i in range(1, 13)},
    }

    def __init__(self, initial: str = "ctrl+shift+space", parent=None) -> None:
        super().__init__(parent)
        self._current    = initial
        self._recording  = False
        self._mods: set[str] = set()
        self._key_str    = ""
        self.setFixedHeight(34)
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── Value ──────────────────────────────────────────────────────────

    def value(self) -> str:
        return self._current

    def setValue(self, hotkey: str) -> None:
        self._current = hotkey
        self.update()

    # ── Input handling ─────────────────────────────────────────────────

    def mousePressEvent(self, _) -> None:
        if not self._recording:
            self._recording = True
            self._mods.clear()
            self._key_str = ""
            self.setFocus()
        else:
            self._finish()
        self.update()

    def keyPressEvent(self, event) -> None:
        if not self._recording: return
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self._recording = False
            self._mods.clear(); self._key_str = ""
            self.update(); return

        if key in self._MODIFIER_MAP:
            self._mods.add(self._MODIFIER_MAP[key])
            self.update(); return

        if key == Qt.Key.Key_Return:
            self._finish(); return

        # Main key
        if key in self._KEY_NAMES:
            self._key_str = self._KEY_NAMES[key]
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            self._key_str = chr(key).lower()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self._key_str = chr(key)
        else:
            self._key_str = event.text().lower() or "?"

        self._finish()

    def keyReleaseEvent(self, event) -> None:
        key = event.key()
        if key in self._MODIFIER_MAP:
            self._mods.discard(self._MODIFIER_MAP[key])
            self.update()

    def _finish(self) -> None:
        if self._key_str:
            # Build combo: modifiers in fixed order + key
            order = ["ctrl", "shift", "alt", "win"]
            parts = [m for m in order if m in self._mods]
            parts.append(self._key_str)
            combo = "+".join(parts)
            if is_safe_hotkey(combo):
                self._current = combo
                self.hotkey_recorded.emit(combo)
            else:
                QToolTip.showText(
                    self.mapToGlobal(self.rect().bottomLeft()),
                    "Use Ctrl, Alt or Win with a letter, digit, Space or Tab, or an F-key.",
                    self)
        self._recording = False
        self._mods.clear()
        self._key_str = ""
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, _) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = _is_dark()

        bg     = QColor("#22222e") if dark else QColor("#ffffff")
        border = QColor("#5a8aff") if self._recording else (
                 QColor("#3a3a50") if dark else QColor("#d0d0d8"))
        text   = QColor("#e0e0e8") if dark else QColor("#1a1a2e")
        hint   = QColor("#5a8aff") if self._recording else (
                 QColor("#606078") if dark else QColor("#909090"))

        w, h = self.width(), self.height()
        r    = 6

        # Background
        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, 2))
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # Text
        if self._recording:
            # Show current modifier state
            order = ["ctrl", "shift", "alt", "win"]
            parts = [m for m in order if m in self._mods]
            display = "+".join(parts) + ("+" if parts else "") + "..."
            p.setPen(QPen(hint))
        else:
            display = self._current
            p.setPen(QPen(text))

        font = QFont("Segoe UI", 11)
        p.setFont(font)
        p.drawText(8, 0, w - 16, h, Qt.AlignmentFlag.AlignVCenter, display)

        # "Click to record" hint on right
        if not self._recording:
            p.setPen(QPen(hint))
            small = QFont("Segoe UI", 9)
            p.setFont(small)
            p.drawText(0, 0, w - 8, h,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       "click to change")
