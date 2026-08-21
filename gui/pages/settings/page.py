"""设置页（FR-D3）— 主题/语言/设备/路径配置，持久化到 user_settings.json。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from gui.core.settings_io import load_user_settings, save_user_settings
from core.constants import CONFIG_DIR as _CONFIG_DIR


class SettingsPage(QWidget):
    """系统设置页。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._build_ui()
        self._wire()
        self._load_settings()

    def _load_settings(self) -> None:
        """从 configs/user_settings.json 加载上次保存的设置。

        使用内部 key (night/daytime, ch_CN/en_US) 匹配，
        而非翻译后的显示文本，确保切换语言后仍能正确恢复。
        （W13 C1：JSON 读取收敛到 gui.core.settings_io）
        """
        # 内部 key → combo index 映射
        _theme_keys = {"night": 0, "daytime": 1, "auto": 2}
        _lang_keys = {"ch_CN": 0, "en_US": 1}
        _device_keys = {"cuda": 0, "cpu": 1}

        try:
            settings = load_user_settings(str(_CONFIG_DIR))
            if "theme" in settings:
                idx = _theme_keys.get(settings["theme"], 0)
                self._theme_combo.setCurrentIndex(idx)
            if "language" in settings:
                idx = _lang_keys.get(settings["language"], 0)
                self._lang_combo.setCurrentIndex(idx)
            if "device" in settings:
                idx = _device_keys.get(settings["device"], 0)
                self._device_combo.setCurrentIndex(idx)
            if "workspace" in settings:
                self._workspace_edit.setText(settings["workspace"])
        except (OSError, KeyError, TypeError):
            import logging
            logging.getLogger(__name__).exception("加载用户设置失败")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        self._title = QLabel(tr("系统设置"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        # 外观设置
        appear_box = QFrame()
        appear_box.setStyleSheet("QFrame { border: 1px solid #333; border-radius: 8px; padding: 12px; }")
        appear_form = QFormLayout(appear_box)
        appear_form.setSpacing(10)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems([tr("深色"), tr("浅色"), tr("自动")])
        appear_form.addRow(tr("主题"), self._theme_combo)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["中文 (简体)", "English (US)"])
        appear_form.addRow(tr("语言"), self._lang_combo)

        root.addWidget(appear_box)

        # 计算设置
        compute_box = QFrame()
        compute_box.setStyleSheet("QFrame { border: 1px solid #333; border-radius: 8px; padding: 12px; }")
        compute_form = QFormLayout(compute_box)
        compute_form.setSpacing(10)

        self._device_combo = QComboBox()
        self._device_combo.addItems(["CUDA (GPU)", "CPU"])
        compute_form.addRow(tr("推理设备"), self._device_combo)

        root.addWidget(compute_box)

        # 路径设置
        # W28：precision/cache_dir 两死键已删（持久化但零消费——虚假能力比
        # 缺失更糟；cache_dir 属 defer-with-trigger：离线权重缓存需求触发再建）
        path_box = QFrame()
        path_box.setStyleSheet("QFrame { border: 1px solid #333; border-radius: 8px; padding: 12px; }")
        path_form = QFormLayout(path_box)
        path_form.setSpacing(10)

        self._workspace_edit = QLineEdit()
        self._workspace_edit.setPlaceholderText(tr("默认工作空间目录"))
        self._workspace_btn = QPushButton(tr("浏览..."))
        ws_row = QHBoxLayout()
        ws_row.addWidget(self._workspace_edit)
        ws_row.addWidget(self._workspace_btn)
        path_form.addRow(tr("工作空间"), ws_row)

        root.addWidget(path_box)

        # 按钮
        btn_row = QHBoxLayout()
        self._save_btn = QPushButton(tr("保存设置"))
        self._save_btn.setObjectName("accentButton")
        self._reset_btn = QPushButton(tr("恢复默认"))
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # 关于（W28：删除"零样本+有监督双范式"stale 宣称——零样本 W18 起未实装）
        about = QLabel(
            "<b>AutoVisionAgent</b><br>"
            "v2.0.0 (M2)<br>"
            "有监督工业视觉平台<br>"
            "PySide6 · Python 3.10+"
        )
        about.setStyleSheet("color: #888; padding: 12px;")
        about.setAlignment(Qt.AlignCenter)
        root.addWidget(about)
        root.addStretch()

    def _wire(self) -> None:
        self._workspace_btn.clicked.connect(self._pick_workspace)
        self._save_btn.clicked.connect(self._save)
        self._reset_btn.clicked.connect(self._reset)

    def _pick_workspace(self) -> None:
        from gui.widgets.file_dialog import pick_directory
        path = pick_directory(self, "选择工作空间")
        if path:
            self._workspace_edit.setText(path)

    def _save(self) -> None:
        """保存设置到 configs/user_settings.json，并即时应用主题/语言。

        存储使用内部 key (night/daytime, ch_CN/en_US)，
        而非翻译后显示文本，避免切换语言后无法恢复。
        """
        # 从 combo index 映射到内部 key
        _theme_keys = ["night", "daytime", "auto"]
        _lang_keys = ["ch_CN", "en_US"]
        _device_keys = ["cuda", "cpu"]

        theme_idx = self._theme_combo.currentIndex()
        lang_idx = self._lang_combo.currentIndex()
        device_idx = self._device_combo.currentIndex()

        # W28：只持久化有消费方的键（workspace→resolve_base_root 单源；
        # precision/cache_dir 死键已删）
        settings = {
            "theme": _theme_keys[theme_idx] if theme_idx < len(_theme_keys) else "night",
            "language": _lang_keys[lang_idx] if lang_idx < len(_lang_keys) else "ch_CN",
            "device": _device_keys[device_idx] if device_idx < len(_device_keys) else "cuda",
            "workspace": self._workspace_edit.text().strip(),
        }

        # 即时应用主题（夜/日/自动——auto 随系统配色解析，W4-T4 / P2-9）
        theme_key = settings["theme"]
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                from gui.core.theme import apply_theme, resolve_theme
                apply_theme(app, resolve_theme(theme_key))
        except (ImportError, RuntimeError):
            import logging
            logging.getLogger(__name__).exception("应用主题失败")

        # 即时应用语言
        lang_key = settings["language"]
        try:
            from gui.core.i18n import set_language
            set_language(lang_key)
        except (ImportError, RuntimeError):
            import logging
            logging.getLogger(__name__).exception("应用语言失败")

        try:
            save_user_settings(settings, str(_CONFIG_DIR))
            self.status_changed.emit(tr("设置已保存"), "ok")
        except (OSError, TypeError) as exc:
            self.status_changed.emit(tr("保存失败"), str(exc)[:40])

    def _reset(self) -> None:
        self._theme_combo.setCurrentIndex(0)
        self._lang_combo.setCurrentIndex(0)
        self._device_combo.setCurrentIndex(0)
        self._workspace_edit.clear()
        self.status_changed.emit(tr("已恢复默认设置"), "info")

    def retranslate(self) -> None:
        self._title.setText(tr("系统设置"))
        self._theme_combo.setItemText(0, tr("深色"))
        self._theme_combo.setItemText(1, tr("浅色"))
        self._theme_combo.setItemText(2, tr("自动"))
        self._workspace_edit.setPlaceholderText(tr("默认工作空间目录"))
        self._workspace_btn.setText(tr("浏览..."))
        self._save_btn.setText(tr("保存设置"))
        self._reset_btn.setText(tr("恢复默认"))
