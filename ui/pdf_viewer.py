"""
PDF viewer built on pypdfium2 (rendering, text, search, page objects)
and pypdf (document structure edits) — both permissively licensed.

Interactive signature placement, page navigation, zoom, text search
with highlights, text selection, rotation, form filling and a PDF
object inspector.

Coordinate systems:
- "page space": PDF user space of the unrotated page, origin bottom-left,
  units = points. pypdfium2 text/object coords and pypdf /Rect values
  live here.
- "view space": the rendered page as displayed (honouring /Rotate),
  origin top-left, units = points. All widget/UI geometry lives here
  (multiplied by PX_PER_PT for pixels).
"""
import io
import logging
import os
from collections import OrderedDict

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QPushButton, QSpinBox, QMenu,
                               QApplication, QToolTip)
from PySide6.QtGui import (QPixmap, QImage, QPainter, QPen, QColor, QFont,
                           QKeySequence, QCursor)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint

logger = logging.getLogger(__name__)

RENDER_DPI = 150
PT_PER_INCH = 72.0
PX_PER_PT = RENDER_DPI / PT_PER_INCH  # image pixels per PDF point
PAGE_CACHE_SIZE = 8

# FPDF_PAGEOBJ_* constants
_PDFIUM_OBJ_TYPES = {1: "Text object", 2: "Path/drawing", 3: "Image",
                     4: "Shading", 5: "Form XObject"}

_FIELD_TYPE_NAMES = {"/Tx": "Text", "/Btn": "Button/Checkbox",
                     "/Ch": "Choice", "/Sig": "Signature"}


class PageView(QWidget):
    """Renders one page plus overlays: signature box, search highlights,
    text selection and object-inspector highlight.

    All geometry is kept in unzoomed image pixels (RENDER_DPI); zoom only
    affects display.
    """
    position_changed = Signal(float, float)  # top-left of box, image px
    signature_clicked = Signal(str)          # field name of existing sig
    ctrl_wheel_zoomed = Signal(int, QPoint)  # wheel delta, pos in widget
    object_inspect_requested = Signal(float, float)  # image px
    selection_changed = Signal(QRectF)       # marquee, unzoomed px
    copy_requested = Signal()
    copy_page_requested = Signal()

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

        p = self._to_image(event.position())

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
            p = self._to_image(event.position())
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

        p = self._to_image(event.position())
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
        chosen = menu.exec(event.globalPos())
        if chosen == copy_action:
            self.copy_requested.emit()
        elif chosen == page_action:
            self.copy_page_requested.emit()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.ctrl_wheel_zoomed.emit(event.angleDelta().y(),
                                        event.position().toPoint())
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


def _pil_to_qpixmap(pil_image):
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    width, height = pil_image.size
    data = pil_image.tobytes("raw", "RGB")
    image = QImage(data, width, height, width * 3,
                   QImage.Format_RGB888).copy()
    return QPixmap.fromImage(image)


def _qualified_field(annot_obj):
    """(fully-qualified name, /FT, value) of a widget annotation,
    resolving /Parent inheritance."""
    names, ft, value = [], None, None
    node, seen = annot_obj, 0
    while node is not None and seen < 16:
        t = node.get("/T")
        if t:
            names.insert(0, str(t))
        if ft is None and node.get("/FT"):
            ft = str(node.get("/FT"))
        if value is None and node.get("/V") is not None:
            value = node.get("/V")
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        seen += 1
    return ".".join(names), ft, value


class PDFViewer(QWidget):
    """Single-document viewer: navigation, zoom, search, placement,
    rotation, form filling and object inspection.

    Coordinates emitted/accepted by this widget are in view points
    (rendered page, origin top-left).
    """
    position_changed = Signal(float, float)   # x_pt, y_pt (view space)
    page_changed = Signal(int, int)           # current (0-based), total
    signature_clicked = Signal(str)           # existing sig field name
    object_inspected = Signal(dict)           # Ctrl+Alt+Click details

    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 3.0, 0.25

    def __init__(self):
        super().__init__()
        self.doc = None               # pdfium document
        self.pdf_path = None
        self.dirty = False
        self.current_page = 0
        self.total_pages = 0
        self.zoom = 1.0
        self._reader = None           # pypdf reader (structure info)
        self._pages = {}              # page_num -> pdfium PdfPage
        self._textpages = {}          # page_num -> pdfium PdfTextPage
        self._cache = OrderedDict()   # page_num -> QPixmap
        self.matches = []             # [(page, QRectF view pt)]
        self.current_match = -1
        self.selected_text = ""
        self._page_words = []         # view-space words of the current page
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

    # --- document lifecycle ---

    def load_pdf(self, pdf_path):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        try:
            with open(pdf_path, "rb") as f:
                data = f.read()
            self.pdf_path = pdf_path
            self.dirty = False
            self._open_from_bytes(data)
            self.show_page(0)
            self.fit_width()
        except Exception:
            logger.exception(f"Failed to load PDF: {pdf_path}")
            raise

    def _open_from_bytes(self, data):
        self._close_engine()
        doc = pdfium.PdfDocument(data)
        try:
            if doc.get_formtype() != 0:  # FORMTYPE_NONE
                doc.init_forms()
        except Exception:
            logger.debug("init_forms failed", exc_info=True)
        self.doc = doc
        try:
            self._reader = PdfReader(io.BytesIO(data), strict=False)
        except Exception:
            logger.exception("pypdf could not parse document structure")
            self._reader = None
        self.total_pages = len(self.doc)
        self._cache.clear()
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, max(1, self.total_pages))
        self.page_spin.blockSignals(False)

    def _close_engine(self):
        for tp in self._textpages.values():
            try:
                tp.close()
            except Exception:
                pass
        for pg in self._pages.values():
            try:
                pg.close()
            except Exception:
                pass
        self._textpages.clear()
        self._pages.clear()
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = None
        self._reader = None
        self._cache.clear()

    def close_doc(self):
        self._close_engine()

    def _serialize(self):
        """Current document state (incl. rotations) as bytes."""
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()

    def _reload_from_bytes(self, data, keep_page=True):
        page = self.current_page if keep_page else 0
        self._open_from_bytes(data)
        self.show_page(min(page, self.total_pages - 1))

    def save_as(self, output_path):
        if not self.doc:
            return
        with open(output_path, "wb") as f:
            self.doc.save(f)
        self.dirty = False

    # --- pdfium page access ---

    def _page(self, page_num):
        if page_num not in self._pages:
            self._pages[page_num] = self.doc[page_num]
        return self._pages[page_num]

    def _textpage(self, page_num):
        if page_num not in self._textpages:
            self._textpages[page_num] = self._page(page_num).get_textpage()
        return self._textpages[page_num]

    # --- coordinate transforms (page space <-> view space, points) ---

    def _geometry(self, page_num=None):
        page = self._page(self.current_page if page_num is None else page_num)
        left, bottom, right, top = page.get_mediabox()
        return left, bottom, right - left, top - bottom, page.get_rotation()

    def _to_view(self, x, y, geom):
        """Page-space point -> view-space point (pt, origin top-left)."""
        ox, oy, w, h, rot = geom
        x, y = x - ox, y - oy
        if rot == 90:
            return y, x
        if rot == 180:
            return w - x, y
        if rot == 270:
            return h - y, w - x
        return x, h - y

    def _to_page(self, u, v, geom):
        """View-space point -> page-space point."""
        ox, oy, w, h, rot = geom
        if rot == 90:
            x, y = v, u
        elif rot == 180:
            x, y = w - u, v
        elif rot == 270:
            x, y = w - v, h - u
        else:
            x, y = u, h - v
        return x + ox, y + oy

    def _page_rect_to_view(self, l, b, r, t, geom):
        """Page-space rect -> view-space QRectF (pt)."""
        u1, v1 = self._to_view(l, b, geom)
        u2, v2 = self._to_view(r, t, geom)
        return QRectF(QPointF(min(u1, u2), min(v1, v2)),
                      QPointF(max(u1, u2), max(v1, v2)))

    def _page_rect_to_px(self, l, b, r, t, geom):
        rect = self._page_rect_to_view(l, b, r, t, geom)
        return QRectF(rect.x() * PX_PER_PT, rect.y() * PX_PER_PT,
                      rect.width() * PX_PER_PT, rect.height() * PX_PER_PT)

    def view_rect_to_page_box(self, x, y, w, h):
        """View rect (pt, top-left origin) -> page-space signature box
        (x1, y1, x2, y2) for pyhanko."""
        geom = self._geometry()
        x1, y1 = self._to_page(x, y, geom)
        x2, y2 = self._to_page(x + w, y + h, geom)
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    # --- rendering / pages ---

    def _render(self, page_num):
        if page_num in self._cache:
            self._cache.move_to_end(page_num)
            return self._cache[page_num]

        bitmap = self._page(page_num).render(scale=PX_PER_PT,
                                             may_draw_forms=True)
        pixmap = _pil_to_qpixmap(bitmap.to_pil())
        try:
            bitmap.close()
        except Exception:
            pass

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
        page = self._page(self.current_page)
        page.set_rotation((page.get_rotation() + delta) % 360)
        self.dirty = True
        # rotation invalidates cached render, text geometry and search rects
        self._cache.pop(self.current_page, None)
        tp = self._textpages.pop(self.current_page, None)
        if tp:
            try:
                tp.close()
            except Exception:
                pass
        self.clear_search()
        self.show_page(self.current_page)

    # --- form fields ---

    def form_fields(self):
        if not self._reader:
            return []
        fields = []
        for page_num, page in enumerate(self._reader.pages):
            for ref in (page.get("/Annots") or []):
                try:
                    obj = ref.get_object()
                    if obj.get("/Subtype") != "/Widget":
                        continue
                    name, ftype, value = _qualified_field(obj)
                    if ftype == "/Sig":
                        continue
                    idnum = getattr(ref, "idnum",
                                    getattr(obj.indirect_reference, "idnum", 0))
                    fields.append({
                        "page": page_num,
                        "xref": idnum,
                        "name": name or f"field-{idnum}",
                        "type": ftype or "",
                        "type_name": _FIELD_TYPE_NAMES.get(ftype, ftype or "?"),
                        "value": str(value if value is not None else ""),
                    })
                except Exception:
                    logger.debug("Skipping malformed widget on page %d",
                                 page_num, exc_info=True)
        return fields

    def apply_form_updates(self, updates):
        """updates: [(field dict from form_fields, new value str)]"""
        if not self.doc or not updates:
            return
        data = self._serialize()
        reader = PdfReader(io.BytesIO(data), strict=False)
        writer = PdfWriter(clone_from=reader)

        by_page = {}
        for field, value in updates:
            if field["type"] == "/Btn" and value and not value.startswith("/"):
                value = "/" + value  # checkbox states are PDF names
            by_page.setdefault(field["page"], {})[field["name"]] = value

        for page_num, values in by_page.items():
            try:
                writer.update_page_form_field_values(
                    writer.pages[page_num], values)
            except Exception:
                logger.exception("Form update failed on page %d", page_num)

        buf = io.BytesIO()
        writer.write(buf)
        self._reload_from_bytes(buf.getvalue())
        self.dirty = True

    # --- document info (properties dialog) ---

    def document_info(self):
        rows = [("Pages", self.total_pages)]
        try:
            version = self.doc.get_version()
            if version:
                rows.append(("PDF format", f"{version // 10}.{version % 10}"))
        except Exception:
            pass
        rows.append(("Encrypted",
                     "Yes" if self._reader and self._reader.is_encrypted
                     else "No"))
        rows.append(("Unsaved changes", "Yes" if self.dirty else "No"))
        try:
            meta = self.doc.get_metadata_dict() or {}
            for key, value in meta.items():
                if value:
                    rows.append((key, value))
        except Exception:
            pass
        return rows

    # --- object inspector ---

    def inspect_object_at(self, x_px, y_px):
        details = self._object_details_at(x_px / PX_PER_PT, y_px / PX_PER_PT)
        self.page_view.set_object_highlight(details.get("highlight_px"))
        self.object_inspected.emit(details)

    def _object_details_at(self, u_pt, v_pt):
        geom = self._geometry()
        px, py = self._to_page(u_pt, v_pt, geom)
        ox, oy, w, h, _rot = geom

        page_idnum, content_ids = "", "none"
        if self._reader:
            try:
                rpage = self._reader.pages[self.current_page]
                page_idnum = rpage.indirect_reference.idnum
                contents = rpage.get("/Contents")
                if contents is not None:
                    ids = ([str(c.idnum) for c in contents]
                           if isinstance(contents, list)
                           else [str(contents.idnum)])
                    content_ids = ", ".join(ids)
            except Exception:
                pass

        base = {
            "kind": "Page",
            "page": self.current_page + 1,
            "point": f"{px:.2f}, {py:.2f} pt (page space)",
            "page_object_id": page_idnum,
            "content_object_ids": content_ids,
            "highlight_px": self._page_rect_to_px(ox, oy, ox + w, oy + h, geom),
        }

        # widgets and annotations (pypdf)
        if self._reader:
            try:
                rpage = self._reader.pages[self.current_page]
                for ref in (rpage.get("/Annots") or []):
                    obj = ref.get_object()
                    rect = [float(v) for v in (obj.get("/Rect") or [])]
                    if len(rect) != 4:
                        continue
                    l, b = min(rect[0], rect[2]), min(rect[1], rect[3])
                    r_, t = max(rect[0], rect[2]), max(rect[1], rect[3])
                    if not (l <= px <= r_ and b <= py <= t):
                        continue
                    idnum = getattr(ref, "idnum", "")
                    if obj.get("/Subtype") == "/Widget":
                        name, ftype, value = _qualified_field(obj)
                        return {**base, "kind": "Widget",
                                "object_id": idnum,
                                "field_name": name,
                                "field_type": _FIELD_TYPE_NAMES.get(
                                    ftype, ftype or "?"),
                                "value": str(value or ""),
                                "rect": str(rect),
                                "highlight_px": self._page_rect_to_px(
                                    l, b, r_, t, geom)}
                    return {**base, "kind": "Annotation",
                            "object_id": idnum,
                            "subtype": str(obj.get("/Subtype", "")),
                            "content": str(obj.get("/Contents", "")),
                            "rect": str(rect),
                            "highlight_px": self._page_rect_to_px(
                                l, b, r_, t, geom)}
            except Exception:
                logger.debug("Annotation hit-test failed", exc_info=True)

        # page content objects (pdfium): images first, then text, then paths
        hits = []
        try:
            for obj in self._page(self.current_page).get_objects():
                try:
                    l, b, r_, t = obj.get_bounds()
                except Exception:
                    continue
                if l <= px <= r_ and b <= py <= t:
                    hits.append((obj.type, (l, b, r_, t)))
        except Exception:
            logger.debug("Object enumeration failed", exc_info=True)

        for wanted in (3, 1, 2, 4, 5):
            for otype, bounds in hits:
                if otype != wanted:
                    continue
                info = {**base,
                        "kind": _PDFIUM_OBJ_TYPES.get(otype, f"type {otype}"),
                        "object_id": "content stream",
                        "bounds": f"({bounds[0]:.1f}, {bounds[1]:.1f}, "
                                  f"{bounds[2]:.1f}, {bounds[3]:.1f}) pt",
                        "highlight_px": self._page_rect_to_px(*bounds, geom)}
                if otype == 1:  # text: include the actual text content
                    try:
                        tp = self._textpage(self.current_page)
                        text = tp.get_text_bounded(*bounds)
                        info["text"] = text[:500]
                    except Exception:
                        pass
                return info

        return base

    # --- words / text selection ---

    def _load_page_words(self, page_num):
        """Extract words as view-space tuples
        (x0, y0, x1, y1, text, block, line, word_no)."""
        words = []
        try:
            geom = self._geometry(page_num)
            tp = self._textpage(page_num)
            n_chars = tp.count_chars()
            text = tp.get_text_range() if n_chars else ""

            current, box, line_no, word_no = [], None, 0, 0
            for i in range(n_chars):
                ch = text[i] if i < len(text) else " "
                if ch.isspace():
                    if current:
                        words.append((box.x(), box.y(),
                                      box.x() + box.width(),
                                      box.y() + box.height(),
                                      "".join(current), 0, line_no, word_no))
                        word_no += 1
                        current, box = [], None
                    if ch == "\n":
                        line_no += 1
                        word_no = 0
                    continue
                try:
                    l, b, r, t = tp.get_charbox(i)
                except Exception:
                    continue
                crect = self._page_rect_to_view(l, b, r, t, geom)
                box = crect if box is None else box.united(crect)
                current.append(ch)
            if current and box is not None:
                words.append((box.x(), box.y(),
                              box.x() + box.width(), box.y() + box.height(),
                              "".join(current), 0, line_no, word_no))
        except Exception:
            logger.debug("Cannot extract words on page %d", page_num,
                         exc_info=True)
        self._page_words = words
        self.page_view.word_boxes = [
            QRectF(w[0] * PX_PER_PT, w[1] * PX_PER_PT,
                   (w[2] - w[0]) * PX_PER_PT, (w[3] - w[1]) * PX_PER_PT)
            for w in words]

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

    def current_page_text(self):
        """Plain text of the currently shown page."""
        if not self.doc:
            return ""
        try:
            return self._textpage(self.current_page).get_text_range()
        except Exception:
            logger.debug("Text extraction failed", exc_info=True)
            return ""

    def copy_page_text(self):
        if not self.doc:
            return
        text = self.current_page_text().strip()
        if text:
            QApplication.clipboard().setText(text)
            QToolTip.showText(QCursor.pos(),
                              f"Copied page {self.current_page + 1} text "
                              f"({len(text)} characters)", self.page_view)

    # --- signature widget areas ---

    def _sig_areas_for(self, page_num):
        """Rectangles (unzoomed px) of signature widgets on a page."""
        areas = []
        if not self._reader:
            return areas
        try:
            geom = self._geometry(page_num)
            rpage = self._reader.pages[page_num]
            for ref in (rpage.get("/Annots") or []):
                obj = ref.get_object()
                if obj.get("/Subtype") != "/Widget":
                    continue
                name, ftype, _ = _qualified_field(obj)
                if ftype != "/Sig":
                    continue
                rect = [float(v) for v in (obj.get("/Rect") or [])]
                if len(rect) != 4:
                    continue
                areas.append((self._page_rect_to_px(
                    min(rect[0], rect[2]), min(rect[1], rect[3]),
                    max(rect[0], rect[2]), max(rect[1], rect[3]), geom),
                    name))
        except Exception:
            logger.debug("Could not enumerate signature widgets on page %d",
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
                try:
                    geom = self._geometry(pno)
                    tp = self._textpage(pno)
                    searcher = tp.search(needle)
                    while True:
                        hit = searcher.get_next()
                        if hit is None:
                            break
                        index, count = hit
                        n_rects = tp.count_rects(index, count)
                        for i in range(n_rects):
                            l, b, r, t = tp.get_rect(i)
                            self.matches.append(
                                (pno, self._page_rect_to_view(l, b, r, t,
                                                              geom)))
                    searcher.close()
                except Exception:
                    logger.debug("Search failed on page %d", pno,
                                 exc_info=True)
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
        cx = rect.center().x() * PX_PER_PT * self.zoom
        cy = rect.center().y() * PX_PER_PT * self.zoom
        self.scroll.ensureVisible(int(cx), int(cy), 140, 140)

    def _apply_highlights(self):
        rects, current_local = [], -1
        for idx, (page, rect) in enumerate(self.matches):
            if page == self.current_page:
                if idx == self.current_match:
                    current_local = len(rects)
                rects.append(QRectF(rect.x() * PX_PER_PT,
                                    rect.y() * PX_PER_PT,
                                    rect.width() * PX_PER_PT,
                                    rect.height() * PX_PER_PT))
        self.page_view.set_highlights(rects, current_local)

    # --- geometry (view points, y from top) ---

    def page_size_pt(self):
        """(width, height) of the current page as displayed, in points."""
        if not self.doc:
            return (612.0, 792.0)
        return self._page(self.current_page).get_size()

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
