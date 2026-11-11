# Диалог «Изменить размер по образцу» — находит текст с заданным размером
# шрифта и меняет его размер. Остальное оформление не трогает.

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from .models import PageData, TextBlock

def _rounded_size(size: float) -> float:
    """Округлить размер до 0.5 pt — для сравнения с допуском."""
    try:
        return round(float(size) * 2) / 2.0
    except (TypeError, ValueError):
        return 11.0

def _collect_sizes(pages: List[PageData]) -> List[float]:
    """Все уникальные размеры в документе (округлённые до 0.5)."""
    seen = set()
    for page in pages:
        for block in page.blocks:
            if block.lines:
                for line in block.lines:
                    seen.add(_rounded_size(line.eff_size()))
            else:
                seen.add(_rounded_size(block.eff_size()))
    return sorted(seen)

def _count_matches(pages: List[PageData], source: float,
                   match_blocks: bool, match_lines: bool):
    """(сколько_блоков, сколько_строк) с округлённым размером == source."""
    bc = 0
    lc = 0
    src = _rounded_size(source)
    for page in pages:
        for block in page.blocks:
            if match_blocks and _rounded_size(block.eff_size()) == src:
                bc += 1
            if match_lines and block.lines:
                for line in block.lines:
                    if _rounded_size(line.eff_size()) == src:
                        lc += 1
    return bc, lc

class BulkResizeDialog(QDialog):
    changed = Signal()

    def __init__(self, pages: List[PageData],
                 current_block: Optional[TextBlock] = None,
                 parent=None):
        super().__init__(parent)
        self.pages = pages
        self.current_block = current_block
        self.setWindowTitle("Изменить размер по образцу")
        self.resize(540, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            "Найти текст с заданным размером шрифта и поменять этот размер у "
            "всех найденных мест. Шрифт, начертание, выравнивание, интервал, "
            "сжатие и геометрия остаются как есть."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()

        # --- исходный размер ---
        row1 = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        for s in _collect_sizes(pages):
            self.source_combo.addItem(f"{s:g} pt", s)
        if current_block is not None:
            self.source_combo.setEditText(
                f"{_rounded_size(current_block.eff_size()):g}"
            )
        row1.addWidget(self.source_combo, 1)

        self.from_block_btn = QPushButton("Из блока")
        self.from_block_btn.setToolTip(
            "Взять размер шрифта из текущего выбранного блока"
        )
        self.from_block_btn.setEnabled(current_block is not None)
        self.from_block_btn.clicked.connect(self._take_from_block)
        row1.addWidget(self.from_block_btn)
        form.addRow("Исходный размер", row1)

        # --- новый размер ---
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(4.0, 200.0)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.setDecimals(1)
        self.target_spin.setSuffix(" pt")
        try:
            src_value = float(self.source_combo.currentData() or 11.0)
        except (TypeError, ValueError):
            src_value = 11.0
        self.target_spin.setValue(src_value)
        form.addRow("Новый размер", self.target_spin)

        layout.addLayout(form)

        # --- область ---
        scope = QLabel("К чему применять:")
        scope.setStyleSheet("font-weight: 600;")
        layout.addWidget(scope)

        self.scope_blocks = QCheckBox(
            "Блоки целиком (у которых размер совпадает)"
        )
        self.scope_blocks.setChecked(True)
        self.scope_lines = QCheckBox(
            "Отдельные строки (у которых размер совпадает)"
        )
        self.scope_lines.setChecked(True)
        self.scope_blocks.stateChanged.connect(self._update_preview)
        self.scope_lines.stateChanged.connect(self._update_preview)
        layout.addWidget(self.scope_blocks)
        layout.addWidget(self.scope_lines)

        # --- превью ---
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        layout.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Применить")
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self.source_combo.currentTextChanged.connect(self._update_preview)
        self.source_combo.currentIndexChanged.connect(self._update_preview)
        self.target_spin.valueChanged.connect(self._update_preview)
        self._update_preview()

    # ---------------- helpers ----------------
    def _parse_source_size(self) -> Optional[float]:
        text = self.source_combo.currentText().strip().lower()
        text = (text.replace("pt", "").replace("пт", "")
                    .replace(",", ".").strip())
        try:
            return float(text)
        except ValueError:
            return None

    def _take_from_block(self) -> None:
        if self.current_block is None:
            return
        self.source_combo.setEditText(
            f"{_rounded_size(self.current_block.eff_size()):g}"
        )

    def _update_preview(self, *args) -> None:
        src = self._parse_source_size()
        if src is None:
            self.preview_label.setText(
                "Введите размер (например, 11 или 11.5)"
            )
            self.preview_label.setStyleSheet(
                "color: #b45309; font-weight: 600;"
            )
            return

        bc, lc = _count_matches(
            self.pages, src,
            self.scope_blocks.isChecked(),
            self.scope_lines.isChecked(),
        )
        if bc == 0 and lc == 0:
            self.preview_label.setText(
                f"Текста с размером {src:g} pt не найдено"
            )
            self.preview_label.setStyleSheet(
                "color: #b45309; font-weight: 600;"
            )
            return

        target = float(self.target_spin.value())
        parts = []
        if self.scope_blocks.isChecked():
            parts.append(f"блоков: {bc}")
        if self.scope_lines.isChecked():
            parts.append(f"строк: {lc}")
        detail = ", ".join(parts) or "0"

        if abs(_rounded_size(target) - _rounded_size(src)) < 0.1:
            self.preview_label.setText(
                f"Найдено: {detail}. Новый размер совпадает с исходным — "
                f"изменений не будет."
            )
            self.preview_label.setStyleSheet(
                "color: #b45309; font-weight: 600;"
            )
        else:
            self.preview_label.setText(
                f"Найдено: {detail}.  "
                f"Будет применено: {src:g} pt → {target:g} pt"
            )
            self.preview_label.setStyleSheet(
                "color: #0f766e; font-weight: 600;"
            )

    # ---------------- apply ----------------
    def _apply(self) -> None:
        src = self._parse_source_size()
        if src is None:
            QMessageBox.warning(
                self, "Размер",
                "Введите исходный размер (например, 11 или 11.5)."
            )
            return
        if not (self.scope_blocks.isChecked()
                or self.scope_lines.isChecked()):
            QMessageBox.information(
                self, "Область применения",
                "Включите хотя бы один вариант: блоки или строки."
            )
            return

        target = float(self.target_spin.value())
        src_r = _rounded_size(src)

        bc, lc = _count_matches(self.pages, src,
                                self.scope_blocks.isChecked(),
                                self.scope_lines.isChecked())
        if bc == 0 and lc == 0:
            QMessageBox.information(
                self, "Размер",
                f"Текста с размером {src:g} pt не найдено."
            )
            return
        if abs(_rounded_size(target) - src_r) < 0.1:
            QMessageBox.information(
                self, "Размер",
                "Исходный и новый размеры совпадают — изменений нет."
            )
            return

        parts = []
        if self.scope_blocks.isChecked():
            parts.append(f"блоков: {bc}")
        if self.scope_lines.isChecked():
            parts.append(f"строк: {lc}")
        detail = ", ".join(parts)

        if QMessageBox.question(
            self, "Применить размер",
            f"Заменить размер {src:g} pt на {target:g} pt?\n\n"
            f"Будет затронуто: {detail}\n\n"
            "Шрифт, начертание, выравнивание, интервал, сжатие, "
            "геометрия и стили не изменятся.",
        ) != QMessageBox.Yes:
            return

        match_blocks = self.scope_blocks.isChecked()
        match_lines = self.scope_lines.isChecked()

        for page in self.pages:
            for block in page.blocks:
                # обновляем блоки
                if match_blocks and _rounded_size(block.eff_size()) == src_r:
                    block.font_size = float(target)
                    # если блок в компактном режиме — нужно синхронизировать
                    # и строки, иначе размеры внутри блока разойдутся
                    if block.use_block_layout:
                        for line in block.lines:
                            line.font_size = float(target)

                # обновляем строки
                if match_lines and block.lines:
                    for line in block.lines:
                        if _rounded_size(line.eff_size()) == src_r:
                            line.font_size = float(target)

        # уведомляем MainWindow до закрытия, чтобы оно перерисовало
        self.changed.emit()

        QMessageBox.information(
            self, "Готово",
            f"Размер заменён: {src:g} pt → {target:g} pt\n"
            f"Обработано: {detail}"
        )
        self.accept()

# ---- END OF FILE app/bulk_resize_dialog.py ----
