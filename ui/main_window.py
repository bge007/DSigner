"""
Main application window for DSigner: tabbed PDF viewer with digital
signing via Windows-store certificates.
"""
import logging
import os
from datetime import datetime

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QLabel, QSpinBox,
                             QGroupBox, QFormLayout, QMessageBox, QSplitter,
                             QLineEdit, QStatusBar, QTabWidget)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QAction

from core.app_info import APP_NAME, APP_VERSION
from ui.document_tab import DocumentTab
from ui.about_dialog import AboutDialog
from ui.cert_dialog import CertificateDialog
from ui.form_dialog import FormFillDialog
from ui.new_cert_dialog import NewCertificateDialog
from ui.object_inspector_dialog import ObjectInspectorDialog
from ui.properties_dialog import PropertiesDialog
from ui.sig_details_dialog import SignatureDetailsDialog
from core import session, wincert
from core.certsigner import (sign_pdf_with_certificate, read_signatures,
                             signature_details)
from core.readaloud import ReadAloud

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1400, 880)

        self.selected_cert = None
        self._syncing = False  # guards spinbox <-> viewer feedback loops

        self.reader = ReadAloud()
        self._tts_timer = QTimer(self)
        self._tts_timer.setInterval(500)
        self._tts_timer.timeout.connect(self._poll_read_aloud)

        self.init_ui()
        self._init_menu()
        self._init_shortcuts()

    def _init_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_pdfs)
        file_menu.addAction(open_action)

        close_action = QAction("&Close", self)
        close_action.setShortcut(QKeySequence.Close)
        close_action.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addAction(close_action)

        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_current_as)
        file_menu.addAction(save_as_action)

        fill_form_action = QAction("&Fill Form...", self)
        fill_form_action.triggered.connect(self.fill_current_form)
        file_menu.addAction(fill_form_action)

        read_action = QAction("&Read Aloud", self)
        read_action.setShortcut("Ctrl+R")
        read_action.setToolTip("Read the selected text (or the whole page) aloud")
        read_action.triggered.connect(self.toggle_read_aloud)
        file_menu.addAction(read_action)

        properties_action = QAction("&Properties...", self)
        properties_action.setShortcut("Alt+Enter")
        properties_action.triggered.connect(self.show_file_properties)
        file_menu.addAction(properties_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction(f"&About {APP_NAME}", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

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

        self.read_btn = QPushButton("🔊  Read Aloud")
        self.read_btn.setToolTip(
            "Read the selected text (or the whole page) aloud (Ctrl+R)")
        self.read_btn.clicked.connect(self.toggle_read_aloud)
        bar.addWidget(self.read_btn)

        self.sign_mode_btn = QPushButton("🔏  Digital Signature")
        self.sign_mode_btn.setObjectName("signButton")
        self.sign_mode_btn.setCheckable(True)
        self.sign_mode_btn.setToolTip(
            "Show the digital signature panel and place a signature")
        self.sign_mode_btn.toggled.connect(self.toggle_sign_pane)
        bar.addWidget(self.sign_mode_btn)

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

        self.sign_pane = self._build_side_panel()
        self.sign_pane.setVisible(False)  # hidden until Digital Signature mode
        splitter.addWidget(self.sign_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1020, 360])
        root.addWidget(splitter)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage(
            "Open PDFs (Ctrl+O), search inside them (Ctrl+F). Click "
            "'Digital Signature' to sign the current document (Ctrl+S).")

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

        new_cert_btn = QPushButton("Create new certificate…")
        new_cert_btn.clicked.connect(self.create_certificate)
        cert_layout.addWidget(new_cert_btn)

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

        # sign action
        self.sign_btn = QPushButton("🔏  Sign && Save…")
        self.sign_btn.setObjectName("signButton")
        self.sign_btn.setEnabled(False)
        self.sign_btn.clicked.connect(self.sign_pdf)
        layout.addWidget(self.sign_btn)

        # existing signatures in the active document
        sigs_group = QGroupBox("Signatures in this document")
        sigs_layout = QVBoxLayout(sigs_group)
        self.signatures_label = QLabel("–")
        self.signatures_label.setWordWrap(True)
        self.signatures_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sigs_layout.addWidget(self.signatures_label)
        layout.addWidget(sigs_group)

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
        QShortcut(QKeySequence("Ctrl+S"), self, self._sign_shortcut)
        QShortcut(QKeySequence("Ctrl+W"), self,
                  lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence.ZoomIn, self, lambda: self._zoom_current(+1))
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self._zoom_current(+1))
        QShortcut(QKeySequence.ZoomOut, self, lambda: self._zoom_current(-1))
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_current)

    def _zoom_current(self, direction):
        tab = self.current_tab()
        if tab:
            (tab.viewer.zoom_in if direction > 0 else tab.viewer.zoom_out)()

    def _fit_current(self):
        tab = self.current_tab()
        if tab:
            tab.viewer.fit_width()

    def _sign_shortcut(self):
        if not self.sign_mode_btn.isChecked():
            self.sign_mode_btn.setChecked(True)  # enter signing mode first
        else:
            self.sign_pdf()

    # --- signing mode ---

    def toggle_sign_pane(self, checked):
        self.sign_pane.setVisible(checked)
        for i in range(self.tabs.count()):
            self.tabs.widget(i).viewer.set_placement_enabled(checked)
        if checked:
            self.on_tab_changed(self.tabs.currentIndex())
            self.statusBar().showMessage(
                "Click the page to place the signature box, drag it to "
                "fine-tune, then Sign & Save.")
        else:
            self.statusBar().showMessage("")

    def refresh_signatures(self):
        if not self.sign_mode_btn.isChecked():
            return
        tab = self.current_tab()
        if not tab:
            self.signatures_label.setText("No document open.")
            return

        sigs = read_signatures(tab.path)
        if not sigs:
            self.signatures_label.setText(
                "No digital signatures in this document.")
            return

        blocks = []
        for s in sigs:
            lines = [f"<b>{s['name'] or 'Unknown signer'}</b>"]
            if s["signed_at"]:
                lines.append(f"Signed: {s['signed_at']}")
            if s["reason"]:
                lines.append(f"Reason: {s['reason']}")
            if s["location"]:
                lines.append(f"Location: {s['location']}")
            cert_bits = s["signer_cn"] or "unknown certificate"
            lines.append(f"<span style='color:#64748b'>Certificate: "
                         f"{cert_bits} · field {s['field']}</span>")
            blocks.append("<br>".join(lines))
        self.signatures_label.setText("<br><br>".join(blocks))

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
            # default placement: 25 pt from the top-left, always visible
            w, h = self.sig_width.value(), self.sig_height.value()
            tab.sig_geometry = {"x": 25, "y": 25, "w": w, "h": h}

        tab.viewer.position_changed.connect(
            lambda x, y, t=tab: self.on_position_changed(t, x, y))
        tab.viewer.page_changed.connect(
            lambda cur, tot, t=tab: self.on_page_changed(t, cur, tot))
        tab.viewer.signature_clicked.connect(
            lambda field, t=tab: self.show_signature_details(t, field))
        tab.viewer.object_inspected.connect(self.show_object_details)

        if self.selected_cert:
            tab.viewer.set_preview_name(self.selected_cert.subject)
        tab.viewer.set_placement_enabled(self.sign_mode_btn.isChecked())

        index = self.tabs.addTab(tab, tab.title)
        self.tabs.setTabToolTip(index, path)
        self.tabs.setCurrentIndex(index)

        if page:
            tab.viewer.show_page(page)
        if zoom:
            tab.viewer.set_zoom(zoom)

    def close_tab(self, index):
        if not (0 <= index < self.tabs.count()):
            return
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
        self.refresh_signatures()

    def _focus_search(self):
        tab = self.current_tab()
        if tab:
            tab.focus_search()

    # --- read aloud ---

    def toggle_read_aloud(self):
        if self.reader.is_speaking():
            self.reader.stop()
            self._on_read_finished()
            return

        tab = self.current_tab()
        if not tab:
            QMessageBox.information(self, "No document",
                                    "Please open a PDF first.")
            return

        text = tab.viewer.selected_text or tab.viewer.current_page_text()
        if not text.strip():
            self.statusBar().showMessage("No text to read on this page.")
            return

        if self.reader.speak(text):
            source = ("selection" if tab.viewer.selected_text
                      else f"page {tab.viewer.current_page + 1}")
            self.read_btn.setText("⏹  Stop Reading")
            self._tts_timer.start()
            self.statusBar().showMessage(f"Reading {source} aloud…")
        else:
            self.statusBar().showMessage("Could not start the speech engine.")

    def _poll_read_aloud(self):
        if not self.reader.is_speaking():
            self._on_read_finished()

    def _on_read_finished(self):
        self._tts_timer.stop()
        self.read_btn.setText("🔊  Read Aloud")

    def show_signature_details(self, tab, field_name):
        details = signature_details(tab.path)
        if not details:
            QMessageBox.information(
                self, "No details",
                "Could not read signature details from this document.")
            return
        SignatureDetailsDialog(details, current_field=field_name,
                               parent=self).exec()

    def show_file_properties(self):
        tab = self.current_tab()
        if not tab:
            QMessageBox.information(self, "No document",
                                    "Please open a PDF first.")
            return
        PropertiesDialog(tab, self).exec()

    def show_about(self):
        AboutDialog(self).exec()

    def show_object_details(self, details):
        ObjectInspectorDialog(details, self).exec()

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
        if cert:
            self._set_certificate(cert)

    def create_certificate(self):
        thumbprint = NewCertificateDialog.create(self)
        if not thumbprint:
            return
        cert = wincert.find_certificate(thumbprint)
        if not cert:
            QMessageBox.warning(self, "Not found",
                                "The certificate was created but could not "
                                "be loaded from the store.")
            return
        self._set_certificate(cert)
        self.statusBar().showMessage(
            f"Certificate '{cert.subject}' created and selected for signing.")

    def _set_certificate(self, cert):
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

    def save_current_as(self):
        tab = self.current_tab()
        if not tab:
            QMessageBox.warning(self, "No document", "Please open a PDF first.")
            return

        base, ext = os.path.splitext(tab.path)
        default_path = f"{base}_copy{ext or '.pdf'}"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", default_path, "PDF Files (*.pdf)")
        if not output_path:
            return
        if os.path.abspath(output_path) == os.path.abspath(tab.path):
            QMessageBox.warning(self, "Choose another file",
                                "Cannot overwrite the open document; "
                                "pick a different output name.")
            return

        try:
            tab.viewer.save_as(output_path)
        except Exception as e:
            logger.exception("Failed to save PDF as %s", output_path)
            QMessageBox.critical(self, "Error", f"Failed to save PDF:\n{e}")
            return

        self.add_document(output_path)
        self.statusBar().showMessage(f"Saved PDF copy: {output_path}")

    def fill_current_form(self):
        tab = self.current_tab()
        if not tab:
            QMessageBox.warning(self, "No document", "Please open a PDF first.")
            return

        fields = tab.viewer.form_fields()
        if not fields:
            QMessageBox.information(self, "No form fields",
                                    "This PDF does not contain fillable form "
                                    "fields.")
            return

        dlg = FormFillDialog(fields, self)
        if dlg.exec() != dlg.Accepted:
            return
        updates = dlg.values()
        if not updates:
            self.statusBar().showMessage("No form field changes to apply.")
            return
        try:
            tab.viewer.apply_form_updates(updates)
        except Exception as e:
            logger.exception("Failed to apply PDF form updates")
            QMessageBox.critical(self, "Error",
                                 f"Failed to update form fields:\n{e}")
            return
        self.statusBar().showMessage(
            "Form fields updated. Use File > Save As to share the filled copy.")

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
        box = tab.viewer.view_rect_to_page_box(g["x"], g["y"], g["w"], g["h"])
        try:
            sign_pdf_with_certificate(
                input_pdf=tab.path,
                output_pdf=output_path,
                win_cert=self.selected_cert,
                page_index=tab.viewer.current_page,
                box=box,
                reason=self.reason_input.text().strip(),
                location=self.location_input.text().strip(),
            )
        except Exception as e:
            logger.exception(f"Failed to sign PDF: {tab.path}")
            QMessageBox.critical(self, "Error", f"Failed to sign PDF:\n{e}")
            return

        # show the signed copy in a new tab; the signature details
        # appear in the "Signatures in this document" panel
        self.add_document(output_path)
        self.refresh_signatures()
        self.statusBar().showMessage(f"Signed PDF saved: {output_path}")

        result = QMessageBox.question(
            self, "PDF signed",
            f"Digitally signed PDF saved and opened in a new tab:\n"
            f"{output_path}\n\nAlso open it in your PDF reader?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
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
        self.reader.stop()
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
