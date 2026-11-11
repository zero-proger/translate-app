# Поиск и замена по переведённому тексту.
# Заменяет вхождения в line.translated (для построчных блоков) или
# block.translated_text (для блочного режима). Исходники не трогает.

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from .models import PageData, TextBlock, TextLine

class FindReplaceDialog(QDialog):
    """Найти и заменить переведённые слова по всему документу."""

    changed = Signal()                      # после замены — перерисовать
    jump_to = Signal(int, int, int)         # page, block_index, line_index (-1)

    def __init__(self, pages: List[PageData],
                 current_block: Optional[TextBlock] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Найти и заменить")
        self.resize(760, 560)

        self.pages = pages
        self.current_block = current_block
        self._matches = []  # (kind, block, line, page_index)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Найти"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Слово или фраза в переводе…")
        self.find_edit.textChanged.connect(self._on_text_changed)
        r1.addWidget(self.find_edit, 1)
        layout.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Заменить на"))
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Пусто = удалить найденное")
        r2.addWidget(self.replace_edit, 1)
        layout.addLayout(r2)

        opts = QHBoxLayout()
        self.case_check = QCheckBox("С учётом регистра")
        self.whole_check = QCheckBox("Только целые слова")
        self.scope_check = QCheckBox("Только в выбранном блоке")
        self.scope_check.setEnabled(current_block is not None)
        self.scope_check.setChecked(False)
        for w in (self.case_check, self.whole_check, self.scope_check):
            w.stateChanged.connect(self._on_text_changed)
            opts.addWidget(w)
        opts.addStretch(1)
        layout.addLayout(opts)

        btns = QHBoxLayout()
        self.find_button = QPushButton("Найти все")
        self.find_button.clicked.connect(self._do_find)
        self.replace_button = QPushButton("Заменить все")
        self.replace_button.clicked.connect(self._do_replace)
        self.replace_button.setEnabled(False)
        btns.addWidget(self.find_button)
        btns.addWidget(self.replace_button)
        btns.addStretch(1)
        layout.addLayout(btns)

        layout.addWidget(QLabel("Результаты (двойной клик — перейти к блоку):"))
        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.result_list, 1)

        self.status_label = QLabel("Введите слово и нажмите «Найти все».")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.status_label)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

    # -------------------- slots --------------------
    def _on_text_changed(self, *args) -> None:
        self._matches.clear()
        self.result_list.clear()
        self.replace_button.setEnabled(False)
        self.status_label.setText("Введите слово и нажмите «Найти все».")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not data:
            return
        page_idx, block_idx, line_idx = data
        self.jump_to.emit(int(page_idx), int(block_idx), int(line_idx))

    # -------------------- helpers --------------------
    def _build_pattern(self) -> Optional[re.Pattern]:
        needle = self.find_edit.text()
        if not needle:
            return None
        flags = 0 if self.case_check.isChecked() else re.IGNORECASE
        if self.whole_check.isChecked():
            return re.compile(r"\b" + re.escape(needle) + r"\b", flags)
        return re.compile(re.escape(needle), flags)

    def _iter_targets(self, block: TextBlock):
        if block.use_block_layout:
            yield ("block", block, None)
        elif block.lines:
            for line in block.lines:
                yield ("line", block, line)
        else:
            yield ("block", block, None)

    @staticmethod
    def _text_of(kind, block, line) -> str:
        if kind == "block":
            return block.translated_text or ""
        return line.translated if line is not None else ""

    @staticmethod
    def _set_text(kind, block, line, text: str) -> None:
        if kind == "block":
            block.translated_text = text
        elif line is not None:
            line.translated = text

    # -------------------- find --------------------
    def _do_find(self) -> None:
        pattern = self._build_pattern()
        if pattern is None:
            self._on_text_changed()
            return

        self._matches = []
        self.result_list.clear()

        for page in self.pages:
            for block in page.blocks:
                if (self.scope_check.isChecked()
                        and self.current_block is not None
                        and block is not self.current_block):
                    continue
                for kind, blk, line in self._iter_targets(block):
                    text = self._text_of(kind, blk, line)
                    if not text:
                        continue
                    m = pattern.search(text)
                    if not m:
                        continue
                    count = len(pattern.findall(text))
                    s = max(0, m.start() - 25)
                    e = min(len(text), m.end() + 25)
                    snippet = text[s:e].strip().replace("\n", " ")
                    prefix = "…" if s > 0 else ""
                    suffix = "…" if e < len(text) else ""
                    loc = f"Стр. {page.index + 1}, блок {blk.block_index + 1}"
                    if kind == "line" and line is not None:
                        loc += f", стр. {line.line_index + 1}"
                    else:
                        loc += " (весь блок)"
                    item = QListWidgetItem(
                        f"{loc} — ×{count}\n   {prefix}{snippet}{suffix}"
                    )
                    item.setData(Qt.UserRole, (
                        page.index,
                        blk.block_index,
                        line.line_index if line is not None else -1,
                    ))
                    self.result_list.addItem(item)
                    self._matches.append((kind, blk, line, page.index))

        n = len(self._matches)
        if n == 0:
            self.status_label.setText("Ничего не найдено.")
            self.replace_button.setEnabled(False)
            return
        total = sum(len(pattern.findall(self._text_of(k, b, l)))
                    for k, b, l, _ in self._matches)
        self.status_label.setText(
            f"Найдено мест: {n}, совпадений: {total}."
        )
        self.replace_button.setEnabled(True)

    # -------------------- replace --------------------
    def _do_replace(self) -> None:
        pattern = self._build_pattern()
        if pattern is None:
            return
        if not self._matches:
            QMessageBox.information(
                self, "Замена", "Сначала нажмите «Найти все»."
            )
            return

        replacement = self.replace_edit.text()
        total = sum(len(pattern.findall(self._text_of(k, b, l)))
                    for k, b, l, _ in self._matches)
        if QMessageBox.question(
            self, "Заменить все",
            f"Заменить {total} совпадений(е) в {len(self._matches)} "
            f"мест(ах)?\n\n"
            f"Найти:    «{self.find_edit.text()}»\n"
            f"Заменить: «{replacement}»\n\n"
            "Действие нельзя отменить.",
        ) != QMessageBox.Yes:
            return

        for kind, blk, line, _ in self._matches:
            text = self._text_of(kind, blk, line)
            if not text:
                continue
            new_text = pattern.sub(lambda _m: replacement, text)
            if new_text != text:
                self._set_text(kind, blk, line, new_text)

        self.changed.emit()
        QMessageBox.information(self, "Готово", "Замена выполнена.")
        self._do_find()

# ---- END OF FILE app/find_replace_dialog.py ----
