"""
Main application window for DSigner: tabbed PDF viewer with digital
signing via Windows-store certificates.
"""
import logging
import os
from datetime import datetime

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QLabel, QSpinBox,
                             QGroupBox, QFormLayout, QMessageBox, QSplitter,
                             QLineEdit, QStatusBar, QTabWidget, QShortcut)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence

from ui.document_tab import DocumentTab
from ui.cert_dialog import CertificateDialog
from core import session
from core.certsigner import sign_pdf_with_certificate

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DSigner")
        self.resize(1400, 880)

        self.selected_cert = None
        self._syncing = False  # guards spinbox <-> viewer feedback loops

        self.init_ui()
        self._init_shortcuts()

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
        self.open_btn.clicked.connect(self.open_pdfs)
        bar.addWidget(self.open_btn)

        bar.addStretch()

        self.sign_btn = QPushButton("🔏  Sign && Save…")
        self.sign_btn.setObjectName("signButton")
        self.sign_btn.setEnabled(False)
        self.sign_btn.clicked.connect(self.sign_pdf)
        bar.addWidget(self.sign_btn)

        root.addLayout(bar)

        # main split: tabs | side panel
        splitter = QSplitter(Qt.Horizontal)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        splitter.addWidget(self.tabs)

        splitter.addWidget(self._build_side_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1020, 360])
        root.addWidget(splitter)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage(
            "Open PDFs (Ctrl+O), search inside them (Ctrl+F), click the page "
            "to place the signature, then Sign & Save (Ctrl+S).")

    def _build_side_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(10)

        # certificate
        cert_group = QGroupBox("Signing Certificate")
        cert_layout = QVBoxLayout(cert_group)

        self.cert_label = QLabel("No certificate selected")
        self.cert_label.setWordWrap(True)
        cert_layout.addWidget(self.cert_label)

        cert_btn = QPushButton("Choose from Windows store…")
        cert_btn.clicked.connect(self.choose_certificate)
        cert_layout.addWidget(cert_btn)

        layout.addWidget(cert_group)

        # signature details
        sig_group = QGroupBox("Signature Details")
        sig_form = QFormLayout(sig_group)

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("e.g. Approved (optional)")
        sig_form.addRow("Reason", self.reason_input)

        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("e.g. Bangalore (optional)")
        sig_form.addRow("Location", self.location_input)

        layout.addWidget(sig_group)

        # placement
        pos_group = QGroupBox("Placement")
        pos_form = QFormLayout(pos_group)

        self.page_info = QLabel("Open a PDF to begin")
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
                      "Click or drag the box on the page instead of typing. "
                      "The signature goes on the page currently shown.")
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
        spin.valueChanged.connect(self._push_geometry_to_tab)
        return spin

    def _init_shortcuts(self):
        QShortcut(QKeySequence.Open, self, self.open_pdfs)
        QShortcut(QKeySequence.Find, self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+S"), self, self.sign_pdf)
        QShortcut(QKeySequence("Ctrl+W"), self,
                  lambda: self.close_tab(self.tabs.currentIndex()))

    # --- tabs ---

    def current_tab(self):
        return self.tabs.currentWidget()

    def add_document(self, path, page=0, zoom=None, sig_geometry=None):
        # already open? just activate it
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).path == path:
                self.tabs.setCurrentIndex(i)
                return

        try:
            tab = DocumentTab(path)
        except Exception as e:
            logger.exception(f"Failed to open PDF: {path}")
            QMessageBox.critical(self, "Error", f"Failed to open PDF:\n{e}")
            return

        if sig_geometry:
            tab.sig_geometry = dict(sig_geometry)
        else:
            # default placement: bottom-right corner of the first page
            page_w, page_h = tab.viewer.page_size_pt()
            w, h = self.sig_width.value(), self.sig_height.value()
            tab.sig_geometry = {"x": max(0, round(page_w - w - 36)),
                                "y": max(0, round(page_h - h - 36)),
                                "w": w, "h": h}

        tab.viewer.position_changed.connect(
            lambda x, y, t=tab: self.on_position_changed(t, x, y))
        tab.viewer.page_changed.connect(
            lambda cur, tot, t=tab: self.on_page_changed(t, cur, tot))

        if self.selected_cert:
            tab.viewer.set_preview_name(self.selected_cert.subject)

        index = self.tabs.addTab(tab, tab.title)
        self.tabs.setTabToolTip(index, path)
        self.tabs.setCurrentIndex(index)

        if page:
            tab.viewer.show_page(page)
        if zoom:
            tab.viewer.set_zoom(zoom)

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if tab:
            tab.close_doc()
            self.tabs.removeTab(index)
            tab.deleteLater()
        if self.tabs.count() == 0:
            self.sign_btn.setEnabled(False)
            self.page_info.setText("Open a PDF to begin")

    def on_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if not tab:
            return
        self.sign_btn.setEnabled(True)

        g = tab.sig_geometry
        self._syncing = True
        self.pos_x.setValue(round(g["x"]))
        self.pos_y.setValue(round(g["y"]))
        self.sig_width.setValue(round(g["w"]))
        self.sig_height.setValue(round(g["h"]))
        self._syncing = False
        tab.viewer.set_signature_geometry_pt(g["x"], g["y"], g["w"], g["h"])

        self.on_page_changed(tab, tab.viewer.current_page,
                             tab.viewer.total_pages)

    def _focus_search(self):
        tab = self.current_tab()
        if tab:
            tab.focus_search()

    # --- geometry sync ---

    def _push_geometry_to_tab(self):
        if self._syncing:
            return
        tab = self.current_tab()
        if not tab:
            return
        g = {"x": self.pos_x.value(), "y": self.pos_y.value(),
             "w": self.sig_width.value(), "h": self.sig_height.value()}
        tab.sig_geometry = g
        tab.viewer.set_signature_geometry_pt(g["x"], g["y"], g["w"], g["h"])

    def on_position_changed(self, tab, x_pt, y_pt):
        tab.sig_geometry["x"] = x_pt
        tab.sig_geometry["y"] = y_pt
        if tab is self.current_tab():
            self._syncing = True
            self.pos_x.setValue(round(x_pt))
            self.pos_y.setValue(round(y_pt))
            self._syncing = False

    def on_page_changed(self, tab, current, total):
        if tab is self.current_tab():
            self.page_info.setText(
                f"Signature will be placed on page {current + 1} of {total}.")

    # --- certificate ---

    def choose_certificate(self):
        cert = CertificateDialog.pick(self)
        if not cert:
            return
        if self.selected_cert:
            self.selected_cert.free()
        self.selected_cert = cert
        self.cert_label.setText(
            f"<b>{cert.subject}</b><br>"
            f"Issued by {cert.issuer}<br>"
            f"Expires {cert.not_after:%Y-%m-%d}")
        for i in range(self.tabs.count()):
            self.tabs.widget(i).viewer.set_preview_name(cert.subject)

    # --- actions ---

    def open_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open PDF Files", "", "PDF Files (*.pdf)")
        for path in paths:
            self.add_document(path)

    def sign_pdf(self):
        tab = self.current_tab()
        if not tab:
            QMessageBox.warning(self, "No document", "Please open a PDF first.")
            return

        if not self.selected_cert:
            self.choose_certificate()
            if not self.selected_cert:
                return

        base, ext = os.path.splitext(tab.path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save Signed PDF", f"{base}_signed_{timestamp}{ext}",
            "PDF Files (*.pdf)")
        if not output_path:
            return
        if os.path.abspath(output_path) == os.path.abspath(tab.path):
            QMessageBox.warning(self, "Choose another file",
                                "Cannot overwrite the open document; "
                                "pick a different output name.")
            return

        g = tab.sig_geometry
        _, page_h = tab.viewer.page_size_pt()
        try:
            sign_pdf_with_certificate(
                input_pdf=tab.path,
                output_pdf=output_path,
                win_cert=self.selected_cert,
                page_index=tab.viewer.current_page,
                position_pt=(g["x"], g["y"]),
                size_pt=(g["w"], g["h"]),
                page_height_pt=page_h,
                reason=self.reason_input.text().strip(),
                location=self.location_input.text().strip(),
            )
        except Exception as e:
            logger.exception(f"Failed to sign PDF: {tab.path}")
            QMessageBox.critical(self, "Error", f"Failed to sign PDF:\n{e}")
            return

        result = QMessageBox.question(
            self, "PDF signed",
            f"Digitally signed PDF saved to:\n{output_path}\n\nOpen it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if result == QMessageBox.Yes:
            os.startfile(output_path)

    # --- session ---

    def restore_session(self):
        data = session.load_session()
        if not data:
            return
        for entry in data.get("files", []):
            path = entry.get("path", "")
            if os.path.exists(path):
                self.add_document(path,
                                  page=entry.get("page", 0),
                                  zoom=entry.get("zoom"),
                                  sig_geometry=entry.get("sig_geometry"))
        active = data.get("active", 0)
        if 0 <= active < self.tabs.count():
            self.tabs.setCurrentIndex(active)

    def closeEvent(self, event):
        files = [self.tabs.widget(i).session_state()
                 for i in range(self.tabs.count())]
        session.save_session({
            "version": 1,
            "active": self.tabs.currentIndex(),
            "files": files,
        })
        for i in range(self.tabs.count()):
            self.tabs.widget(i).close_doc()
        super().closeEvent(event)
