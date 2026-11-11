# Извлечение с разбиением raw-блоков PyMuPDF на семантические группы:
# заголовки, абзацы, элементы списков — каждая становится отдельным TextBlock.

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import fitz

from .config import FONTS, guess_family
from .models import PageData, TextBlock, TextLine

_HYPHEN_CHARS = "-\u00AD\u2010\u2011\u2012\u2013\u2014\u2212"
_HYPHEN_END = re.compile(r"[-\u00AD\u2010\u2011\u2012\u2013\u2014\u2212]$")
_SENTENCE_END = ".!?:;…"
_CONTINUATION_CHARS = ",;:-—–({\"'«“"

_BULLET_PATTERN = re.compile(r"^\s*[-•·*–—]\s")
_NUMBER_PATTERN = re.compile(r"^\s*\d+[.)]\s")
_LETTER_PATTERN = re.compile(r"^\s*[a-zA-Zа-яА-Я][.)]\s")

def _line_text(line) -> str:
    return "".join(span["text"] for span in line["spans"])

def _join_lines(lines: List[str]) -> str:
    result = ""
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if not result:
            result = text
            continue
        last = result[-1]
        first = text[:1]
        if last in _HYPHEN_CHARS and first.islower():
            result = result[:-1] + text
        elif last in _HYPHEN_CHARS and first.isupper():
            result = result + text
        else:
            result = result + " " + text
    return result

def _line_bbox(line) -> Tuple[float, float, float, float]:
    return tuple(float(v) for v in line["bbox"])

def _combine_bboxes(bboxes: List[Tuple[float, float, float, float]]) -> Tuple[float, float, float, float]:
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return (x0, y0, x1, y1)

def _dominant_span(line):
    spans = [s for s in line["spans"] if s["text"].strip()]
    if not spans:
        return None
    return max(spans, key=lambda s: len(s["text"]))

def _is_list_item(text: str) -> bool:
    return bool(_BULLET_PATTERN.match(text) or
                _NUMBER_PATTERN.match(text) or
                _LETTER_PATTERN.match(text))

def _should_split_after(prev_line, cur_line, median_advance: float) -> bool:
    """True, если prev_line и cur_line — разные смысловые блоки."""
    ps = _dominant_span(prev_line)
    cs = _dominant_span(cur_line)
    if ps is None or cs is None:
        return True

    p_text = _line_text(prev_line).strip()
    c_text = _line_text(cur_line).strip()
    if not p_text or not c_text:
        return True

    # 1) размер шрифта
    p_size = float(ps.get("size", 11))
    c_size = float(cs.get("size", 11))
    if abs(p_size - c_size) / max(p_size, c_size, 0.1) > 0.12:
        return True

    # 2) начертание
    p_flags = int(ps.get("flags", 0))
    c_flags = int(cs.get("flags", 0))
    if (p_flags & 16) != (c_flags & 16):
        return True
    if (p_flags & 2) != (c_flags & 2):
        return True

    # 3) шрифт
    p_font = ps.get("font", "") or ""
    c_font = cs.get("font", "") or ""
    if p_font and c_font and p_font != c_font:
        return True

    p_box = _line_bbox(prev_line)
    c_box = _line_bbox(cur_line)

    # 4) вертикальный разрыв заметно больше обычного
    adv = c_box[1] - p_box[1]
    if median_advance > 0 and adv > median_advance * 1.4:
        return True

    # 5) смена отступа
    if abs(p_box[0] - c_box[0]) > 15:
        return True

    # 6) cur — новый элемент списка → всегда split
    if _is_list_item(c_text):
        return True

    # 7) prev — элемент списка, cur — нет, cur начинается с заглавной/цифры
    if _is_list_item(p_text) and not _is_list_item(c_text):
        if c_text[:1].isupper() or c_text[:1].isdigit():
            return True

    # 8) prev заканчивается на ':' — заголовок для следующего
    if p_text.rstrip().endswith(":"):
        return True

    # 9) prev заметно короче cur и cur начинается с заглавной/цифры,
    #    при этом prev не оканчивается на «продолжение»
    p_width = p_box[2] - p_box[0]
    c_width = c_box[2] - c_box[0]
    if p_width > 0 and c_width > 0 and p_width < c_width * 0.55:
        if not p_text.endswith(tuple(_CONTINUATION_CHARS)):
            if c_text[:1].isupper() or c_text[:1].isdigit():
                return True

    return False

def _split_block_into_groups(lines_raw: List) -> List[List]:
    if not lines_raw:
        return []
    if len(lines_raw) == 1:
        return [list(lines_raw)]

    advances = []
    for i in range(len(lines_raw) - 1):
        b1 = _line_bbox(lines_raw[i])
        b2 = _line_bbox(lines_raw[i + 1])
        adv = b2[1] - b1[1]
        if adv > 0.5:
            advances.append(adv)
    advances.sort()
    median_advance = advances[len(advances) // 2] if advances else 0.0

    groups: List[List] = []
    current = [lines_raw[0]]
    for i in range(1, len(lines_raw)):
        prev = lines_raw[i - 1]
        cur = lines_raw[i]
        if _should_split_after(prev, cur, median_advance):
            groups.append(current)
            current = [cur]
        else:
            current.append(cur)
    if current:
        groups.append(current)
    return groups

def _estimate_spacing(lines, size: float) -> float:
    if len(lines) < 2 or size <= 0:
        return 1.15
    tops = [line["bbox"][1] for line in lines]
    deltas = [tops[i + 1] - tops[i]
              for i in range(len(tops) - 1)
              if tops[i + 1] - tops[i] > 0.1]
    if not deltas:
        return 1.15
    deltas.sort()
    return round(max(0.95, min(2.5, deltas[len(deltas) // 2] / size)), 2)

def _guess_align(lines, bbox, page_width: float) -> str:
    if not lines:
        return "left"
    x0s = [line["bbox"][0] for line in lines]
    x1s = [line["bbox"][2] for line in lines]
    block_width = bbox[2] - bbox[0]
    if len(lines) == 1:
        center = (bbox[0] + bbox[2]) / 2
        if abs(center - page_width / 2) < 6 and block_width < page_width * 0.75:
            return "center"
        return "left"
    left_aligned = (max(x0s) - min(x0s)) < 2.0
    right_aligned = (max(x1s) - min(x1s)) < 2.0
    if left_aligned and right_aligned:
        return "justify"
    if left_aligned:
        body = x1s[:-1]
        if len(body) >= 2 and (max(body) - min(body)) < 2.5:
            return "justify"
        return "left"
    if right_aligned:
        return "right"
    centers = [(x0 + x1) / 2 for x0, x1 in zip(x0s, x1s)]
    if max(centers) - min(centers) < 2.5:
        return "center"
    return "left"

def _color_tuple(int_color: int) -> Tuple[float, float, float]:
    return (
        ((int_color >> 16) & 0xFF) / 255.0,
        ((int_color >> 8) & 0xFF) / 255.0,
        (int_color & 0xFF) / 255.0,
    )

def _span_info(spans) -> dict:
    dominant = max(spans, key=lambda s: len(s["text"]))
    origin = dominant.get("origin", (0.0, 0.0))
    return {
        "size": float(dominant.get("size") or 11.0),
        "color": _color_tuple(int(dominant.get("color", 0))),
        "flags": int(dominant.get("flags", 0)),
        "font": dominant.get("font", ""),
        "origin": (float(origin[0]), float(origin[1])),
    }

def _pick_family(original_font: str, preferred: Optional[str]) -> str:
    if preferred and preferred in FONTS:
        return preferred
    return guess_family(original_font)

def extract_document(path: str, preferred_family: Optional[str] = None):
    """Открыть PDF и вернуть (fitz.Document, список PageData).

    Каждый raw-блок PyMuPDF разбивается на семантические группы —
    заголовок, абзац, элемент списка — и каждая группа становится
    отдельным TextBlock. Это устраняет «склеивание» заголовков,
    перечислений и других не связанных по смыслу строк.
    """
    doc = fitz.open(path)
    pages: List[PageData] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        data = page.get_text("dict")
        page_width, page_height = page.rect.width, page.rect.height
        blocks: List[TextBlock] = []
        block_index = 0

        for raw in data.get("blocks", []):
            if raw.get("type", 0) != 0:
                continue
            lines_raw = [
                ln for ln in raw.get("lines", [])
                if any(s["text"].strip() for s in ln["spans"])
            ]
            if not lines_raw:
                continue

            for group in _split_block_into_groups(lines_raw):
                if not group:
                    continue
                spans = [s for ln in group for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                block_text = _join_lines([_line_text(ln) for ln in group])
                if not block_text.strip():
                    continue

                info = _span_info(spans)
                bbox = _combine_bboxes([_line_bbox(ln) for ln in group])
                family = _pick_family(info["font"], preferred_family)

                block = TextBlock(
                    page_index=pno,
                    block_index=block_index,
                    bbox=bbox,
                    original_text=block_text,
                    base_size=info["size"],
                    base_color=info["color"],
                    base_bold=bool(info["flags"] & 16),
                    base_italic=bool(info["flags"] & 2),
                    base_font=info["font"],
                    default_family=family,
                    default_align=_guess_align(group, bbox, page_width),
                    default_line_spacing=_estimate_spacing(group, info["size"]),
                )

                for li, ln_raw in enumerate(group):
                    line_text = _line_text(ln_raw).strip()
                    if not line_text:
                        continue
                    line_spans = [s for s in ln_raw["spans"] if s["text"].strip()]
                    if not line_spans:
                        continue
                    li_info = _span_info(line_spans)
                    lb = _line_bbox(ln_raw)
                    origin_raw = line_spans[0].get("origin", (lb[0], lb[3]))
                    origin = (float(origin_raw[0]), float(origin_raw[1]))
                    block.lines.append(TextLine(
                        page_index=pno,
                        block_index=block_index,
                        line_index=li,
                        bbox=lb,
                        origin=origin,
                        original=line_text,
                        base_size=li_info["size"],
                        base_color=li_info["color"],
                        base_bold=bool(li_info["flags"] & 16),
                        base_italic=bool(li_info["flags"] & 2),
                        base_font=li_info["font"],
                        default_family=family,
                        default_align="left",
                    ))

                if not block.lines:
                    continue

                # Авто-режим «переводить блоком» — только для настоящих абзацев,
                # у которых ≥3 строки и большинство строк не заканчивается точкой.
                if len(block.lines) >= 3:
                    no_punct = sum(
                        1 for ln in block.lines[:-1]
                        if ln.original.rstrip()
                        and ln.original.rstrip()[-1] not in _SENTENCE_END
                    )
                    if no_punct >= max(2, int((len(block.lines) - 1) * 0.5)):
                        block.use_block_layout = True

                blocks.append(block)
                block_index += 1

        pages.append(PageData(
            index=pno,
            width=page_width,
            height=page_height,
            rotation=page.rotation,
            blocks=blocks,
        ))

    return doc, pages

__all__ = ["extract_document"]

# ---- END OF FILE app/extractor.py ----
