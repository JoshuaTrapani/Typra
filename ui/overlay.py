# ui/overlay.py
"""
Recording overlay: a small panel at the bottom of the screen that never
steals focus. It shows what Typra is doing (listening, transcribing with
progress, done), where the text will go, and the microphone level.

Three-layer focus protection:
 1. WS_EX_NOACTIVATE  — Windows won't activate this window
 2. WindowTransparentForInput — clicks go to the window underneath
 3. show_overlay()     — saves foreground HWND before show(), restores it
                         immediately if Qt's show() stole it
"""
from __future__ import annotations
import sys, math, random, time
from PyQt6.QtCore import QPoint, QPropertyAnimation, QEasingCurve, Qt, \
                         QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QBrush
from PyQt6.QtWidgets import QApplication, QWidget

_W       = 380
_H       = 62
_N_BARS  = 7
_BAR_W   = 3
_BAR_GAP = 6

# state -> (accent colour, default text)
_STATES = {
    "listening":    (QColor(255, 77, 79),  "Listening"),
    "recording":    (QColor(255, 77, 79),  "Recording"),
    "processing":   (QColor(245, 166, 35), "Processing…"),
    "transcribing": (QColor(245, 166, 35), "Transcribing…"),
    "done":         (QColor(46, 213, 115), "Done"),
    "warning":      (QColor(255, 159, 67), "Attention"),
    "error":        (QColor(255, 77, 79),  "Error"),
}


def _is_dark() -> bool:
    if sys.platform != "win32": return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k); return v == 0
    except Exception: return True


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class RecordingOverlay(QWidget):
    stop_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,  True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground,     True)
        self.setFixedSize(_W, _H)

        self._phase  = 0.0
        self._status = "listening"
        self._text   = ""          # overrides the state's default text
        self._target = ""          # where the text goes
        self._target_warn = False
        self._progress: float | None = None
        self._t0: float | None = None   # recording start, for the clock
        self._limit: float | None = None
        self._dark   = _is_dark()
        self._slide  = None
        self._level  = 0.0
        self._bar_h  = [random.uniform(0.1, 0.35) for _ in range(_N_BARS)]
        self._visible_wanted = False

        # Force native HWND creation NOW so WS_EX_NOACTIVATE is set
        # before the window is ever shown
        _ = self.winId()
        self._set_noactivate()

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_overlay)

    # ── Windows: prevent activation ──────────────────────────────────

    def _set_noactivate(self) -> None:
        if sys.platform != "win32": return
        try:
            import ctypes
            hwnd = int(self.winId())
            if not hwnd: return
            GWL_EXSTYLE       = -20
            WS_EX_NOACTIVATE  = 0x08000000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW  = 0x00000080
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                cur | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        except Exception as e:
            print(f"[Overlay] _set_noactivate: {e}")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._set_noactivate()   # re-apply after Qt may reset extended styles

    # ── Public API ───────────────────────────────────────────────────

    def set_level(self, rms: float) -> None:
        scaled = min(1.0, rms * 10.0)
        if scaled > self._level:
            self._level = scaled

    def set_status(self, s: str, text: str = "") -> None:
        """One of the _STATES keys; `text` replaces its default label."""
        if s in _STATES:
            self._status, self._text = s, text
            if s not in ("transcribing",):
                self._progress = None
            self.update()

    def set_target(self, text: str, warn: bool = False) -> None:
        self._target, self._target_warn = text, warn
        self.update()

    def set_progress(self, fraction: float | None) -> None:
        self._progress = fraction
        self.update()

    def start_clock(self, limit_seconds: float | None = None) -> None:
        self._t0, self._limit = time.monotonic(), limit_seconds

    def stop_clock(self) -> None:
        self._t0 = None

    def flash(self, status: str, text: str, ms: int = 2500) -> None:
        """Show a final message (e.g. 'Typed into Word'), then slide away."""
        self.stop_clock()
        self.set_status(status, text)
        if not self.isVisible() or not self._visible_wanted:
            self.show_overlay()
        self._hide_timer.start(ms)

    def refresh_theme(self) -> None:
        self._dark = _is_dark()
        self.update()

    # ── Show / hide ──────────────────────────────────────────────────

    def show_overlay(self) -> None:
        self._hide_timer.stop()
        self._dark  = _is_dark()
        self._level = 0.0
        if self._visible_wanted and self.isVisible():
            return
        self._visible_wanted = True

        screen = QApplication.primaryScreen().availableGeometry()
        x      = screen.x() + (screen.width() - _W) // 2
        y_show = screen.y() + screen.height() - _H - 24
        y_hide = screen.y() + screen.height() + 10

        # Save foreground window BEFORE showing
        prev_fg = 0
        if sys.platform == "win32":
            try:
                import ctypes
                prev_fg = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                pass

        self.move(x, y_hide)
        self.show()
        self._timer.start()

        # If show() stole focus, give it back immediately
        if sys.platform == "win32" and prev_fg:
            try:
                import ctypes
                own_hwnd = int(self.winId())
                if ctypes.windll.user32.GetForegroundWindow() == own_hwnd:
                    ctypes.windll.user32.SetForegroundWindow(prev_fg)
                    print("[Overlay] Restored focus to previous window")
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(QPoint(x, y_hide))
        anim.setEndValue(QPoint(x, y_show))
        anim.start(); self._slide = anim

    def hide_overlay(self) -> None:
        self._hide_timer.stop()
        if not self._visible_wanted:
            return
        self._visible_wanted = False
        self.stop_clock()
        screen = QApplication.primaryScreen().availableGeometry()
        y_hide = screen.y() + screen.height() + 10
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(self.x(), y_hide))
        anim.finished.connect(self._hidden)
        anim.start(); self._slide = anim

    def _hidden(self) -> None:
        if not self._visible_wanted:
            self._timer.stop()
            self.hide()

    # ── Tick ─────────────────────────────────────────────────────────

    def _tick(self) -> None:
        live = self._status in ("listening", "recording")
        speed       = 0.015 if live else 0.035
        self._phase = (self._phase + speed) % 1.0
        self._level = max(0.0, self._level - 0.05)

        for i in range(_N_BARS):
            idle = 0.18 + 0.12 * math.sin(
                self._phase * 2 * math.pi + i * (2 * math.pi / _N_BARS))
            target = (idle + random.random() * self._level * 0.82
                      if live and self._level > 0.04 else idle)
            target = min(1.0, max(0.0, target))
            k = 0.55 if target > self._bar_h[i] else 0.12
            self._bar_h[i] += (target - self._bar_h[i]) * k

        self.update()

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = float(_W), float(_H)
        r    = 10.0   # Windows 11 native corner radius

        # Clear to transparent
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(0, 0, _W, _H, Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        pill_bg = QColor(18, 18, 20) if self._dark else QColor(236, 236, 238)
        fg      = QColor(240, 240, 244) if self._dark else QColor(20, 20, 25)
        dim     = QColor(150, 150, 165) if self._dark else QColor(95, 95, 110)
        accent, default_text = _STATES.get(self._status, _STATES["listening"])

        path = QPainterPath()
        path.addRoundedRect(QRectF(1.0, 1.0, w - 2.0, h - 2.0), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(pill_bg))
        p.drawPath(path)

        # Level bars in the state colour (they also pulse while busy)
        x0, cy, max_bar_h = 16, _H // 2, _H - 26
        for i in range(_N_BARS):
            frac  = self._bar_h[i]
            bh    = max(3, int(3 + frac * (max_bar_h - 3)))
            c     = QColor(accent)
            c.setAlpha(int(120 + frac * 135))
            p.setBrush(QBrush(c))
            p.drawRoundedRect(x0 + i * _BAR_GAP, cy - bh // 2, _BAR_W, bh, 1, 1)

        # Text: state on the first line, destination on the second
        tx = x0 + _N_BARS * _BAR_GAP + 12
        right = _W - 14
        title = self._text or default_text
        clock = ""
        if self._t0 is not None:
            clock = _clock(time.monotonic() - self._t0)
            if self._limit:
                clock += f" / {_clock(self._limit)}"
        elif self._progress is not None:
            clock = f"{int(self._progress * 100)}%"

        f1 = QFont("Segoe UI", 10); f1.setBold(True)
        p.setFont(f1); p.setPen(fg)
        fm1 = QFontMetrics(f1)
        clock_w = fm1.horizontalAdvance(clock) + 10 if clock else 0
        p.drawText(QRectF(tx, 9, right - tx - clock_w, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm1.elidedText(title, Qt.TextElideMode.ElideRight, int(right - tx - clock_w)))
        if clock:
            p.setPen(dim)
            p.drawText(QRectF(right - clock_w, 9, clock_w, 20),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, clock)

        if self._target:
            f2 = QFont("Segoe UI", 9)
            p.setFont(f2)
            p.setPen(_STATES["warning"][0] if self._target_warn else dim)
            fm2 = QFontMetrics(f2)
            p.drawText(QRectF(tx, 31, right - tx, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm2.elidedText(self._target, Qt.TextElideMode.ElideRight, int(right - tx)))

        # Thin progress line along the bottom edge
        if self._progress is not None:
            track = QColor(dim); track.setAlpha(60)
            p.setBrush(QBrush(track))
            p.drawRoundedRect(QRectF(tx, h - 9, right - tx, 3), 1.5, 1.5)
            p.setBrush(QBrush(accent))
            p.drawRoundedRect(QRectF(tx, h - 9, (right - tx) * max(0.02, min(1.0, self._progress)), 3),
                              1.5, 1.5)
