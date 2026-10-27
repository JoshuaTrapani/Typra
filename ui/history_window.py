# ui/history_window.py
"""History browser: search, copy, re-paste past transcriptions."""
from __future__ import annotations
import sys
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)
from db.history import HistoryStore
from ui.clipboard import copy_private


def _is_dark() -> bool:
    if sys.platform != "win32": return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k)
        return v == 0
    except Exception: return True


def _qss(dark: bool) -> str:
    bg = "#16161c" if dark else "#f5f5f7"
    bg2 = "#1e1e28" if dark else "#ffffff"
    border = "#3a3a50" if dark else "#d0d0d8"
    text = "#e0e0e8" if dark else "#1a1a2e"
    sel = "#2a2a45" if dark else "#c8d0f0"
    dim = "#606078" if dark else "#808090"
    btn = "#2a2a38" if dark else "#e8e8f0"
    return f"""
QWidget {{ background:{bg}; color:{text}; font-family:"Segoe UI",Arial; font-size:13px; }}
QLineEdit {{ background:{bg2}; border:1px solid {border}; border-radius:6px;
             padding:5px 10px; color:{text}; }}
QListWidget {{ background:{bg2}; border:1px solid {border}; border-radius:6px;
               outline:none; padding:4px; }}
QListWidget::item {{ border-radius:4px; padding:6px 10px; color:{text}; }}
QListWidget::item:selected {{ background:{sel}; }}
QListWidget::item:hover:!selected {{ background:{bg}; }}
QTextEdit {{ background:{bg2}; border:1px solid {border}; border-radius:6px;
             padding:6px; color:{text}; }}
QPushButton {{ background:{btn}; border:1px solid {border}; border-radius:5px;
               color:{text}; font-size:11px; min-height:26px; padding:0 12px; }}
QPushButton:hover {{ background:{sel}; border-color:#5a5a80; }}
QLabel#title {{ font-size:16px; font-weight:bold; color:{text}; }}
QLabel#count {{ font-size:11px; color:{dim}; }}
QScrollBar:vertical {{ background:{bg}; width:6px; border-radius:3px; }}
QScrollBar::handle:vertical {{ background:{border}; border-radius:3px; min-height:20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
"""


class HistoryWindow(QWidget):
    """Browse, search, copy, delete transcription history."""

    paste_requested = pyqtSignal(str)   # re-paste a past entry

    def __init__(self, store: HistoryStore, app_icon: QIcon, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._store = store
        self.setWindowTitle("Typra: History")
        self.setWindowIcon(app_icon)
        self.setMinimumSize(520, 480)
        self._dark = _is_dark()
        self.setStyleSheet(_qss(self._dark))
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        t = QLabel("Transcription History"); t.setObjectName("title")
        hdr.addWidget(t); hdr.addStretch()
        self._count_lbl = QLabel(""); self._count_lbl.setObjectName("count")
        hdr.addWidget(self._count_lbl)
        root.addLayout(hdr)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search transcriptions…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        root.addWidget(self._search)

        # List + preview split
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        root.addWidget(self._list, stretch=2)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("Select an entry to preview…")
        self._preview.setMaximumHeight(120)
        root.addWidget(self._preview)

        # Buttons
        btns = QHBoxLayout()
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.clicked.connect(self._copy)
        self._paste_btn = QPushButton("Paste")
        self._paste_btn.clicked.connect(self._paste)
        self._del_btn = QPushButton("Delete")
        self._del_btn.clicked.connect(self._delete)
        clr_btn = QPushButton("Clear all")
        clr_btn.clicked.connect(self._clear_all)
        for b in [self._copy_btn, self._paste_btn, self._del_btn, clr_btn]:
            # A focused button is "clicked" by every space typed into it
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btns.addWidget(b)
        btns.addStretch()
        root.addLayout(btns)

    def _load(self, query: str = "") -> None:
        self._list.clear()
        rows = self._store.search(query)
        self._count_lbl.setText(f"{len(rows)} entries")
        for row in rows:
            ts   = row["timestamp"].replace("T", "  ")[:16]
            lang = row["language"].upper()
            preview = row["text"][:60].replace("\n", " ")
            if len(row["text"]) > 60: preview += "…"
            item = QListWidgetItem(f"[{lang}]  {ts}    {preview}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)

    def refresh(self) -> None:
        self._load(self._search.text())

    def _on_search(self, text: str) -> None:
        QTimer.singleShot(200, lambda: self._load(text))

    def _on_select(self, item: QListWidgetItem) -> None:
        if item:
            row = item.data(Qt.ItemDataRole.UserRole)
            self._preview.setPlainText(row["text"] if row else "")

    def _current_row(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _copy(self) -> None:
        row = self._current_row()
        if row:
            copy_private(row["text"])

    def _paste(self) -> None:
        row = self._current_row()
        if row:
            # Typing now would go into this window. Hide it first so the
            # previous window gets focus back, then type there.
            text = row["text"]
            self.hide()
            QTimer.singleShot(400, lambda: self.paste_requested.emit(text))

    def _delete(self) -> None:
        row = self._current_row()
        if row:
            self._store.delete(row["id"])
            self._load(self._search.text())

    def _clear_all(self) -> None:
        if QMessageBox.question(
            self, "Clear history",
            "Delete all transcription history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._store.clear_all()
            self._load()
            self._preview.clear()

    def closeEvent(self, e) -> None:
        e.ignore(); self.hide()
