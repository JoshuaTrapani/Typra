# ui/language_picker.py
from __future__ import annotations
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

LANGUAGES = [
    ("en", "English"),
    ("de", "German"),
    ("fr", "French"),
]

class LanguagePicker(QWidget):
    language_selected = pyqtSignal(str)

    def __init__(self, active_code: str = "en", parent=None) -> None:
        super().__init__(parent)
        self._active = active_code if active_code in [c for c,_ in LANGUAGES] else "en"
        self._build()
        self._populate()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background: #1e1e28;
                border: 1px solid #3a3a50;
                border-radius: 6px;
                outline: none;
                padding: 4px;
            }
            QListWidget::item {
                border-radius: 5px;
                color: #e0e0e8;
                padding: 10px 14px;
                font-size: 13px;
            }
            QListWidget::item:selected {
                background: #2a2a45;
                color: #e0e0e8;
            }
            QListWidget::item:hover:!selected {
                background: #252535;
            }
        """)
        self._list.itemClicked.connect(self._on_click)
        root.addWidget(self._list)

    def _populate(self) -> None:
        self._list.clear()
        for code, name in LANGUAGES:
            label = f"  ✓  {name}" if code == self._active else f"      {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, code)
            if code == self._active:
                item.setBackground(QColor("#2a2a45"))
            self._list.addItem(item)
        self._list.setFixedHeight(len(LANGUAGES) * 46 + 10)

    def _on_click(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole)
        if code:
            self._active = code
            self._populate()
            self.language_selected.emit(code)

    def get_active_code(self) -> str:
        return self._active

    def set_active(self, code: str) -> None:
        self._active = code
        self._populate()
