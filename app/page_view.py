# Интерактивный предпросмотр с учётом bbox_override.

from __future__ import annotations

from typing import Dict, Optional, Tuple

import fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPixmap,
    QTextCursor, QTextOption, QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsTextItem,
    QGraphicsView,
)

from . import builder
from .config import FONTS
from .models import PageData, TextBlock, TextLine

_FONT_FAMILY_CACHE: Dict[str, str] = {}
_PDF_FONTS: Dict[str, str] = {}

ALIGN_MAP = {
    "left": Qt.AlignLeft,
    "center": Qt.AlignHCenter,
    "right": Qt.AlignRight,
    "justify": Qt.AlignJustify,
}

def _normalize_font_name(name: str) -> str:
    if not name:
        return ""
    return name.split("+", 1)[1] if "+" in name else name

def family_name_for(family_key: str) -> str:
    fam = FONTS.get(family_key) or FONTS.get("sans")
    if not fam:
        return "Arial"
    path = fam.get("regular")
    if not path:
        return "Arial"
    if path in _FONT_FAMILY_CACHE:
        return _FONT_FAMILY_CACHE[path]
    font_id = QFontDatabase.addApplicationFont(path)
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            _FONT_FAMILY_CACHE[path] = families[0]
            return families[0]
    _FONT_FAMILY_CACHE[path] = "Arial"
    return "Arial"

def register_pdf_fonts(doc: Optional["fitz.Document"]) -> Dict[str, str]:
    _PDF_FONTS.clear()
    if doc is None:
        return _PDF_FONTS
    for page in doc:
        try:
            font_list = page.get_fonts(full=True)
        except Exception:
            continue
        for info in font_list:
            try:
                xref = int(info[0])
                ext = str(info[1]).lower() if len(info) > 1 else ""
                basefont = str(info[3]) if len(info) > 3 else ""
                if not basefont or ext not in ("ttf", "otf"):
                    continue
                normalized = _normalize_font_name(basefont)
                if normalized in _PDF_FONTS:
                    continue
                result = doc.extract_font(xref)
                if not result or len(result) < 4:
                    continue
                buffer = result[3]
                if not buffer:
                    continue
                fid = QFontDatabase.addApplicationFontFromData(buffer)
                if fid < 0:
                    continue
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    _PDF_FONTS[normalized] = families[0]
            except Exception:
                continue
    return _PDF_FONTS

class EditableLineItem(QGraphicsTextItem):
    def __init__(self, view: "PageView", block: TextBlock, line_index: int):
        super().__init__()
        self._view = view
        self._block = block
        self._line_index = line_index
        self._editing = False
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(10)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAcceptHoverEvents(True)

    @property
    def line(self) -> Optional[TextLine]:
        if self._line_index >= 0 and self._block.lines:
            if 0 <= self._line_index < len(self._block.lines):
                return self._block.lines[self._line_index]
        return None

    def refresh(self) -> None:
        if self._editing:
            return
        zoom = self._view.zoom_factor
        line = self.line

        if line is not None:
            text = line.eff_text()
            is_translated = bool(line.translated.strip())
            explicit_family = line.font_family
            default_family = line.default_family
            base_font = line.base_font
            size = line.eff_size()
            bold = line.eff_bold()
            italic = line.eff_italic()
            color = line.base_color
            align = line.eff_align()
            bbox = line.bbox
            origin = line.origin
            condense = bool(getattr(line, "condense_enabled", True))
            sx_min = float(getattr(line, "min_horizontal_scale", 0.80))
        else:
            text = self._block.block_text()
            is_translated = bool(self._block.translated_text.strip())
            explicit_family = self._block.font_family
            default_family = self._block.default_family
            base_font = self._block.base_font
            size = self._block.eff_size()
            bold = self._block.eff_bold()
            italic = self._block.eff_italic()
            color = self._block.base_color
            align = self._block.eff_align()
            bbox = self._block.eff_bbox()  # ← учитывает width override
            origin = (bbox[0], bbox[3])
            condense = bool(getattr(self._block, "condense_enabled", True))
            sx_min = float(getattr(self._block, "min_horizontal_scale", 0.80))

        family_name: Optional[str] = None
        if explicit_family is not None:
            family_name = family_name_for(explicit_family)
        elif not is_translated and base_font:
            normalized = _normalize_font_name(base_font)
            if normalized in _PDF_FONTS:
                family_name = _PDF_FONTS[normalized]
        if family_name is None:
            family_name = family_name_for(default_family)

        font = QFont(family_name)
        font.setPixelSize(max(1, int(round(size * zoom))))
        font.setBold(bool(bold))
        font.setItalic(bool(italic))

        self.setPlainText(text)
        self.document().setDocumentMargin(0)
        self.setFont(font)

        try:
            r, g, b = [max(0, min(255, int(c * 255))) for c in color[:3]]
        except Exception:
            r = g = b = 0
        self.setDefaultTextColor(QColor(r, g, b))

        is_block_item = (line is None)
        wrap_enabled = is_block_item
        condense_active = (line is not None) and is_translated and condense
        align_flag = ALIGN_MAP.get(align, Qt.AlignLeft)
        if not wrap_enabled and align_flag == Qt.AlignJustify:
            align_flag = Qt.AlignLeft

        option = self.document().defaultTextOption()
        option.setWrapMode(
            QTextOption.WrapAtWordBoundaryOrAnywhere if wrap_enabled else QTextOption.NoWrap
        )
        option.setAlignment(align_flag)
        self.document().setDefaultTextOption(option)

        if wrap_enabled:
            self.setTextWidth(max(1.0, (bbox[2] - bbox[0]) * zoom))
        else:
            self.setTextWidth(-1)

        available_w = (bbox[2] - bbox[0]) * zoom
        natural_w = QFontMetricsF(font).horizontalAdvance(text)
        sx = 1.0
        if condense_active and natural_w > available_w + 0.5:
            sx = max(sx_min, available_w / max(1.0, natural_w))
        self.setTransform(QTransform.fromScale(sx, 1.0) if sx < 0.999 else QTransform())

        display_w = natural_w * sx if not wrap_enabled else None
        fm = QFontMetricsF(font)
        ascent = fm.ascent()

        if not wrap_enabled:
            if align == "center" and display_w is not None:
                x_start = bbox[0] * zoom + (available_w - display_w) / 2.0
            elif align == "right" and display_w is not None:
                x_start = bbox[2] * zoom - display_w
            else:
                x_start = bbox[0] * zoom
        else:
            x_start = bbox[0] * zoom

        if line is not None:
            bx, by = origin
            self.setPos(x_start, by * zoom - ascent)
        else:
            self.setPos(x_start, bbox[1] * zoom)

        self._update_tooltip()

    def _update_tooltip(self) -> None:
        line = self.line
        if line is not None:
            original = line.original
            translated = line.translated
            source_font = line.base_font
        else:
            original = self._block.original_text
            translated = self._block.translated_text
            source_font = self._block.base_font
        tip = f"Шрифт в PDF: {source_font or '—'}"
        tip += " (строка)" if line is not None else " (блок)"
        tip += f"\nОригинал: {original[:180]}"
        if translated.strip():
            tip += f"\nПеревод: {translated[:180]}"
        tip += "\n\nДвойной клик — редактировать, Esc — отменить"
        self.setToolTip(tip)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._view.line_clicked.emit(self._block.block_index, self._line_index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._editing = True
        self.setTransform(QTransform())
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        cursor = self.textCursor()
        cursor.select(QTextCursor.Document)
        self.setTextCursor(cursor)
        event.accept()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if self._editing:
            self._editing = False
            self.setTextInteractionFlags(Qt.NoTextInteraction)
            self._view.line_edited.emit(
                self._block.block_index, self._line_index, self.toPlainText()
            )
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._editing = False
            self.setTextInteractionFlags(Qt.NoTextInteraction)
            self.refresh()
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)

class PageView(QGraphicsView):
    line_clicked = Signal(int, int)
    line_edited = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QColor("#eef0f4"))
        self.setAlignment(Qt.AlignCenter)
        self.setDragMode(QGraphicsView.NoDrag)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._src_doc: Optional[fitz.Document] = None
        self._page_data: Optional[PageData] = None
        self._zoom = 1.0
        self._items: Dict[Tuple[int, int], EditableLineItem] = {}
        self._bg_cache: Dict[Tuple[int, float], QPixmap] = {}
        self._bg_item: Optional[QGraphicsPixmapItem] = None

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    def set_document(self, src_doc: Optional[fitz.Document]) -> None:
        self._src_doc = src_doc
        self._bg_cache.clear()

    def set_page(self, src_doc: Optional[fitz.Document], page_data: Optional[PageData],
                 zoom: float = 1.0) -> None:
        self._src_doc = src_doc
        self._page_data = page_data
        self._zoom = max(0.15, min(4.0, zoom))
        self._rebuild()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.15, min(4.0, zoom))
        if self._page_data is not None:
            self._rebuild()

    def invalidate_background(self) -> None:
        if self._page_data is None:
            return
        page_index = self._page_data.index
        for key in [k for k in self._bg_cache if k[0] == page_index]:
            del self._bg_cache[key]

    def _get_background(self) -> QPixmap:
        if self._page_data is None or self._src_doc is None:
            pm = QPixmap(400, 600)
            pm.fill(QColor("#ffffff"))
            return pm
        page_index = self._page_data.index
        zoom_key = round(self._zoom, 2)
        cache_key = (page_index, zoom_key)
        if cache_key in self._bg_cache:
            return self._bg_cache[cache_key]
        try:
            bg_doc = builder.build_page_background(self._src_doc, self._page_data)
            try:
                page = bg_doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(self._zoom, self._zoom), alpha=False)
                image = QImage(
                    pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888
                ).copy()
                pm = QPixmap.fromImage(image)
            finally:
                bg_doc.close()
        except Exception:
            pm = QPixmap(400, 600)
            pm.fill(QColor("#ffffff"))
        self._bg_cache[cache_key] = pm
        page_keys = [k for k in self._bg_cache if k[0] == page_index]
        if len(page_keys) > 6:
            for k in page_keys[:-6]:
                del self._bg_cache[k]
        return pm

    def _rebuild(self) -> None:
        self._scene.clear()
        self._items.clear()
        self._bg_item = None
        if self._page_data is None:
            return

        pm = self._get_background()
        self._bg_item = QGraphicsPixmapItem(pm)
        self._bg_item.setPos(0, 0)
        self._bg_item.setZValue(0)
        self._scene.addItem(self._bg_item)
        self._scene.setSceneRect(0, 0, pm.width(), pm.height())

        for block in self._page_data.blocks:
            if block.use_block_layout and block.is_any_translated():
                item = EditableLineItem(self, block, -1)
                self._scene.addItem(item)
                self._items[(block.block_index, -1)] = item
                item.refresh()
                continue
            if block.lines:
                for li in range(len(block.lines)):
                    item = EditableLineItem(self, block, li)
                    self._scene.addItem(item)
                    self._items[(block.block_index, li)] = item
                    item.refresh()
            else:
                item = EditableLineItem(self, block, -1)
                self._scene.addItem(item)
                self._items[(block.block_index, -1)] = item
                item.refresh()

    def refresh_block(self, block_index: int) -> None:
        for (bi, _), item in list(self._items.items()):
            if bi == block_index:
                item.refresh()

    def refresh_all(self) -> None:
        for item in self._items.values():
            item.refresh()

    def highlight_block(self, block_index: int, line_index: Optional[int] = None) -> None:
        for (bi, li), item in self._items.items():
            if bi == block_index and (line_index is None or li == line_index):
                item.setSelected(True)
                self.ensureVisible(item)
            else:
                item.setSelected(False)
