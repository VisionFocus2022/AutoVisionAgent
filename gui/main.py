"""AutoVisionAgent 桌面入口（FR-D）—— M2 完整版。

运行：python -m gui.main

组装：单实例锁（P2-14）→ QApplication → 主题(night) → MainWindow →
注册 11 页（全实装，页面导入一律经 gui.pages 注册表）→ show。
所有页面 status_changed → 主壳状态栏；language_changed → retranslate()。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import tempfile

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.core.i18n import current_language, set_language, tr
from gui.core.settings_io import load_user_settings
from gui.core.shell import MainWindow
from gui.core.theme import ThemeManager
from gui.pages import (
    DataManagePage,
    DeployPage,
    EvalPage,
    FlawGenPage,
    HomePage,
    LabelPage,
    LoginPage,
    PredictPage,
    ProjectPage,
    SettingsPage,
    TrainPage,
)

SINGLE_INSTANCE_LOCK_FILENAME = "autovisionagent-single-instance.lock"

# W26：打包态 matplotlib 后端确定性——tkinter 已被 spec 排除，Agg 依赖
# ImportError 回退而非契约；在任何引擎（ultralytics 链）加载前显式钉死，
# 防 matplotlib 升级改变回退行为。引擎加载全部惰性晚于此行。
os.environ.setdefault("MPLBACKEND", "Agg")

# 进程生命周期内持有 QLockFile 引用，防止对象被回收导致锁提前释放
_SINGLE_INSTANCE_LOCK: QLockFile | None = None


def default_single_instance_lock_path() -> str:
    """单实例锁文件路径：%TEMP% 下（Windows 按用户隔离，打包/源码运行均可写）。"""
    return os.path.join(tempfile.gettempdir(), SINGLE_INSTANCE_LOCK_FILENAME)


def acquire_single_instance_lock(lock_path: str | None = None) -> bool:
    """尝试获取单实例互斥锁（QLockFile）。

    QLockFile 自带陈旧锁恢复：持锁进程死亡（含 UIA taskkill）后，
    其 PID 检测会判定锁陈旧并自动清除，新实例可正常启动。

    Args:
        lock_path: 锁文件路径（测试注入用）；默认 %TEMP% 下。

    Returns:
        True: 获取成功（本进程持锁至退出）。
        False: 锁已被占用——已有另一实例在运行（同进程重复 acquire 亦为 False）。
    """
    global _SINGLE_INSTANCE_LOCK
    path = lock_path or default_single_instance_lock_path()
    lock = QLockFile(path)
    # PySide6 tryLock 无默认参：0 = 不阻塞（与 C++ Qt 默认一致）
    if lock.tryLock(0):
        _SINGLE_INSTANCE_LOCK = lock
        return True
    return False


# W19（v3 第三波 FR-5.4）：敏感信息兜底过滤——"初始密码: XXX"字样在
# handler 输出前的最后防线（正常路径 FR-5.1 已不落明文，此为防回归兜底）
_SENSITIVE_REDACT_PATTERN = re.compile(r"初始密码[:：]\s*\S+")


class SensitiveRedactFilter(logging.Filter):
    """把 record.msg 中"初始密码: XXX"字样掩码为"初始密码: [REDACTED]"。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_REDACT_PATTERN.sub(
                "初始密码: [REDACTED]", record.msg
            )
        return True


def _install_sensitive_redact_filter(target: logging.Logger) -> None:
    """把 SensitiveRedactFilter 装到目标 logger 的全部 handler（幂等）。"""
    for handler in target.handlers:
        if not any(isinstance(f, SensitiveRedactFilter) for f in handler.filters):
            handler.addFilter(SensitiveRedactFilter())


def setup_logging() -> None:
    """初始化日志系统：控制台 + RotatingFileHandler。

    读取 core.config.LoggingConfig 设置；若配置不可用则使用默认值。
    必须在 QApplication 创建之前调用，确保所有模块的 logger 生效。
    """
    try:
        from core.config import get_config
        cfg = get_config().logging
        level = getattr(logging, cfg.level.upper(), logging.INFO)
        fmt = cfg.format
        log_dir = cfg.log_dir
        max_bytes = cfg.max_file_size_mb * 1024 * 1024
        backup = cfg.backup_count
    except (AttributeError, TypeError, ValueError):
        level = logging.INFO
        fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        log_dir = "./logs"
        max_bytes = 10 * 1024 * 1024
        backup = 5

    # W23（v4 P2-1c）：测试态/生产态日志隔离——AVA_LOG_DIR 显式指定时优先于
    # config 的 CWD 相对 ./logs（测试进程经根 conftest setdefault 指向会话
    # 临时目录；生产/打包 exe 不设 env，行为不变）。
    env_log_dir = os.environ.get("AVA_LOG_DIR")
    if env_log_dir:
        log_dir = env_log_dir
    os.makedirs(log_dir, exist_ok=True)
    formatter = logging.Formatter(fmt)

    # 根 logger
    root = logging.getLogger()
    root.setLevel(level)

    # RotatingFileHandler
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "autovision.log"),
        maxBytes=max_bytes,
        backupCount=backup,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台输出（开发模式 / console=True 打包模式）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # W19（v3 第三波 FR-5.4）：root 全部 handler 装敏感兜底过滤
    _install_sensitive_redact_filter(root)

    logging.getLogger(__name__).info("日志系统已初始化")


def build_window() -> MainWindow:
    """构造主窗口并注册全部实装页面。"""
    win = MainWindow("AutoVisionAgent")

    # ---- 实例化所有页面 ----
    login_page = LoginPage()
    home_page = HomePage()
    label_page = LabelPage()
    data_page = DataManagePage()
    train_page = TrainPage()
    predict_page = PredictPage()
    eval_page = EvalPage()
    deploy_page = DeployPage()
    flaw_gen_page = FlawGenPage()
    project_page = ProjectPage()
    settings_page = SettingsPage()

    # ---- 状态栏联动 ----
    def _connect_status(page) -> None:
        page.status_changed.connect(
            lambda text, accent: win.set_status(text, accent)
        )

    all_pages = [
        login_page, home_page, label_page, data_page,
        train_page, predict_page, eval_page, deploy_page,
        flaw_gen_page, project_page, settings_page,
    ]
    for page in all_pages:
        _connect_status(page)

    # ---- 项目打开 → 通知工作页 ----
    project_page.project_opened.connect(data_page.set_project_dir)
    project_page.project_opened.connect(predict_page.set_project_dir)

    # ---- 项目打开 → 刷新仪表盘统计 ----
    def _refresh_home_stats(project_dir: str) -> None:
        import os
        img_count = 0
        model_count = 0
        _img_exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
        _model_exts = (".pt", ".pth", ".onnx", ".ckpt")
        for root, _dirs, files in os.walk(project_dir):
            for f in files:
                ext = f.lower()
                if ext.endswith(_img_exts):
                    img_count += 1
                elif ext.endswith(_model_exts):
                    model_count += 1
        # GPU 状态
        gpu_status = "—"
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_status = f"✓ {gpu_name[:20]}"
            else:
                gpu_status = "CPU"
        except ImportError:
            pass
        home_page.update_stats(
            projects=1, images=img_count, models=model_count, gpu=gpu_status,
        )

    project_page.project_opened.connect(_refresh_home_stats)

    # ---- 主页导航 ----
    home_page.navigate.connect(win.select)

    # ---- 主页最近项目/检测历史刷新（W28 生产接线，见 _wire_home_refresh）----
    _wire_home_refresh(win, home_page, login_page, project_page)

    # ---- 语言切换 → 全部页面 retranslate ----
    win.language_changed.connect(
        lambda _lang: [_p.retranslate() for _p in all_pages]
    )

    # ---- 注册页面（侧边导航顺序）----
    win.add_page("login", "login", tr("登录"), login_page)
    win.add_page("home", "home", tr("主页"), home_page)
    win.add_page("label", "label", tr("标注"), label_page)
    win.add_page("data_manage", "data", tr("数据管理"), data_page)
    win.add_page("train", "train", tr("训练"), train_page)
    win.add_page("predict", "predict", tr("推理"), predict_page)
    win.add_page("eval", "eval", tr("评估"), eval_page)
    win.add_page("deploy", "deploy", tr("发布"), deploy_page)
    win.add_page("flaw_gen", "flaw_gen", tr("缺陷生成"), flaw_gen_page)
    win.add_page("project", "project", tr("项目管理"), project_page)
    win.add_page("settings", "settings", tr("设置"), settings_page)

    # 默认进登录页
    win.select("login")
    return win


def _wire_home_refresh(win, home_page, login_page, project_page) -> None:
    """主页最近项目/检测历史的生产接线（W28）。

    refresh_recent/refresh_history 此前无任何生产调用方——最近项目列表
    恒空、历史统计恒旧。两触发点：登录成功（进主页前）与项目打开。
    根目录经 resolve_base_root 单源（设置页 workspace 可配）。
    """
    from project.paths import resolve_base_root

    def _refresh_home_lists() -> None:
        try:
            home_page.refresh_recent(resolve_base_root())
        except (OSError, ValueError, RuntimeError):
            logging.getLogger(__name__).warning(
                "刷新最近项目列表失败", exc_info=True
            )
        home_page.refresh_history()

    def _on_login_success(_username: str, _role: str) -> None:
        # 先切页再延一拍刷新：登录槽内同步走磁盘 IO 会拖长 login→home
        # 切换（UIA 以「登录按钮从树中消失」为硬校验，随后导航点击与
        # 槽尾执行竞争——实测同步刷新致导航点击失效 4/4，singleShot 0
        # 解耦后恢复）。功能不变：主页入场即可见最新列表。
        win.select("home")
        QTimer.singleShot(0, _refresh_home_lists)

    login_page.login_success.connect(_on_login_success)
    project_page.project_opened.connect(lambda _dir: _refresh_home_lists())


def _load_user_settings() -> dict:
    """从 configs/user_settings.json 加载持久化设置（W13 C1 收敛到 settings_io）。

    返回字典，可能包含 theme/language/device/precision 等键。
    文件不存在时返回空字典（使用代码默认值）。
    """
    return load_user_settings()


def main() -> int:
    setup_logging()

    # 加载持久化设置（主题/语言），回退到默认值
    settings = _load_user_settings()
    set_language(settings.get("language", "ch_CN"))

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AutoVisionAgent")

    # 单实例互斥（P2-14）：双开会导致 user_settings.json 双写与
    # RotatingFileHandler 同一日志文件轮转竞争
    if not acquire_single_instance_lock():
        QMessageBox.warning(
            None,
            tr("提示"),
            tr("AutoVisionAgent 已在运行，请勿重复启动。"),
        )
        return 1

    theme_mgr = ThemeManager(app)
    theme_mgr.apply(settings.get("theme", "night"))

    win = build_window()
    win.attach_theme(theme_mgr)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
