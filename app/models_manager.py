# Менеджер локальных моделей: скачивание + выбор активной LLM.
# ВАЖНО: использует QSettings с sync() — чтобы выбор был виден в других окнах.

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressDialog, QPushButton, QVBoxLayout,
)

LLM_MODELS: List[Tuple[str, str, str, str]] = [
    ("Qwen/Qwen2.5-1.5B-Instruct", "Qwen2.5 1.5B", "~3 ГБ", "быстро, CPU-ok"),
    ("Qwen/Qwen2.5-3B-Instruct", "Qwen2.5 3B", "~6 ГБ", "рекомендуется"),
    ("Qwen/Qwen2.5-7B-Instruct", "Qwen2.5 7B", "~15 ГБ", "лучшее качество"),
]

TRANSLATE_MODELS: List[Tuple[str, str, str, str]] = [
    ("facebook/nllb-200-distilled-600M", "NLLB-200 600M", "~2.5 ГБ",
     "200 языков, GPU/CPU"),
    ("Helsinki-NLP/opus-mt-en-ru", "Opus MT en→ru", "~300 МБ",
     "быстрая, только en→ru"),
]

def _hf_cache_root() -> Path:
    env = os.environ.get("HF_HOME")
    if env:
        return Path(env) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"

def _model_dir(model_id: str) -> Path:
    return _hf_cache_root() / ("models--" + model_id.replace("/", "--"))

def is_model_downloaded(model_id: str) -> bool:
    """Модель считается скачанной, если в snapshots/ есть непустой каталог
    ИЛИ есть config.json в корне (некоторые версии HF кладут так)."""
    if not model_id:
        return False
    model_dir = _model_dir(model_id)
    if not model_dir.exists():
        return False
    snapshots = model_dir / "snapshots"
    if snapshots.exists():
        try:
            for sub in snapshots.iterdir():
                if not sub.is_dir():
                    continue
                try:
                    if any(sub.iterdir()):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
    if (model_dir / "config.json").exists():
        return True
    return False

def model_local_path(model_id: str) -> Optional[str]:
    if not model_id:
        return None
    snapshots = _model_dir(model_id) / "snapshots"
    if not snapshots.exists():
        return None
    try:
        for sub in snapshots.iterdir():
            if sub.is_dir() and any(sub.iterdir()):
                return str(sub)
    except Exception:
        return None
    return None

def delete_model(model_id: str) -> None:
    path = _model_dir(model_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)

def downloaded_llm_models() -> List[str]:
    return [m_id for m_id, *_ in LLM_MODELS if is_model_downloaded(m_id)]

class _DownloadWorker(QThread):
    finished_ok = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, model_id: str):
        super().__init__()
        self.model_id = model_id

    def run(self) -> None:  # noqa: D401
        try:
            from huggingface_hub import snapshot_download
            path = snapshot_download(
                repo_id=self.model_id,
                resume_download=True,
                allow_patterns=[
                    "*.json", "*.safetensors", "*.bin", "*.model", "*.txt",
                    "tokenizer*", "*.py", "*.md",
                ],
            )
            self.finished_ok.emit(self.model_id, path)
        except Exception as exc:
            self.failed.emit(self.model_id, str(exc))

class ModelsManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("BetterDeepSeek", "PdfBookTranslator")
        # принудительно синхронизируемся со стором, чтобы видеть актуальное
        self.settings.sync()

        self.setWindowTitle("Менеджер моделей")
        self.resize(700, 540)
        layout = QVBoxLayout(self)

        cache = QLabel(f"Кеш: {_hf_cache_root()}")
        cache.setWordWrap(True)
        cache.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(cache)

        layout.addWidget(QLabel(
            "Скачайте модели заранее, чтобы работать без интернета. "
            "Выбранная LLM будет использоваться движком «Локальная чат-LLM»."
        ))

        self.list_llm = QListWidget()
        self.list_tr = QListWidget()
        for widget, title, models in (
            (self.list_llm, "LLM (перевод с промптом)", LLM_MODELS),
            (self.list_tr, "Модели перевода (NLLB/Opus)", TRANSLATE_MODELS),
        ):
            layout.addWidget(QLabel(title))
            for model_id, name, size, comment in models:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, model_id)
                self._refresh_item(item, model_id, name, size, comment)
                widget.addItem(item)
            widget.setMinimumHeight(110)
            layout.addWidget(widget, 1)

        row = QHBoxLayout()
        self.btn_download = QPushButton("Скачать выбранную")
        self.btn_download.clicked.connect(self._download_selected)
        self.btn_delete = QPushButton("Удалить выбранную")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_use = QPushButton("Использовать выбранную")
        self.btn_use.setToolTip(
            "Сделать активной. Сохраняется немедленно, без кнопки OK."
        )
        self.btn_use.clicked.connect(self._use_selected)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_download)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        row.addWidget(self.btn_use)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self._workers: List[_DownloadWorker] = []
        self._dialogs: dict = {}

        self._active_list = self.list_llm
        self.list_llm.itemClicked.connect(
            lambda *_: self._mark_active(self.list_llm)
        )
        self.list_tr.itemClicked.connect(
            lambda *_: self._mark_active(self.list_tr)
        )
        self.list_llm.itemSelectionChanged.connect(self._sync_use_button)
        self.list_tr.itemSelectionChanged.connect(self._sync_use_button)
        self._sync_use_button()

    def _mark_active(self, active) -> None:
        self._active_list = active
        self._sync_use_button()

    def _sync_use_button(self) -> None:
        lst = self._active_list
        item = lst.currentItem() if lst is not None else None
        # кнопка активна для ЛЮБОЙ LLM из списка (скачана или нет)
        enabled = lst is self.list_llm and item is not None
        self.btn_use.setEnabled(enabled)

    def _refresh_item(self, item: QListWidgetItem, model_id: str,
                      name: str, size: str, comment: str) -> None:
        ok = is_model_downloaded(model_id)
        active = (self.settings.value("llm_model_path", "") or "") == model_id
        badge = "ACTIVE" if active else ("OK" if ok else "—")
        item.setText(f"[{badge}] {name} · {size}\n{comment}\n{model_id}")
        if active:
            item.setForeground(Qt.blue)
        elif ok:
            item.setForeground(Qt.darkGreen)
        else:
            item.setForeground(Qt.darkGray)

    def _refresh_all_items(self) -> None:
        self.settings.sync()
        for lst, models in (
            (self.list_llm, LLM_MODELS),
            (self.list_tr, TRANSLATE_MODELS),
        ):
            by_id = {m[0]: m for m in models}
            for i in range(lst.count()):
                item = lst.item(i)
                model_id = item.data(Qt.UserRole)
                m = by_id.get(model_id)
                if m:
                    self._refresh_item(item, *m)

    def _current(self):
        lst = self._active_list
        if lst is None or lst.currentItem() is None:
            for candidate in (self.list_llm, self.list_tr):
                if candidate.currentItem() is not None:
                    self._active_list = candidate
                    return candidate, candidate.currentItem()
            return None, None
        return lst, lst.currentItem()

    def _download_selected(self) -> None:
        lst, item = self._current()
        if item is None:
            QMessageBox.information(self, "Модель", "Выберите модель в списке.")
            return
        model_id = item.data(Qt.UserRole)
        if is_model_downloaded(model_id):
            QMessageBox.information(self, "Модель", "Эта модель уже скачана.")
            return
        dlg = QProgressDialog(
            f"Скачивание {model_id}…\nЭто может занять несколько минут.",
            "Отмена", 0, 0, self,
        )
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        self._dialogs[model_id] = (dlg, lst, item)

        worker = _DownloadWorker(model_id)
        worker.finished_ok.connect(self._on_downloaded)
        worker.failed.connect(self._on_failed)
        self._workers.append(worker)
        worker.start()

    def _on_downloaded(self, model_id: str, path: str) -> None:
        entry = self._dialogs.pop(model_id, None)
        if entry:
            entry[0].close()
        self._refresh_all_items()
        self._sync_use_button()
        QMessageBox.information(
            self, "Готово",
            f"Модель скачана:\n{path}\n\n"
            "Нажмите «Использовать выбранную», чтобы сделать её активной.",
        )

    def _on_failed(self, model_id: str, error: str) -> None:
        entry = self._dialogs.pop(model_id, None)
        if entry:
            entry[0].close()
        QMessageBox.warning(self, "Ошибка загрузки", f"{model_id}:\n{error}")

    def _delete_selected(self) -> None:
        lst, item = self._current()
        if item is None:
            return
        model_id = item.data(Qt.UserRole)
        if not is_model_downloaded(model_id):
            QMessageBox.information(self, "Модель", "Модель не скачана.")
            return
        if QMessageBox.question(
            self, "Удалить модель",
            f"Удалить локальную копию {model_id}?",
        ) != QMessageBox.Yes:
            return
        delete_model(model_id)
        if (self.settings.value("llm_model_path", "") or "") == model_id:
            self.settings.setValue("llm_model_path", "")
            self.settings.sync()
        self._refresh_all_items()
        self._sync_use_button()

    def _use_selected(self) -> None:
        lst, item = self._current()
        if lst is not self.list_llm or item is None:
            QMessageBox.information(
                self, "Модель",
                "Выберите модель в верхнем списке (LLM)."
            )
            return
        model_id = item.data(Qt.UserRole)
        if not model_id:
            return

        # Сохраняем без требований к скачиванию — можно скачать позже.
        self.settings.setValue("llm_model_path", str(model_id))
        self.settings.sync()  # КРИТИЧНО: делаем значение видимым другим
        self._refresh_all_items()

        if is_model_downloaded(model_id):
            msg = (
                f"Активная LLM:\n{model_id}\n\n"
                "Она будет использоваться движком «Локальная чат-LLM с промптом»."
            )
        else:
            msg = (
                f"Выбрана LLM:\n{model_id}\n\n"
                "ВНИМАНИЕ: модель ещё не скачана. Либо нажмите «Скачать "
                "выбранную», либо приложение скачает её при первом переводе "
                "(нужен интернет)."
            )
        QMessageBox.information(self, "LLM выбрана", msg)
