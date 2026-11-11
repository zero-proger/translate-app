#!/usr/bin/env python3
"""Импорт каждого модуля по отдельности + проверка публичных имён.

Запускать из корня проекта:
    python check_imports.py
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

# (модуль, [обязательные публичные имена])
CHECKS = [
    ("app.config", ["FONTS", "build_fonts", "font_label", "guess_family"]),
    ("app.models", ["TextLine", "TextBlock", "PageData"]),
    ("app.extractor", ["extract_document"]),
    ("app.builder", ["export_pdf", "build_page_background", "build_page_doc"]),
    ("app.translator", [
        "TranslatorError", "create_backend", "TranslateWorker",
        "DEFAULT_LLM_PROMPT", "get_gpu_info", "install_argos_package",
    ]),
    ("app.models_manager", [
        "LLM_MODELS", "TRANSLATE_MODELS", "ModelsManagerDialog",
        "is_model_downloaded", "model_local_path", "delete_model",
    ]),
    ("app.wrap_check_dialog", ["WrapCheckDialog"]),
    ("app.project", [
        "save_project", "load_project", "apply_project_to_pages", "PROJECT_VERSION",
    ]),
    ("app.page_view", ["PageView", "register_pdf_fonts"]),
    ("app.settings_dialog", ["SettingsDialog"]),
    ("app.main_window_files", ["WindowFilesMixin"]),
    ("app.main_window_edit", ["WindowEditMixin"]),
    ("app.main_window_translate", ["WindowTranslateMixin"]),
    ("app.main_window", ["MainWindow"]),
]

def main() -> int:
    # чтобы `import app.*` работал из корня
    root = Path(__file__).parent.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    failures = 0
    print(f"Корень: {root}\n")

    for module_name, names in CHECKS:
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            print(f"[IMPORT FAIL] {module_name}")
            traceback.print_exc()
            print()
            failures += 1
            continue

        missing = [n for n in names if not hasattr(mod, n)]
        if missing:
            print(f"[MISSING NAMES] {module_name}: {', '.join(missing)}")
            failures += 1
        else:
            print(f"[OK] {module_name}")

    print()
    if failures == 0:
        print("✓ Все модули импортируются, все нужные имена на месте.")
        return 0
    print(f"✗ Проблем: {failures}. Перезапишите указанные файлы и повторите.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
