"""PyDracula 风格 QSS 主题（FR-D1 双主题 night/daytime）。

原创 QSS：暗色底 + 霓虹紫/青强调 + 无边框圆角 + 侧边栏选中高亮。
ThemeManager 负责在 QApplication 上应用/切换主题。
"""
from __future__ import annotations

from typing import Dict, Literal

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ThemeName = Literal["night", "daytime"]

# 共享控件样式（与主题无关的部分）
_BASE_WIDGETS = """
QToolTip {
    background-color: #15171d; color: #e2e8f0; border: 1px solid #3f4452;
    border-radius: 4px; padding: 4px 8px;
}
QMenuBar { background-color: $BG_APP; color: $TEXT; }
QMenu { background-color: $BG_CHILD; color: $TEXT; border: 1px solid $BORDER; }
QMenu::item:selected { background-color: $ACCENT; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: $BORDER; min-height: 30px; border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: $ACCENT; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: $BORDER; min-width: 30px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""

# night 主题：暗色 + 紫强调
_NIGHT_VARS = {
    "BG_APP": "#2c2f38",
    "BG_CHILD": "#1b1e26",
    "BG_RAISED": "#232733",
    "BG_DEEP": "#15171d",
    "BORDER": "#3f4452",
    "ACCENT": "#7c3aed",
    "ACCENT2": "#06b6d4",
    "TEXT": "#e2e8f0",
    "TEXT_DIM": "#94a3b8",
    "DANGER": "#e81123",
}

# daytime 主题：浅色 + 紫强调
_DAYTIME_VARS = {
    "BG_APP": "#f1f5f9",
    "BG_CHILD": "#ffffff",
    "BG_RAISED": "#e2e8f0",
    "BG_DEEP": "#cbd5e1",
    "BORDER": "#cbd5e1",
    "ACCENT": "#7c3aed",
    "ACCENT2": "#0891b2",
    "TEXT": "#1e2025",
    "TEXT_DIM": "#64748b",
    "DANGER": "#dc2626",
}


def _qss_base(v: Dict[str, str]) -> str:
    """QSS 区块：QWidget 默认样式 + 主容器 + 标题栏 + 窗口控制按钮。"""
    return f"""
    QWidget {{
        background-color: {v['BG_CHILD']}; color: {v['TEXT']};
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 13px;
    }}
    /* 主应用容器：圆角无边框外壳 */
    QFrame#bgApp {{ background-color: {v['BG_APP']}; border-radius: 10px; }}
    /* 标题栏 */
    QFrame#titleBar {{
        background-color: {v['BG_CHILD']}; border-top-left-radius: 10px;
        border-top-right-radius: 10px; border-bottom: 1px solid {v['BG_DEEP']};
    }}
    QLabel#titleText {{ color: {v['TEXT']}; padding-left: 8px; font-size: 13px; }}
    QLabel#titleLogo {{ color: {v['ACCENT']}; padding-left: 10px; font-size: 15px; font-weight: bold; }}
    QPushButton#btn_close, QPushButton#btn_min, QPushButton#btn_max {{
        background: transparent; border: none; border-radius: 0px; padding: 12px 16px;
    }}
    QPushButton#btn_close:hover {{ background-color: {v['DANGER']}; }}
    QPushButton#btn_min:hover, QPushButton#btn_max:hover {{ background-color: {v['BG_RAISED']}; }}"""


def _qss_nav(v: Dict[str, str]) -> str:
    """QSS 区块：侧边导航容器 + 导航按钮（hover/选中态）。"""
    return f"""
    /* 侧边导航 */
    QFrame#leftMenu {{
        background-color: {v['BG_CHILD']}; border-right: 1px solid {v['BG_DEEP']};
        border-bottom-left-radius: 10px;
    }}
    QPushButton[nav="true"] {{
        background: transparent; border: none; border-left: 3px solid transparent;
        text-align: left; padding: 14px 18px; color: {v['TEXT_DIM']}; font-size: 13px;
    }}
    QPushButton[nav="true"]:hover {{ background-color: {v['BG_RAISED']}; color: {v['TEXT']}; }}
    QPushButton[nav="true"][selected="true"] {{
        background-color: {v['BG_RAISED']}; border-left: 3px solid {v['ACCENT']};
        color: {v['ACCENT2']}; font-weight: bold;
    }}"""


def _qss_pages(v: Dict[str, str]) -> str:
    """QSS 区块：页面栈与正文标题/提示。"""
    return f"""
    /* 页面栈与正文 */
    QStackedWidget#pagesContainer {{ background-color: {v['BG_APP']}; }}
    QFrame#pageBody {{ background-color: {v['BG_APP']}; border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}
    QLabel#pageTitle {{ color: {v['TEXT']}; font-size: 18px; font-weight: bold; }}
    QLabel#pageHint {{ color: {v['TEXT_DIM']}; font-size: 12px; }}"""


def _qss_buttons(v: Dict[str, str]) -> str:
    """QSS 区块：通用按钮 + accent 角色按钮。"""
    return f"""
    /* 通用按钮 */
    QPushButton {{
        background-color: {v['BG_RAISED']}; color: {v['TEXT']};
        border: 1px solid {v['BORDER']}; border-radius: 6px; padding: 7px 14px;
    }}
    QPushButton:hover {{ background-color: {v['BORDER']}; }}
    QPushButton:pressed {{ background-color: {v['BG_DEEP']}; }}
    QPushButton:disabled {{ color: {v['TEXT_DIM']}; }}
    QPushButton[role="accent"] {{
        background-color: {v['ACCENT']}; color: #ffffff; border: none; border-radius: 6px;
    }}
    QPushButton[role="accent"]:hover {{ background-color: #6d28d9; }}
    QPushButton[role="accent"]:pressed {{ background-color: #5b21b6; }}"""


def _qss_inputs(v: Dict[str, str]) -> str:
    """QSS 区块：输入控件 + 列表。"""
    return f"""
    /* 输入控件 */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
        background-color: {v['BG_CHILD']}; color: {v['TEXT']};
        border: 1px solid {v['BORDER']}; border-radius: 6px; padding: 6px 10px;
        selection-background-color: {v['ACCENT']};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {v['ACCENT']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {v['BG_CHILD']}; color: {v['TEXT']};
        selection-background-color: {v['ACCENT']}; border: 1px solid {v['BORDER']};
    }}
    /* 列表 */
    QListWidget {{
        background-color: {v['BG_CHILD']}; border: 1px solid {v['BORDER']};
        border-radius: 6px; outline: 0;
    }}
    QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {v['BG_RAISED']}; }}
    QListWidget::item:selected {{ background-color: {v['ACCENT']}; color: #ffffff; }}"""


def _qss_toolbar(v: Dict[str, str]) -> str:
    """QSS 区块：工具栏/工具按钮 + 画布。"""
    return f"""
    /* 工具栏与工具按钮 */
    QFrame#toolbar {{ background-color: {v['BG_RAISED']}; border-radius: 8px; }}
    QPushButton[tool="true"] {{
        background-color: {v['BG_CHILD']}; border: 1px solid {v['BORDER']};
        border-radius: 6px; padding: 8px 12px; color: {v['TEXT']};
    }}
    QPushButton[tool="true"]:hover {{ border: 1px solid {v['ACCENT']}; }}
    QPushButton[tool="true"][active="true"] {{
        background-color: {v['ACCENT']}; border: 1px solid {v['ACCENT']}; color: #ffffff;
    }}
    /* 画布 */
    QGraphicsView {{ background-color: {v['BG_DEEP']}; border: 1px solid {v['BORDER']}; border-radius: 6px; }}"""


def _qss_groups(v: Dict[str, str]) -> str:
    """QSS 区块：分组框 + 标签页。"""
    return f"""
    /* 分组与标签页 */
    QGroupBox {{
        background-color: {v['BG_CHILD']}; border: 1px solid {v['BORDER']};
        border-radius: 8px; margin-top: 12px; padding: 10px;
    }}
    QGroupBox::title {{ color: {v['TEXT_DIM']}; subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QTabWidget::pane {{ border: 1px solid {v['BORDER']}; border-radius: 6px; }}
    QTabBar::tab {{
        background: {v['BG_CHILD']}; color: {v['TEXT_DIM']}; padding: 8px 16px;
        border: 1px solid {v['BORDER']}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    }}
    QTabBar::tab:selected {{ background: {v['BG_RAISED']}; color: {v['ACCENT2']}; }}"""


def _qss_statusbar(v: Dict[str, str]) -> str:
    """QSS 区块：底部状态栏（末块，保留结尾换行与缩进）。"""
    return f"""
    /* 状态栏 */
    QFrame#statusBar {{ background-color: {v['BG_CHILD']}; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; border-top: 1px solid {v['BG_DEEP']}; }}
    QLabel#statusText {{ color: {v['TEXT_DIM']}; padding: 4px 12px; }}
    QLabel#statusAccent {{ color: {v['ACCENT2']}; padding: 4px 12px; font-weight: bold; }}
    """


def _build_qss(theme: ThemeName) -> str:
    """按主题变量拼装完整 QSS（区块拼接顺序即原选择器顺序）。"""
    v = _NIGHT_VARS if theme == "night" else _DAYTIME_VARS

    def sub(text: str) -> str:
        for k, val in v.items():
            text = text.replace(f"${k}", val)
        return text

    qss = (
        _qss_base(v)
        + _qss_nav(v)
        + _qss_pages(v)
        + _qss_buttons(v)
        + _qss_inputs(v)
        + _qss_toolbar(v)
        + _qss_groups(v)
        + _qss_statusbar(v)
    )
    return sub(qss) + sub(_BASE_WIDGETS)


# 当前主题单例状态
_current: ThemeName = "night"


def resolve_theme(theme: str) -> ThemeName:
    """解析主题名（W4-T4 / P2-9）。

    - night / daytime 原样透传；
    - auto → 随系统配色（Qt≥6.5 QStyleHints.colorScheme：Light→daytime，
      Dark/Unknown/旧平台 → night 回退）。
    """
    if theme in ("night", "daytime"):
        return theme  # type: ignore[return-value]
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return "daytime"
        return "night"
    except Exception:
        return "night"


class ThemeManager:
    """主题管理器：应用与切换 night/daytime。"""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._theme: ThemeName = "night"

    @property
    def theme(self) -> ThemeName:
        return self._theme

    def apply(self, theme: str) -> None:
        """应用指定主题（auto 先解析；刷新 QSS + QPalette）。"""
        global _current
        resolved = resolve_theme(theme)
        self._theme = resolved
        _current = resolved
        self._app.setStyleSheet(_build_qss(resolved))
        self._apply_palette(resolved)

    def toggle(self) -> ThemeName:
        """在 night/daytime 之间切换，返回新主题。"""
        nxt: ThemeName = "daytime" if self._theme == "night" else "night"
        self.apply(nxt)
        return nxt

    @staticmethod
    def _apply_palette(theme: ThemeName) -> None:
        """同步 QPalette（部分原生控件不走 QSS）。"""
        v = _NIGHT_VARS if theme == "night" else _DAYTIME_VARS
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(v["BG_CHILD"]))
        pal.setColor(QPalette.ColorRole.Base, QColor(v["BG_CHILD"]))
        pal.setColor(QPalette.ColorRole.Text, QColor(v["TEXT"]))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(v["TEXT"]))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(v["ACCENT"]))
        QApplication.instance().setPalette(pal) if QApplication.instance() else None


def apply_theme(app: QApplication, theme: ThemeName = "night") -> ThemeManager:
    """便捷函数：创建 ThemeManager 并应用主题。"""
    mgr = ThemeManager(app)
    mgr.apply(theme)
    return mgr


def current_theme() -> ThemeName:
    """返回当前主题名。"""
    return _current


__all__ = ["ThemeManager", "ThemeName", "apply_theme", "current_theme", "resolve_theme"]
