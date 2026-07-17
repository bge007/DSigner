"""
Dialog for PDF object details found with Ctrl+Alt+Click.
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox
from PySide6.QtCore import Qt


class ObjectInspectorDialog(QDialog):
    def __init__(self, details, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Object Inspector")
        self.resize(560, 440)

        layout = QVBoxLayout(self)
        title = QLabel(
            f"<b>{details.get('kind', 'Object')}</b> on page "
            f"{details.get('page', '')}")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lines = []
        for key, value in details.items():
            if key == "highlight_px":
                continue
            lines.append(f"{key}: {value}")
        view.setPlainText("\n".join(lines))
        layout.addWidget(view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
