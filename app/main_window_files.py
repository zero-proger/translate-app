# WindowFilesMixin: файлы, проекты, предпросмотр.
# Сохранение проекта передаёт styles «как есть» (Dict[str, TextStyle]) —
# сериализация выполняется внутри save_project().

from __future__ import annotations

import os
from typing import List

import fitz
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QProgressDialog,
)

from . import builder
from .config import build_fonts
from .extractor import extract_document
from .page_view import register_pdf_fonts
from .project import (
    FILE_EXTENSION as PROJECT_EXT,
    apply_project_to_pages,
    load_project,
    resolve_project_paths,
    save_project,
)
from .text_style import styles_from_dict

_TRANSLATE_SETTING_KEYS = (
    "backend", "source_lang", "target_lang", "delay_ms", "use_batch",
    "local_model", "local_device", "local_batch", "translate_font",
    "llm_model_path", "llm_prompt", "llm_device", "llm_max_new_tokens",
)

class WindowFilesMixin:
    def open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть PDF", "", "PDF (*.pdf)")
        if not path:
            return
        self._load_pdf(path)

    def _load_pdf(self, path: str) -> bool:
        try:
            self._close_document()
            preferred = self._effective_translate_font()
            doc, pages = extract_document(path, preferred_family=preferred)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{exc}")
            return False

        self.src_doc = doc
        self.pages = pages
        self.path = path
        self.current_page = 0
        self.zoom_mode = "fit"

        register_pdf_fonts(doc)

        self.page_list.blockSignals(True)
        self.page_list.clear()
        for i in range(len(pages)):
            self.page_list.addItem(f"Стр. {i + 1}")
        self.page_list.blockSignals(False)

        total_blocks = sum(len(page.blocks) for page in pages)
        total_lines = sum(
            len(block.lines) if block.lines else 1
            for page in pages for block in page.blocks
        )
        if total_blocks == 0:
            QMessageBox.information(
                self, "Текстовый слой не найден",
                "В документе нет текстового слоя. Скорее всего, это скан.\n\n"
                "Распознайте его, например:\n"
                "    ocrmypdf input.pdf output.pdf -l rus+eng\n"
                "и откройте полученный файл.",
            )

        self.page_view.set_document(doc)
        self.page_list.setCurrentRow(0)
        self.status_label.setText(
            f"{os.path.basename(path)} — страниц: {len(pages)}, "
            f"блоков: {total_blocks}, строк: {total_lines}"
        )
        return True

    # ------------------------------------------------------------- проекты
    def save_project_dialog(self) -> None:
        if not self.pages or not self.path:
            QMessageBox.information(self, "Проект", "Сначала откройте PDF-файл.")
            return
        self._commit_text_edit()

        base, _ = os.path.splitext(self.path)
        default_path = base + PROJECT_EXT
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект", default_path,
            f"Проект перевода (*{PROJECT_EXT});;Все файлы (*)",
        )
        if not path:
            return
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT

        settings_dict = {
            key: self.settings.value(key, "")
            for key in _TRANSLATE_SETTING_KEYS
        }
        fonts = self.settings.value("custom_fonts", [])
        if isinstance(fonts, str):
            fonts = [fonts] if fonts else []
        settings_dict["custom_fonts"] = [str(f) for f in fonts if f]

        # ВАЖНО: передаём self.styles как есть (Dict[str, TextStyle]).
        # Сериализацию выполняет save_project -> _styles_to_plain().
        # Раньше здесь было styles_to_dict(self.styles) — из-за этого
        # save_project получал dict-of-dicts и падал с "'dict' object has
        # no attribute 'to_dict'".
        styles_arg = getattr(self, "styles", {}) or {}

        try:
            save_project(path, self.path, self.pages, settings_dict,
                         self.current_page, styles=styles_arg)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось сохранить проект:\n{exc}")
            return
        styles_count = len(styles_arg)
        self.status_label.setText(
            f"Проект сохранён: {os.path.basename(path)} "
            f"(стилей: {styles_count}, пути относительные)"
        )

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть проект", "",
            f"Проект перевода (*{PROJECT_EXT});;Все файлы (*)",
        )
        if not path:
            return
        try:
            data = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось прочитать проект:\n{exc}")
            return

        if int(data.get("version", 0)) != 1:
            QMessageBox.warning(
                self, "Проект",
                "Версия файла проекта не поддерживается этой сборкой."
            )
            return

        data = resolve_project_paths(data, path)
        saved_settings = data.get("settings", {}) or {}

        fonts_abs = saved_settings.get("custom_fonts") or []
        if fonts_abs:
            self.settings.setValue("custom_fonts", list(fonts_abs))
            self.settings.sync()
            build_fonts(self._custom_fonts())
            self._refresh_font_combo()

        for key in _TRANSLATE_SETTING_KEYS:
            if key in saved_settings and saved_settings[key] != "":
                self.settings.setValue(key, saved_settings[key])
        self.settings.sync()

        pdf_path = data.get("_pdf_abs", "") or ""
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self, "Проект",
                f"Исходный PDF не найден рядом с проектом:\n{pdf_path or '(пусто)'}\n\n"
                "Положите PDF в ту же папку, где лежит проект."
            )
            return

        if not self._load_pdf(pdf_path):
            return

        try:
            self.styles = styles_from_dict(data.get("styles", {}))
        except Exception:
            self.styles = {}
        if hasattr(self, "_refresh_style_buttons"):
            self._refresh_style_buttons()

        try:
            applied = apply_project_to_pages(data, self.pages)
        except Exception as exc:
            QMessageBox.warning(
                self, "Проект",
                f"Данные проекта прочитаны, но применить их не удалось:\n{exc}"
            )
            return

        saved_page = int(data.get("current_page", 0))
        if 0 <= saved_page < len(self.pages):
            self.page_list.setCurrentRow(saved_page)
        else:
            self.page_view.refresh_all()
            self.render_current_page()

        styles_count = len(getattr(self, "styles", {}) or {})
        self.status_label.setText(
            f"Проект загружен: {os.path.basename(path)} — "
            f"блоков: {applied}, стилей: {styles_count}"
        )

    # ---------------------------------------------------------------- export
    def export_pdf(self) -> None:
        if not self.pages or self.src_doc is None:
            return
        self._commit_text_edit()
        has_translation = any(
            block.is_any_translated() for page in self.pages for block in page.blocks
        )
        if not has_translation:
            answer = QMessageBox.question(
                self, "Нет перевода", "Переводов ещё нет. Сохранить копию оригинала?"
            )
            if answer != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить PDF", self._default_output_name(), "PDF (*.pdf)"
        )
        if not path:
            return
        dialog = QProgressDialog("Сборка PDF…", "Отмена", 0, len(self.pages), self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        def progress(done: int, total: int) -> bool:
            dialog.setMaximum(total)
            dialog.setValue(done)
            QApplication.processEvents()
            return not dialog.wasCanceled()

        try:
            finished = builder.export_pdf(self.src_doc, self.pages, path, progress)
        except Exception as exc:
            dialog.close()
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить PDF:\n{exc}")
            return
        dialog.close()
        if not finished:
            self.status_label.setText("Сохранение отменено")
            return
        self.status_label.setText(f"Сохранено: {path}")
        QMessageBox.information(self, "Готово", f"PDF сохранён:\n{path}")

    def _default_output_name(self) -> str:
        if not self.path:
            return "translated.pdf"
        base, _ = os.path.splitext(self.path)
        return base + "_ru.pdf"

    def _close_document(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        self.worker = None
        if self.src_doc is not None:
            try:
                self.src_doc.close()
            except Exception:
                pass
        self.src_doc = None
        self.pages = []
        self.styles = {}
        self._last_style_name = None
        self.page_list.clear()
        self.block_list.clear()
        self.line_list.clear()
        self.original_edit.clear()
        self.translation_edit.clear()
        self.page_view.set_page(None, None)
        self.page_view.set_document(None)
        if hasattr(self, "_refresh_style_buttons"):
            self._refresh_style_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_document()
        super().closeEvent(event)

    # -------------------------------------------------------------- preview
    def _current_zoom(self, page_width: float) -> float:
        if self.zoom_mode == "fit":
            available = max(200, self.page_view.viewport().width() - 30)
            return max(0.15, min(3.0, available / max(1.0, page_width)))
        return self.zoom

    def render_current_page(self) -> None:
        if not self.pages:
            self.page_view.set_page(None, None)
            return
        page = self.pages[self.current_page]
        zoom = self._current_zoom(page.width)
        self.page_view.set_page(self.src_doc, page, zoom)

    def fit_width(self) -> None:
        self.zoom_mode = "fit"
        self.render_current_page()

    def change_zoom(self, delta: float) -> None:
        self.zoom_mode = "manual"
        self.zoom = max(0.2, min(3.0, self.zoom + delta))
        self.render_current_page()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.page_view.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                self.change_zoom(0.1 if event.angleDelta().y() > 0 else -0.1)
                return True
        return super().eventFilter(obj, event)

# ---- END OF FILE app/main_window_files.py ----
