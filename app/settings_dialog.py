# Настройки перевода — компактное окно с вкладками + sync() при работе с LLM.

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from .config import FAMILY_LABELS, FONTS
from .models_manager import (
    LLM_MODELS, ModelsManagerDialog, downloaded_llm_models,
    is_model_downloaded, model_local_path,
)
from .translator import (
    DEFAULT_LLM_PROMPT, TranslatorError, get_gpu_info, install_argos_package,
)

LANGS = [
    ("auto", "Автоопределение"), ("en", "Английский"), ("de", "Немецкий"),
    ("fr", "Французский"), ("es", "Испанский"), ("it", "Итальянский"),
    ("pt", "Португальский"), ("nl", "Нидерландский"), ("pl", "Польский"),
    ("uk", "Украинский"), ("ru", "Русский"), ("tr", "Турецкий"),
    ("zh-CN", "Китайский"), ("ja", "Японский"), ("ko", "Корейский"),
]
_FONT_ORDER = ("narrow", "sans", "serif", "mono")
LOCAL_MODELS = [
    ("nllb", "NLLB-200 600M (~2.5 ГБ)"),
    ("opus", "Opus MT (маленькая)"),
]
DEVICES = [
    ("auto", "Авто (CUDA → MPS → CPU)"),
    ("cuda", "CUDA (NVIDIA)"),
    ("mps", "MPS (Apple)"),
    ("cpu", "CPU"),
]

class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.settings.sync()  # видим свежие значения
        self.setWindowTitle("Настройки перевода")
        self.resize(620, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_translate(), "Перевод")
        self.tabs.addTab(self._tab_local(), "NLLB/Opus")
        self.tabs.addTab(self._tab_llm(), "Чат-LLM")
        self.tabs.addTab(self._tab_fonts(), "Шрифты")
        layout.addWidget(self.tabs, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._load()
        self.backend_combo.currentIndexChanged.connect(self._sync)
        self.source_combo.currentIndexChanged.connect(self._sync)
        self._sync()

    # ---------------- вкладки ----------------
    def _tab_translate(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(10, 10, 10, 10)
        form.setVerticalSpacing(6)

        self.backend_combo = QComboBox()
        for k, lbl in [
            ("google", "Google Translate (онлайн)"),
            ("argos", "Argos Translate (офлайн)"),
            ("local", "Локальная NLLB/Opus"),
            ("local_llm", "Локальная чат-LLM"),
        ]:
            self.backend_combo.addItem(lbl, k)
        form.addRow("Движок", self.backend_combo)

        self.source_combo = QComboBox()
        for code, title in LANGS:
            self.source_combo.addItem(title, code)
        form.addRow("Исходный", self.source_combo)

        self.target_combo = QComboBox()
        for code, title in LANGS:
            if code != "auto":
                self.target_combo.addItem(title, code)
        form.addRow("Целевой", self.target_combo)

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 5000)
        self.delay_spin.setSingleStep(50)
        self.delay_spin.setSuffix(" мс")
        form.addRow("Пауза (Google)", self.delay_spin)

        self.batch_check = QCheckBox("Пакетный перевод")
        form.addRow("", self.batch_check)

        self.argos_button = QPushButton("Установить модель Argos")
        self.argos_button.clicked.connect(self._install_argos)
        form.addRow("", self.argos_button)
        return w

    def _tab_local(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(10, 10, 10, 10)
        form.setVerticalSpacing(6)

        self.local_model_combo = QComboBox()
        for k, lbl in LOCAL_MODELS:
            self.local_model_combo.addItem(lbl, k)
        form.addRow("Модель", self.local_model_combo)

        self.local_device_combo = QComboBox()
        for k, lbl in DEVICES:
            self.local_device_combo.addItem(lbl, k)
        form.addRow("Устройство", self.local_device_combo)

        self.local_batch_spin = QSpinBox()
        self.local_batch_spin.setRange(1, 64)
        form.addRow("Batch size", self.local_batch_spin)

        gpu = QLabel(get_gpu_info())
        gpu.setWordWrap(True)
        gpu.setStyleSheet("color: #4d6bfe; font-weight: 600;")
        form.addRow("GPU-статус", gpu)

        hint = QLabel(
            "Для офлайн-работы скачайте модели заранее: "
            "«Перевод → Менеджер моделей»."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        form.addRow("", hint)
        return w

    def _tab_llm(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(10, 10, 10, 10)
        form.setVerticalSpacing(6)

        model_row = QHBoxLayout()
        self.llm_model_combo = QComboBox()
        self.llm_model_combo.setMinimumWidth(240)
        self.llm_refresh_button = QPushButton("Обновить")
        self.llm_refresh_button.setToolTip(
            "Обновить список скачанных LLM (после загрузки в менеджере)"
        )
        self.llm_refresh_button.clicked.connect(self._refresh_llm_combo)
        self.llm_pick_button = QPushButton("Модели…")
        self.llm_pick_button.clicked.connect(self._open_models)

        model_row.addWidget(self.llm_model_combo, 1)
        model_row.addWidget(self.llm_refresh_button)
        model_row.addWidget(self.llm_pick_button)
        form.addRow("Модель", model_row)

        self.llm_status_label = QLabel()
        self.llm_status_label.setWordWrap(True)
        self.llm_status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        form.addRow("", self.llm_status_label)

        self.llm_device_combo = QComboBox()
        for k, lbl in DEVICES:
            self.llm_device_combo.addItem(lbl, k)
        form.addRow("Устройство", self.llm_device_combo)

        self.llm_tokens_spin = QSpinBox()
        self.llm_tokens_spin.setRange(64, 4096)
        self.llm_tokens_spin.setSingleStep(64)
        self.llm_tokens_spin.setSuffix(" токенов")
        form.addRow("Max tokens", self.llm_tokens_spin)

        self.llm_prompt_edit = QPlainTextEdit()
        self.llm_prompt_edit.setMinimumHeight(120)
        form.addRow("Промпт", self.llm_prompt_edit)

        reset = QPushButton("Сбросить промпт по умолчанию")
        reset.clicked.connect(
            lambda: self.llm_prompt_edit.setPlainText(DEFAULT_LLM_PROMPT)
        )
        form.addRow("", reset)

        # после построения всех виджетов — заполняем список
        self._refresh_llm_combo()
        return w

    def _refresh_llm_combo(self) -> None:
        # синхронизируемся, чтобы увидеть выбор, сделанный в модельном менеджере
        self.settings.sync()

        saved = str(self.settings.value("llm_model_path", "") or "")

        # запомним текущий выбор в комбо (если пользователь успел поменять)
        current = saved
        if hasattr(self, "llm_model_combo"):
            data = self.llm_model_combo.currentData()
            if data:  # не затираем текущее вручную выбранное значение
                current = str(data)

        if not hasattr(self, "llm_model_combo"):
            return

        self.llm_model_combo.blockSignals(True)
        self.llm_model_combo.clear()
        self.llm_model_combo.addItem("— не выбрана —", "")

        by_id = {m[0]: m for m in LLM_MODELS}
        seen = set()
        for m_id in downloaded_llm_models():
            seen.add(m_id)
            name = by_id.get(m_id, (m_id, m_id, "", ""))[1]
            self.llm_model_combo.addItem(f"{name}  ({m_id})", m_id)

        if current and current not in seen:
            # показываем сохранённую, но не скачанную модель
            self.llm_model_combo.addItem(
                f"{current}  (не скачана)", current
            )

        idx = self.llm_model_combo.findData(current) if current else 0
        if idx < 0:
            idx = 0
        self.llm_model_combo.setCurrentIndex(idx)
        self.llm_model_combo.blockSignals(False)

        self._update_llm_status()

    def _update_llm_status(self) -> None:
        if not hasattr(self, "llm_status_label"):
            return
        model_id = ""
        if hasattr(self, "llm_model_combo"):
            model_id = str(self.llm_model_combo.currentData() or "")
        if not model_id:
            self.llm_status_label.setText(
                "Выберите модель из списка или нажмите «Модели…», чтобы скачать."
            )
            self.llm_status_label.setStyleSheet(
                "color: #6b7280; font-size: 11px;"
            )
            return
        if is_model_downloaded(model_id):
            path = model_local_path(model_id) or ""
            self.llm_status_label.setText(f"OK  {path}")
            self.llm_status_label.setStyleSheet(
                "color: #15803d; font-size: 11px;"
            )
        else:
            self.llm_status_label.setText(
                "Модель не скачана. Откройте «Модели…» и скачайте её."
            )
            self.llm_status_label.setStyleSheet(
                "color: #b45309; font-size: 11px;"
            )

    def _tab_fonts(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        top = QFormLayout()
        self.translate_font_combo = QComboBox()
        self.translate_font_combo.addItem("Авто", "auto")
        for k in _FONT_ORDER:
            if k in FONTS:
                self.translate_font_combo.addItem(FAMILY_LABELS.get(k, k), k)
        top.addRow("Шрифт перевода", self.translate_font_combo)
        layout.addLayout(top)

        grp = QGroupBox("Свои шрифты (TTF/OTF)")
        gl = QVBoxLayout(grp)
        self.fonts_list = QListWidget()
        self.fonts_list.setSelectionMode(QListWidget.ExtendedSelection)
        gl.addWidget(self.fonts_list, 1)
        row = QHBoxLayout()
        add_btn = QPushButton("Добавить…")
        add_btn.clicked.connect(self._add_fonts)
        del_btn = QPushButton("Удалить")
        del_btn.clicked.connect(self._remove_fonts)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        gl.addLayout(row)
        layout.addWidget(grp, 1)
        return w

    # ---------------- загрузка / сохранение ----------------
    def _load(self) -> None:
        for combo, key, default in (
            (self.backend_combo, "backend", "google"),
            (self.source_combo, "source_lang", "auto"),
            (self.target_combo, "target_lang", "ru"),
            (self.local_model_combo, "local_model", "nllb"),
            (self.local_device_combo, "local_device", "auto"),
            (self.llm_device_combo, "llm_device", "auto"),
            (self.translate_font_combo, "translate_font", "auto"),
        ):
            idx = combo.findData(self.settings.value(key, default))
            if idx >= 0:
                combo.setCurrentIndex(idx)

        for spin, key, default, lo, hi in (
            (self.delay_spin, "delay_ms", 250, 0, 5000),
            (self.local_batch_spin, "local_batch", 8, 1, 64),
            (self.llm_tokens_spin, "llm_max_new_tokens", 1024, 64, 4096),
        ):
            try:
                v = int(self.settings.value(key, default))
            except (TypeError, ValueError):
                v = default
            spin.setValue(max(lo, min(hi, v)))

        self.batch_check.setChecked(
            str(self.settings.value("use_batch", "false")).lower()
            in ("true", "1", "yes", "on")
        )
        self.llm_prompt_edit.setPlainText(
            self.settings.value("llm_prompt", "") or DEFAULT_LLM_PROMPT
        )

        self._refresh_llm_combo()

        fonts = self.settings.value("custom_fonts", [])
        if isinstance(fonts, str):
            fonts = [fonts] if fonts else []
        for p in fonts:
            if p:
                self._add_font_item(str(p))

    def accept(self) -> None:
        for key, combo in (
            ("backend", self.backend_combo),
            ("source_lang", self.source_combo),
            ("target_lang", self.target_combo),
            ("local_model", self.local_model_combo),
            ("local_device", self.local_device_combo),
            ("llm_device", self.llm_device_combo),
            ("translate_font", self.translate_font_combo),
        ):
            self.settings.setValue(key, combo.currentData())

        # ВАЖНО: сохраняем то, что реально выбрано в комбо.
        # Если пользователь выбрал «— не выбрана —», будет "".
        if hasattr(self, "llm_model_combo"):
            value = str(self.llm_model_combo.currentData() or "")
            self.settings.setValue("llm_model_path", value)

        self.settings.setValue("delay_ms", int(self.delay_spin.value()))
        self.settings.setValue(
            "use_batch", "true" if self.batch_check.isChecked() else "false"
        )
        self.settings.setValue("local_batch", int(self.local_batch_spin.value()))
        self.settings.setValue(
            "llm_max_new_tokens", int(self.llm_tokens_spin.value())
        )
        self.settings.setValue("llm_prompt", self.llm_prompt_edit.toPlainText())
        fonts = [self.fonts_list.item(i).text()
                 for i in range(self.fonts_list.count())]
        self.settings.setValue("custom_fonts", fonts)

        # синхронизируем, чтобы другие QSettings-инстансы увидели изменения
        self.settings.sync()
        super().accept()

    # ---------------- helpers ----------------
    def _sync(self, *args) -> None:
        kind = self.backend_combo.currentData()
        self.argos_button.setEnabled(
            kind == "argos" and self.source_combo.currentData() != "auto"
        )
        self.delay_spin.setEnabled(kind == "google")
        self.batch_check.setEnabled(kind in ("google", "argos"))
        is_local = kind == "local"
        self.local_model_combo.setEnabled(is_local)
        self.local_device_combo.setEnabled(is_local)
        self.local_batch_spin.setEnabled(is_local)
        is_llm = kind == "local_llm"
        for widget in (
            self.llm_model_combo, self.llm_refresh_button, self.llm_pick_button,
            self.llm_device_combo, self.llm_tokens_spin, self.llm_prompt_edit,
        ):
            widget.setEnabled(is_llm)

    def _open_models(self) -> None:
        ModelsManagerDialog(self).exec()
        # синхронизация — ключ к решению проблемы «выбрал, а не видит»
        self.settings.sync()
        self._refresh_llm_combo()

    def _add_font_item(self, path: str) -> None:
        for i in range(self.fonts_list.count()):
            if self.fonts_list.item(i).text() == path:
                return
        self.fonts_list.addItem(QListWidgetItem(path))

    def _add_fonts(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "TTF/OTF", "", "Шрифты (*.ttf *.otf)"
        )
        for p in paths:
            self._add_font_item(p)

    def _remove_fonts(self) -> None:
        for item in self.fonts_list.selectedItems():
            self.fonts_list.takeItem(self.fonts_list.row(item))

    def _install_argos(self) -> None:
        src = self.source_combo.currentData()
        tgt = self.target_combo.currentData()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            install_argos_package(src, tgt)
        except TranslatorError as e:
            QMessageBox.warning(self, "Argos", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Argos", f"Ошибка: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Argos", "Модель установлена.")
