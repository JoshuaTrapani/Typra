# input/hotkey.py
"""
Global hotkey manager — toggle mode only.
suppress=False at all times so the keyboard works normally everywhere.
"""
from __future__ import annotations
import threading
from PyQt6.QtCore import QObject, pyqtSignal

_KEY_MAP = {
    "ctrl": "<ctrl>", "shift": "<shift>", "alt": "<alt>",
    "win": "<cmd>", "space": "<space>", "tab": "<tab>",
    **{f"f{i}": f"<f{i}>" for i in range(1, 13)},
}

DEFAULT_HOTKEY = "ctrl+shift+space"
_F_KEYS = {f"f{i}" for i in range(1, 13)}
_ALLOWED_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {"space", "tab"} | _F_KEYS


def is_safe_hotkey(combo: str) -> bool:
    """Ctrl, Alt or Win plus a letter, digit, Space or Tab, or an F-key alone:
    a combination that never occurs while typing (or while Typra types)."""
    parts = [p.strip().lower() for p in combo.split("+")]
    key, mods = parts[-1], set(parts[:-1])
    if key not in _ALLOWED_KEYS or not mods <= {"ctrl", "shift", "alt", "win"}:
        return False
    return key in _F_KEYS or bool(mods & {"ctrl", "alt", "win"})


def _to_pynput(key_str: str) -> str:
    parts = [p.strip().lower() for p in key_str.split("+")]
    return "+".join(_KEY_MAP.get(p, p) for p in parts)


class HotkeyManager(QObject):
    """Fires `activated` each time the combo is pressed (toggle mode only)."""
    activated = pyqtSignal()

    def __init__(self, hotkey_str: str = "ctrl+shift+space", parent=None) -> None:
        super().__init__(parent)
        self._hotkey_str = hotkey_str
        self._listener   = None

    def start(self) -> None:
        self._stop()
        pynput_key = _to_pynput(self._hotkey_str)
        print(f"[Hotkey] Listening for '{pynput_key}'")
        try:
            from pynput import keyboard as kb
            self._listener = kb.GlobalHotKeys({pynput_key: self._on_activate})
            t = threading.Thread(target=self._listener.run, daemon=True,
                                 name="HotkeyListener")
            t.start()
        except Exception as e:
            print(f"[Hotkey] Error: {e}")

    def stop(self) -> None:
        self._stop()

    def update(self, hotkey_str: str, mode: str = "toggle") -> None:
        """mode arg accepted but ignored — always toggle."""
        self._hotkey_str = hotkey_str
        self.start()

    def _on_activate(self) -> None:
        self.activated.emit()

    def _stop(self) -> None:
        if self._listener:
            try: self._listener.stop()
            except Exception: pass
            self._listener = None
