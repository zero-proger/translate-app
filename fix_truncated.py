#!/usr/bin/env python3
"""Поиск файлов .py, у которых первый docstring не закрыт (обрезан при копировании).

Запускать из корня проекта:
    python fix_truncated.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TRIPLE = re.compile(r'"""')

def scan(path: Path) -> int:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return 0
    if not src.strip():
        return 0

    first_line = src.split("\n", 1)[0].lstrip()
    if first_line.startswith('"""'):
        # только начало docstring — считаем количество """ во всём файле
        count = len(TRIPLE.findall(src))
        if count % 2 != 0:
            print(f"  [ОБРЕЗАН] {path} — нечётное количество '\"\"\"' ({count})")
            return 1
        # проверка: docstring в начале, но нет закрывающей кавычки
        # на той же или следующей строке?
        head = src[:400]
        if head.count('"""') == 1:
            print(f"  [ОБРЕЗАН?] {path} — одинокий '\"\"\"' в начале файла")
            return 1
    return 0

def main() -> int:
    root = Path(__file__).parent
    bad = 0
    print("Сканирование всех .py файлов на незакрытые docstring:\n")
    for p in root.rglob("*.py"):
        if p.name == "fix_truncated.py":
            continue
        bad += scan(p)
    if bad == 0:
        print("✓ Все файлы выглядят целыми.\n")
        return 0
    print(
        f"\n✗ Найдено файлов с проблемой: {bad}\n"
        "Перезапишите их содержимым из ZIP-архива целиком "
        "(от первой до последней строки).\n"
    )
    return 1

if __name__ == "__main__":
    sys.exit(main())
