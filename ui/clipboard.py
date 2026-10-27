# ui/clipboard.py
"""Clipboard helper: dictated text copied by Typra is kept out of the Windows
clipboard history (Win+V) and is not synced to the cloud clipboard."""
from __future__ import annotations
from PyQt6.QtCore import QByteArray, QMimeData
from PyQt6.QtWidgets import QApplication

_DWORD_ZERO = QByteArray(b"\x00\x00\x00\x00")


def copy_private(text: str) -> None:
    mime = QMimeData()
    mime.setText(text)
    for fmt in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
        mime.setData(f'application/x-qt-windows-mime;value="{fmt}"', _DWORD_ZERO)
    QApplication.clipboard().setMimeData(mime)
