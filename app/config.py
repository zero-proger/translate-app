"""Обнаружение шрифтов: системные (с кириллицей), узкие и пользовательские."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FAMILY_LABELS: Dict[str, str] = {
    "narrow": "Узкий (без засечек)",
    "sans": "Без засечек",
    "serif": "С засечками",
    "mono": "Моноширинный",
}

_WIN = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_MAC = Path("/System/Library/Fonts")
_MAC_SUP = _MAC / "Supplemental"
_LIN = Path("/usr/share/fonts")

PathTuple = Tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]

def _pairs(entries) -> List[PathTuple]:
    return [tuple(Path(p) if p else None for p in entry) for entry in entries]  # type: ignore[arg-type]

# --- Стандартные шрифты без засечек (широкие) ---
_SANS = _pairs([
    (_WIN / "arial.ttf", _WIN / "arialbd.ttf", _WIN / "ariali.ttf", _WIN / "arialbi.ttf"),
    (_WIN / "calibri.ttf", _WIN / "calibrib.ttf", _WIN / "calibrii.ttf", _WIN / "calibriz.ttf"),
    (
        _LIN / "truetype/dejavu/DejaVuSans.ttf",
        _LIN / "truetype/dejavu/DejaVuSans-Bold.ttf",
        _LIN / "truetype/dejavu/DejaVuSans-Oblique.ttf",
        _LIN / "truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    ),
    (
        _LIN / "truetype/liberation/LiberationSans-Regular.ttf",
        _LIN / "truetype/liberation/LiberationSans-Bold.ttf",
        _LIN / "truetype/liberation/LiberationSans-Italic.ttf",
        _LIN / "truetype/liberation/LiberationSans-BoldItalic.ttf",
    ),
    (
        _MAC_SUP / "Arial.ttf",
        _MAC_SUP / "Arial Bold.ttf",
        _MAC_SUP / "Arial Italic.ttf",
        _MAC_SUP / "Arial Bold Italic.ttf",
    ),
    (_MAC / "Helvetica.ttc", None, None, None),
])

# --- Узкие шрифты без засечек (экономят до 20–25 % ширины) ---
_NARROW = _pairs([
    # Windows: Arial Narrow
    (_WIN / "arialn.ttf", _WIN / "arialnb.ttf", _WIN / "arialni.ttf", _WIN / "arialnbi.ttf"),
    # Linux: Liberation Sans Narrow (метрический аналог Arial Narrow)
    (
        _LIN / "truetype/liberation/LiberationSansNarrow-Regular.ttf",
        _LIN / "truetype/liberation/LiberationSansNarrow-Bold.ttf",
        _LIN / "truetype/liberation/LiberationSansNarrow-Italic.ttf",
        _LIN / "truetype/liberation/LiberationSansNarrow-BoldItalic.ttf",
    ),
    # Linux: DejaVu Sans Condensed
    (
        _LIN / "truetype/dejavu/DejaVuSansCondensed.ttf",
        _LIN / "truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        _LIN / "truetype/dejavu/DejaVuSansCondensed-Oblique.ttf",
        _LIN / "truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf",
    ),
    # macOS: Arial Narrow
    (
        _MAC_SUP / "Arial Narrow.ttf",
        _MAC_SUP / "Arial Narrow Bold.ttf",
        _MAC_SUP / "Arial Narrow Italic.ttf",
        _MAC_SUP / "Arial Narrow Bold Italic.ttf",
    ),
])

_SERIF = _pairs([
    (_WIN / "times.ttf", _WIN / "timesbd.ttf", _WIN / "timesi.ttf", _WIN / "timesbi.ttf"),
    (_WIN / "georgia.ttf", _WIN / "georgiab.ttf", _WIN / "georgiai.ttf", _WIN / "georgiaz.ttf"),
    (
        _LIN / "truetype/dejavu/DejaVuSerif.ttf",
        _LIN / "truetype/dejavu/DejaVuSerif-Bold.ttf",
        _LIN / "truetype/dejavu/DejaVuSerif-Italic.ttf",
        _LIN / "truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
    ),
    (
        _LIN / "truetype/liberation/LiberationSerif-Regular.ttf",
        _LIN / "truetype/liberation/LiberationSerif-Bold.ttf",
        _LIN / "truetype/liberation/LiberationSerif-Italic.ttf",
        _LIN / "truetype/liberation/LiberationSerif-BoldItalic.ttf",
    ),
    (
        _MAC_SUP / "Times New Roman.ttf",
        _MAC_SUP / "Times New Roman Bold.ttf",
        _MAC_SUP / "Times New Roman Italic.ttf",
        _MAC_SUP / "Times New Roman Bold Italic.ttf",
    ),
])

_MONO = _pairs([
    (_WIN / "cour.ttf", _WIN / "courbd.ttf", _WIN / "couri.ttf", _WIN / "courbi.ttf"),
    (
        _LIN / "truetype/dejavu/DejaVuSansMono.ttf",
        _LIN / "truetype/dejavu/DejaVuSansMono-Bold.ttf",
        _LIN / "truetype/dejavu/DejaVuSansMono-Oblique.ttf",
        _LIN / "truetype/dejavu/DejaVuSansMono-BoldOblique.ttf",
    ),
    (
        _LIN / "truetype/liberation/LiberationMono-Regular.ttf",
        _LIN / "truetype/liberation/LiberationMono-Bold.ttf",
        _LIN / "truetype/liberation/LiberationMono-Italic.ttf",
        _LIN / "truetype/liberation/LiberationMono-BoldItalic.ttf",
    ),
])

def _resolve(entries: List[PathTuple]) -> Optional[Dict[str, str]]:
    for regular, bold, italic, bolditalic in entries:
        if regular and regular.exists():
            reg = str(regular)
            bold_path = str(bold) if bold and bold.exists() else reg
            italic_path = str(italic) if italic and italic.exists() else reg
            bolditalic_path = str(bolditalic) if bolditalic and bolditalic.exists() else bold_path
            return {
                "regular": reg,
                "bold": bold_path,
                "italic": italic_path,
                "bolditalic": bolditalic_path,
            }
    return None

FONTS: Dict[str, Dict[str, str]] = {}

def build_fonts(custom_paths: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    FONTS.clear()
    for key, entries in (
        ("narrow", _NARROW),
        ("sans", _SANS),
        ("serif", _SERIF),
        ("mono", _MONO),
    ):
        resolved = _resolve(entries)
        if resolved:
            FONTS[key] = resolved

    for path in (custom_paths or []):
        if not path:
            continue
        p = Path(path)
        if not p.exists():
            continue
        key = "custom:" + str(p.resolve())
        FONTS[key] = {
            "regular": str(p),
            "bold": str(p),
            "italic": str(p),
            "bolditalic": str(p),
            "label": p.stem,
        }
    return FONTS

def font_label(key: str) -> str:
    if key in FAMILY_LABELS:
        return FAMILY_LABELS[key]
    entry = FONTS.get(key)
    if entry:
        return entry.get("label", key)
    return key

def guess_family(font_name: str) -> str:
    """Подобрать семейство по имени оригинального шрифта."""
    name = (font_name or "").lower()
    if any(tok in name for tok in ("courier", "mono", "consol")):
        return "mono"
    if any(tok in name for tok in ("narrow", "condensed", "compressed", "compact")):
        return "narrow"
    if any(tok in name for tok in
           ("times", "serif", "roman", "georgia", "cambria", "garamond", "book")):
        return "serif"
    return "sans"

def resolve_family(name: Optional[str]) -> Optional[str]:
    """Вернуть имя семейства, только если оно реально установлено."""
    if not name:
        return None
    return name if name in FONTS else None

build_fonts()
