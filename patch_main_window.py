#!/usr/bin/env python3
# Патч: добавляет «Изменить размер по образцу…» в app/main_window.py.
# Запускать из корня проекта:
#     python patch_main_window.py
# При успехе создаёт app/main_window.py.bak с бэкапом.

import ast
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
TARGET = ROOT / "app" / "main_window.py"
BACKUP = ROOT / "app" / "main_window.py.bak"

IMPORT_MARKER = "from .find_replace_dialog import FindReplaceDialog"
IMPORT_NEW = (
    "from .find_replace_dialog import FindReplaceDialog\n"
    "from .bulk_resize_dialog import BulkResizeDialog"
)

ACTION_MARKER = "triggered=self.open_find_replace)"
ACTION_NEW = (
    "triggered=self.open_find_replace)\n"
    "        self.act_bulk_resize = QAction(\n"
    "            \"Изменить размер по образцу…\", self, shortcut=\"Ctrl+R\",\n"
    "            triggered=self.open_bulk_resize,\n"
    "        )"
)

MENU_MARKER = "em.addAction(self.act_find_replace)"
MENU_NEW = (
    "em.addAction(self.act_find_replace)\n"
    "        em.addAction(self.act_bulk_resize)"
)

REQUIRED_MARKER = '"open_find_replace", "_on_find_replace_changed", "_jump_from_find",'
REQUIRED_NEW = (
    REQUIRED_MARKER + "\n"
    '    "open_bulk_resize", "_on_bulk_resize_changed",'
)

EOF_MARKER = "# ---- END OF FILE app/main_window.py ----"

METHODS_CODE = (
    "    # ---------------- изменение размера по образцу ----------------\n"
    "    def open_bulk_resize(self) -> None:\n"
    "        if not self.pages:\n"
    "            QMessageBox.information(self, \"Размер\",\n"
    "                                    \"Сначала откройте PDF-файл.\")\n"
    "            return\n"
    "        dlg = BulkResizeDialog(self.pages, self.current_block, self)\n"
    "        dlg.changed.connect(self._on_bulk_resize_changed)\n"
    "        dlg.exec()\n"
    "\n"
    "    def _on_bulk_resize_changed(self) -> None:\n"
    "        self.page_view.refresh_all()\n"
    "        self._populate_blocks()\n"
    "        self._populate_lines()\n"
    "        if self.current_block is not None:\n"
    "            self._loading = True\n"
    "            try:\n"
    "                self.size_spin.setValue(self.current_block.eff_size())\n"
    "            finally:\n"
    "                self._loading = False\n"
    "\n"
    "\n"
)

def fail(msg: str, code: int = 1) -> int:
    print(f"[FAIL] {msg}")
    return code

def main() -> int:
    print(f"Патчу: {TARGET}")

    if not TARGET.exists():
        return fail("файл app/main_window.py не найден", 2)

    src = TARGET.read_text(encoding="utf-8")

    if "act_bulk_resize" in src:
        print("[SKIP] Патч уже был применён ранее — ничего не меняю.")
        return 0

    # Проверяем маркеры
    missing = []
    for label, marker in (
        ("import", IMPORT_MARKER),
        ("action", ACTION_MARKER),
        ("menu", MENU_MARKER),
        ("required", REQUIRED_MARKER),
        ("EOF", EOF_MARKER),
    ):
        if marker not in src:
            missing.append(f"  - {label}: {marker!r}")
    if missing:
        print("[FAIL] не найдены маркеры:")
        for m in missing:
            print(m)
        print()
        print("Возможно, ваш main_window.py другой версии.")
        print("Патч рассчитан на версию с 'Найти и заменить' и '# ---- END OF FILE'.")
        return 3

    # Бэкап
    shutil.copyfile(TARGET, BACKUP)
    print(f"[OK] Бэкап: {BACKUP}")

    # Применяем
    new_src = src
    new_src = new_src.replace(IMPORT_MARKER, IMPORT_NEW, 1)
    new_src = new_src.replace(ACTION_MARKER, ACTION_NEW, 1)
    new_src = new_src.replace(MENU_MARKER, MENU_NEW, 1)
    new_src = new_src.replace(REQUIRED_MARKER, REQUIRED_NEW, 1)
    new_src = new_src.replace(EOF_MARKER, METHODS_CODE + EOF_MARKER, 1)

    # Проверяем AST
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[FAIL] патч сломал синтаксис: строка {e.lineno}: {e.msg}")
        print(f"       восстанавливаю оригинал из {BACKUP.name}")
        shutil.copyfile(BACKUP, TARGET)
        return 4

    # Проверяем, что новые методы реально внутри класса MainWindow
    try:
        tree = ast.parse(new_src)
        main_cls = next(
            n for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "MainWindow"
        )
        method_names = {n.name for n in main_cls.body
                        if isinstance(n, ast.FunctionDef)}
        for required in ("open_bulk_resize", "_on_bulk_resize_changed"):
            if required not in method_names:
                print(
                    f"[FAIL] метод {required} не оказался внутри класса MainWindow "
                    f"(возможно, EOF-маркер стоит в неправильном месте)."
                )
                print(f"       восстанавливаю оригинал из {BACKUP.name}")
                shutil.copyfile(BACKUP, TARGET)
                return 5
    except Exception as e:
        print(f"[FAIL] проверка AST: {e}")
        shutil.copyfile(BACKUP, TARGET)
        return 6

    TARGET.write_text(new_src, encoding="utf-8")
    print("[OK] Патч применён")
    print()
    print("Что появилось:")
    print("  • Меню «Правка → Изменить размер по образцу…» (Ctrl+R)")
    print("  • Диалог с фильтром по размеру и массовой заменой")
    print()
    print("Удалите __pycache__ и перезапустите:")
    print("  find . -name \"__pycache__\" -type d -exec rm -rf {} +")
    print("  python3 main.py")
    return 0

if __name__ == "__main__":
    sys.exit(main())
