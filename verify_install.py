#!/usr/bin/env python3
"""Проверка целостности установки: файлы, AST, docstring, публичные имена."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REQUIRED = [
    "main.py",
    "requirements.txt",
    "app/__init__.py",
    "app/config.py",
    "app/models.py",
    "app/extractor.py",
    "app/builder.py",
    "app/page_view.py",
    "app/translator.py",
    "app/settings_dialog.py",
    "app/project.py",
    "app/models_manager.py",
    "app/wrap_check_dialog.py",
    "app/main_window.py",
    "app/main_window_files.py",
    "app/main_window_edit.py",
    "app/main_window_translate.py",
]

MIN_SIZE = 200
_TRIPLE = re.compile(r'"""')

# обязательные публичные имена в конкретных файлах
PUBLIC_NAMES = {
    "app/extractor.py": ["def extract_document"],
    "app/translator.py": [
        "class ChatLlmBackend", "class TranslateWorker", "class LocalGpuBackend",
        "DEFAULT_LLM_PROMPT", "def create_backend", "def get_gpu_info",
    ],
    "app/models_manager.py": [
        "class ModelsManagerDialog", "LLM_MODELS",
        "def is_model_downloaded", "def model_local_path",
    ],
    "app/wrap_check_dialog.py": ["class WrapCheckDialog"],
    "app/page_view.py": ["class PageView", "def register_pdf_fonts"],
    "app/main_window.py": [
        "class MainWindow", "def _build_format_toolbar",
        "def open_wrap_check", "def open_models_manager",
    ],
    "app/main_window_files.py": ["class WindowFilesMixin", "def open_pdf"],
    "app/main_window_edit.py": ["class WindowEditMixin", "def _apply_format"],
    "app/main_window_translate.py": ["class WindowTranslateMixin", "def _run_translation"],
}

def _check_docstring(src: str, path: Path) -> bool:
    first_line = src.split("\n", 1)[0].lstrip()
    if not first_line.startswith('"""'):
        return True
    count = len(_TRIPLE.findall(src))
    if count % 2 != 0:
        print(f"  [UNTERMINATED DOCSTRING] {path}: "
              f"нечётное число \"\"\" ({count}) — файл обрезан")
        return False
    return True

def check_file(path: Path) -> bool:
    if not path.exists():
        print(f"  [MISSING] {path}")
        return False
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [READ ERROR] {path}: {e}")
        return False
    if not src.strip():
        print(f"  [EMPTY] {path}")
        return False
    if len(src) < MIN_SIZE:
        print(f"  [TOO SHORT] {path} ({len(src)} bytes)")
        return False
    if not _check_docstring(src, path):
        return False
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  [SYNTAX ERROR] {path} line {e.lineno}: {e.msg}")
        return False
    lines = src.count("\n") + 1
    print(f"  [OK] {path} ({len(src)} bytes, {lines} lines)")
    return True

def check_public_names() -> bool:
    root = Path(__file__).parent
    ok = True
    for rel, markers in PUBLIC_NAMES.items():
        p = root / rel
        if not p.exists():
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            ok = False
            continue
        for m in markers:
            if m not in src:
                print(f"  [MISSING] {rel}: '{m}' не найден")
                ok = False
    if ok:
        print("  [OK] все публичные имена на месте")
    return ok

def main() -> int:
    root = Path(__file__).parent
    print("Проверка файлов проекта:\n")
    ok = True
    for rel in REQUIRED:
        ok &= check_file(root / rel)

    print("\nПроверка публичных имён:")
    ok &= check_public_names()

    if ok:
        print("\n✓ Всё в порядке. Можно запускать: python main.py")
        return 0
    print(
        "\n✗ Обнаружены проблемы. Перезапишите указанные файлы из ZIP-архива "
        "целиком (от первой до последней строки)."
    )
    return 1

if __name__ == "__main__":
    sys.exit(main())
