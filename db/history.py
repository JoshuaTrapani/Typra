# db/history.py
"""
Local SQLite transcription history.
Stores every transcription with timestamp, language, duration, text.
Zero telemetry: all data stays on device.
"""
from __future__ import annotations
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_DB_DIR  = Path.home() / ".whisper_dictation"
_DB_PATH = _DB_DIR / "history.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    language  TEXT    NOT NULL DEFAULT 'en',
    duration  REAL    NOT NULL DEFAULT 0.0,
    text      TEXT    NOT NULL,
    tone      TEXT    NOT NULL DEFAULT 'none'
);
CREATE INDEX IF NOT EXISTS idx_timestamp ON transcriptions (timestamp DESC);
"""


class HistoryStore:
    """Thread-safe SQLite wrapper for transcription history."""

    def __init__(self) -> None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # Overwrite deleted text instead of leaving it recoverable in the file
            self._conn.execute("PRAGMA secure_delete = ON")
            self._conn.executescript(_CREATE)
            self._conn.commit()
            # Databases from earlier versions still hold text deleted back then
            # in their free pages: rebuild them once.
            if self._conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                self._conn.execute("VACUUM")
                self._conn.execute("PRAGMA user_version = 1")

    def add(self, text: str, language: str = "en",
            duration: float = 0.0, tone: str = "none") -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO transcriptions (timestamp, language, duration, text, tone) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, language, duration, text, tone),
            )
            self._conn.commit()
            return cur.lastrowid

    def search(self, query: str = "", limit: int = 200) -> list[dict]:
        sql = ("SELECT * FROM transcriptions "
               + ("WHERE text LIKE ? ESCAPE '\\' " if query else "")
               + "ORDER BY timestamp DESC LIMIT ?")
        # Search literally: % and _ typed by the user are not wildcards
        pattern = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params = (f"%{pattern}%", limit) if query else (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def delete(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM transcriptions WHERE id=?", (row_id,))
            self._conn.commit()

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM transcriptions")
            self._conn.commit()
            self._conn.execute("VACUUM")   # rebuild the file without old pages

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
