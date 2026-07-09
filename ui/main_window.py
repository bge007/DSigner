"""
Main application window for PDF Digital Signer
"""
import logging
import os

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QLabel, QSpinBox,
                             QGroupBox, QFormLayout, QMessageBox, QSplitter,
                             QLineEdit, QCheckBox, QStatusBar)
from PyQt5.QtCore import Qt

from ui.pdf_viewer import PDFViewer
from core.signer import DigitalSigner

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Digital Signer")
        self.resize(1400, 860)

        self.current_pdf_path = None
        self.signer = DigitalSigner()
        self._syncing = False  # guards spinbox <-> viewer feedback loops

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # top toolbar
        bar = QHBoxLayout()

        self.open_btn = QPushButton("📂  Open PDF…")
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self.open_pdf)
        bar.addWidget(self.open_btn)

        self.file_label = QLabel("No document loaded")
        self.file_label.setObjectName("fileLabel")
        bar.addWidget(self.file_label)
        bar.addStretch()

        self.sign_btn = QPushButton("🔏  Sign && Save…")
        self.sign_btn.setObjectName("signButton")
        self.sign_btn.setEnabled(False)
        self.sign_btn.clicked.connect(self.sign_pdf)
        bar.addWidget(self.sign_btn)

        root.addLayout(bar)

        # main split: viewer | side panel
        splitter = QSplitter(Qt.Horizontal)

        self.pdf_viewer = PDFViewer()
        self.pdf_viewer.position_changed.connect(self.on_position_changed)
        self.pdf_viewer.page_changed.connect(self.on_page_changed)
        splitter.addWidget(self.pdf_viewer)

        splitter.addWidget(self._build_side_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1020, 360])
        root.addWidget(splitter)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage(
            "Open a PDF, then click anywhere on the page to place the signature — drag the box to fine-tune.")

    def _build_side_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(10)

        # signer details
        sig_group = QGroupBox("Signer Details")
        sig_form = QFormLayout(sig_group)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Ben George")
        self.name_input.textChanged.connect(self.pdf_viewer.set_preview_name)
        sig_form.addRow("Name*", self.name_input)

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("e.g. Approved (optional)")
        sig_form.addRow("Reason", self.reason_input)

        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("e.g. Bangalore (optional)")
        sig_form.addRow("Location", self.location_input)

        self.date_check = QCheckBox("Include date && time")
        self.date_check.setChecked(True)
        sig_form.addRow("", self.date_check)

        layout.addWidget(sig_group)

        # placement
        pos_group = QGroupBox("Placement")
        pos_form = QFormLayout(pos_group)

        self.page_info = QLabel("Load a PDF to begin")
        self.page_info.setWordWrap(True)
        pos_form.addRow(self.page_info)

        self.pos_x = self._make_spin(0, 5000, 36)
        self.pos_y = self._make_spin(0, 5000, 36)
        self.sig_width = self._make_spin(80, 400, 190)
        self.sig_height = self._make_spin(30, 200, 64)

        pos_form.addRow("X (from left)", self.pos_x)
        pos_form.addRow("Y (from top)", self.pos_y)
        pos_form.addRow("Width", self.sig_width)
        pos_form.addRow("Height", self.sig_height)

        hint = QLabel("Values are in PDF points (72 pt = 1 inch). "
                      "Click or drag the box on the page instead of typing.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        pos_form.addRow(hint)

        layout.addWidget(pos_group)
        layout.addStretch()

        return panel

    def _make_spin(self, lo, hi, value):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(value)
        spin.setSuffix(" pt")
        spin.valueChanged.connect(self._push_geometry_to_viewer)
        return spin

    # --- geometry sync ---

    def _push_geometry_to_viewer(self):
        if self._syncing or not self.current_pdf_path:
            return
        self.pdf_viewer.set_signature_geometry_pt(
            self.pos_x.value(), self.pos_y.value(),
            self.sig_width.value(), self.sig_height.value())

    def on_position_changed(self, x_pt, y_pt):
        self._syncing = True
        self.pos_x.setValue(round(x_pt))
        self.pos_y.setValue(round(y_pt))
        self._syncing = False

    def on_page_changed(self, current, total):
        self.page_info.setText(
            f"Signature will be placed on page {current + 1} of {total} "
            f"(the page shown in the viewer).")

    # --- actions ---

    def open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF File", "", "PDF Files (*.pdf)")
        if not file_path:
            return

        try:
            self.pdf_viewer.load_pdf(file_path)
        except Exception as e:
            logger.exception(f"Failed to load PDF: {file_path}")
            QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{e}")
            return

        self.current_pdf_path = file_path
        self.file_label.setText(os.path.basename(file_path))
        self.sign_btn.setEnabled(True)

        # default placement: bottom-right corner of the page
        page_w, page_h = self.pdf_viewer.page_size_pt()
        w, h = self.sig_width.value(), self.sig_height.value()
        self._syncing = True
        self.pos_x.setValue(max(0, round(page_w - w - 36)))
        self.pos_y.setValue(max(0, round(page_h - h - 36)))
        self._syncing = False
        self._push_geometry_to_viewer()
        self.pdf_viewer.set_preview_name(self.name_input.text())

        self.statusBar().showMessage(
            "Click anywhere on the page to move the signature box, or drag it to fine-tune.")

    def sign_pdf(self):
        if not self.current_pdf_path:
            QMessageBox.warning(self, "No document", "Please open a PDF first.")
            return

        signer_name = self.name_input.text().strip()
        if not signer_name:
            QMessageBox.warning(self, "Missing name", "Please enter the signer name.")
            self.name_input.setFocus()
            return

        base, ext = os.path.splitext(self.current_pdf_path)
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save Signed PDF", f"{base}_signed{ext}", "PDF Files (*.pdf)")
        if not output_path:
            return

        try:
            self.signer.sign_pdf(
                input_pdf=self.current_pdf_path,
                output_pdf=output_path,
                page_index=self.pdf_viewer.current_page,
                position_pt=(self.pos_x.value(), self.pos_y.value()),
                size_pt=(self.sig_width.value(), self.sig_height.value()),
                signer_name=signer_name,
                reason=self.reason_input.text().strip(),
                location=self.location_input.text().strip(),
                include_date=self.date_check.isChecked(),
            )
        except Exception as e:
            logger.exception(f"Failed to sign PDF: {self.current_pdf_path}")
            QMessageBox.critical(self, "Error", f"Failed to sign PDF:\n{e}")
            return

        result = QMessageBox.question(
            self, "PDF signed",
            f"Signed PDF saved to:\n{output_path}\n\nOpen it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if result == QMessageBox.Yes:
            os.startfile(output_path)
