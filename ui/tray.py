# ui/tray.py
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


_TONE_LABELS = [
    ("none",         "None (raw)"),
    ("cleanup",      "Cleanup"),
    ("casual",       "Casual"),
    ("professional", "Professional"),
    ("concise",      "Concise"),
]

_MODE_LABELS = [
    ("live",     "Live (typed while you speak)"),
    ("complete", "Whole text (transcribed when you stop)"),
]


class SystemTray(QSystemTrayIcon):
    toggle_recording = pyqtSignal()
    open_settings    = pyqtSignal()
    open_history     = pyqtSignal()
    open_activity    = pyqtSignal()
    open_result      = pyqtSignal()
    quit_app         = pyqtSignal()
    tone_selected    = pyqtSignal(str)
    mode_selected    = pyqtSignal(str)

    def __init__(self, app_icon: QIcon, parent=None) -> None:
        super().__init__(parent)
        self._app_icon    = app_icon
        self._recording   = False
        self._loading     = True
        self._hotkey      = "Ctrl+Shift+Space"
        self._tone_actions: dict[str, object] = {}
        self._mode_actions: dict[str, object] = {}
        self.setIcon(app_icon)
        self.setToolTip("Typra: Loading...")
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        menu = QMenu()

        self._action_toggle = menu.addAction("Start Recording")
        self._action_toggle.setEnabled(False)
        self._action_toggle.triggered.connect(self.toggle_recording)

        menu.addSeparator()

        mode_menu = menu.addMenu("Dictation Mode")
        for code, label in _MODE_LABELS:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.triggered.connect(lambda _, c=code: self._on_mode_clicked(c))
            self._mode_actions[code] = a

        # Tone submenu — checkable actions so active tone gets a dot
        tone_menu = menu.addMenu("Tone Mode")
        for code, label in _TONE_LABELS:
            a = tone_menu.addAction(label)
            a.setCheckable(True)
            a.triggered.connect(lambda _, c=code: self._on_tone_clicked(c))
            self._tone_actions[code] = a

        menu.addSeparator()
        menu.addAction("Last Result...").triggered.connect(self.open_result)
        menu.addAction("History...").triggered.connect(self.open_history)
        menu.addAction("Activity...").triggered.connect(self.open_activity)
        menu.addAction("Settings").triggered.connect(self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Typra").triggered.connect(self.quit_app)
        self.setContextMenu(menu)

    def _on_tone_clicked(self, code: str) -> None:
        self.set_active_tone(code)
        self.tone_selected.emit(code)

    def _on_mode_clicked(self, code: str) -> None:
        self.set_active_mode(code)
        self.mode_selected.emit(code)

    def set_active_tone(self, code: str) -> None:
        """Update checkmark to reflect the active tone."""
        for c, action in self._tone_actions.items():
            action.setChecked(c == code)

    def set_active_mode(self, code: str) -> None:
        for c, action in self._mode_actions.items():
            action.setChecked(c == code)

    def set_hotkey_label(self, hotkey: str) -> None:
        self._hotkey = "+".join(k.capitalize() for k in hotkey.split("+"))
        self._update()

    def set_model_ready(self) -> None:
        self._loading = False
        self._action_toggle.setEnabled(True)
        self._update()

    def update_recording_state(self, recording: bool) -> None:
        self._recording = recording
        self._update()

    def _update(self) -> None:
        self.setIcon(self._app_icon)
        if self._loading:
            self.setToolTip("Typra: Loading model...")
        elif self._recording:
            self._action_toggle.setText("Stop Recording")
            self.setToolTip("Typra: Recording")
        else:
            self._action_toggle.setText("Start Recording")
            self.setToolTip(f"Typra: Ready  ({self._hotkey})")

    def _on_activated(self, reason) -> None:
        # A double-click delivers a Trigger first: reacting to both would
        # start and immediately stop recording.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_recording.emit()
