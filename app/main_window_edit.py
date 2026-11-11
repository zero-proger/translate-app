# WindowEditMixin: списки, геометрия, форматирование, стили, «только интервал».

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from .config import FONTS, font_label
from .models import TextBlock, TextLine

class WindowEditMixin:
    def on_page_selected(self, row: int) -> None:
        if row < 0 or not self.pages:
            return
        self._commit_text_edit()
        self.current_page = row
        self._populate_blocks()
        if self.pages[row].blocks:
            self.block_list.setCurrentRow(0)
        else:
            self.block_list.clear()
            self.line_list.clear()
            self._clear_editor()
        self.render_current_page()
        self.status_label.setText(f"Страница {row + 1} из {len(self.pages)}")

    def _style_prefix(self, block: TextBlock) -> str:
        marks = []
        if block.style_name:
            marks.append(f"[{block.style_name}]")
        if block.use_block_layout:
            marks.append("▪")
        return " ".join(marks)

    def _populate_blocks(self) -> None:
        self.block_list.blockSignals(True)
        self.block_list.clear()
        if self.pages:
            for i, block in enumerate(self.pages[self.current_page].blocks):
                preview = " ".join(block.eff_text().split())
                if len(preview) > 60:
                    preview = preview[:60] + "…"
                prefix = self._style_prefix(block)
                if prefix:
                    self.block_list.addItem(f"{i + 1}. {prefix} {preview}")
                else:
                    self.block_list.addItem(f"{i + 1}. {preview}")
        self.block_list.blockSignals(False)

    def _clear_editor(self) -> None:
        self._loading = True
        try:
            self.original_edit.clear()
            self.translation_edit.clear()
            for spin in (self.block_width_spin, self.block_height_spin,
                         self.block_x_spin, self.block_y_spin):
                spin.blockSignals(True)
                spin.setValue(0.0)
                spin.blockSignals(False)
        finally:
            self._loading = False

    def on_block_selected(self, row: int) -> None:
        if not self.pages:
            return
        page = self.pages[self.current_page]
        if not (0 <= row < len(page.blocks)):
            self.current_block = None
            self.current_line = None
            self.line_list.clear()
            self._clear_editor()
            if hasattr(self, "_sync_style_buttons"):
                self._sync_style_buttons(None)
            return
        self._commit_text_edit()
        block = page.blocks[row]
        self.current_block = block
        self._populate_lines()
        if block.lines and not block.use_block_layout:
            self.line_list.setCurrentRow(0)
        else:
            self.current_line = None
            self._show_block_only(block)
        self.page_view.highlight_block(block.block_index)
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(block)

    def _populate_lines(self) -> None:
        self.line_list.blockSignals(True)
        self.line_list.clear()
        block = self.current_block
        if block is not None and block.lines:
            for li, line in enumerate(block.lines):
                preview = " ".join(line.eff_text().split())
                if len(preview) > 70:
                    preview = preview[:70] + "…"
                self.line_list.addItem(f"{li + 1}. {preview}")
        self.line_list.blockSignals(False)

    def _show_block_only(self, block: TextBlock) -> None:
        self._loading = True
        try:
            self.original_edit.setPlainText(block.original_text)
            self.translation_edit.setPlainText(block.translated_text)
            self._sync_controls(block.eff_family(), block.eff_size(),
                                block.eff_spacing(), block.eff_align(),
                                block.eff_bold(), block.eff_italic(),
                                block.auto_fit, block.use_block_layout,
                                block.condense_enabled, block.min_horizontal_scale)
            self._sync_geometry_controls(block)
        finally:
            self._loading = False

    def on_line_selected(self, row: int) -> None:
        block = self.current_block
        if block is None or not block.lines:
            return
        if not (0 <= row < len(block.lines)):
            return
        self._commit_text_edit()
        line = block.lines[row]
        self.current_line = line
        self._load_line_into_editor(line)
        self.page_view.highlight_block(block.block_index, row)

    def _load_line_into_editor(self, line: TextLine) -> None:
        self._loading = True
        try:
            self.original_edit.setPlainText(line.original)
            self.translation_edit.setPlainText(line.translated)
            block = self.current_block
            use_compact = block.use_block_layout if block is not None else False
            self._sync_controls(line.eff_family(), line.eff_size(),
                                None, line.eff_align(),
                                line.eff_bold(), line.eff_italic(),
                                None, use_compact,
                                line.condense_enabled, line.min_horizontal_scale)
            if block is not None:
                self._sync_geometry_controls(block)
        finally:
            self._loading = False

    def _sync_geometry_controls(self, block: TextBlock) -> None:
        if not hasattr(self, "block_width_spin"):
            return
        bbox = block.eff_bbox()
        width = max(0.0, bbox[2] - bbox[0])
        height = max(0.0, bbox[3] - bbox[1])
        x_offset = bbox[0] - block.bbox[0]
        y_offset = bbox[1] - block.bbox[1]
        for spin, val in (
            (self.block_width_spin, width),
            (self.block_height_spin, height),
            (self.block_x_spin, x_offset),
            (self.block_y_spin, y_offset),
        ):
            spin.blockSignals(True)
            try:
                spin.setValue(float(val))
            finally:
                spin.blockSignals(False)

    def _sync_controls(self, family, size, spacing, align, bold, italic,
                       autofit, compact, condense, condense_min) -> None:
        idx = self.font_combo.findData(family)
        self.font_combo.setCurrentIndex(max(0, idx))
        if size:
            self.size_spin.setValue(float(size))
        if spacing is not None:
            self.spacing_spin.setValue(float(spacing))
        target = align if align in self.align_buttons else "left"
        self.align_buttons[target].setChecked(True)
        self.bold_check.setChecked(bool(bold))
        self.italic_check.setChecked(bool(italic))
        if autofit is not None:
            self.autofit_check.setChecked(bool(autofit))
        if compact is not None:
            self.compact_check.setChecked(bool(compact))
        if condense is not None:
            self.condense_check.setChecked(bool(condense))
        if condense_min is not None:
            self.condense_min_spin.setValue(float(condense_min) * 100.0)

    def _current_align(self) -> str:
        for key, btn in self.align_buttons.items():
            if btn.isChecked():
                return key
        return "left"

    def _on_translation_changed(self) -> None:
        if self._loading:
            return
        self._edit_timer.start()

    def _commit_text_edit(self) -> None:
        if self._loading:
            return
        text = self.translation_edit.toPlainText()
        block = self.current_block
        if block is not None and block.use_block_layout:
            block.translated_text = text
            self.page_view.refresh_block(block.block_index)
            self._refresh_block_list_item()
            return
        if self.current_line is not None:
            self.current_line.translated = text
            self.page_view.refresh_block(self.current_line.block_index)
            self._refresh_line_list_item()
        elif block is not None:
            block.translated_text = text
            self.page_view.refresh_block(block.block_index)
            self._refresh_block_list_item()

    def _refresh_line_list_item(self) -> None:
        line = self.current_line
        if line is None:
            return
        row = self.line_list.currentRow()
        if row < 0:
            return
        item = self.line_list.item(row)
        if item is None:
            return
        preview = " ".join(line.eff_text().split())
        if len(preview) > 70:
            preview = preview[:70] + "…"
        self.line_list.blockSignals(True)
        item.setText(f"{row + 1}. {preview}")
        self.line_list.blockSignals(False)
        self._refresh_block_list_item()

    def _refresh_block_list_item(self) -> None:
        block = self.current_block
        if block is None:
            return
        row = self.block_list.currentRow()
        if row < 0:
            return
        item = self.block_list.item(row)
        if item is None:
            return
        preview = " ".join(block.eff_text().split())
        if len(preview) > 60:
            preview = preview[:60] + "…"
        prefix = self._style_prefix(block)
        self.block_list.blockSignals(True)
        if prefix:
            item.setText(f"{row + 1}. {prefix} {preview}")
        else:
            item.setText(f"{row + 1}. {preview}")
        self.block_list.blockSignals(False)

    def on_canvas_line_clicked(self, block_index: int, line_index: int) -> None:
        page = self.pages[self.current_page] if self.pages else None
        if page is None:
            return
        block_row = -1
        for i, block in enumerate(page.blocks):
            if block.block_index == block_index:
                block_row = i
                break
        if block_row < 0:
            return
        self.block_list.blockSignals(True)
        self.block_list.setCurrentRow(block_row)
        self.block_list.blockSignals(False)
        block = page.blocks[block_row]
        self.current_block = block
        self._populate_lines()
        if line_index >= 0 and block.lines and not block.use_block_layout:
            self.line_list.blockSignals(True)
            self.line_list.setCurrentRow(line_index)
            self.line_list.blockSignals(False)
            self.current_line = block.lines[line_index]
            self._load_line_into_editor(self.current_line)
        else:
            self.current_line = None
            self._show_block_only(block)
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(block)

    def on_canvas_line_edited(self, block_index: int, line_index: int,
                              new_text: str) -> None:
        page = self.pages[self.current_page] if self.pages else None
        if page is None:
            return
        block = next((b for b in page.blocks if b.block_index == block_index), None)
        if block is None:
            return
        if line_index >= 0 and block.lines and not block.use_block_layout \
                and 0 <= line_index < len(block.lines):
            block.lines[line_index].translated = new_text
        else:
            block.translated_text = new_text
        self.page_view.refresh_block(block.block_index)
        if self.current_block is block:
            if self.current_line is not None and self.current_line in block.lines:
                idx = block.lines.index(self.current_line)
                if idx == line_index:
                    self._loading = True
                    try:
                        self.translation_edit.setPlainText(new_text)
                    finally:
                        self._loading = False
            elif block.use_block_layout:
                self._loading = True
                try:
                    self.translation_edit.setPlainText(new_text)
                finally:
                    self._loading = False
            self._populate_lines()
            row = self.line_list.currentRow()
            if 0 <= row < self.line_list.count():
                self.line_list.setCurrentRow(row)
            self._refresh_block_list_item()

    def go_prev_block(self) -> None:
        row = self.block_list.currentRow()
        if row > 0:
            self.block_list.setCurrentRow(row - 1)

    def go_next_block(self) -> None:
        row = self.block_list.currentRow()
        if 0 <= row < self.block_list.count() - 1:
            self.block_list.setCurrentRow(row + 1)

    def go_prev_line(self) -> None:
        row = self.line_list.currentRow()
        if row > 0:
            self.line_list.setCurrentRow(row - 1)
        else:
            self.go_prev_block()

    def go_next_line(self) -> None:
        row = self.line_list.currentRow()
        if 0 <= row < self.line_list.count() - 1:
            self.line_list.setCurrentRow(row + 1)
        else:
            self.go_next_block()
            if self.line_list.count() > 0:
                self.line_list.setCurrentRow(0)

    def _maybe_auto_translate(self) -> None:
        if not self.auto_translate_check.isChecked():
            return
        if self.current_line is None:
            return
        if not self.current_line.translated.strip():
            QTimer.singleShot(0, self.translate_line)

    def apply_block_geometry(self) -> None:
        block = self.current_block
        if block is None:
            QMessageBox.information(
                self, "Геометрия", "Сначала выберите блок в списке."
            )
            return
        try:
            width_pt = float(self.block_width_spin.value())
            height_pt = float(self.block_height_spin.value())
            x_offset_pt = float(self.block_x_spin.value())
            y_offset_pt = float(self.block_y_spin.value())
        except (TypeError, ValueError):
            return
        if width_pt < 20.0:
            QMessageBox.warning(self, "Геометрия",
                                "Ширина должна быть не меньше 20 pt.")
            return
        if height_pt < 10.0:
            QMessageBox.warning(self, "Геометрия",
                                "Высота должна быть не меньше 10 pt.")
            return

        block.set_geometry(width_pt, height_pt, x_offset_pt, y_offset_pt)

        if not block.use_block_layout:
            block.use_block_layout = True
            self.compact_check.setChecked(True)

        self.page_view.invalidate_background()
        self.render_current_page()
        self._sync_geometry_controls(block)
        self.status_label.setText(
            f"Блок {block.block_index + 1}: "
            f"{width_pt:.0f}×{height_pt:.0f} pt, "
            f"сдвиг X {x_offset_pt:+.0f}, Y {y_offset_pt:+.0f}"
        )

    def reset_block_geometry(self) -> None:
        block = self.current_block
        if block is None:
            return
        block.reset_bbox()
        self.page_view.invalidate_background()
        self.render_current_page()
        self._sync_geometry_controls(block)
        self.status_label.setText(
            f"Блок {block.block_index + 1}: геометрия сброшена."
        )

    def _apply_format(self, *args) -> None:
        if self._loading:
            return
        block = self.current_block
        line = self.current_line
        if block is None:
            return
        family = self.font_combo.currentData()
        size = float(self.size_spin.value())
        spacing = float(self.spacing_spin.value())
        align = self._current_align()
        bold = self.bold_check.isChecked()
        italic = self.italic_check.isChecked()
        autofit = self.autofit_check.isChecked()
        condense = self.condense_check.isChecked()
        condense_min = max(0.5, min(1.0, float(self.condense_min_spin.value()) / 100.0))
        compact = self.compact_check.isChecked()

        prev_layout = block.use_block_layout
        block.use_block_layout = compact
        mode_changed = (prev_layout != compact)

        block.condense_enabled = condense
        block.min_horizontal_scale = condense_min

        block.style_name = None
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(block)

        if line is not None and not compact:
            line.font_family = family
            line.font_size = size
            line.align = align
            line.bold = bold
            line.italic = italic
            line.condense_enabled = condense
            line.min_horizontal_scale = condense_min
        else:
            block.font_family = family
            block.font_size = size
            block.line_spacing = spacing
            block.align = align
            block.bold = bold
            block.italic = italic
            block.auto_fit = autofit

        if mode_changed:
            self.page_view.invalidate_background()
            self.render_current_page()
        else:
            self.page_view.refresh_block(block.block_index)
        self._refresh_block_list_item()

    def apply_format_to_line(self) -> None:
        self._apply_format()

    def _copy_format_to_target(self, block: TextBlock, line: Optional[TextLine]) -> None:
        family = self.font_combo.currentData()
        size = float(self.size_spin.value())
        spacing = float(self.spacing_spin.value())
        align = self._current_align()
        bold = self.bold_check.isChecked()
        italic = self.italic_check.isChecked()
        autofit = self.autofit_check.isChecked()
        condense = self.condense_check.isChecked()
        condense_min = max(0.5, min(1.0, float(self.condense_min_spin.value()) / 100.0))
        compact = self.compact_check.isChecked()

        block.use_block_layout = compact
        block.condense_enabled = condense
        block.min_horizontal_scale = condense_min
        block.style_name = None

        if line is not None:
            line.font_family = family
            line.font_size = size
            line.align = align
            line.bold = bold
            line.italic = italic
            line.condense_enabled = condense
            line.min_horizontal_scale = condense_min
        else:
            block.font_family = family
            block.font_size = size
            block.line_spacing = spacing
            block.align = align
            block.bold = bold
            block.italic = italic
            block.auto_fit = autofit

    def apply_format_to_block(self) -> None:
        block = self.current_block
        if block is None:
            return
        prev = block.use_block_layout
        self._copy_format_to_target(block, None)
        for line in block.lines:
            line.font_family = block.font_family
            line.font_size = block.font_size
            line.align = block.align
            line.bold = block.bold
            line.italic = block.italic
            line.condense_enabled = block.condense_enabled
            line.min_horizontal_scale = block.min_horizontal_scale
        self._populate_lines()
        self._populate_blocks()
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(block)
        if prev != block.use_block_layout:
            self.page_view.invalidate_background()
            self.render_current_page()
        else:
            self.page_view.refresh_block(block.block_index)

    def apply_format_to_page(self) -> None:
        if not self.pages:
            return
        page = self.pages[self.current_page]
        for block in page.blocks:
            self._copy_format_to_target(block, None)
            for line in block.lines:
                line.font_family = block.font_family
                line.font_size = block.font_size
                line.align = block.align
                line.bold = block.bold
                line.italic = block.italic
                line.condense_enabled = block.condense_enabled
                line.min_horizontal_scale = block.min_horizontal_scale
        self.page_view.invalidate_background()
        self.render_current_page()
        self._populate_blocks()
        self._populate_lines()
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(self.current_block)

    def apply_format_to_all(self) -> None:
        if not self.pages:
            return
        answer = QMessageBox.question(
            self, "Применить ко всей книге",
            "Применить текущие настройки оформления ко всем строкам книги?",
        )
        if answer != QMessageBox.Yes:
            return
        for page in self.pages:
            for block in page.blocks:
                self._copy_format_to_target(block, None)
                for line in block.lines:
                    line.font_family = block.font_family
                    line.font_size = block.font_size
                    line.align = block.align
                    line.bold = block.bold
                    line.italic = block.italic
                    line.condense_enabled = block.condense_enabled
                    line.min_horizontal_scale = block.min_horizontal_scale
        self.page_view.invalidate_background()
        self.render_current_page()
        self._populate_blocks()
        self._populate_lines()
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(self.current_block)
        self.status_label.setText("Оформление применено ко всем строкам книги")

    def apply_font_only_to_all(self) -> None:
        family = self.font_combo.currentData()
        if not family or family not in FONTS:
            QMessageBox.information(
                self, "Шрифт", "Сначала выберите шрифт в списке «Шрифт»."
            )
            return
        if not self.pages:
            QMessageBox.information(self, "Шрифт", "Сначала откройте PDF-файл.")
            return
        for page in self.pages:
            for block in page.blocks:
                block.font_family = family
                block.default_family = family
                for line in block.lines:
                    line.font_family = family
                    line.default_family = family
        self.page_view.refresh_all()
        self.status_label.setText(
            f"Шрифт «{font_label(family)}» применён ко всей книге"
        )

    def apply_spacing_only_to_all(self) -> None:
        """Применить ТОЛЬКО межстрочный интервал ко всем блокам книги.

        Не трогает шрифт, размер, начертание, выравнивание, сжатие,
        компактный режим, геометрию — только `line_spacing`.

        Применяется к блокам; у строк нет собственного интервала
        (интервал — это свойство блока при отрисовке).
        """
        if not self.pages:
            QMessageBox.information(
                self, "Интервал", "Сначала откройте PDF-файл."
            )
            return

        spacing = float(self.spacing_spin.value())
        if spacing <= 0:
            return

        if QMessageBox.question(
            self, "Применить интервал",
            f"Применить межстрочный интервал {spacing:.2f} ко всей книге?\n\n"
            "Будут затронуты только параметры интервала — шрифт, размер, "
            "начертание, выравнивание и сжатие не изменятся.\n\n"
            "Совет: интервал реально влияет на отрисовку только у блоков "
            "в режиме «Переводить блоком целиком (как абзац)». У построчных "
            "блоков каждая строка стоит на своей позиции из PDF, и интервал "
            "там не используется. Значение сохранится и применится, если "
            "вы включите блочный режим.",
        ) != QMessageBox.Yes:
            return

        count = 0
        for page in self.pages:
            for block in page.blocks:
                block.line_spacing = spacing
                count += 1

        self.page_view.invalidate_background()
        self.render_current_page()
        self._populate_blocks()
        self._populate_lines()

        if self.current_block is not None:
            self._loading = True
            try:
                self.spacing_spin.setValue(spacing)
            finally:
                self._loading = False

        self.status_label.setText(
            f"Межстрочный интервал {spacing:.2f} применён к {count} блокам"
        )

    def reset_line_format(self) -> None:
        block = self.current_block
        line = self.current_line
        if block is None:
            return
        prev = block.use_block_layout
        if line is not None and not block.use_block_layout:
            line.font_family = None
            line.font_size = None
            line.bold = None
            line.italic = None
            line.align = None
            line.condense_enabled = True
            line.min_horizontal_scale = 0.80
        else:
            block.font_family = None
            block.font_size = None
            block.line_spacing = None
            block.align = None
            block.bold = None
            block.italic = None
            block.auto_fit = True
            block.use_block_layout = False
            block.condense_enabled = True
            block.min_horizontal_scale = 0.80
        block.style_name = None
        if hasattr(self, "_sync_style_buttons"):
            self._sync_style_buttons(block)
        if line is not None and not block.use_block_layout:
            self._load_line_into_editor(line)
        else:
            self._show_block_only(block)
        self._refresh_block_list_item()
        if prev != block.use_block_layout:
            self.page_view.invalidate_background()
            self.render_current_page()
        else:
            self.page_view.refresh_block(block.block_index)

# ---- END OF FILE app/main_window_edit.py ----
