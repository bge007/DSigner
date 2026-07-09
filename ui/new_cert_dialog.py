"""
Dialog for creating a new self-signed signing certificate in the
Windows certificate store.
"""
import logging

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QSpinBox, QLabel, QDialogButtonBox, QMessageBox,
                             QApplication)
from PyQt5.QtCore import Qt

from core import wincert

logger = logging.getLogger(__name__)


class NewCertificateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Digital Signature Certificate")
        self.setMinimumWidth(420)
        self.thumbprint = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Ben George")
        form.addRow("Full name*", self.name_input)

        self.org_input = QLineEdit()
        self.org_input.setPlaceholderText("optional")
        form.addRow("Organization", self.org_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("optional")
        form.addRow("Email", self.email_input)

        self.years_spin = QSpinBox()
        self.years_spin.setRange(1, 10)
        self.years_spin.setValue(3)
        self.years_spin.setSuffix(" years")
        form.addRow("Valid for", self.years_spin)

        layout.addLayout(form)

        note = QLabel(
            "The certificate is created in your Windows store "
            "(Current User → Personal) and can be used for signing "
            "immediately. Being self-signed, PDF readers will show its "
            "signatures as valid but untrusted unless the recipient "
            "chooses to trust the certificate.")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name",
                                "Please enter the signer's full name.")
            self.name_input.setFocus()
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.thumbprint = wincert.create_self_signed(
                common_name=name,
                organization=self.org_input.text().strip(),
                email=self.email_input.text().strip(),
                years=self.years_spin.value())
        except Exception as e:
            logger.exception("Certificate creation failed")
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error",
                                 f"Could not create the certificate:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.accept()

    @staticmethod
    def create(parent=None):
        """Show the dialog; returns the new cert's thumbprint or None."""
        dlg = NewCertificateDialog(parent)
        return dlg.thumbprint if dlg.exec_() == QDialog.Accepted else None
