"""主窗口框架（PyDracula 风格侧边导航）。
无边框圆角窗口 + 侧边导航栏 + QStackedWidget 页面栈 + 底部状态栏。
提供 add_page / select / set_status 等接口供 gui.main 组装。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from gui.core.permissions import page_allowed

# 窗口控制按钮样式
_BTN_STYLE = """
QPushButton {
    background: transparent; border: none; border-radius: 4px;
    min-width: 36px; max-width: 36px; min-height: 28px; max-height: 28px;
    font-size: 14px; color: #94a3b8;
}
QPushButton:hover { background: #3f4452; color: #e2e8f0; }
QPushButton#btn_close:hover { background: #ef4444; color: #ffffff; }
"""

# 退出停机预算（W15-J4 / P2-3）：确认退出后全部等待有界——正常路径毫秒级
# 返回，最坏情况合计 3s 量级上限（1.0s 注册表 join 总预算 + 1.5s 单个
# TrainWorker wait + 0.5s×2 缩略图池 waitForDone），任何一路都不得无限等。
_EXIT_JOBS_TIMEOUT_S = 1.0
_EXIT_WORKER_WAIT_MS = 1500
_EXIT_POOL_WAIT_MS = 500


class MainWindow(QMainWindow):
    """主窗口：无边框 + 侧边导航 + 页面栈 + 状态栏。"""

    language_changed = Signal(str)
    theme_changed = Signal(str)

    def __init__(self, title: str = "AutoVisionAgent") -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(1200, 760)
        self._prev_geometry = None  # 最大化前保存位置/尺寸

        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._theme_manager = None
        # W29 角色消费（W39 反转）：None=未登录 → operator 最小集
        # （原宽容态全可见废弃，v6 P2-3 收口）
        self._active_role: str | None = None

        self._build_shell(title)

    # ============================== UI ============================== #

    def _build_shell(self, title: str) -> None:
        """构建无边框外壳（侧边栏 + 标题栏 + 页面栈 + 状态栏）。"""
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left_lay = self._build_left_menu(title)
        self._build_top_bar()
        self._build_sidebar_nav(left_lay, root)
        self._build_right_panel(root)

    def _build_left_menu(self, title: str) -> QVBoxLayout:
        """侧边导航容器 + LOGO（返回侧栏布局，供导航区续接）。"""
        self._left_menu = QFrame()
        self._left_menu.setObjectName("leftMenu")
        self._left_menu.setFixedWidth(200)
        left_lay = QVBoxLayout(self._left_menu)
        left_lay.setContentsMargins(0, 10, 0, 0)
        left_lay.setSpacing(2)

        # LOGO
        logo = QLabel(f"  {title}")
        logo.setObjectName("titleLogo")
        logo.setFixedHeight(48)
        left_lay.addWidget(logo)
        return left_lay

    def _build_top_bar(self) -> None:
        """顶部窗口控制栏（关闭/最小化/最大化）。"""
        self._top_bar = QFrame()
        self._top_bar.setFixedHeight(32)
        self._top_bar.setObjectName("topBar")
        tb_lay = QHBoxLayout(self._top_bar)
        tb_lay.setContentsMargins(0, 0, 0, 0)
        tb_lay.setSpacing(0)
        tb_lay.addStretch()

        btn_min = QPushButton("–")
        btn_min.setToolTip("最小化")
        btn_min.setStyleSheet(_BTN_STYLE)
        btn_min.clicked.connect(self.showMinimized)
        tb_lay.addWidget(btn_min)

        btn_max = QPushButton("□")
        btn_max.setToolTip("最大化/还原")
        btn_max.setStyleSheet(_BTN_STYLE)
        btn_max.clicked.connect(self._toggle_maximize)
        self._btn_max = btn_max
        tb_lay.addWidget(btn_max)

        btn_close = QPushButton("✕")
        btn_close.setToolTip("关闭")
        btn_close.setObjectName("btn_close")
        btn_close.setStyleSheet(_BTN_STYLE)
        btn_close.clicked.connect(self.close)
        tb_lay.addWidget(btn_close)

    def _build_sidebar_nav(self, left_lay: QVBoxLayout, root: QHBoxLayout) -> None:
        """侧边栏下半部：导航按钮容器 + 语言/主题切换，并挂到主布局。"""
        # 导航按钮容器（动态添加）
        self._nav_container = QWidget()
        self._nav_lay = QVBoxLayout(self._nav_container)
        self._nav_lay.setContentsMargins(0, 0, 0, 0)
        self._nav_lay.setSpacing(0)
        left_lay.addWidget(self._nav_container)
        left_lay.addStretch()

        # 语言切换按钮
        self._lang_btn = QPushButton("  中文/EN")
        self._lang_btn.setProperty("nav", True)
        self._lang_btn.clicked.connect(self._toggle_language)
        left_lay.addWidget(self._lang_btn)

        # 主题切换按钮
        self._theme_btn = QPushButton("  🌙/☀")
        self._theme_btn.setProperty("nav", True)
        self._theme_btn.setToolTip("Toggle Theme")
        self._theme_btn.clicked.connect(self._toggle_theme)
        left_lay.addWidget(self._theme_btn)

        root.addWidget(self._left_menu)

    def _build_right_panel(self, root: QHBoxLayout) -> None:
        """右侧面板：标题栏 + 页面栈 + 状态栏。"""
        right = QFrame()
        right.setObjectName("bgApp")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        right_lay.addWidget(self._top_bar)

        self._stack = QStackedWidget()
        self._stack.setObjectName("pagesContainer")
        right_lay.addWidget(self._stack, 1)

        self._build_status_bar(right_lay)

        root.addWidget(right, 1)

    def _build_status_bar(self, right_lay: QVBoxLayout) -> None:
        """底部状态栏：状态文本 + 强调文本。"""
        self._status_bar = QFrame()
        self._status_bar.setObjectName("statusBar")
        self._status_bar.setFixedHeight(32)
        sb_lay = QHBoxLayout(self._status_bar)
        sb_lay.setContentsMargins(12, 0, 12, 0)
        self._status_text = QLabel("就绪")
        self._status_text.setObjectName("statusText")
        self._status_accent = QLabel("")
        self._status_accent.setObjectName("statusAccent")
        sb_lay.addWidget(self._status_text)
        sb_lay.addStretch()
        sb_lay.addWidget(self._status_accent)
        right_lay.addWidget(self._status_bar)

    # ============================== 公开接口 ============================== #

    def add_page(
        self, key: str, icon: str, title: str, widget: QWidget
    ) -> None:
        """注册页面到侧边导航 + 页面栈。"""
        self._pages[key] = widget
        self._stack.addWidget(widget)

        btn = QPushButton(f"  {title}")
        btn.setProperty("nav", True)
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self.select(key))
        self._nav_buttons[key] = btn
        self._nav_lay.addWidget(btn)

    def select(self, key: str) -> None:
        """切换到指定页面（W39 反转：未登录=operator 最小集，拒绝即审计）。"""
        if key not in self._pages:
            return
        if not page_allowed(self._active_role or "", key):
            # 操作护栏非安全边界（见 gui/core/permissions.py）——拒绝即
            # 显式反馈 + 审计留痕，不留静默路径
            self.set_status(tr("无权限访问该页面"), key)
            self._audit_access_denied(key)
            return
        widget = self._pages[key]
        self._stack.setCurrentWidget(widget)

        # 更新导航按钮选中态
        for k, btn in self._nav_buttons.items():
            btn.setProperty("selected", k == key)
            btn.style().polish(btn)

    # ============================== 角色门控（W29） ============================== #

    def set_role(self, role: str | None) -> None:
        """设置当前会话角色并即时同步导航可见性。

        None=未登录（宽容态，全可见）；登录成功处调用（gui/main.py）。
        """
        self._active_role = role
        self._apply_nav_visibility()

    def _apply_nav_visibility(self) -> None:
        """按角色过滤导航按钮可见性（登录页恒可见；W39：未登录=operator 最小集）。"""
        role = self._active_role
        for key, btn in self._nav_buttons.items():
            btn.setVisible(page_allowed(role or "", key))

    def _audit_access_denied(self, page_key: str) -> None:
        """拒绝访问审计（失败不阻塞导航反馈）。"""
        try:
            from core.audit_logger import log_access_denied
            from core.session import get_current_user

            log_access_denied(
                user=get_current_user(),
                role=self._active_role or "",
                page=page_key,
            )
        except (ImportError, OSError):
            import logging

            logging.getLogger(__name__).exception("拒绝访问审计写入失败")

    def set_status(self, text: str, accent: str = "") -> None:
        """更新状态栏。"""
        self._status_text.setText(text)
        self._status_accent.setText(accent)

    def attach_theme(self, theme_manager) -> None:
        """绑定主题管理器（用于切换时刷新）。"""
        self._theme_manager = theme_manager

    def _toggle_theme(self) -> None:
        """切换暗/亮主题。"""
        if self._theme_manager is None:
            return
        # 使用 ThemeManager.theme 属性获取当前主题（而非错误属性名 _current_theme）
        current = self._theme_manager.theme
        new_theme = "daytime" if current == "night" else "night"
        self._theme_manager.apply(new_theme)
        self.theme_changed.emit(new_theme)

    def _toggle_language(self) -> None:
        """切换中英文。"""
        from gui.core.i18n import current_language, set_language

        new_lang = "en_US" if current_language() == "ch_CN" else "ch_CN"
        set_language(new_lang)
        self.language_changed.emit(new_lang)

    def _toggle_maximize(self) -> None:
        """最大化/还原窗口。"""
        if self.isMaximized():
            self.showNormal()
            if self._prev_geometry:
                self.setGeometry(self._prev_geometry)
            self._btn_max.setText("□")
        else:
            self._prev_geometry = self.geometry()
            self.showMaximized()
            self._btn_max.setText("❐")

    # ============================== 窗口拖动 ============================== #

    def mousePressEvent(self, event) -> None:
        """无边框窗口拖动支持。"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        """无边框窗口拖动。"""
        if hasattr(self, "_drag_pos") and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    # ============================== 优雅退出 ============================== #

    def _collect_active_busy(self) -> tuple[list, list, list]:
        """活跃任务三路并集检测（W18 自 closeEvent 抽出，v3 AC-012）。

        ① gui.core.jobs 注册表（run_job 任务真相源）；② 各页 TrainWorker
        (QThread) isRunning；③ 批量按钮禁用约定页（未迁移过渡期——按钮名
        btn_batch/_btn_batch 双名兼容，P2-2）。
        """
        from gui.core import jobs

        registry_names = jobs.active_jobs()
        running_worker_keys: list = []
        batch_keys: list = []
        for key, widget in self._pages.items():
            worker = getattr(widget, "_worker", None)
            if worker is not None and hasattr(worker, "isRunning") and worker.isRunning():
                running_worker_keys.append(key)
            if hasattr(widget, "_batch_cancel"):
                for attr in ("_btn_batch", "btn_batch"):
                    batch_btn = getattr(widget, attr, None)
                    if batch_btn is not None and not batch_btn.isEnabled():
                        batch_keys.append(key)
                        break
        return registry_names, running_worker_keys, batch_keys

    def closeEvent(self, event) -> None:
        """窗口关闭事件：检查活动任务 + 有界停机 + 释放资源。

        W15-J4（P2-2/P2-3）：活跃检测以 gui.core.jobs 注册表为真相源
        （run_job 统一调度的全部后台任务可观测，不再依赖逐页猜属性名），
        兼容 TrainWorker(QThread) isRunning 与批量按钮禁用两条既有约定
        （未迁移页面过渡期）；确认退出后 stop/wait 全部有界（见模块头
        _EXIT_* 常量），随后按原顺序清引擎缓存 → 刷审计日志。
        """
        import logging

        from gui.core.i18n import tr
        _logger = logging.getLogger(__name__)

        from gui.core import jobs

        # ---- 活跃检测（三路并集，W18 抽为 _collect_active_busy）----
        registry_names, running_worker_keys, batch_keys = self._collect_active_busy()

        if registry_names or running_worker_keys or batch_keys:
            from PySide6.QtWidgets import QMessageBox

            names = "、".join(dict.fromkeys(registry_names))
            if names:
                detail = tr("有正在进行的后台任务：") + names + "\n"
            else:
                detail = tr("有正在进行的操作（训练/推理）。\n")
            reply = QMessageBox.question(
                self, tr("确认退出"),
                detail + tr("确定要退出吗？未保存的数据可能丢失。"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

            # ---- 确认退出：有界停机（P2-3）----
            still = jobs.request_stop_all(timeout_s=_EXIT_JOBS_TIMEOUT_S)
            if still:
                _logger.warning(
                    "退出停机超时，未退出的后台任务：%s", "、".join(still)
                )

            for key in running_worker_keys:
                worker = getattr(self._pages.get(key), "_worker", None)
                if worker is None or not worker.isRunning():
                    continue  # stop 期间已自行退出
                stop = getattr(worker, "stop", None)
                if callable(stop):
                    stop()
                do_wait = getattr(worker, "wait", None)
                if callable(do_wait):
                    do_wait(_EXIT_WORKER_WAIT_MS)
                if worker.isRunning():
                    # W18（P2-3 退出链补完）：stop/wait 超时不得静默 continue
                    # ——留痕"将随进程退出被强制终止、可能丢失未保存进度"。
                    _logger.warning(
                        "训练线程(%s)未在 %dms 内停止，将随进程退出被强制"
                        "终止，可能丢失未保存进度", key, _EXIT_WORKER_WAIT_MS,
                    )

            for widget in self._pages.values():
                pool = getattr(widget, "_thumb_pool", None)
                if pool is None:
                    continue
                try:
                    pool.clear()  # 丢弃仍在排队的缩略图任务
                    pool.waitForDone(_EXIT_POOL_WAIT_MS)
                except Exception:
                    _logger.debug("等待缩略图线程池退出时出错", exc_info=True)

        # 释放引擎缓存（GPU 显存）——registry 直连为 GUI 正式形态（v3 P2-7）
        try:
            from models.supervised.registry import get_default_registry
            get_default_registry().clear_cache()
        except Exception:
            _logger.debug("清理引擎缓存时出错", exc_info=True)

        # 退出前显式刷盘审计日志（缓冲未满 _buffer_max 时不落盘 → 必须显式 flush）
        try:
            from core.audit_logger import get_audit_logger
            get_audit_logger().flush()
        except Exception:
            _logger.warning("退出前刷写审计日志失败", exc_info=True)

        _logger.info("应用正常退出")
        event.accept()


__all__ = ["MainWindow"]
