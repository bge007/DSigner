"""
Dialog for picking a signing certificate from the Windows store.
"""
import logging
from datetime import datetime, timezone

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget,
                             QTableWidgetItem, QDialogButtonBox,
                             QAbstractItemView, QHeaderView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from core import wincert

logger = logging.getLogger(__name__)


class CertificateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Signing Certificate")
        self.resize(640, 320)
        self.certs = []
        self.selected = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Certificates with a private key in your Windows store "
            "(Current User → Personal):"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Issued to", "Issued by", "Expires"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    def _populate(self):
        try:
            self.certs = wincert.list_certificates()
        except Exception:
            logger.exception("Failed to enumerate certificates")
            self.certs = []

        now = datetime.now(timezone.utc)
        self.table.setRowCount(len(self.certs))
        for row, cert in enumerate(self.certs):
            expired = cert.not_after < now
            expires = cert.not_after.strftime("%Y-%m-%d")
            if expired:
                expires += "  (expired)"
            for col, value in enumerate([cert.subject, cert.issuer, expires]):
                item = QTableWidgetItem(value)
                if expired:
                    item.setForeground(QColor(185, 28, 28))
                self.table.setItem(row, col, item)
        if self.certs:
            self.table.selectRow(0)

    def accept(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.certs):
            self.selected = self.certs[row]
        super().accept()

    @staticmethod
    def pick(parent=None):
        """Show the dialog; returns the chosen WinCertificate or None."""
        dlg = CertificateDialog(parent)
        result = dlg.exec_()
        chosen = dlg.selected if result == QDialog.Accepted else None
        # release contexts of certificates that were not chosen
        for cert in dlg.certs:
            if cert is not chosen:
                cert.free()
        return chosen
