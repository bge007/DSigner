"""
PDF viewer built on PyMuPDF with interactive signature placement,
page navigation, zoom and text search with highlights.
"""
import logging
import os
from collections import OrderedDict

import fitz  # PyMuPDF

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QPushButton, QSpinBox)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QPointF

logger = logging.getLogger(__name__)

RENDER_DPI = 150
PT_PER_INCH = 72.0
PX_PER_PT = RENDER_DPI / PT_PER_INCH  # image pixels per PDF point
PAGE_CACHE_SIZE = 8


class PageView(QWidget):
    """Renders one page plus overlays: signature box and search highlights.

    All geometry is kept in unzoomed image pixels (RENDER_DPI); zoom only
    affects display.
    """
    position_changed = pyqtSignal(float, float)  # top-left of box, image px

    def __init__(self):
        super().__init__()
        self.base_pixmap = None
        self.zoom = 1.0
        self.sig_rect = None          # QRectF, unzoomed image px
        self.preview_name = ""
        self.placement_enabled = False  # signing mode: show/move the box
        self.highlights = []          # [QRectF], unzoomed image px
        self.current_highlight = -1   # index into highlights
        self._dragging = False
        self._drag_offset = QPointF()
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    # --- page / zoom ---

    def set_page(self, pixmap):
        self.base_pixmap = pixmap
        self._update_size()
        self.update()

    def set_zoom(self, zoom):
        self.zoom = zoom
        self._update_size()
        self.update()

    def _update_size(self):
        if self.base_pixmap:
            self.setFixedSize(int(self.base_pixmap.width() * self.zoom),
                              int(self.base_pixmap.height() * self.zoom))

    # --- overlays ---

    def set_sig_rect(self, x, y, w, h):
        self.sig_rect = self._clamped(QRectF(x, y, w, h))
        self.update()

    def set_preview_name(self, name):
        self.preview_name = name
        self.update()

    def set_highlights(self, rects, current=-1):
        self.highlights = rects
        self.current_highlight = current
        self.update()

    def _clamped(self, rect):
        if not self.base_pixmap:
            return rect
        max_x = max(0.0, self.base_pixmap.width() - rect.width())
        max_y = max(0.0, self.base_pixmap.height() - rect.height())
        rect.moveLeft(min(max(rect.x(), 0.0), max_x))
        rect.moveTop(min(max(rect.y(), 0.0), max_y))
        return rect

    def _to_image(self, pos):
        return QPointF(pos.x() / self.zoom, pos.y() / self.zoom)

    # --- interaction ---

    def mousePressEvent(self, event):
        if (not self.placement_enabled or event.button() != Qt.LeftButton
                or not self.base_pixmap or not self.sig_rect):
            return

        p = self._to_image(event.pos())
        if self.sig_rect.contains(p):
            self._dragging = True
            self._drag_offset = p - self.sig_rect.topLeft()
        else:
            # place the box centered on the click
            self.sig_rect = self._clamped(QRectF(
                p.x() - self.sig_rect.width() / 2,
                p.y() - self.sig_rect.height() / 2,
                self.sig_rect.width(), self.sig_rect.height()))
            self.update()
            self.position_changed.emit(self.sig_rect.x(), self.sig_rect.y())

    def mouseMoveEvent(self, event):
        if not self.placement_enabled or not self.base_pixmap or not self.sig_rect:
            return

        p = self._to_image(event.pos())
        if self._dragging:
            rect = QRectF(self.sig_rect)
            rect.moveTopLeft(p - self._drag_offset)
            self.sig_rect = self._clamped(rect)
            self.update()
            self.position_changed.emit(self.sig_rect.x(), self.sig_rect.y())
        else:
            inside = self.sig_rect.contains(p)
            self.setCursor(Qt.SizeAllCursor if inside else Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        self._dragging = False

    # --- painting ---

    def _zoomed(self, rect):
        return QRectF(rect.x() * self.zoom, rect.y() * self.zoom,
                      rect.width() * self.zoom, rect.height() * self.zoom)

    def paintEvent(self, event):
        if not self.base_pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(0, 0, self.width(), self.height()),
                           self.base_pixmap, QRectF(self.base_pixmap.rect()))

        # search highlights
        for idx, rect in enumerate(self.highlights):
            r = self._zoomed(rect).adjusted(-1, -1, 1, 1)
            if idx == self.current_highlight:
                painter.setPen(QPen(QColor(234, 88, 12), 2))
                painter.setBrush(QColor(251, 146, 60, 110))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(250, 204, 21, 100))
            painter.drawRect(r)

        # signature box (only while in signing mode)
        if self.sig_rect and self.placement_enabled:
            r = self._zoomed(self.sig_rect)
            painter.setPen(QPen(QColor(37, 99, 235), 2, Qt.DashLine))
            painter.setBrush(QColor(37, 99, 235, 40))
            painter.drawRoundedRect(r, 6, 6)

            if r.height() >= 18 and r.width() >= 60:
                painter.setPen(QColor(30, 64, 175))
                font = QFont()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                label = self.preview_name.strip() or "Signature"
                painter.drawText(r.adjusted(8, 5, -8, -5),
                                 Qt.AlignTop | Qt.AlignLeft, label)


class PDFViewer(QWidget):
    """Single-document viewer: navigation, zoom, search, placement.

    Coordinates emitted/accepted by this widget are in PDF points,
    measured from the TOP-LEFT of the page.
    """
    position_changed = pyqtSignal(float, float)   # x_pt, y_pt (from top-left)
    page_changed = pyqtSignal(int, int)           # current (0-based), total

    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 3.0, 0.25

    def __init__(self):
        super().__init__()
        self.doc = None
        self.current_page = 0
        self.total_pages = 0
        self.zoom = 1.0
        self._cache = OrderedDict()   # page -> QPixmap
        self.matches = []             # [(page, fitz.Rect)]
        self.current_match = -1
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        nav = QHBoxLayout()

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(34)
        self.prev_btn.clicked.connect(lambda: self.show_page(self.current_page - 1))
        nav.addWidget(self.prev_btn)

        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.valueChanged.connect(self._on_page_spin)
        nav.addWidget(self.page_spin)

        self.total_label = QLabel("/ –")
        nav.addWidget(self.total_label)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(34)
        self.next_btn.clicked.connect(lambda: self.show_page(self.current_page + 1))
        nav.addWidget(self.next_btn)

        nav.addStretch()

        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(34)
        zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom - self.ZOOM_STEP))
        nav.addWidget(zoom_out)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        nav.addWidget(self.zoom_label)

        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(34)
        zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom + self.ZOOM_STEP))
        nav.addWidget(zoom_in)

        fit_w = QPushButton("Fit width")
        fit_w.clicked.connect(self.fit_width)
        nav.addWidget(fit_w)

        fit_p = QPushButton("Fit page")
        fit_p.clicked.connect(self.fit_page)
        nav.addWidget(fit_p)

        layout.addLayout(nav)

        self.page_view = PageView()
        self.page_view.position_changed.connect(self._on_view_position)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.page_view)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.scroll)

        self._update_nav()

    # --- loading / pages ---

    def load_pdf(self, pdf_path):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            self.doc = fitz.open(pdf_path)
            self.total_pages = self.doc.page_count
            self._cache.clear()
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, max(1, self.total_pages))
            self.page_spin.blockSignals(False)
            self.show_page(0)
            self.fit_width()
        except Exception:
            logger.exception(f"Failed to load PDF: {pdf_path}")
            raise

    def close_doc(self):
        if self.doc:
            self.doc.close()
            self.doc = None
        self._cache.clear()

    def _render(self, page_num):
        if page_num in self._cache:
            self._cache.move_to_end(page_num)
            return self._cache[page_num]

        pix = self.doc[page_num].get_pixmap(dpi=RENDER_DPI)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)

        self._cache[page_num] = pixmap
        if len(self._cache) > PAGE_CACHE_SIZE:
            self._cache.popitem(last=False)
        return pixmap

    def show_page(self, page_num):
        if not self.doc or not (0 <= page_num < self.total_pages):
            return
        self.current_page = page_num
        self.page_view.set_page(self._render(page_num))
        self._apply_highlights()
        self._update_nav()
        self.page_changed.emit(self.current_page, self.total_pages)

    def _on_page_spin(self, value):
        if value - 1 != self.current_page:
            self.show_page(value - 1)

    def _update_nav(self):
        loaded = self.total_pages > 0
        self.prev_btn.setEnabled(loaded and self.current_page > 0)
        self.next_btn.setEnabled(loaded and self.current_page < self.total_pages - 1)
        self.total_label.setText(f"/ {self.total_pages}" if loaded else "/ –")
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)

    # --- zoom ---

    def set_zoom(self, zoom):
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        self.page_view.set_zoom(self.zoom)
        self.zoom_label.setText(f"{self.zoom * 100:.0f}%")

    def fit_width(self):
        if self.page_view.base_pixmap:
            available = max(1, self.scroll.viewport().width() - 4)
            self.set_zoom(available / self.page_view.base_pixmap.width())

    def fit_page(self):
        pm = self.page_view.base_pixmap
        if pm:
            vw = max(1, self.scroll.viewport().width() - 4)
            vh = max(1, self.scroll.viewport().height() - 4)
            self.set_zoom(min(vw / pm.width(), vh / pm.height()))

    # --- text search ---

    def search(self, needle):
        """Find all matches in the document; jumps to the first one.
        Returns the number of matches."""
        self.matches = []
        self.current_match = -1
        needle = needle.strip()
        if self.doc and needle:
            for pno in range(self.total_pages):
                for rect in self.doc[pno].search_for(needle):
                    self.matches.append((pno, rect))
        if self.matches:
            self._goto_match(0)
        else:
            self._apply_highlights()
        return len(self.matches)

    def next_match(self):
        if self.matches:
            self._goto_match((self.current_match + 1) % len(self.matches))
        return self.current_match, len(self.matches)

    def prev_match(self):
        if self.matches:
            self._goto_match((self.current_match - 1) % len(self.matches))
        return self.current_match, len(self.matches)

    def clear_search(self):
        self.matches = []
        self.current_match = -1
        self._apply_highlights()

    def _goto_match(self, index):
        self.current_match = index
        page, rect = self.matches[index]
        if page != self.current_page:
            self.show_page(page)
        else:
            self._apply_highlights()
        # scroll the match into view
        cx = (rect.x0 + rect.x1) / 2 * PX_PER_PT * self.zoom
        cy = (rect.y0 + rect.y1) / 2 * PX_PER_PT * self.zoom
        self.scroll.ensureVisible(int(cx), int(cy), 140, 140)

    def _apply_highlights(self):
        rects, current_local = [], -1
        for idx, (page, rect) in enumerate(self.matches):
            if page == self.current_page:
                if idx == self.current_match:
                    current_local = len(rects)
                rects.append(QRectF(rect.x0 * PX_PER_PT, rect.y0 * PX_PER_PT,
                                    (rect.x1 - rect.x0) * PX_PER_PT,
                                    (rect.y1 - rect.y0) * PX_PER_PT))
        self.page_view.set_highlights(rects, current_local)

    # --- geometry (PDF points, y from top) ---

    def page_size_pt(self):
        """(width, height) of the current page in PDF points."""
        if not self.doc:
            return (612.0, 792.0)
        rect = self.doc[self.current_page].rect
        return (rect.width, rect.height)

    def set_placement_enabled(self, enabled):
        self.page_view.placement_enabled = enabled
        self.page_view.setCursor(
            Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.page_view.update()

    def set_signature_geometry_pt(self, x, y, w, h):
        self.page_view.set_sig_rect(x * PX_PER_PT, y * PX_PER_PT,
                                    w * PX_PER_PT, h * PX_PER_PT)

    def set_preview_name(self, name):
        self.page_view.set_preview_name(name)

    def _on_view_position(self, x_px, y_px):
        self.position_changed.emit(x_px / PX_PER_PT, y_px / PX_PER_PT)
