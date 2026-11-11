# WindowTranslateMixin: перевод + прогресс с % / слов / сл-в-сек.

from __future__ import annotations

import traceback
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .models import PageData
from .translator import TranslateWorker, TranslatorError, create_backend

def _fmt_stats(done_units: int, total_units: int,
               words: int, elapsed_ms: int) -> str:
    pct = int(round(done_units * 100 / total_units)) if total_units else 0
    seconds = elapsed_ms / 1000.0
    wps = words / seconds if seconds > 0.1 else 0.0
    return (
        f"{pct}% ({done_units}/{total_units})"
        f" · {words} слов"
        f" · {wps:.1f} сл/сек"
    )

class WindowTranslateMixin:
    def _make_backend(self):
        self.settings.sync()
        kind = str(self.settings.value("backend", "google"))
        source = str(self.settings.value("source_lang", "auto"))
        target = str(self.settings.value("target_lang", "ru"))

        try:
            delay = int(self.settings.value("delay_ms", 250))
        except (TypeError, ValueError):
            delay = 250
        local_model = str(self.settings.value("local_model", "nllb"))
        local_device = str(self.settings.value("local_device", "auto"))
        try:
            local_batch = int(self.settings.value("local_batch", 8))
        except (TypeError, ValueError):
            local_batch = 8

        llm_path = str(self.settings.value("llm_model_path", "") or "")
        llm_prompt = str(self.settings.value("llm_prompt", "") or "")
        llm_device = str(self.settings.value("llm_device", "auto"))
        try:
            llm_tokens = int(self.settings.value("llm_max_new_tokens", 1024))
        except (TypeError, ValueError):
            llm_tokens = 1024

        try:
            backend = create_backend(
                kind, source, target,
                delay_ms=delay,
                local_model=local_model,
                local_device=local_device,
                local_batch=local_batch,
                llm_model_path=llm_path,
                llm_prompt=llm_prompt,
                llm_device=llm_device,
                llm_max_new_tokens=llm_tokens,
            )
            return backend, None
        except TranslatorError as exc:
            return None, str(exc) or "Ошибка создания переводчика (без текста)."
        except ImportError:
            return None, (
                "Не установлены зависимости перевода.\n"
                "Google: pip install deep-translator\n"
                "NLLB/Opus/Chat-LLM: "
                "pip install torch transformers accelerate sentencepiece"
            )
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) or repr(exc) or type(exc).__name__
            return None, f"Не удалось создать переводчик:\n{msg}"

    def _prepare_backend(self, kind: str):
        if kind in ("local", "local_llm"):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            try:
                return self._make_backend()
            finally:
                QApplication.restoreOverrideCursor()
        return self._make_backend()

    def translate_all(self) -> None:
        self._run_translation(self.pages)

    def translate_current_page(self) -> None:
        if self.pages:
            self._run_translation([self.pages[self.current_page]])

    def _run_translation(self, subset: List[PageData]) -> None:
        if not subset:
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Перевод", "Перевод уже выполняется.")
            return
        self._commit_text_edit()
        self.settings.sync()
        kind = str(self.settings.value("backend", "google"))
        backend, error = self._prepare_backend(kind)
        if error:
            QMessageBox.warning(self, "Перевод", error)
            return
        use_batch = (kind in ("local", "local_llm")) or self._get_bool(
            "use_batch", False
        )
        self.worker = TranslateWorker(subset, backend, only_empty=True,
                                      use_batch=use_batch, parent=self)
        self.worker.progress.connect(self._on_translation_progress)
        self.worker.finished_ok.connect(self._on_translation_done)
        self.worker.cancelled.connect(self._on_translation_cancelled)
        self.worker.failed.connect(self._on_translation_failed)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        device = getattr(backend, "device", None)
        self.status_label.setText(
            f"Перевод…{' (GPU: ' + device + ')' if device else ''}"
        )
        self._set_busy(True)
        self.worker.start()

    def stop_translation(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Останавливаю перевод…")
            stop = getattr(self, "act_stop", None)
            if stop is not None:
                stop.setEnabled(False)

    def translate_block(self) -> None:
        block = self.current_block
        if block is None:
            return
        self.settings.sync()
        kind = str(self.settings.value("backend", "google"))
        backend, error = self._prepare_backend(kind)
        if error:
            QMessageBox.warning(self, "Перевод", error)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if block.use_block_layout:
                block.translated_text = backend.translate(block.original_text) or ""
            elif block.lines:
                for line in block.lines:
                    if line.original.strip():
                        line.translated = backend.translate(line.original) or ""
            else:
                block.translated_text = backend.translate(block.original_text) or ""
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) or repr(exc) or type(exc).__name__
            QMessageBox.warning(self, "Ошибка перевода", msg)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.page_view.refresh_block(block.block_index)
        self._populate_lines()
        self._populate_blocks()
        row = self.line_list.currentRow()
        if row >= 0:
            self.line_list.setCurrentRow(row)

    def translate_line(self) -> None:
        line = self.current_line
        if line is None:
            self.translate_block()
            return
        self.settings.sync()
        kind = str(self.settings.value("backend", "google"))
        backend, error = self._prepare_backend(kind)
        if error:
            QMessageBox.warning(self, "Перевод", error)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            line.translated = backend.translate(line.original) or ""
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) or repr(exc) or type(exc).__name__
            QMessageBox.warning(self, "Ошибка перевода", msg)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._loading = True
        try:
            self.translation_edit.setPlainText(line.translated)
        finally:
            self._loading = False
        self.page_view.refresh_block(line.block_index)
        self._refresh_line_list_item()

    # ---------- прогресс ----------
    def _on_translation_progress(self, done: int, total: int,
                                 words: int, elapsed_ms: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.status_label.setText(
            "Перевод: " + _fmt_stats(done, total, words, elapsed_ms)
        )

    def _refresh_after_translation(self) -> None:
        block_row = self.block_list.currentRow()
        line_row = self.line_list.currentRow()
        self._populate_blocks()
        if 0 <= block_row < self.block_list.count():
            self.block_list.setCurrentRow(block_row)
        self._populate_lines()
        if 0 <= line_row < self.line_list.count():
            self.line_list.setCurrentRow(line_row)
        self.page_view.refresh_all()

    def _worker_stats(self):
        w = self.worker
        if w is None:
            return 0, 0
        return (
            int(getattr(w, "total_words_done", 0) or 0),
            int(getattr(w, "elapsed_ms", 0) or 0),
        )

    def _on_translation_done(self, count: int) -> None:
        self.progress.setVisible(False)
        self._set_busy(False)
        words, elapsed_ms = self._worker_stats()
        seconds = elapsed_ms / 1000.0
        wps = words / seconds if seconds > 0.1 else 0.0
        self.status_label.setText(
            f"Перевод завершён: {count} блоков"
            f" · {words} слов · {wps:.1f} сл/сек · {seconds:.1f} сек"
        )
        self._refresh_after_translation()

    def _on_translation_cancelled(self, count: int) -> None:
        self.progress.setVisible(False)
        self._set_busy(False)
        words, elapsed_ms = self._worker_stats()
        seconds = elapsed_ms / 1000.0
        wps = words / seconds if seconds > 0.1 else 0.0
        self.status_label.setText(
            f"Остановлено: {count} блоков"
            f" · {words} слов · {wps:.1f} сл/сек · {seconds:.1f} сек"
        )
        self._refresh_after_translation()

    def _on_translation_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self._set_busy(False)
        self.status_label.setText("Ошибка перевода")
        msg = message or ("Неизвестная ошибка (без сообщения). "
                          "Смотрите консоль — там полный traceback.")
        QMessageBox.warning(self, "Ошибка перевода", msg)

    def _set_busy(self, busy: bool) -> None:
        for name in (
            "act_open", "act_open_project", "act_export",
            "act_save_project", "act_translate_all",
            "act_translate_page", "act_translate_block",
            "act_translate_line", "act_wrap_check",
        ):
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(not busy)
        stop = getattr(self, "act_stop", None)
        if stop is not None:
            stop.setEnabled(busy)

# ---- END OF FILE app/main_window_translate.py ----
