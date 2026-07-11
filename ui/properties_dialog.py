"""
PDF file properties dialog.
"""
import os
from datetime import datetime

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox
from PyQt5.QtCore import Qt


def _fmt_size(size):
    for unit in ["bytes", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "bytes" else f"{size} bytes"
        size /= 1024
    return f"{size:.1f} GB"


class PropertiesDialog(QDialog):
    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Properties")
        self.resize(620, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{os.path.basename(tab.path)}</b>"))

        info = self._collect(tab)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setTextInteractionFlags(Qt.TextSelectableByMouse)
        view.setPlainText("\n".join(f"{k}: {v}" for k, v in info))
        layout.addWidget(view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _collect(self, tab):
        path = tab.path
        doc = tab.viewer.doc
        stat = os.stat(path)
        meta = doc.metadata or {}
        encrypted = "Yes" if getattr(doc, "is_encrypted", False) else "No"
        dirty = "Yes" if getattr(doc, "is_dirty", False) else "No"

        rows = [
            ("Path", path),
            ("File size", _fmt_size(stat.st_size)),
            ("Created", datetime.fromtimestamp(stat.st_ctime).isoformat(" ", "seconds")),
            ("Modified", datetime.fromtimestamp(stat.st_mtime).isoformat(" ", "seconds")),
            ("Pages", doc.page_count),
            ("Encrypted", encrypted),
            ("Unsaved changes", dirty),
            ("PDF format", getattr(doc, "pdf_version", "") or "Unknown"),
        ]
        for key in ["title", "author", "subject", "keywords", "creator",
                    "producer", "creationDate", "modDate"]:
            value = meta.get(key)
            if value:
                rows.append((key, value))
        return rows
