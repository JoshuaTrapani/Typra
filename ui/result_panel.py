# ui/result_panel.py
"""Result panel: shows dictated text that was not typed straight away
(whole-text mode, or the window changed during dictation). The user can
edit it, insert it into the window where the dictation started, or copy it.
It appears without taking the keyboard focus."""
from __future__ import annotations
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ui import winutil
from ui.clipboard import copy_private
from ui.settings_window import _is_dark, _qss


class ResultPanel(QWidget):
    insert_requested = pyqtSignal(str, int)   # text, target window

    def __init__(self, app_icon: QIcon, parent=None) -> None:
        super().__init__(parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle("Typra: Dictation result")
        self.setWindowIcon(app_icon)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(460)
        self._sid = 0
        self._target = 0
        self.setStyleSheet(_qss(_is_dark()))

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        title = QLabel("Dictation result"); title.setObjectName("AppTitle")
        v.addWidget(title)
        self._info = QLabel(); self._info.setObjectName("AppSub"); self._info.setWordWrap(True)
        v.addWidget(self._info)
        self._reason = QLabel(); self._reason.setWordWrap(True)
        self._reason.setStyleSheet("color: #e8a030; font-size: 11px;")
        v.addWidget(self._reason)
        self._edit = QPlainTextEdit()
        self._edit.setMinimumHeight(150)
        self._edit.setPlaceholderText("The transcribed text appears here.")
        v.addWidget(self._edit)
        self._where = QLabel(); self._where.setObjectName("Hint"); self._where.setWordWrap(True)
        v.addWidget(self._where)

        row = QHBoxLayout(); row.setSpacing(8)
        self._insert_btn = QPushButton("Insert"); self._insert_btn.setObjectName("Green")
        self._insert_btn.clicked.connect(self._insert)
        copy_btn = QPushButton("Copy"); copy_btn.setObjectName("Btn")
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton("Close"); close_btn.setObjectName("Btn")
        close_btn.clicked.connect(self.close)
        row.addWidget(self._insert_btn, 1); row.addWidget(copy_btn); row.addWidget(close_btn)
        v.addLayout(row)
        self._status = QLabel(); self._status.setObjectName("Hint"); self._status.setWordWrap(True)
        v.addWidget(self._status)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

    # ── Public API ───────────────────────────────────────────────────

    @property
    def session(self) -> int:
        return self._sid if self.isVisible() else 0

    def has_text(self) -> bool:
        return bool(self._edit.toPlainText().strip())

    def show_result(self, sid: int, text: str, target: int, info: str = "",
                    reason: str = "") -> None:
        """Show text for a session; more text for the same session is appended."""
        appending = self.isVisible() and sid == self._sid \
            and bool(self._edit.toPlainText().strip())
        if appending:
            self._edit.setPlainText(self._edit.toPlainText().rstrip() + " " + text)
        else:
            self._edit.setPlainText(text)
            self._status.clear()
            self._info.setText(info)
            self._reason.setText(reason)
        if appending and info:
            self._info.setText(info)
        if appending and reason:
            self._reason.setText(reason)
        self._info.setVisible(bool(self._info.text()))
        self._reason.setVisible(bool(self._reason.text()))
        self._sid, self._target = sid, target
        self._update_target()
        self._place()
        self.show()
        self.raise_()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def refresh_theme(self) -> None:
        self.setStyleSheet(_qss(_is_dark()))

    # ── Internals ────────────────────────────────────────────────────

    def _update_target(self) -> None:
        alive = winutil.is_window(self._target) and not winutil.is_own_window(self._target)
        app = winutil.app_name(self._target) if alive else ""
        if alive:
            self._where.setText(f"Dictation started in: {winutil.describe(self._target, 70)}")
            self._insert_btn.setText(f"Insert into {app or 'that window'}")
            self._insert_btn.setEnabled(True)
        else:
            self._where.setText("Click where the text should go, then use Copy and Ctrl+V.")
            self._insert_btn.setText("Insert")
            self._insert_btn.setEnabled(False)

    def _place(self) -> None:
        if self.isVisible():
            return
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24,
                  screen.bottom() - self.height() - 110)

    def _insert(self) -> None:
        text = self._edit.toPlainText().strip()
        if text:
            self.insert_requested.emit(text, self._target)

    def _copy(self) -> None:
        text = self._edit.toPlainText().strip()
        if not text:
            return
        copy_private(text)
        self._status.setText("Copied. Click where you want the text and press Ctrl+V.")

    def closeEvent(self, e) -> None:
        self._reason.clear()
        self._status.clear()
        super().closeEvent(e)

    def focus_text_later(self) -> None:
        QTimer.singleShot(0, self._edit.setFocus)
