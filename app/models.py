# Модель данных. Класс TextBlock содержит style_name для привязки к стилю.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

BBox = Tuple[float, float, float, float]

@dataclass
class TextLine:
    page_index: int
    block_index: int
    line_index: int
    bbox: BBox
    origin: Tuple[float, float]
    original: str
    translated: str = ""

    base_size: float = 11.0
    base_color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    base_bold: bool = False
    base_italic: bool = False
    base_font: str = ""
    default_family: str = "sans"
    default_align: str = "left"

    font_family: Optional[str] = None
    font_size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    align: Optional[str] = None

    condense_enabled: bool = True
    min_horizontal_scale: float = 0.80

    def eff_text(self) -> str:
        return self.translated if self.translated.strip() else self.original

    def eff_family(self) -> str:
        return self.font_family or self.default_family

    def eff_size(self) -> float:
        return float(self.font_size if self.font_size else self.base_size)

    def eff_bold(self) -> bool:
        return self.bold if self.bold is not None else self.base_bold

    def eff_italic(self) -> bool:
        return self.italic if self.italic is not None else self.base_italic

    def eff_align(self) -> str:
        return self.align or self.default_align

@dataclass
class TextBlock:
    page_index: int
    block_index: int
    bbox: BBox
    original_text: str
    translated_text: str = ""

    base_size: float = 11.0
    base_color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    base_bold: bool = False
    base_italic: bool = False
    base_font: str = ""
    default_family: str = "sans"
    default_align: str = "left"
    default_line_spacing: float = 1.15

    font_family: Optional[str] = None
    font_size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    line_spacing: Optional[float] = None
    align: Optional[str] = None
    auto_fit: bool = True
    allow_overflow: bool = True

    use_block_layout: bool = False
    condense_enabled: bool = True
    min_horizontal_scale: float = 0.80

    # имя применённого стиля, если блок оформлен через «Стиль».
    # При любом ручном изменении оформления сбрасывается в None.
    style_name: Optional[str] = None

    bbox_override: Optional[BBox] = None

    lines: List[TextLine] = field(default_factory=list)

    def has_lines(self) -> bool:
        return bool(self.lines)

    def is_any_translated(self) -> bool:
        if self.use_block_layout and self.translated_text.strip():
            return True
        if self.has_lines():
            return any(ln.translated.strip() for ln in self.lines)
        return bool(self.translated_text.strip())

    def block_text(self) -> str:
        if self.translated_text.strip():
            return self.translated_text
        if self.has_lines():
            parts: List[str] = []
            for ln in self.lines:
                t = (ln.translated if ln.translated.strip() else ln.original).strip()
                if t:
                    parts.append(t)
            return " ".join(parts)
        return self.original_text

    def eff_text(self) -> str:
        if self.use_block_layout and self.translated_text.strip():
            return self.translated_text
        if self.has_lines():
            return "\n".join(ln.eff_text() for ln in self.lines)
        return self.translated_text if self.translated_text.strip() else self.original_text

    def eff_family(self) -> str:
        return self.font_family or self.default_family

    def eff_size(self) -> float:
        return float(self.font_size if self.font_size else self.base_size)

    def eff_bold(self) -> bool:
        return self.bold if self.bold is not None else self.base_bold

    def eff_italic(self) -> bool:
        return self.italic if self.italic is not None else self.base_italic

    def eff_spacing(self) -> float:
        return float(self.line_spacing if self.line_spacing else self.default_line_spacing)

    def eff_align(self) -> str:
        return self.align or self.default_align

    def eff_bbox(self) -> BBox:
        return self.bbox_override if self.bbox_override else self.bbox

    def reset_bbox(self) -> None:
        self.bbox_override = None

    def set_geometry(self, width_pt: float, height_pt: float,
                     x_offset_pt: float = 0.0, y_offset_pt: float = 0.0) -> None:
        orig = self.bbox
        x0 = orig[0] + float(x_offset_pt)
        y0 = orig[1] + float(y_offset_pt)
        x1 = x0 + max(20.0, float(width_pt))
        y1 = y0 + max(10.0, float(height_pt))
        self.bbox_override = (x0, y0, x1, y1)

    def set_width(self, new_width_pt: float, x_offset_pt: float = 0.0) -> None:
        orig = self.bbox
        height = orig[3] - orig[1]
        self.set_geometry(new_width_pt, height, x_offset_pt, 0.0)

    def wrap_issue_count(self) -> int:
        if len(self.lines) < 2:
            return 0
        issues = 0
        punctuation = ".!?:;…"
        for i, line in enumerate(self.lines[:-1]):
            text = line.original.rstrip()
            if not text:
                continue
            last = text[-1]
            nxt = self.lines[i + 1].original.lstrip()
            if not nxt:
                continue
            if last in punctuation:
                continue
            if last in "-—–,(":
                issues += 1
                continue
            if nxt[:1].islower():
                issues += 1
        return issues

    def merged_original_text(self) -> str:
        """Оригинальный текст блока «как единый абзац»: строки склеиваются
        через пробел (дефис на границе переноса склеивается без пробела)."""
        parts: List[str] = []
        for ln in self.lines:
            t = " ".join(ln.original.split())
            if t:
                parts.append(t)
        if parts:
            out = parts[0]
            for p in parts[1:]:
                if out.endswith("-"):
                    out += p
                else:
                    out += " " + p
            return out
        return " ".join(self.original_text.split())

    def merge_style_from(self, other: "TextBlock") -> None:
        """Наследует оформление другого блока, если у него явных настроек нет."""
        if self.font_family is None and other.font_family is not None:
            self.font_family = other.font_family
        if self.font_size is None and other.font_size is not None:
            self.font_size = other.font_size
        if self.bold is None and other.bold is not None:
            self.bold = other.bold
        if self.italic is None and other.italic is not None:
            self.italic = other.italic
        if self.line_spacing is None and other.line_spacing is not None:
            self.line_spacing = other.line_spacing
        if self.align is None and other.align is not None:
            self.align = other.align
        if self.style_name is None and other.style_name:
            self.style_name = other.style_name
        self.auto_fit = self.auto_fit or other.auto_fit
        self.allow_overflow = self.allow_overflow or other.allow_overflow
        self.condense_enabled = self.condense_enabled or other.condense_enabled
        self.min_horizontal_scale = min(self.min_horizontal_scale,
                                        other.min_horizontal_scale)

    def union_bbox(self, others: List["TextBlock"]) -> BBox:
        """Объединяющая рамка этого блока и перечисленных других."""
        boxes = [self.eff_bbox()] + [b.eff_bbox() for b in others]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def renumber_lines(self) -> None:
        """Пересчитывает line_index строк по фактическому порядку в блоке."""
        for i, ln in enumerate(self.lines):
            ln.line_index = i
            ln.block_index = self.block_index

def renumber_page_blocks(page: "PageData") -> None:
    """Синхронизирует block_index блоков страницы с позициями в списке.

    Вызывается после объединения/удаления блоков; заодно обновляет
    page_index/block_index у строк блока.
    """
    for i, block in enumerate(page.blocks):
        block.block_index = i
        for ln in block.lines:
            ln.page_index = block.page_index
            ln.block_index = i
        block.renumber_lines()

def merge_blocks(target: TextBlock, absorbed: List[TextBlock]) -> TextBlock:
    """Объединяет блоки в один (target остаётся).

    Строки поглощённых блоков дописываются к строкам target (при их
    наличии); иначе тексты склеиваются в original_text. Оформление
    наследуется от первого поглощённого блока, объединяется bbox.
    Возвращает target.
    """
    for src in absorbed:
        if target.lines or src.lines:
            target.lines.extend(src.lines)
            # оригинальный текст держим в соответствии со строками
            target.original_text = target.merged_original_text()
        else:
            t = target.original_text.rstrip()
            s = src.original_text.strip()
            if t and s:
                target.original_text = f"{t} {s}" if not t.endswith("-") else t + s
            elif s:
                target.original_text = s
        target.merge_style_from(src)
    target.bbox_override = target.union_bbox(absorbed)
    target.renumber_lines()
    return target

@dataclass
class PageData:
    index: int
    width: float
    height: float
    rotation: int = 0
    blocks: List[TextBlock] = field(default_factory=list)

# ---- END OF FILE app/models.py ----
