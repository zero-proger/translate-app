# Диалог «Проверка переносов». Работает без '"""' в начале файла,
# чтобы не падать, если файл обрезан при копировании.

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .models import PageData, TextBlock

class WrapCheckDialog(QDialog):
    def __init__(self, pages: List[PageData], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Проверка переносов")
        self.resize(760, 600)

        self.pages = pages
        self._blocks: List[TextBlock] = []

        layout = QVBoxLayout(self)

        info = QLabel(
            "Найдены блоки, где строки обрываются без точки, а следующая "
            "начинается с маленькой буквы — это разрывы предложений. "
            "Включите для таких блоков режим «переводить блоком», иначе "
            "перевод может получиться фрагментарным."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        self._collect()

        controls = QHBoxLayout()
        self.select_all = QPushButton("Выбрать все")
        self.select_all.clicked.connect(self._select_all)
        self.select_none = QPushButton("Снять все")
        self.select_none.clicked.connect(self._select_none)
        controls.addWidget(self.select_all)
        controls.addWidget(self.select_none)
        controls.addStretch(1)
        layout.addLayout(controls)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Применить к выбранным блокам")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _collect(self) -> None:
        self.list.clear()
        self._blocks.clear()
        for page in self.pages:
            for block in page.blocks:
                issues = block.wrap_issue_count()
                if issues < 1:
                    continue
                preview_lines = [ln.original for ln in block.lines[:3]]
                preview = " / ".join(l.strip() for l in preview_lines if l.strip())
                if len(preview) > 160:
                    preview = preview[:160] + "…"
                already = block.use_block_layout
                mark = "✓" if already else " "
                text = (
                    f"[{mark}] Стр. {page.index + 1}, блок {block.block_index + 1}  "
                    f"(переносов: {issues})\n   {preview}"
                )
                item = QListWidgetItem(text)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if not already else Qt.Unchecked)
                item.setData(Qt.UserRole, block)
                if already:
                    item.setForeground(Qt.darkGray)
                self.list.addItem(item)
                self._blocks.append(block)

    def _select_all(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            block = item.data(Qt.UserRole)
            if block is not None and not block.use_block_layout:
                item.setCheckState(Qt.Checked)

    def _select_none(self) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)

    def _apply(self) -> None:
        applied = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            block = item.data(Qt.UserRole)
            if block is None:
                continue
            if item.checkState() == Qt.Checked and not block.use_block_layout:
                block.use_block_layout = True
                applied += 1

        if applied == 0:
            QMessageBox.information(self, "Проверка переносов", "Ничего не изменено.")
            self.reject()
            return
        QMessageBox.information(
            self, "Готово",
            f"Включён режим «переводить блоком» для {applied} блок(ов).\n"
            "При следующем переводе эти блоки будут переведены целиком.",
        )
        self.accept()

# ---- END OF FILE app/wrap_check_dialog.py ----
