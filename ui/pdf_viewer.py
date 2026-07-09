"""
PDF Viewer widget with interactive signature placement.
Click to place, drag to fine-tune, page navigation and zoom.
"""
import logging
import os

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QPushButton)
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QPointF

from pdf2image import convert_from_path

logger = logging.getLogger(__name__)

RENDER_DPI = 150
PT_PER_INCH = 72.0
PX_PER_PT = RENDER_DPI / PT_PER_INCH  # image pixels per PDF point


def pil_to_qpixmap(pil_image):
    """Convert a PIL Image to a QPixmap without relying on PIL.ImageQt"""
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")

    width, height = pil_image.size
    bytes_per_line = width * 3
    data = pil_image.tobytes("raw", "RGB")

    qimage = QImage(data, width, height, bytes_per_line, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class PageView(QWidget):
    """Renders one page and an interactive signature-box overlay.

    All geometry is kept in unzoomed image pixels (RENDER_DPI); zoom only
    affects display.
    """
    position_changed = pyqtSignal(float, float)  # top-left of box, image px

    def __init__(self):
        super().__init__()
        self.base_pixmap = None
        self.zoom = 1.0
        self.sig_rect = None  # QRectF in unzoomed image px
        self.preview_name = ""
        self._dragging = False
        self._drag_offset = QPointF()
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

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

    # --- signature rect ---

    def set_sig_rect(self, x, y, w, h):
        self.sig_rect = self._clamped(QRectF(x, y, w, h))
        self.update()

    def set_preview_name(self, name):
        self.preview_name = name
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
        if event.button() != Qt.LeftButton or not self.base_pixmap or not self.sig_rect:
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
        if not self.base_pixmap or not self.sig_rect:
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

    def paintEvent(self, event):
        if not self.base_pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(0, 0, self.width(), self.height()),
                           self.base_pixmap, QRectF(self.base_pixmap.rect()))

        if self.sig_rect:
            r = QRectF(self.sig_rect.x() * self.zoom, self.sig_rect.y() * self.zoom,
                       self.sig_rect.width() * self.zoom, self.sig_rect.height() * self.zoom)

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
    """PDF viewer with page navigation, zoom and signature placement.

    Coordinates emitted/accepted by this widget are in PDF points,
    measured from the TOP-LEFT of the page (converted to PDF's
    bottom-left origin at signing time).
    """
    position_changed = pyqtSignal(float, float)   # x_pt, y_pt (from top-left)
    page_changed = pyqtSignal(int, int)           # current (0-based), total

    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 3.0, 0.25

    def __init__(self):
        super().__init__()
        self.pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        self.images = []
        self.zoom = 1.0
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # navigation / zoom bar
        nav = QHBoxLayout()

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(36)
        self.prev_btn.clicked.connect(lambda: self.show_page(self.current_page - 1))
        nav.addWidget(self.prev_btn)

        self.page_label = QLabel("–")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(90)
        nav.addWidget(self.page_label)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(36)
        self.next_btn.clicked.connect(lambda: self.show_page(self.current_page + 1))
        nav.addWidget(self.next_btn)

        nav.addStretch()

        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(36)
        zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom - self.ZOOM_STEP))
        nav.addWidget(zoom_out)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(52)
        nav.addWidget(self.zoom_label)

        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(36)
        zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom + self.ZOOM_STEP))
        nav.addWidget(zoom_in)

        fit_btn = QPushButton("Fit width")
        fit_btn.clicked.connect(self.fit_width)
        nav.addWidget(fit_btn)

        layout.addLayout(nav)

        # page view inside scroll area
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
            self.images = convert_from_path(pdf_path, dpi=RENDER_DPI)
            self.pdf_path = pdf_path
            self.total_pages = len(self.images)
            self.show_page(0)
            self.fit_width()
        except Exception:
            logger.exception(f"Failed to load PDF: {pdf_path}")
            raise

    def show_page(self, page_num):
        if not (0 <= page_num < self.total_pages):
            return
        self.current_page = page_num
        self.page_view.set_page(pil_to_qpixmap(self.images[page_num]))
        self._update_nav()
        self.page_changed.emit(self.current_page, self.total_pages)

    def _update_nav(self):
        loaded = self.total_pages > 0
        self.prev_btn.setEnabled(loaded and self.current_page > 0)
        self.next_btn.setEnabled(loaded and self.current_page < self.total_pages - 1)
        self.page_label.setText(
            f"Page {self.current_page + 1} / {self.total_pages}" if loaded else "–")

    # --- zoom ---

    def set_zoom(self, zoom):
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        self.page_view.set_zoom(self.zoom)
        self.zoom_label.setText(f"{self.zoom * 100:.0f}%")

    def fit_width(self):
        if self.page_view.base_pixmap:
            available = max(1, self.scroll.viewport().width() - 4)
            self.set_zoom(available / self.page_view.base_pixmap.width())

    # --- geometry (PDF points, y from top) ---

    def page_size_pt(self):
        """(width, height) of the current page in PDF points."""
        pm = self.page_view.base_pixmap
        if not pm:
            return (612.0, 792.0)
        return (pm.width() / PX_PER_PT, pm.height() / PX_PER_PT)

    def set_signature_geometry_pt(self, x, y, w, h):
        self.page_view.set_sig_rect(x * PX_PER_PT, y * PX_PER_PT,
                                    w * PX_PER_PT, h * PX_PER_PT)

    def set_preview_name(self, name):
        self.page_view.set_preview_name(name)

    def _on_view_position(self, x_px, y_px):
        self.position_changed.emit(x_px / PX_PER_PT, y_px / PX_PER_PT)
