# Главное окно. Добавлена кнопка «Только интервал — ко всей книге».

from __future__ import annotations

from typing import Dict, List, Optional

import fitz
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QTextEdit, QVBoxLayout,
    QWidget,
)

from .config import FONTS, build_fonts, font_label
from .models import PageData, TextBlock, TextLine
from .page_view import PageView
from .settings_dialog import SettingsDialog
from .wrap_check_dialog import WrapCheckDialog
from .models_manager import ModelsManagerDialog
from .find_replace_dialog import FindReplaceDialog
from .bulk_resize_dialog import BulkResizeDialog
from .text_style import TextStyle

from .main_window_edit import WindowEditMixin
from .main_window_files import WindowFilesMixin
from .main_window_translate import WindowTranslateMixin

ALIGN_BUTTONS = (
    ("left", "Л", "По левому краю"),
    ("center", "Ц", "По центру"),
    ("justify", "Ш", "По ширине"),
    ("right", "П", "По правому краю"),
)

_ALIGN_BUTTON_STYLE = (
    "QPushButton {"
    "  font-weight: 600; font-size: 12px;"
    "  padding: 0; min-width: 0;"
    "  background: #ffffff; color: #4d6bfe;"
    "  border: 1px solid #4d6bfe; border-radius: 4px;"
    "}"
    "QPushButton:hover { background: #eef2ff; }"
    "QPushButton:checked { background: #4d6bfe; color: #ffffff; }"
)

_STYLE_BUTTON_STYLE = (
    "QPushButton {"
    "  font-weight: 600; font-size: 11px;"
    "  padding: 2px 8px; min-height: 22px;"
    "  background: #ffffff; color: #0f766e;"
    "  border: 1px solid #0f766e; border-radius: 4px;"
    "}"
    "QPushButton:hover { background: #ecfdf5; }"
    "QPushButton:checked { background: #0f766e; color: #ffffff; }"
)

_REQUIRED_METHODS = (
    "_build_ui", "_build_format_toolbar", "_build_editor_panel",
    "_load_settings", "_refresh_font_combo", "_get_bool", "open_settings",
    "open_pdf", "_load_pdf", "save_project_dialog", "open_project",
    "export_pdf", "_current_zoom", "render_current_page",
    "fit_width", "change_zoom",
    "on_page_selected", "on_block_selected", "on_line_selected",
    "_commit_text_edit", "on_canvas_line_clicked", "on_canvas_line_edited",
    "_apply_format", "apply_font_only_to_all", "_current_align",
    "_run_translation", "translate_block", "translate_line",
    "stop_translation", "_set_busy",
    "open_wrap_check", "open_models_manager",
    "apply_block_geometry", "reset_block_geometry",
    "open_find_replace", "_on_find_replace_changed", "_jump_from_find",
    "open_bulk_resize", "_on_bulk_resize_changed",
    "_refresh_style_buttons", "_sync_style_buttons",
    "_on_style_button_clicked", "save_current_as_style", "delete_selected_style",
    "apply_spacing_only_to_all",
)

class MainWindow(WindowFilesMixin, WindowEditMixin, WindowTranslateMixin, QMainWindow):
    def __init__(self):
        super().__init__()

        missing = [m for m in _REQUIRED_METHODS if not hasattr(type(self), m)]
        if missing:
            raise RuntimeError(
                "Не найдены методы: " + ", ".join(missing) + ".\n"
                "Проверьте, что все файлы скопированы полностью."
            )

        self.setWindowTitle("Переводчик PDF-книг")
        self.resize(1520, 960)

        self.settings = QSettings("BetterDeepSeek", "PdfBookTranslator")
        self.src_doc: Optional[fitz.Document] = None
        self.path: str = ""
        self.pages: List[PageData] = []
        self.styles: Dict[str, TextStyle] = {}
        self._last_style_name: Optional[str] = None
        self.current_page = 0
        self.current_block: Optional[TextBlock] = None
        self.current_line: Optional[TextLine] = None
        self.zoom_mode = "fit"
        self.zoom = 1.0
        self.worker = None
        self._loading = False

        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(350)
        self._edit_timer.timeout.connect(self._commit_text_edit)

        self._build_ui()
        self._load_settings()
        self._refresh_style_buttons()

    def _build_ui(self) -> None:
        self.act_open = QAction("Открыть PDF…", self, shortcut=QKeySequence.Open,
                                triggered=self.open_pdf)
        self.act_open_project = QAction("Открыть проект…", self,
                                        shortcut="Ctrl+Shift+O",
                                        triggered=self.open_project)
        self.act_export = QAction("Сохранить PDF…", self, shortcut=QKeySequence.Save,
                                  triggered=self.export_pdf)
        self.act_save_project = QAction("Сохранить проект…", self,
                                        shortcut="Ctrl+Shift+S",
                                        triggered=self.save_project_dialog)
        self.act_translate_all = QAction("Перевести книгу", self, shortcut="Ctrl+T",
                                         triggered=self.translate_all)
        self.act_translate_page = QAction("Перевести текущую страницу", self,
                                          triggered=self.translate_current_page)
        self.act_translate_block = QAction("Перевести блок", self,
                                           triggered=self.translate_block)
        self.act_translate_line = QAction("Перевести строку", self,
                                          shortcut="Ctrl+Return",
                                          triggered=self.translate_line)
        self.act_stop = QAction("Остановить", self, triggered=self.stop_translation)
        self.act_stop.setToolTip("Прервать текущий перевод")
        self.act_stop.setEnabled(False)
        self.act_wrap_check = QAction("Проверить переносы…", self,
                                       triggered=self.open_wrap_check)
        self.act_models_manager = QAction("Менеджер моделей…", self,
                                           triggered=self.open_models_manager)
        self.act_settings = QAction("Настройки перевода…", self,
                                    triggered=self.open_settings)
        self.act_quit = QAction("Выход", self, triggered=self.close)
        self.act_find_replace = QAction("Найти и заменить…", self, shortcut="Ctrl+H",
                                        triggered=self.open_find_replace)
        self.act_bulk_resize = QAction(
            "Изменить размер по образцу…", self, shortcut="Ctrl+R",
            triggered=self.open_bulk_resize,
        )
        self.act_prev_block = QAction("Предыдущий блок", self, shortcut="Alt+Up",
                                      triggered=self.go_prev_block)
        self.act_next_block = QAction("Следующий блок", self, shortcut="Alt+Down",
                                      triggered=self.go_next_block)
        self.act_prev_line = QAction("Предыдущая строка", self, shortcut="Alt+Left",
                                     triggered=self.go_prev_line)
        self.act_next_line = QAction("Следующая строка", self, shortcut="Alt+Right",
                                     triggered=self.go_next_line)

        mb = self.menuBar()
        fm = mb.addMenu("Файл")
        fm.addAction(self.act_open)
        fm.addAction(self.act_open_project)
        fm.addSeparator()
        fm.addAction(self.act_export)
        fm.addAction(self.act_save_project)
        fm.addSeparator()
        fm.addAction(self.act_quit)

        em = mb.addMenu("Правка")
        em.addAction(self.act_find_replace)
        em.addAction(self.act_bulk_resize)

        tm = mb.addMenu("Перевод")
        tm.addAction(self.act_translate_all)
        tm.addAction(self.act_translate_page)
        tm.addSeparator()
        tm.addAction(self.act_translate_block)
        tm.addAction(self.act_translate_line)
        tm.addSeparator()
        tm.addAction(self.act_stop)
        tm.addSeparator()
        tm.addAction(self.act_wrap_check)
        tm.addSeparator()
        tm.addAction(self.act_models_manager)
        tm.addAction(self.act_settings)

        nm = mb.addMenu("Навигация")
        nm.addAction(self.act_prev_block)
        nm.addAction(self.act_next_block)
        nm.addAction(self.act_prev_line)
        nm.addAction(self.act_next_line)

        tb = self.addToolBar("Главная")
        tb.setMovable(False)
        tb.addAction(self.act_open)
        tb.addAction(self.act_translate_all)
        tb.addAction(self.act_stop)
        tb.addAction(self.act_export)
        tb.addSeparator()

        self.fit_action = QAction("По ширине", self, triggered=self.fit_width)
        self.zoom_in_action = QAction("+", self, triggered=lambda: self.change_zoom(0.1))
        self.zoom_out_action = QAction("−", self, triggered=lambda: self.change_zoom(-0.1))
        tb.addAction(self.fit_action)
        tb.addAction(self.zoom_out_action)
        tb.addAction(self.zoom_in_action)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)
        ll.addWidget(QLabel("Страницы"))
        self.page_list = QListWidget()
        self.page_list.setMaximumWidth(170)
        self.page_list.currentRowChanged.connect(self.on_page_selected)
        ll.addWidget(self.page_list)
        splitter.addWidget(left)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._build_format_toolbar())

        self.page_view = PageView()
        self.page_view.line_clicked.connect(self.on_canvas_line_clicked)
        self.page_view.line_edited.connect(self.on_canvas_line_edited)
        self.page_view.viewport().installEventFilter(self)
        cl.addWidget(self.page_view, 1)

        splitter.addWidget(center)
        splitter.addWidget(self._build_editor_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([170, 900, 400])

        self.status_label = QLabel("Готово")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _build_format_toolbar(self) -> QWidget:
        box = QGroupBox("Оформление")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # ---- строка 0: СТИЛИ ----
        l0 = QHBoxLayout()
        l0.setSpacing(6)
        l0.addWidget(QLabel("Стиль:"))

        self.style_buttons_layout = QHBoxLayout()
        self.style_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.style_buttons_layout.setSpacing(4)
        self.style_buttons: Dict[str, QPushButton] = {}
        l0.addLayout(self.style_buttons_layout)

        self.style_add_button = QPushButton("+")
        self.style_add_button.setFixedSize(28, 24)
        self.style_add_button.setToolTip(
            "Сохранить текущее оформление как именованный стиль"
        )
        self.style_add_button.clicked.connect(self.save_current_as_style)
        l0.addWidget(self.style_add_button)

        self.style_del_button = QPushButton("×")
        self.style_del_button.setFixedSize(28, 24)
        self.style_del_button.setToolTip("Удалить текущий выбранный стиль")
        self.style_del_button.clicked.connect(self.delete_selected_style)
        l0.addWidget(self.style_del_button)

        self.style_apply_all_check = QCheckBox("применять ко всей книге")
        self.style_apply_all_check.setToolTip(
            "Если включено — клик по кнопке стиля применяет его ко всем блокам книги. "
            "Иначе — только к текущему блоку."
        )
        l0.addWidget(self.style_apply_all_check)

        l0.addStretch(1)
        outer.addLayout(l0)

        # ---- строка 1: шрифт / размер / интервал / выравнивание / начертание ----
        l1 = QHBoxLayout()
        l1.setSpacing(6)
        l1.addWidget(QLabel("Шрифт"))
        self.font_combo = QComboBox()
        self.font_combo.setMinimumWidth(160)
        self.font_combo.currentIndexChanged.connect(self._apply_format)
        l1.addWidget(self.font_combo)

        l1.addSpacing(6)
        l1.addWidget(QLabel("Размер"))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(4, 200)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setDecimals(1)
        self.size_spin.setFixedWidth(74)
        self.size_spin.valueChanged.connect(self._apply_format)
        l1.addWidget(self.size_spin)

        l1.addSpacing(6)
        l1.addWidget(QLabel("Интервал"))
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.8, 3.0)
        self.spacing_spin.setSingleStep(0.05)
        self.spacing_spin.setDecimals(2)
        self.spacing_spin.setValue(1.15)
        self.spacing_spin.setFixedWidth(74)
        self.spacing_spin.setToolTip(
            "Множитель межстрочного интервала (1.15 = 115 % от размера шрифта)."
        )
        self.spacing_spin.valueChanged.connect(self._apply_format)
        l1.addWidget(self.spacing_spin)

        l1.addSpacing(8)
        l1.addWidget(QLabel("Выравнивание"))
        self.align_buttons = {}
        self.align_group = QButtonGroup(self)
        self.align_group.setExclusive(True)
        for key, letter, tooltip in ALIGN_BUTTONS:
            btn = QPushButton(letter)
            btn.setCheckable(True)
            btn.setFixedSize(28, 24)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(_ALIGN_BUTTON_STYLE)
            self.align_group.addButton(btn)
            l1.addWidget(btn)
            btn.clicked.connect(self._apply_format)
            self.align_buttons[key] = btn

        self._loading = True
        try:
            self.align_buttons["left"].setChecked(True)
        finally:
            self._loading = False

        l1.addSpacing(8)
        self.bold_check = QCheckBox("Жирный")
        self.bold_check.stateChanged.connect(self._apply_format)
        self.italic_check = QCheckBox("Курсив")
        self.italic_check.stateChanged.connect(self._apply_format)
        l1.addWidget(self.bold_check)
        l1.addWidget(self.italic_check)
        l1.addStretch(1)
        outer.addLayout(l1)

        # ---- строка 2: сжатие / автоподгонка / компактный режим ----
        l2 = QHBoxLayout()
        l2.setSpacing(8)
        self.autofit_check = QCheckBox("Уменьшать шрифт при переполнении")
        self.autofit_check.setChecked(True)
        self.autofit_check.stateChanged.connect(self._apply_format)
        l2.addWidget(self.autofit_check)

        self.condense_check = QCheckBox("Сжимать текст по ширине")
        self.condense_check.setChecked(True)
        self.condense_check.stateChanged.connect(self._apply_format)
        l2.addWidget(self.condense_check)

        l2.addWidget(QLabel("мин."))
        self.condense_min_spin = QDoubleSpinBox()
        self.condense_min_spin.setRange(50.0, 100.0)
        self.condense_min_spin.setSingleStep(1.0)
        self.condense_min_spin.setDecimals(0)
        self.condense_min_spin.setValue(80.0)
        self.condense_min_spin.setSuffix(" %")
        self.condense_min_spin.setFixedWidth(74)
        self.condense_min_spin.valueChanged.connect(self._apply_format)
        l2.addWidget(self.condense_min_spin)

        self.compact_check = QCheckBox("Переводить блоком целиком (как абзац)")
        self.compact_check.stateChanged.connect(self._apply_format)
        l2.addWidget(self.compact_check)
        l2.addStretch(1)
        outer.addLayout(l2)

        # ---- строка 3: применения ----
        l3 = QHBoxLayout()
        l3.setSpacing(6)
        self.apply_line_button = QPushButton("К строке")
        self.apply_line_button.clicked.connect(self.apply_format_to_line)
        self.apply_block_button = QPushButton("К блоку")
        self.apply_block_button.clicked.connect(self.apply_format_to_block)
        self.apply_page_button = QPushButton("К странице")
        self.apply_page_button.clicked.connect(self.apply_format_to_page)
        self.apply_all_button = QPushButton("Ко всей книге")
        self.apply_all_button.clicked.connect(self.apply_format_to_all)
        self.apply_font_only_button = QPushButton("Только шрифт — ко всей книге")
        self.apply_font_only_button.setToolTip(
            "Применить только шрифт, не меняя размер/начертание/сжатие/выравнивание."
        )
        self.apply_font_only_button.clicked.connect(self.apply_font_only_to_all)
        self.apply_spacing_only_button = QPushButton("Только интервал — ко всей книге")
        self.apply_spacing_only_button.setToolTip(
            "Применить только межстрочный интервал из поля «Интервал» "
            "ко всем блокам книги. Шрифт, размер, начертание, выравнивание "
            "и сжатие не изменятся.\n\n"
            "Совет: интервал реально влияет на отрисовку только у блоков "
            "в режиме «Переводить блоком целиком (как абзац)»."
        )
        self.apply_spacing_only_button.clicked.connect(self.apply_spacing_only_to_all)
        self.reset_format_button = QPushButton("Сбросить оформление")
        self.reset_format_button.clicked.connect(self.reset_line_format)

        l3.addWidget(self.apply_line_button)
        l3.addWidget(self.apply_block_button)
        l3.addWidget(self.apply_page_button)
        l3.addWidget(self.apply_all_button)
        l3.addSpacing(10)
        l3.addWidget(self.apply_font_only_button)
        l3.addWidget(self.apply_spacing_only_button)
        l3.addSpacing(10)
        l3.addWidget(self.reset_format_button)
        l3.addStretch(1)
        outer.addLayout(l3)

        # ---- строка 4: геометрия блока ----
        l4 = QHBoxLayout()
        l4.setSpacing(6)
        l4.addWidget(QLabel("Геометрия блока:"))

        l4.addWidget(QLabel("Ш"))
        self.block_width_spin = QDoubleSpinBox()
        self.block_width_spin.setRange(20.0, 3000.0)
        self.block_width_spin.setSingleStep(5.0)
        self.block_width_spin.setDecimals(1)
        self.block_width_spin.setSuffix(" pt")
        self.block_width_spin.setFixedWidth(94)
        self.block_width_spin.setToolTip("Ширина области блока")
        l4.addWidget(self.block_width_spin)

        l4.addWidget(QLabel("В"))
        self.block_height_spin = QDoubleSpinBox()
        self.block_height_spin.setRange(10.0, 3000.0)
        self.block_height_spin.setSingleStep(5.0)
        self.block_height_spin.setDecimals(1)
        self.block_height_spin.setSuffix(" pt")
        self.block_height_spin.setFixedWidth(94)
        self.block_height_spin.setToolTip("Высота области блока")
        l4.addWidget(self.block_height_spin)

        l4.addWidget(QLabel("X"))
        self.block_x_spin = QDoubleSpinBox()
        self.block_x_spin.setRange(-1000.0, 1000.0)
        self.block_x_spin.setSingleStep(1.0)
        self.block_x_spin.setDecimals(1)
        self.block_x_spin.setSuffix(" pt")
        self.block_x_spin.setFixedWidth(82)
        self.block_x_spin.setToolTip("Сдвиг по X относительно оригинала")
        l4.addWidget(self.block_x_spin)

        l4.addWidget(QLabel("Y"))
        self.block_y_spin = QDoubleSpinBox()
        self.block_y_spin.setRange(-1000.0, 1000.0)
        self.block_y_spin.setSingleStep(1.0)
        self.block_y_spin.setDecimals(1)
        self.block_y_spin.setSuffix(" pt")
        self.block_y_spin.setFixedWidth(82)
        self.block_y_spin.setToolTip("Сдвиг по Y относительно оригинала")
        l4.addWidget(self.block_y_spin)

        self.apply_geom_button = QPushButton("Применить")
        self.apply_geom_button.clicked.connect(self.apply_block_geometry)
        l4.addWidget(self.apply_geom_button)

        self.reset_geom_button = QPushButton("Сбросить")
        self.reset_geom_button.clicked.connect(self.reset_block_geometry)
        l4.addWidget(self.reset_geom_button)

        l4.addStretch(1)
        outer.addLayout(l4)

        return box

    def _build_editor_panel(self) -> QWidget:
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        wl.addWidget(scroll)
        panel = QWidget()
        panel.setMinimumWidth(340)
        scroll.setWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        gb = QGroupBox("Блоки на странице")
        gbl = QVBoxLayout(gb)
        self.block_list = QListWidget()
        self.block_list.setMaximumHeight(120)
        self.block_list.currentRowChanged.connect(self.on_block_selected)
        gbl.addWidget(self.block_list)
        nav_b = QHBoxLayout()
        self.prev_block_button = QPushButton("◀ Блок")
        self.prev_block_button.clicked.connect(self.go_prev_block)
        self.next_block_button = QPushButton("Блок ▶")
        self.next_block_button.clicked.connect(self.go_next_block)
        nav_b.addWidget(self.prev_block_button)
        nav_b.addWidget(self.next_block_button)
        gbl.addLayout(nav_b)
        layout.addWidget(gb)

        gl = QGroupBox("Строки в блоке")
        gll = QVBoxLayout(gl)
        self.line_list = QListWidget()
        self.line_list.setMaximumHeight(140)
        self.line_list.currentRowChanged.connect(self.on_line_selected)
        gll.addWidget(self.line_list)
        nav_l = QHBoxLayout()
        self.prev_line_button = QPushButton("◀ Строка")
        self.prev_line_button.clicked.connect(self.go_prev_line)
        self.next_line_button = QPushButton("Строка ▶")
        self.next_line_button.clicked.connect(self.go_next_line)
        nav_l.addWidget(self.prev_line_button)
        nav_l.addWidget(self.next_line_button)
        gll.addLayout(nav_l)

        self.auto_translate_check = QCheckBox(
            "Автоперевод при переходе к строке без перевода"
        )
        self.auto_translate_check.setChecked(True)
        gll.addWidget(self.auto_translate_check)
        layout.addWidget(gl)

        tr_row = QHBoxLayout()
        self.translate_block_button = QPushButton("Перевести блок")
        self.translate_block_button.clicked.connect(self.translate_block)
        self.translate_line_button = QPushButton("Перевести строку")
        self.translate_line_button.clicked.connect(self.translate_line)
        tr_row.addWidget(self.translate_block_button)
        tr_row.addWidget(self.translate_line_button)
        layout.addLayout(tr_row)

        og = QGroupBox("Оригинал")
        ol = QVBoxLayout(og)
        self.original_edit = QTextEdit()
        self.original_edit.setReadOnly(True)
        self.original_edit.setMaximumHeight(90)
        ol.addWidget(self.original_edit)
        layout.addWidget(og)

        tg = QGroupBox("Перевод (можно править здесь или на листе)")
        tl = QVBoxLayout(tg)
        self.translation_edit = QTextEdit()
        self.translation_edit.setMaximumHeight(140)
        self.translation_edit.textChanged.connect(self._on_translation_changed)
        tl.addWidget(self.translation_edit)
        layout.addWidget(tg)

        layout.addStretch(1)
        return wrapper

    # ============ СТИЛИ ============
    def _refresh_style_buttons(self) -> None:
        if not hasattr(self, "style_buttons_layout"):
            return
        for btn in self.style_buttons.values():
            try:
                self.style_buttons_layout.removeWidget(btn)
                btn.deleteLater()
            except Exception:
                pass
        self.style_buttons.clear()

        for name in sorted((self.styles or {}).keys()):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setMinimumHeight(22)
            btn.setStyleSheet(_STYLE_BUTTON_STYLE)
            btn.setToolTip(f"Применить стиль «{name}»")
            btn.clicked.connect(
                lambda _checked=False, n=name: self._on_style_button_clicked(n)
            )
            self.style_buttons_layout.addWidget(btn)
            self.style_buttons[name] = btn

        self._sync_style_buttons(self.current_block)

    def _sync_style_buttons(self, block: Optional[TextBlock]) -> None:
        if not hasattr(self, "style_buttons"):
            return
        active = block.style_name if block is not None else None
        for name, btn in self.style_buttons.items():
            btn.blockSignals(True)
            try:
                btn.setChecked(name == active)
            finally:
                btn.blockSignals(False)

    def _on_style_button_clicked(self, name: str) -> None:
        style = self.styles.get(name)
        if style is None:
            self._sync_style_buttons(self.current_block)
            return
        self._last_style_name = name

        if self.style_apply_all_check.isChecked():
            if not self.pages:
                QMessageBox.information(self, "Стиль",
                                        "Сначала откройте PDF-файл.")
                self._sync_style_buttons(self.current_block)
                return
            if QMessageBox.question(
                self, "Стиль",
                f"Применить стиль «{name}» ко всем блокам книги?",
            ) != QMessageBox.Yes:
                self._sync_style_buttons(self.current_block)
                return
            for page in self.pages:
                for block in page.blocks:
                    style.apply_to_block(block, to_lines=True)
                    block.style_name = name
            self.page_view.invalidate_background()
            self.render_current_page()
            self._populate_blocks()
            self._populate_lines()
            self.status_label.setText(f"Стиль «{name}» применён ко всей книге")
            return

        block = self.current_block
        if block is None:
            QMessageBox.information(
                self, "Стиль",
                "Сначала выберите блок в списке (или включите «ко всей книге»)."
            )
            self._sync_style_buttons(None)
            return

        prev_layout = block.use_block_layout
        style.apply_to_block(block, to_lines=True)
        block.style_name = name

        if prev_layout != block.use_block_layout:
            self.page_view.invalidate_background()
            self.render_current_page()
        else:
            self.page_view.refresh_block(block.block_index)
        self._populate_blocks()
        self._populate_lines()

        self._loading = True
        try:
            self._sync_controls(
                block.eff_family(), block.eff_size(),
                block.eff_spacing(), block.eff_align(),
                block.eff_bold(), block.eff_italic(),
                block.auto_fit, block.use_block_layout,
                block.condense_enabled, block.min_horizontal_scale,
            )
        finally:
            self._loading = False

        self._sync_style_buttons(block)
        self.status_label.setText(
            f"Стиль «{name}» применён к блоку {block.block_index + 1}"
        )

    def save_current_as_style(self) -> None:
        default_name = f"Стиль {len(self.styles) + 1}"
        name, ok = QInputDialog.getText(
            self, "Сохранить стиль", "Название стиля:", text=default_name,
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if name in self.styles:
            if QMessageBox.question(
                self, "Стиль", f"Стиль «{name}» уже существует. Заменить?",
            ) != QMessageBox.Yes:
                return

        style = TextStyle(
            name=name,
            font_family=self.font_combo.currentData(),
            font_size=float(self.size_spin.value()),
            bold=bool(self.bold_check.isChecked()),
            italic=bool(self.italic_check.isChecked()),
            align=self._current_align(),
            line_spacing=float(self.spacing_spin.value()),
            condense_enabled=bool(self.condense_check.isChecked()),
            min_horizontal_scale=max(
                0.5, min(1.0, float(self.condense_min_spin.value()) / 100.0)
            ),
            auto_fit=bool(self.autofit_check.isChecked()),
            use_block_layout=bool(self.compact_check.isChecked()),
        )
        self.styles[name] = style
        self._last_style_name = name
        self._refresh_style_buttons()
        self.status_label.setText(f"Стиль «{name}» сохранён")

    def delete_selected_style(self) -> None:
        name = self._last_style_name
        if self.current_block is not None and self.current_block.style_name:
            name = self.current_block.style_name
        if not name or name not in self.styles:
            QMessageBox.information(
                self, "Стиль",
                "Сначала выберите стиль (кликните по его кнопке или "
                "выберите блок с этим стилем)."
            )
            return
        if QMessageBox.question(
            self, "Стиль", f"Удалить стиль «{name}»?\n"
            "У блоков, к которым он применён, будет снята метка стиля, "
            "а оформление останется."
        ) != QMessageBox.Yes:
            return

        self.styles.pop(name, None)
        for page in self.pages:
            for block in page.blocks:
                if block.style_name == name:
                    block.style_name = None
        self._last_style_name = None
        self._refresh_style_buttons()
        self._populate_blocks()
        self.status_label.setText(f"Стиль «{name}» удалён")

    # ============ меню ============
    def open_wrap_check(self) -> None:
        if not self.pages:
            QMessageBox.information(self, "Проверка переносов",
                                    "Сначала откройте PDF-файл.")
            return
        dlg = WrapCheckDialog(self.pages, self)
        if dlg.exec() == QDialog.Accepted:
            self.page_view.refresh_all()
            self._populate_blocks()
            self._populate_lines()
            self.render_current_page()
            if self.current_block is not None:
                self.compact_check.setChecked(self.current_block.use_block_layout)

    def open_models_manager(self) -> None:
        ModelsManagerDialog(self).exec()

    def open_find_replace(self) -> None:
        if not self.pages:
            QMessageBox.information(self, "Поиск",
                                    "Сначала откройте PDF-файл.")
            return
        dlg = FindReplaceDialog(self.pages, self.current_block, self)
        dlg.changed.connect(self._on_find_replace_changed)
        dlg.jump_to.connect(self._jump_from_find)
        dlg.exec()

    def _on_find_replace_changed(self) -> None:
        self._refresh_after_translation()

    def _jump_from_find(self, page_index: int, block_index: int,
                        line_index: int) -> None:
        if not self.pages:
            return
        if not (0 <= page_index < len(self.pages)):
            return
        if self.page_list.currentRow() != page_index:
            self.page_list.setCurrentRow(page_index)
        page = self.pages[self.current_page]
        for i, blk in enumerate(page.blocks):
            if blk.block_index == block_index:
                self.block_list.setCurrentRow(i)
                if line_index >= 0 and blk.lines:
                    for j, ln in enumerate(blk.lines):
                        if ln.line_index == line_index:
                            self.line_list.setCurrentRow(j)
                            break
                break

    def _custom_fonts(self) -> List[str]:
        fonts = self.settings.value("custom_fonts", [])
        if isinstance(fonts, str):
            return [fonts] if fonts else []
        return [str(f) for f in (fonts or []) if f]

    def _load_settings(self) -> None:
        build_fonts(self._custom_fonts())
        current = self.settings.value("translate_font", None)
        if not current:
            self.settings.setValue(
                "translate_font", "narrow" if "narrow" in FONTS else "sans"
            )
        self._refresh_font_combo()
        if not FONTS:
            QMessageBox.warning(
                self, "Шрифты",
                "Не найден TTF-шрифт с поддержкой кириллицы.\n"
                "Добавьте свой шрифт в «Настройках перевода».",
            )

    def _refresh_font_combo(self) -> None:
        self._loading = True
        try:
            current = self.font_combo.currentData()
            self.font_combo.clear()
            for key in ("narrow", "sans", "serif", "mono"):
                if key in FONTS:
                    self.font_combo.addItem(font_label(key), key)
            for key in FONTS.keys():
                if key.startswith("custom:"):
                    self.font_combo.addItem(font_label(key), key)
            if current:
                idx = self.font_combo.findData(current)
                if idx >= 0:
                    self.font_combo.setCurrentIndex(idx)
        finally:
            self._loading = False

    def _effective_translate_font(self) -> Optional[str]:
        value = self.settings.value("translate_font", "auto")
        if value in (None, "", "auto"):
            return None
        return value if value in FONTS else None

    def _apply_default_family(self, family: Optional[str]) -> None:
        if not family or family not in FONTS:
            return
        for page in self.pages:
            for block in page.blocks:
                block.default_family = family
                for line in block.lines:
                    line.default_family = family

    def open_settings(self) -> None:
        old_font = self.settings.value("translate_font", "auto")
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.Accepted:
            return
        build_fonts(self._custom_fonts())
        self._refresh_font_combo()
        new_font = self.settings.value("translate_font", "auto")
        if new_font != old_font and new_font not in (None, "", "auto"):
            if new_font in FONTS and self.pages:
                self._apply_default_family(new_font)
        self.page_view.refresh_all()

    def _get_bool(self, key: str, default: bool = False) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")

    # ---------------- изменение размера по образцу ----------------
    def open_bulk_resize(self) -> None:
        if not self.pages:
            QMessageBox.information(self, "Размер",
                                    "Сначала откройте PDF-файл.")
            return
        dlg = BulkResizeDialog(self.pages, self.current_block, self)
        dlg.changed.connect(self._on_bulk_resize_changed)
        dlg.exec()

    def _on_bulk_resize_changed(self) -> None:
        self.page_view.refresh_all()
        self._populate_blocks()
        self._populate_lines()
        if self.current_block is not None:
            self._loading = True
            try:
                self.size_spin.setValue(self.current_block.eff_size())
            finally:
                self._loading = False


# ---- END OF FILE app/main_window.py ----
