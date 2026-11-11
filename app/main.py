#!/usr/bin/env python3
# Точка входа. Настраивает потоки CPU до импорта тяжёлых библиотек.

import os
import sys

# Все логические ядра для OpenMP/MKL (numpy, torch, ctranslate2).
_cpu = os.cpu_count() or 4
os.environ.setdefault("OMP_NUM_THREADS", str(_cpu))
os.environ.setdefault("MKL_NUM_THREADS", str(_cpu))

# CTranslate2 (движок Argos) по умолчанию ограничивает intra_threads
# физическими ядрами. Патчим __init__, чтобы использовались все логические
# (для гибридных Intel это +30–50 % скорости).
try:
    import ctranslate2
    _orig_init = ctranslate2.Translator.__init__

    def _patched_init(self, *args, **kwargs):
        n = int(os.environ.get("ARGOS_THREADS") or os.cpu_count() or 4)
        kwargs.setdefault("intra_threads", n)
        kwargs.setdefault("inter_threads", 1)
        return _orig_init(self, *args, **kwargs)

    ctranslate2.Translator.__init__ = _patched_init
except ImportError:
    pass

def main() -> int:
    from PySide6.QtWidgets import QApplication
    from app.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Book Translator")
    app.setOrganizationName("BetterDeepSeek")
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QMainWindow { background: #f7f8fa; }"
        "QGroupBox { font-weight: 600; border: 1px solid #e2e4e8;"
        "  border-radius: 8px; margin-top: 14px; background: #ffffff; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 10px;"
        "  padding: 0 4px; color: #4d6bfe; }"
        "QPushButton { background: #4d6bfe; color: #ffffff; border: none;"
        "  border-radius: 6px; padding: 7px 12px; }"
        "QPushButton:hover { background: #3d5ae0; }"
        "QPushButton:disabled { background: #c7d0f5; }"
        "QListWidget, QTextEdit, QLineEdit, QComboBox, QDoubleSpinBox {"
        "  background: #ffffff; border: 1px solid #e2e4e8;"
        "  border-radius: 6px; }"
        "QToolBar { background: #ffffff; border-bottom: 1px solid #e2e4e8;"
        "  spacing: 6px; padding: 4px; }"
        "QStatusBar { background: #ffffff; }"
    )
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
