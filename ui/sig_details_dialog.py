"""
Dialog showing full details of a digital signature for review:
signer, certificate, integrity status, and the public key.
"""
import logging

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPlainTextEdit,
                             QDialogButtonBox, QPushButton, QApplication,
                             QComboBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


class SignatureDetailsDialog(QDialog):
    def __init__(self, details, current_field=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digital Signature Details")
        self.resize(560, 620)
        self.details = details

        layout = QVBoxLayout(self)

        if len(details) > 1:
            self.selector = QComboBox()
            for d in details:
                self.selector.addItem(
                    f"{d['name'] or d['subject'] or d['field']}  "
                    f"({d['signed_at'] or 'no date'})")
            self.selector.currentIndexChanged.connect(self._show)
            layout.addWidget(self.selector)
        else:
            self.selector = None

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info_label)

        layout.addWidget(QLabel("<b>Public key</b>"))
        self.pem_view = QPlainTextEdit()
        self.pem_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setPointSize(8)
        self.pem_view.setFont(mono)
        layout.addWidget(self.pem_view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_btn = QPushButton("Copy public key")
        copy_btn.clicked.connect(self._copy_pem)
        buttons.addButton(copy_btn, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        start = 0
        if current_field:
            for i, d in enumerate(details):
                if d["field"] == current_field:
                    start = i
                    break
        if self.selector:
            self.selector.setCurrentIndex(start)
        self._show(start)

    def _show(self, index):
        d = self.details[index]

        if d["intact"] is True and d["valid_crypto"] is True:
            self.status_label.setText(
                "<span style='color:#15803d; font-weight:600'>✔ Signature is "
                "cryptographically valid — the document has not been "
                "modified since signing.</span><br>"
                "<span style='color:#64748b'>Trust in the certificate chain "
                "is not evaluated here; verify the issuer below.</span>")
        elif d["intact"] is False:
            self.status_label.setText(
                "<span style='color:#b91c1c; font-weight:600'>✖ The document "
                "has been MODIFIED after this signature was applied.</span>")
        else:
            self.status_label.setText(
                "<span style='color:#b45309; font-weight:600'>⚠ Integrity "
                "could not be verified.</span>")

        def row(label, value):
            return (f"<tr><td style='color:#64748b; padding-right:12px; "
                    f"white-space:nowrap'>{label}</td><td>{value}</td></tr>"
                    if value else "")

        self.info_label.setText(
            "<table>"
            + row("Signed by", f"<b>{d['name'] or '–'}</b>")
            + row("Date", d["signed_at"])
            + row("Reason", d["reason"])
            + row("Location", d["location"])
            + row("Field", d["field"])
            + row("Certificate", d["subject"])
            + row("Issued by", d["issuer"])
            + row("Serial", d["serial"])
            + row("Valid", f"{d['valid_from']} → {d['valid_to']}"
                  if d["valid_from"] else "")
            + row("Public key", d["key_info"])
            + row("Signature alg.", d["sig_algorithm"])
            + row("SHA-256", f"<span style='font-size:8pt'>{d['sha256_fp']}"
                  "</span>")
            + "</table>")

        self.pem_view.setPlainText(d["pubkey_pem"] or "(unavailable)")

    def _copy_pem(self):
        QApplication.clipboard().setText(self.pem_view.toPlainText())
        self.status_label.setText(
            self.status_label.text()
            + "<br><span style='color:#2563eb'>Public key copied to "
              "clipboard.</span>")
