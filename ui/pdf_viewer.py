"""
PDF viewer built on PyMuPDF with interactive signature placement,
page navigation, zoom and text search with highlights.
"""
import logging
import os
from collections import OrderedDict

import fitz  # PyMuPDF

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QPushButton, QSpinBox, QMenu,
                             QApplication, QToolTip)
from PyQt5.QtGui import (QPixmap, QImage, QPainter, QPen, QColor, QFont,
                         QKeySequence, QCursor)
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QPointF, QPoint

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
    signature_clicked = pyqtSignal(str)          # field name of existing sig
    ctrl_wheel_zoomed = pyqtSignal(int, QPoint)  # wheel delta, pos in widget
    object_inspect_requested = pyqtSignal(float, float)  # image px
    selection_changed = pyqtSignal(QRectF)       # marquee, unzoomed px
    copy_requested = pyqtSignal()
    copy_page_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.base_pixmap = None
        self.zoom = 1.0
        self.sig_rect = None          # QRectF, unzoomed image px
        self.preview_name = ""
        self.placement_enabled = False  # signing mode: show/move the box
        self.sig_areas = []           # [(QRectF px, field_name)] existing sigs
        self.highlights = []          # [QRectF], unzoomed image px
        self.object_highlight = None  # QRectF px selected by object inspector
        self.current_highlight = -1   # index into highlights
        self.word_boxes = []          # [QRectF px] text words (for cursor)
        self.selected_word_rects = []  # [QRectF px] current text selection
        self.sel_marquee = None       # QRectF px while dragging a selection
        self._selecting = False
        self._sel_anchor = QPointF()
        self._dragging = False
        self._drag_offset = QPointF()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
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

    def set_object_highlight(self, rect):
        self.object_highlight = rect
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

    def _sig_area_at(self, p):
        for rect, field_name in self.sig_areas:
            if rect.contains(p):
                return field_name
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.base_pixmap:
            return

        p = self._to_image(event.pos())

        if (event.modifiers() & Qt.ControlModifier
                and event.modifiers() & Qt.AltModifier):
            self.object_inspect_requested.emit(p.x(), p.y())
            return

        # reading mode: signature click, or start a text selection
        if not self.placement_enabled:
            field_name = self._sig_area_at(p)
            if field_name is not None:
                self.signature_clicked.emit(field_name)
                return
            self.setFocus()
            self._selecting = True
            self._sel_anchor = p
            self.sel_marquee = None
            self.selected_word_rects = []
            self.selection_changed.emit(QRectF())  # clear previous selection
            self.update()
            return

        if not self.sig_rect:
            return
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
        if not self.base_pixmap:
            return

        if not self.placement_enabled:
            p = self._to_image(event.pos())
            if self._selecting and (event.buttons() & Qt.LeftButton):
                self.sel_marquee = QRectF(self._sel_anchor, p).normalized()
                self.selection_changed.emit(self.sel_marquee)
                self.update()
                return
            # cursor: hand over signatures, I-beam over text
            if self._sig_area_at(p) is not None:
                self.setCursor(Qt.PointingHandCursor)
            elif any(r.contains(p) for r in self.word_boxes):
                self.setCursor(Qt.IBeamCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        if not self.sig_rect:
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
        if self._selecting:
            self._selecting = False
            self.sel_marquee = None  # keep word highlights, drop the marquee
            self.update()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_requested.emit()
        elif event.key() == Qt.Key_Escape and self.selected_word_rects:
            self.selected_word_rects = []
            self.sel_marquee = None
            self.selection_changed.emit(QRectF())
            self.update()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if self.placement_enabled or not self.base_pixmap:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy selected text\tCtrl+C")
        copy_action.setEnabled(bool(self.selected_word_rects))
        page_action = menu.addAction("Copy all page text")
        chosen = menu.exec_(event.globalPos())
        if chosen == copy_action:
            self.copy_requested.emit()
        elif chosen == page_action:
            self.copy_page_requested.emit()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.ctrl_wheel_zoomed.emit(event.angleDelta().y(), event.pos())
            event.accept()
        else:
            event.ignore()  # let the scroll area scroll normally

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

        # text selection
        if self.selected_word_rects:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(37, 99, 235, 70))
            for rect in self.selected_word_rects:
                painter.drawRect(self._zoomed(rect))
        if self.sel_marquee:
            painter.setPen(QPen(QColor(37, 99, 235, 170), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._zoomed(self.sel_marquee))

        # object inspector highlight
        if self.object_highlight:
            painter.setPen(QPen(QColor(124, 58, 237), 3, Qt.DashLine))
            painter.setBrush(QColor(124, 58, 237, 45))
            painter.drawRect(self._zoomed(self.object_highlight))

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
    signature_clicked = pyqtSignal(str)           # existing sig field name
    object_inspected = pyqtSignal(dict)           # Ctrl+Alt+Click details

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
        self.selected_text = ""
        self._page_words = []         # fitz words of the current page
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
        zoom_out.setToolTip("Zoom out (Ctrl+-, Ctrl+Scroll)")
        zoom_out.clicked.connect(self.zoom_out)
        nav.addWidget(zoom_out)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        nav.addWidget(self.zoom_label)

        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(34)
        zoom_in.setToolTip("Zoom in (Ctrl++, Ctrl+Scroll)")
        zoom_in.clicked.connect(self.zoom_in)
        nav.addWidget(zoom_in)

        fit_w = QPushButton("Fit width")
        fit_w.clicked.connect(self.fit_width)
        nav.addWidget(fit_w)

        fit_p = QPushButton("Fit page")
        fit_p.clicked.connect(self.fit_page)
        nav.addWidget(fit_p)

        rotate_left = QPushButton("Rotate left")
        rotate_left.setToolTip("Rotate current page left")
        rotate_left.clicked.connect(lambda: self.rotate_current_page(-90))
        nav.addWidget(rotate_left)

        rotate_right = QPushButton("Rotate right")
        rotate_right.setToolTip("Rotate current page right")
        rotate_right.clicked.connect(lambda: self.rotate_current_page(90))
        nav.addWidget(rotate_right)

        layout.addLayout(nav)

        self.page_view = PageView()
        self.page_view.position_changed.connect(self._on_view_position)
        self.page_view.signature_clicked.connect(self.signature_clicked.emit)
        self.page_view.ctrl_wheel_zoomed.connect(self._on_ctrl_wheel)
        self.page_view.object_inspect_requested.connect(self.inspect_object_at)
        self.page_view.selection_changed.connect(self._on_selection_changed)
        self.page_view.copy_requested.connect(self.copy_selection)
        self.page_view.copy_page_requested.connect(self.copy_page_text)

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
        self.page_view.sig_areas = self._sig_areas_for(page_num)
        self.page_view.set_object_highlight(None)
        self._load_page_words(page_num)
        self._clear_selection()
        self._apply_highlights()
        self._update_nav()
        self.page_changed.emit(self.current_page, self.total_pages)

    def rotate_current_page(self, delta):
        if not self.doc:
            return
        page = self.doc[self.current_page]
        page.set_rotation((page.rotation + delta) % 360)
        self._cache.pop(self.current_page, None)
        self.show_page(self.current_page)

    def save_as(self, output_path):
        if not self.doc:
            return
        self.doc.save(output_path, garbage=4, deflate=True)

    # --- form fields ---

    def form_fields(self):
        if not self.doc:
            return []
        fields = []
        for page_num in range(self.total_pages):
            try:
                widgets = self.doc[page_num].widgets() or []
            except Exception:
                logger.debug("Could not enumerate widgets on page %d",
                             page_num, exc_info=True)
                continue
            for widget in widgets:
                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    continue
                fields.append({
                    "page": page_num,
                    "xref": getattr(widget, "xref", 0),
                    "name": widget.field_name or f"field-{getattr(widget, 'xref', '')}",
                    "type": widget.field_type,
                    "type_name": widget.field_type_string or str(widget.field_type),
                    "value": str(widget.field_value or ""),
                })
        return fields

    def apply_form_updates(self, updates):
        if not self.doc:
            return
        touched_pages = set()
        for field, value in updates:
            page_num = field["page"]
            for widget in self.doc[page_num].widgets() or []:
                if getattr(widget, "xref", None) == field["xref"]:
                    widget.field_value = value
                    widget.update()
                    touched_pages.add(page_num)
                    break
        for page_num in touched_pages:
            self._cache.pop(page_num, None)
        self.show_page(self.current_page)

    # --- object inspector ---

    def inspect_object_at(self, x_px, y_px):
        details = self._object_details_at(x_px / PX_PER_PT, y_px / PX_PER_PT)
        highlight = details.get("highlight_px")
        self.page_view.set_object_highlight(highlight)
        self.object_inspected.emit(details)

    def _object_details_at(self, x_pt, y_pt):
        page = self.doc[self.current_page]
        point = fitz.Point(x_pt, y_pt)
        base = {
            "kind": "Page",
            "page": self.current_page + 1,
            "point": f"{x_pt:.2f}, {y_pt:.2f} pt",
            "page_xref": page.xref,
            "content_xrefs": ", ".join(str(x) for x in page.get_contents()) or "none",
            "highlight_px": QRectF(0, 0, page.rect.width * PX_PER_PT,
                                   page.rect.height * PX_PER_PT),
        }

        for widget in page.widgets() or []:
            if widget.rect.contains(point):
                return {
                    **base,
                    "kind": "Widget",
                    "xref": getattr(widget, "xref", ""),
                    "field_name": widget.field_name or "",
                    "field_type": widget.field_type_string or widget.field_type,
                    "value": str(widget.field_value or ""),
                    "rect": str(widget.rect),
                    "highlight_px": self._rect_to_px(widget.rect),
                }

        annot = page.first_annot
        while annot:
            if annot.rect.contains(point):
                return {
                    **base,
                    "kind": "Annotation",
                    "xref": annot.xref,
                    "type": annot.type[1],
                    "content": annot.info.get("content", ""),
                    "rect": str(annot.rect),
                    "highlight_px": self._rect_to_px(annot.rect),
                }
            annot = annot.next

        for img in page.get_images(full=True):
            xref = img[0]
            for rect in page.get_image_rects(xref):
                if rect.contains(point):
                    return {
                        **base,
                        "kind": "Image",
                        "xref": xref,
                        "width": img[2],
                        "height": img[3],
                        "colorspace": img[5],
                        "rect": str(rect),
                        "highlight_px": self._rect_to_px(rect),
                    }

        for rect, text in self._text_blocks():
            if rect.contains(point):
                return {
                    **base,
                    "kind": "Text block",
                    "xref": "content stream",
                    "text": text[:500],
                    "rect": str(rect),
                    "highlight_px": self._rect_to_px(rect),
                }

        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect and rect.contains(point):
                return {
                    **base,
                    "kind": "Drawing/path",
                    "xref": "content stream",
                    "items": len(drawing.get("items", [])),
                    "rect": str(rect),
                    "highlight_px": self._rect_to_px(rect),
                }
        return base

    def _text_blocks(self):
        blocks = []
        for block in self.doc[self.current_page].get_text("blocks"):
            if len(block) >= 5 and block[4].strip():
                blocks.append((fitz.Rect(block[:4]), block[4].strip()))
        return blocks

    def _rect_to_px(self, rect):
        return QRectF(rect.x0 * PX_PER_PT, rect.y0 * PX_PER_PT,
                      rect.width * PX_PER_PT, rect.height * PX_PER_PT)

    def _load_page_words(self, page_num):
        try:
            self._page_words = self.doc[page_num].get_text("words")
        except Exception:
            logger.debug("Cannot extract words on page %d", page_num,
                         exc_info=True)
            self._page_words = []
        self.page_view.word_boxes = [
            QRectF(w[0] * PX_PER_PT, w[1] * PX_PER_PT,
                   (w[2] - w[0]) * PX_PER_PT, (w[3] - w[1]) * PX_PER_PT)
            for w in self._page_words]

    # --- text selection ---

    def _clear_selection(self):
        self.selected_text = ""
        self.page_view.selected_word_rects = []
        self.page_view.sel_marquee = None
        self.page_view.update()

    def _on_selection_changed(self, marquee_px):
        if marquee_px.isNull() or marquee_px.isEmpty():
            self._clear_selection()
            return

        marquee_pt = QRectF(marquee_px.x() / PX_PER_PT,
                            marquee_px.y() / PX_PER_PT,
                            marquee_px.width() / PX_PER_PT,
                            marquee_px.height() / PX_PER_PT)

        # words are (x0, y0, x1, y1, text, block, line, word_no)
        selected, rects = [], []
        for w in self._page_words:
            rect = QRectF(w[0], w[1], w[2] - w[0], w[3] - w[1])
            if rect.intersects(marquee_pt):
                selected.append(w)
                rects.append(QRectF(w[0] * PX_PER_PT, w[1] * PX_PER_PT,
                                    (w[2] - w[0]) * PX_PER_PT,
                                    (w[3] - w[1]) * PX_PER_PT))

        lines = {}
        for w in selected:
            lines.setdefault((w[5], w[6]), []).append(w)
        parts = []
        for key in sorted(lines):
            words = sorted(lines[key], key=lambda w: w[7])
            parts.append(" ".join(w[4] for w in words))
        self.selected_text = "\n".join(parts)

        self.page_view.selected_word_rects = rects
        self.page_view.update()

    def copy_selection(self):
        if self.selected_text:
            QApplication.clipboard().setText(self.selected_text)
            QToolTip.showText(QCursor.pos(),
                              f"Copied {len(self.selected_text)} characters",
                              self.page_view)

    def copy_page_text(self):
        if not self.doc:
            return
        text = self.doc[self.current_page].get_text().strip()
        if text:
            QApplication.clipboard().setText(text)
            QToolTip.showText(QCursor.pos(),
                              f"Copied page {self.current_page + 1} text "
                              f"({len(text)} characters)", self.page_view)

    def _sig_areas_for(self, page_num):
        """Rectangles (unzoomed px) of signature widgets on a page."""
        areas = []
        try:
            for widget in self.doc[page_num].widgets() or []:
                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    r = widget.rect
                    areas.append((
                        QRectF(r.x0 * PX_PER_PT, r.y0 * PX_PER_PT,
                               (r.x1 - r.x0) * PX_PER_PT,
                               (r.y1 - r.y0) * PX_PER_PT),
                        widget.field_name or ""))
        except Exception:
            logger.debug("Could not enumerate widgets on page %d",
                         page_num, exc_info=True)
        return areas

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

    def zoom_in(self):
        self._anchored_zoom(self.zoom + self.ZOOM_STEP)

    def zoom_out(self):
        self._anchored_zoom(self.zoom - self.ZOOM_STEP)

    def _anchored_zoom(self, new_zoom, anchor=None):
        """Zoom while keeping the document point under `anchor`
        (viewport coordinates; defaults to the center) in place."""
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        old_zoom = self.zoom
        if not self.page_view.base_pixmap or abs(new_zoom - old_zoom) < 1e-9:
            self.set_zoom(new_zoom)
            return

        viewport = self.scroll.viewport()
        if anchor is None:
            anchor = QPoint(viewport.width() // 2, viewport.height() // 2)

        in_widget = self.page_view.mapFrom(viewport, anchor)
        doc_x = in_widget.x() / old_zoom
        doc_y = in_widget.y() / old_zoom

        self.set_zoom(new_zoom)

        self.scroll.horizontalScrollBar().setValue(
            round(doc_x * self.zoom - anchor.x()))
        self.scroll.verticalScrollBar().setValue(
            round(doc_y * self.zoom - anchor.y()))

    def _on_ctrl_wheel(self, delta, widget_pos):
        factor = 1.1 ** (delta / 120.0)  # one notch = 10%
        anchor = self.page_view.mapTo(self.scroll.viewport(), widget_pos)
        self._anchored_zoom(self.zoom * factor, anchor)

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
