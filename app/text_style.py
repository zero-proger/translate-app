# Именованные стили текста — для быстрого применения одного и того же
# оформления к блокам/строкам. Стили хранятся в .pdftr-проекте.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .models import TextBlock

@dataclass
class TextStyle:
    """Набор параметров оформления под общим именем.

    Применение стиля к блоку перезаписывает font_family / font_size /
    bold / italic / align / line_spacing / condense_enabled /
    min_horizontal_scale / auto_fit / use_block_layout. Все эти поля
    не трогают геометрию (bbox_override), шрифт-заголовок и прочие
    свойства блока, не относящиеся к виду текста.
    """

    name: str = ""
    font_family: Optional[str] = None
    font_size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    align: Optional[str] = None
    line_spacing: Optional[float] = None
    condense_enabled: bool = True
    min_horizontal_scale: float = 0.80
    auto_fit: bool = True
    use_block_layout: bool = False

    def apply_to_block(self, block: TextBlock, to_lines: bool = True) -> None:
        block.font_family = self.font_family
        block.font_size = self.font_size
        block.bold = self.bold
        block.italic = self.italic
        block.align = self.align
        block.line_spacing = self.line_spacing
        block.condense_enabled = self.condense_enabled
        block.min_horizontal_scale = self.min_horizontal_scale
        block.auto_fit = self.auto_fit
        block.use_block_layout = self.use_block_layout
        if to_lines:
            for line in block.lines:
                line.font_family = self.font_family
                line.font_size = self.font_size
                line.bold = self.bold
                line.italic = self.italic
                line.align = self.align
                line.condense_enabled = self.condense_enabled
                line.min_horizontal_scale = self.min_horizontal_scale

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "align": self.align,
            "line_spacing": self.line_spacing,
            "condense_enabled": bool(self.condense_enabled),
            "min_horizontal_scale": float(self.min_horizontal_scale),
            "auto_fit": bool(self.auto_fit),
            "use_block_layout": bool(self.use_block_layout),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextStyle":
        d = data or {}

        def _opt_str(key):
            v = d.get(key)
            return None if v in (None, "") else str(v)

        def _opt_bool(key):
            v = d.get(key)
            return None if v is None else bool(v)

        def _opt_float(key):
            v = d.get(key)
            try:
                return None if v is None else float(v)
            except (TypeError, ValueError):
                return None

        try:
            mhs = float(d.get("min_horizontal_scale", 0.80) or 0.80)
        except (TypeError, ValueError):
            mhs = 0.80

        return cls(
            name=str(d.get("name", "") or ""),
            font_family=_opt_str("font_family"),
            font_size=_opt_float("font_size"),
            bold=_opt_bool("bold"),
            italic=_opt_bool("italic"),
            align=_opt_str("align"),
            line_spacing=_opt_float("line_spacing"),
            condense_enabled=bool(d.get("condense_enabled", True)),
            min_horizontal_scale=mhs,
            auto_fit=bool(d.get("auto_fit", True)),
            use_block_layout=bool(d.get("use_block_layout", False)),
        )

def styles_to_dict(styles: Dict[str, TextStyle]) -> dict:
    return {name: st.to_dict() for name, st in (styles or {}).items()}

def styles_from_dict(data: dict) -> Dict[str, TextStyle]:
    out: Dict[str, TextStyle] = {}
    for name, sd in (data or {}).items():
        try:
            st = TextStyle.from_dict(sd or {})
            st.name = str(name)
            out[str(name)] = st
        except Exception:
            continue
    return out

# ---- END OF FILE app/text_style.py ----
