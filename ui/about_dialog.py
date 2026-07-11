"""
About dialog for DSigner.
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTextEdit,
                             QDialogButtonBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from core.app_info import (APP_DESCRIPTION, APP_NAME, APP_ORGANIZER,
                           APP_PUBLISHER, APP_VERSION)
from core.resources import resource_path


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.resize(520, 560)

        layout = QVBoxLayout(self)

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(resource_path("assets/logo.png"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToWidth(96, Qt.SmoothTransformation))
            layout.addWidget(logo)

        title = QLabel(f"<h2>{APP_NAME} {APP_VERSION}</h2>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        details = QLabel(
            f"{APP_DESCRIPTION}<br><br>"
            f"<b>Organised by:</b> {APP_ORGANIZER}<br>"
            f"<b>Publisher:</b> {APP_PUBLISHER}<br>"
            "<b>License:</b> MIT License")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(details)

        layout.addWidget(QLabel("<b>MIT License</b>"))
        license_view = QTextEdit()
        license_view.setReadOnly(True)
        try:
            with open(resource_path("LICENSE"), "r", encoding="utf-8") as f:
                license_view.setPlainText(f.read())
        except OSError:
            license_view.setPlainText("LICENSE file not found.")
        layout.addWidget(license_view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
