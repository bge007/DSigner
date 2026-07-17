"""
PDF file properties dialog.
"""
import os
from datetime import datetime

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox
from PySide6.QtCore import Qt


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
        stat = os.stat(path)

        rows = [
            ("Path", path),
            ("File size", _fmt_size(stat.st_size)),
            ("Created", datetime.fromtimestamp(stat.st_ctime).isoformat(" ", "seconds")),
            ("Modified", datetime.fromtimestamp(stat.st_mtime).isoformat(" ", "seconds")),
        ]
        rows.extend(tab.viewer.document_info())
        return rows
