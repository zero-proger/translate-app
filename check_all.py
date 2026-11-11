#!/usr/bin/env python3
# Проверка целостности проекта: файлы, синтаксис, ключевые классы.
# Запуск: python check_all.py  (Windows)  /  python3 check_all.py  (Linux)

import ast
import sys
from pathlib import Path

REQUIRED_FILES = [
    "main.py", "requirements.txt",
    "app/__init__.py", "app/config.py", "app/models.py",
    "app/extractor.py", "app/builder.py", "app/page_view.py",
    "app/translator.py", "app/settings_dialog.py", "app/project.py",
    "app/models_manager.py", "app/wrap_check_dialog.py",
    "app/find_replace_dialog.py", "app/text_style.py",
    "app/main_window.py", "app/main_window_files.py",
    "app/main_window_edit.py", "app/main_window_translate.py",
]

PUBLIC_NAMES = {
    "app/models.py": ["class TextLine", "class TextBlock", "class PageData"],
    "app/extractor.py": ["def extract_document"],
    "app/translator.py": ["class ChatLlmBackend", "class TranslateWorker"],
    "app/text_style.py": ["class TextStyle", "def styles_from_dict"],
    "app/project.py": ["def save_project", "def load_project"],
    "app/wrap_check_dialog.py": ["class WrapCheckDialog"],
    "app/find_replace_dialog.py": ["class FindReplaceDialog"],
    "app/page_view.py": ["class PageView", "def register_pdf_fonts"],
    "app/main_window.py": ["class MainWindow", "def open_find_replace"],
    "app/main_window_files.py": ["class WindowFilesMixin", "def save_project_dialog"],
    "app/main_window_edit.py": ["class WindowEditMixin", "def _apply_format"],
    "app/main_window_translate.py": ["class WindowTranslateMixin", "def _run_translation"],
}

TRIPLE = '"""'
MIN_SIZE = 200

def check_file(path: Path) -> bool:
    rel = path.relative_to(path.parents[len(path.parts) - path.parts.index(path.name) - 1])
    rel_str = str(path).split("bootstrap")[0]  # fallback
    if not path.exists():
        print(f"  [ОТСУТСТВУЕТ] {path}")
        return False
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [ОШИБКА ЧТЕНИЯ] {path}: {e}")
        return False
    if not src.strip():
        print(f"  [ПУСТОЙ] {path}")
        return False
    if len(src) < MIN_SIZE:
        print(f"  [СЛИШКОМ КОРОТКИЙ] {path} ({len(src)} байт)")
        return False
    first = src.split("\n", 1)[0].lstrip()
    if first.startswith(TRIPLE) and src.count(TRIPLE) % 2 != 0:
        print(f"  [ОБРЕЗАН] {path} — нечётное число '\"\"\"'")
        return False
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  [СИНТАКСИС] {path} строка {e.lineno}: {e.msg}")
        return False
    print(f"  [OK] {path}")
    return True

def check_markers(root: Path) -> bool:
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
                print(f"  [НЕТ] {rel}: '{m}'")
                ok = False
    if ok:
        print("  [OK] все ключевые классы/функции на месте")
    return ok

def main() -> int:
    root = Path(__file__).parent
    print(f"Проверка проекта: {root}\n")

    print("Файлы:")
    ok = True
    for f in REQUIRED_FILES:
        ok &= check_file(root / f)

    print("\nКлючевые классы и функции:")
    ok &= check_markers(root)

    print()
    if ok:
        print("✓ Проект полный, можно запускать: python bootstrap.py")
        return 0
    print("✗ Есть проблемы. Перезапишите указанные файлы из архива целиком "
          "(от первой до последней строки).")
    return 1

if __name__ == "__main__":
    sys.exit(main())
