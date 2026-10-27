# ui/activity.py
"""Activity log shown in Settings > Activity: what Typra did, how long it
took, and what went wrong. Never contains dictated text, only lengths."""
from __future__ import annotations
import collections, threading, time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class Entry:
    when: float
    level: str      # info | warning | error
    message: str

    def line(self) -> str:
        mark = {"warning": "!", "error": "✖"}.get(self.level, "·")
        return f"{time.strftime('%H:%M:%S', time.localtime(self.when))}  {mark} {self.message}"


class ActivityLog(QObject):
    """Thread-safe: add() may be called from any thread; listeners receive
    entry_added in the GUI thread."""
    entry_added = pyqtSignal(object)   # Entry
    stats_changed = pyqtSignal()

    def __init__(self, maxlen: int = 300) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._entries: collections.deque[Entry] = collections.deque(maxlen=maxlen)
        self._speeds: collections.deque[float] = collections.deque(maxlen=20)
        self.last_timing = ""   # e.g. "3.2 s of audio in 1.1 s"
        self.errors = 0

    def add(self, level: str, message: str) -> None:
        entry = Entry(time.time(), level, message)
        with self._lock:
            self._entries.append(entry)
            if level == "error":
                self.errors += 1
        print(f"[Activity] {level}: {message}")
        self.entry_added.emit(entry)

    def info(self, message: str) -> None:    self.add("info", message)
    def warning(self, message: str) -> None: self.add("warning", message)
    def error(self, message: str) -> None:   self.add("error", message)

    def record_timing(self, audio_s: float, total_s: float) -> None:
        """One transcription: audio length and processing time."""
        if audio_s > 0:
            with self._lock:
                self._speeds.append(total_s / audio_s)
        self.last_timing = f"{audio_s:.1f} s of audio in {total_s:.1f} s"
        self.stats_changed.emit()

    def average_speed(self) -> float | None:
        """Processing time per second of audio (lower is faster)."""
        with self._lock:
            return sum(self._speeds) / len(self._speeds) if self._speeds else None

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.errors = 0
        self.stats_changed.emit()
