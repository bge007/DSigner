"""
One tab = one open PDF: a search bar, the viewer, and this document's
signature placement state.
"""
import logging
import os

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QLabel)
from PySide6.QtCore import Signal

from ui.pdf_viewer import PDFViewer

logger = logging.getLogger(__name__)


class DocumentTab(QWidget):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.sig_geometry = {"x": 0, "y": 0, "w": 190, "h": 64}
        self._last_query = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # search bar
        search_bar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search text in document…  (Enter = next match)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._search_or_next)
        self.search_input.textChanged.connect(self._on_text_changed)
        search_bar.addWidget(self.search_input)

        self.match_label = QLabel("")
        self.match_label.setObjectName("hintLabel")
        self.match_label.setMinimumWidth(70)
        search_bar.addWidget(self.match_label)

        prev_btn = QPushButton("▲")
        prev_btn.setFixedWidth(34)
        prev_btn.setToolTip("Previous match")
        prev_btn.clicked.connect(self._prev_match)
        search_bar.addWidget(prev_btn)

        next_btn = QPushButton("▼")
        next_btn.setFixedWidth(34)
        next_btn.setToolTip("Next match")
        next_btn.clicked.connect(self._search_or_next)
        search_bar.addWidget(next_btn)

        layout.addLayout(search_bar)

        # viewer
        self.viewer = PDFViewer()
        self.viewer.load_pdf(path)
        layout.addWidget(self.viewer)

    @property
    def title(self):
        return os.path.basename(self.path)

    def focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    # --- search plumbing ---

    def _search_or_next(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if query != self._last_query:
            self._last_query = query
            count = self.viewer.search(query)
            self._show_count(self.viewer.current_match, count)
        else:
            current, count = self.viewer.next_match()
            self._show_count(current, count)

    def _prev_match(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if query != self._last_query:
            self._search_or_next()
        else:
            current, count = self.viewer.prev_match()
            self._show_count(current, count)

    def _on_text_changed(self, text):
        if not text.strip():
            self._last_query = ""
            self.viewer.clear_search()
            self.match_label.setText("")

    def _show_count(self, current, count):
        if count:
            self.match_label.setText(f"{current + 1} / {count}")
        else:
            self.match_label.setText("no matches")

    # --- lifecycle / session ---

    def close_doc(self):
        self.viewer.close_doc()

    def session_state(self):
        return {
            "path": self.path,
            "page": self.viewer.current_page,
            "zoom": self.viewer.zoom,
            "sig_geometry": dict(self.sig_geometry),
        }
