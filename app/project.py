# Проект .pdftr — JSON. Стили, относительные пути, bbox_override.
# styles_to_dict сделан устойчивым к тому, что передают dict-of-dicts,
# dict-of-TextStyle или смесь.

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .models import PageData, TextBlock, TextLine
from .text_style import TextStyle, styles_from_dict, styles_to_dict as _ts_to_dict

PROJECT_VERSION = 1
FILE_EXTENSION = ".pdftr"

def _styles_to_plain(styles) -> dict:
    """Принимает любой из вариантов и возвращает dict-of-dicts.

    * Dict[str, TextStyle]   → сериализует через .to_dict()
    * Dict[str, dict]        → возвращает как есть (уже сериализовано)
    * смесь — работает поштучно
    * None/{}                → {}
    """
    out: dict = {}
    for name, st in (styles or {}).items():
        if st is None:
            continue
        if isinstance(st, dict):
            out[str(name)] = st
        elif hasattr(st, "to_dict"):
            try:
                out[str(name)] = st.to_dict()
            except Exception:
                continue
        else:
            continue
    return out

def relpath(path: str, base: str) -> str:
    if not path:
        return ""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
        if rel.count(os.pardir) <= 6:
            return rel.replace("\\", "/")
    except (ValueError, OSError):
        pass
    return os.path.abspath(path).replace("\\", "/")

def abspath(path: str, base: str) -> str:
    if not path:
        return ""
    path = path.replace("/", os.sep)
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(os.path.abspath(base), path))

def _line_to_dict(line: TextLine) -> dict:
    return {
        "line_index": line.line_index,
        "translated": line.translated,
        "font_family": line.font_family,
        "font_size": line.font_size,
        "bold": line.bold,
        "italic": line.italic,
        "align": line.align,
        "condense_enabled": bool(line.condense_enabled),
        "min_horizontal_scale": float(line.min_horizontal_scale),
    }

def _block_to_dict(block: TextBlock) -> dict:
    return {
        "block_index": block.block_index,
        "translated_text": block.translated_text,
        "font_family": block.font_family,
        "font_size": block.font_size,
        "bold": block.bold,
        "italic": block.italic,
        "line_spacing": block.line_spacing,
        "align": block.align,
        "auto_fit": bool(block.auto_fit),
        "allow_overflow": bool(block.allow_overflow),
        "use_block_layout": bool(block.use_block_layout),
        "condense_enabled": bool(block.condense_enabled),
        "min_horizontal_scale": float(block.min_horizontal_scale),
        "style_name": block.style_name,
        "bbox_override": list(block.bbox_override) if block.bbox_override else None,
        "lines": [_line_to_dict(ln) for ln in block.lines],
    }

def _page_to_dict(page: PageData) -> dict:
    return {
        "index": page.index,
        "blocks": [_block_to_dict(b) for b in page.blocks],
    }

def _normalize_fonts_in_settings(settings: dict, transform) -> dict:
    out = dict(settings or {})
    fonts = out.get("custom_fonts")
    if not fonts:
        out["custom_fonts"] = []
        return out
    if isinstance(fonts, str):
        fonts = [fonts] if fonts else []
    out["custom_fonts"] = [transform(f) for f in fonts if f]
    return out

def save_project(path: str, pdf_path: str, pages: List[PageData],
                 settings: dict, current_page: int,
                 styles=None) -> None:
    base = os.path.dirname(os.path.abspath(path))
    settings_out = _normalize_fonts_in_settings(
        settings, lambda f: relpath(f, base)
    )
    data = {
        "version": PROJECT_VERSION,
        "pdf_path": relpath(pdf_path, base),
        "current_page": int(current_page),
        "settings": settings_out,
        "styles": _styles_to_plain(styles or {}),
        "pages": [_page_to_dict(p) for p in pages],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_project(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def resolve_project_paths(data: dict, project_path: str) -> dict:
    base = os.path.dirname(os.path.abspath(project_path))
    out = dict(data or {})
    out["_pdf_abs"] = abspath(out.get("pdf_path", "") or "", base)
    settings = out.get("settings") or {}
    out["settings"] = _normalize_fonts_in_settings(
        settings, lambda f: abspath(f, base)
    )
    return out

def apply_project_to_pages(data: dict, pages: List[PageData]) -> int:
    pages_map = {int(p.get("index", -1)): p for p in data.get("pages", []) or []}
    applied = 0

    for page in pages:
        pdata = pages_map.get(page.index)
        if not pdata:
            continue
        blocks_map = {int(b.get("block_index", -1)): b
                      for b in pdata.get("blocks", []) or []}
        for block in page.blocks:
            bdata = blocks_map.get(block.block_index)
            if not bdata:
                continue

            block.translated_text = bdata.get("translated_text", "") or ""
            block.font_family = bdata.get("font_family")
            block.font_size = bdata.get("font_size")
            block.bold = bdata.get("bold")
            block.italic = bdata.get("italic")
            block.line_spacing = bdata.get("line_spacing")
            block.align = bdata.get("align")
            block.auto_fit = bool(bdata.get("auto_fit", True))
            block.allow_overflow = bool(bdata.get("allow_overflow", True))
            block.use_block_layout = bool(bdata.get("use_block_layout", False))
            block.condense_enabled = bool(bdata.get("condense_enabled", True))
            try:
                block.min_horizontal_scale = float(
                    bdata.get("min_horizontal_scale", 0.80)
                )
            except (TypeError, ValueError):
                block.min_horizontal_scale = 0.80

            sn = bdata.get("style_name")
            block.style_name = None if sn in (None, "") else str(sn)

            bbox_ov = bdata.get("bbox_override")
            if bbox_ov and len(bbox_ov) == 4:
                try:
                    block.bbox_override = tuple(float(v) for v in bbox_ov)
                except (TypeError, ValueError):
                    block.bbox_override = None
            else:
                block.bbox_override = None

            lines_map = {int(ln.get("line_index", -1)): ln
                         for ln in bdata.get("lines", []) or []}
            for line in block.lines:
                ldata = lines_map.get(line.line_index)
                if not ldata:
                    continue
                line.translated = ldata.get("translated", "") or ""
                line.font_family = ldata.get("font_family")
                line.font_size = ldata.get("font_size")
                line.bold = ldata.get("bold")
                line.italic = ldata.get("italic")
                line.align = ldata.get("align")
                line.condense_enabled = bool(ldata.get("condense_enabled", True))
                try:
                    line.min_horizontal_scale = float(
                        ldata.get("min_horizontal_scale", 0.80)
                    )
                except (TypeError, ValueError):
                    line.min_horizontal_scale = 0.80
            applied += 1
    return applied

# ---- END OF FILE app/project.py ----
