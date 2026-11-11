# Сборка PDF с горизонтальным сжатием и учётом bbox_override у блоков.

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import fitz

from .config import FONTS
from .models import PageData, TextBlock, TextLine

_FONT_CACHE: Dict[str, "fitz.Font"] = {}

def get_font(family: str, bold: bool, italic: bool) -> "fitz.Font":
    fam = FONTS.get(family) or FONTS.get("sans")
    if not fam:
        raise RuntimeError(
            "Не найден TTF-шрифт с поддержкой кириллицы. Добавьте свой шрифт."
        )
    key = "bolditalic" if (bold and italic) else (
        "bold" if bold else ("italic" if italic else "regular"))
    path = fam.get(key) or fam["regular"]
    if path not in _FONT_CACHE:
        _FONT_CACHE[path] = fitz.Font(fontfile=path)
    return _FONT_CACHE[path]

def wrap_text(text: str, font: "fitz.Font", size: float, max_width: float) -> List[str]:
    text = " ".join(text.split())
    if not text:
        return []
    words = text.split(" ")
    lines: List[str] = []
    current = ""
    for word in words:
        if font.text_length(word, size) > max_width:
            if current:
                lines.append(current)
                current = ""
            chunk = ""
            for ch in word:
                trial = chunk + ch
                if font.text_length(trial, size) <= max_width:
                    chunk = trial
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            current = chunk
            continue
        trial = word if not current else current + " " + word
        if font.text_length(trial, size) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def _apply_redactions(page: "fitz.Page") -> None:
    kwargs = {}
    if hasattr(fitz, "PDF_REDACT_IMAGE_NONE"):
        kwargs["images"] = fitz.PDF_REDACT_IMAGE_NONE
    if hasattr(fitz, "PDF_REDACT_LINE_ART_NONE"):
        kwargs["graphics"] = fitz.PDF_REDACT_LINE_ART_NONE
    try:
        page.apply_redactions(**kwargs)
    except TypeError:
        try:
            page.apply_redactions(images=kwargs.get("images", 0))
        except TypeError:
            page.apply_redactions()

def _draw_text_line(page: "fitz.Page", text: str, rect: "fitz.Rect",
                    baseline_y: float, font: "fitz.Font", size: float,
                    align: str, color: Tuple[float, float, float],
                    sx: float) -> None:
    natural_w = font.text_length(text, size)
    display_w = natural_w * sx

    if align == "center":
        x_start = rect.x0 + (rect.width - display_w) / 2.0
    elif align == "right":
        x_start = rect.x1 - display_w
    else:
        x_start = rect.x0

    if align == "justify" and sx >= 0.999 and display_w < rect.width - 0.5:
        words = text.split(" ")
        if len(words) > 1:
            widths = [font.text_length(w, size) for w in words]
            gap = (rect.width - sum(widths)) / (len(words) - 1)
            if 0 < gap <= size * 2.0:
                tw = fitz.TextWriter(page.rect)
                x = rect.x0
                for w, ww in zip(words, widths):
                    tw.append((x, baseline_y), w, font=font, fontsize=size)
                    x += ww + gap
                tw.write_text(page, color=color)
                return

    tw = fitz.TextWriter(page.rect)
    tw.append((x_start, baseline_y), text, font=font, fontsize=size)
    if sx < 0.999:
        morph = (fitz.Point(x_start, baseline_y), fitz.Matrix(sx, 1.0))
        try:
            tw.write_text(page, color=color, morph=morph)
            return
        except Exception:
            pass
    tw.write_text(page, color=color)

def _best_single_line_sx(text: str, font: "fitz.Font", size: float,
                         max_width: float, sx_min: float) -> Optional[float]:
    natural_w = font.text_length(text, size)
    if natural_w <= max_width + 0.5:
        return 1.0
    sx = max_width / natural_w
    return sx if sx >= sx_min else None

def draw_line(page: "fitz.Page", line: TextLine) -> None:
    text = line.eff_text().strip()
    if not text:
        return
    rect = fitz.Rect(line.bbox) & page.rect
    if rect.is_empty or rect.width < 1:
        return

    font = get_font(line.eff_family(), line.eff_bold(), line.eff_italic())
    base_size = max(1.0, line.eff_size())
    align = line.eff_align()
    color = tuple(line.base_color) if line.base_color else (0.0, 0.0, 0.0)
    sx_min = max(0.5, min(1.0, getattr(line, "min_horizontal_scale", 0.80)))
    condense = bool(getattr(line, "condense_enabled", True))
    asc = font.ascender
    desc = abs(font.descender)

    ox, oy = line.origin
    if not (rect.y0 - base_size < oy < rect.y1 + base_size * 2):
        oy = rect.y0 + asc * base_size

    sx = (_best_single_line_sx(text, font, base_size, rect.width, sx_min)
          if condense else
          (1.0 if font.text_length(text, base_size) <= rect.width + 0.5 else None))
    if sx is not None:
        _draw_text_line(page, text, rect, oy, font, base_size, align, color, sx)
        return

    size_min = max(6.0, base_size * 0.92)
    size = base_size
    while size > size_min:
        size = max(size_min, size - 0.5)
        sx = (_best_single_line_sx(text, font, size, rect.width, sx_min)
              if condense else
              (1.0 if font.text_length(text, size) <= rect.width + 0.5 else None))
        if sx is not None:
            new_oy = oy if (rect.y0 - size < oy < rect.y1 + size * 2) else (rect.y0 + asc * size)
            _draw_text_line(page, text, rect, new_oy, font, size, align, color, sx)
            return

    size = base_size
    spacing = 1.15
    wrapped: List[str] = []
    for _ in range(50):
        wrapped = wrap_text(text, font, size, rect.width)
        if not wrapped:
            return
        total_h = asc * size + (len(wrapped) - 1) * size * spacing + desc * size
        available_h = page.rect.y1 - (oy - asc * size) - 1.0
        if total_h <= available_h:
            break
        if size > 6.0:
            size = max(6.0, size - 0.5)
            continue
        break

    baseline = oy
    for ln_text in wrapped:
        if baseline + desc * size > page.rect.y1 - 1.0:
            break
        sx2 = _best_single_line_sx(ln_text, font, size, rect.width, sx_min) if condense else 1.0
        if sx2 is None:
            sx2 = max(0.5, rect.width / max(1.0, font.text_length(ln_text, size)))
        _draw_text_line(page, ln_text, rect, baseline, font, size, align, color, sx2)
        baseline += size * spacing

def draw_block_as_whole(page: "fitz.Page", block: TextBlock,
                        text: Optional[str] = None) -> None:
    """В режиме block_layout — рисуем по eff_bbox()."""
    body = (text if text is not None else block.block_text()).strip()
    if not body:
        return
    rect = fitz.Rect(block.eff_bbox()) & page.rect
    if rect.is_empty or rect.width < 2 or rect.height < 2:
        return

    font = get_font(block.eff_family(), block.eff_bold(), block.eff_italic())
    base_size = max(1.0, block.eff_size())
    base_spacing = max(1.0, block.eff_spacing())
    align = block.eff_align()
    color = tuple(block.base_color) if block.base_color else (0.0, 0.0, 0.0)
    sx_min = max(0.5, min(1.0, getattr(block, "min_horizontal_scale", 0.80)))
    condense = bool(getattr(block, "condense_enabled", True))
    auto_fit = bool(getattr(block, "auto_fit", True))
    asc = font.ascender
    desc = abs(font.descender)

    sx_single = (_best_single_line_sx(body, font, base_size, rect.width, sx_min)
                 if condense else
                 (1.0 if font.text_length(body, base_size) <= rect.width + 0.5 else None))
    if sx_single is not None:
        baseline = rect.y0 + asc * base_size
        _draw_text_line(page, body, rect, baseline, font, base_size, align, color, sx_single)
        return

    size = base_size
    spacing = base_spacing
    wrapped: List[str] = []
    for _ in range(60):
        wrapped = wrap_text(body, font, size, rect.width)
        if not wrapped:
            return
        needed = asc * size + (len(wrapped) - 1) * size * spacing + desc * size
        if needed <= rect.height + 0.5:
            break
        if spacing > 1.0:
            spacing = max(1.0, spacing - 0.05)
            continue
        if auto_fit and size > 5.0:
            size = max(5.0, size - 0.5)
            continue
        break

    baseline = rect.y0 + asc * size
    for ln_text in wrapped:
        if baseline + desc * size > rect.y1 + 0.5:
            break
        sx2 = _best_single_line_sx(ln_text, font, size, rect.width, sx_min) if condense else 1.0
        _draw_text_line(page, ln_text, rect, baseline, font, size, align, color, sx2 or 1.0)
        baseline += size * spacing

def build_page_background(src_doc: "fitz.Document", page_data: PageData) -> "fitz.Document":
    out = fitz.open()
    out.insert_pdf(src_doc, from_page=page_data.index, to_page=page_data.index)
    page = out[0]

    added = False
    for block in page_data.blocks:
        # в блочном режиме вырезаем по eff_bbox (иначе останется оригинал под переводом)
        if block.use_block_layout and block.is_any_translated():
            rect = fitz.Rect(block.eff_bbox()) & page.rect
            if not (rect.is_empty or rect.width < 0.5 or rect.height < 0.5):
                try:
                    page.add_redact_annot(rect, fill=None)
                except TypeError:
                    page.add_redact_annot(rect)
                added = True
            continue
        if block.lines:
            for line in block.lines:
                rect = fitz.Rect(line.bbox)
                if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
                    continue
                try:
                    page.add_redact_annot(rect, fill=None)
                except TypeError:
                    page.add_redact_annot(rect)
                added = True
        else:
            rect = fitz.Rect(block.eff_bbox())
            if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
                continue
            try:
                page.add_redact_annot(rect, fill=None)
            except TypeError:
                page.add_redact_annot(rect)
            added = True
    if added:
        _apply_redactions(page)
    return out

def build_page_doc(src_doc: "fitz.Document", page_data: PageData) -> "fitz.Document":
    out = fitz.open()
    out.insert_pdf(src_doc, from_page=page_data.index, to_page=page_data.index)
    page = out[0]

    redacted = False
    for block in page_data.blocks:
        if block.use_block_layout and block.is_any_translated():
            rect = fitz.Rect(block.eff_bbox()) & page.rect
            if not (rect.is_empty or rect.width < 0.5 or rect.height < 0.5):
                try:
                    page.add_redact_annot(rect, fill=None)
                except TypeError:
                    page.add_redact_annot(rect)
                redacted = True
            continue
        if block.lines:
            for line in block.lines:
                if not line.translated.strip():
                    continue
                rect = fitz.Rect(line.bbox)
                if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
                    continue
                try:
                    page.add_redact_annot(rect, fill=None)
                except TypeError:
                    page.add_redact_annot(rect)
                redacted = True
        else:
            if not block.translated_text.strip():
                continue
            rect = fitz.Rect(block.eff_bbox())
            if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
                continue
            try:
                page.add_redact_annot(rect, fill=None)
            except TypeError:
                page.add_redact_annot(rect)
            redacted = True

    if redacted:
        _apply_redactions(page)

    for block in page_data.blocks:
        if block.use_block_layout and block.is_any_translated():
            try:
                draw_block_as_whole(page, block)
            except Exception:
                continue
            continue
        if block.lines:
            for line in block.lines:
                if not line.translated.strip():
                    continue
                try:
                    draw_line(page, line)
                except Exception:
                    continue
        else:
            if not block.translated_text.strip():
                continue
            try:
                draw_block_as_whole(page, block, text=block.translated_text)
            except Exception:
                continue
    return out

def export_pdf(src_doc: "fitz.Document", pages: List[PageData], out_path: str,
               progress=None) -> bool:
    out = fitz.open()
    try:
        for i, page_data in enumerate(pages):
            tmp = build_page_doc(src_doc, page_data)
            try:
                out.insert_pdf(tmp, from_page=0, to_page=0)
            finally:
                tmp.close()
            if progress is not None and progress(i + 1, len(pages)) is False:
                return False
        out.save(out_path, garbage=4, deflate=True)
    finally:
        out.close()
    return True
