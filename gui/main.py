"""AutoVisionAgent 桌面入口（FR-D）—— M2 完整版。

运行：python -m gui.main

组装：QApplication → 主题(night) → MainWindow → 注册 10 页（全实装）→ show。
所有页面 status_changed → 主壳状态栏；language_changed → retranslate()。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from PySide6.QtWidgets import QApplication

from gui.core.i18n import current_language, set_language, tr
from gui.core.shell import MainWindow
from gui.core.theme import ThemeManager
from gui.pages import LabelPage
from gui.pages.data_manage import DataManagePage
from gui.pages.train import TrainPage
from gui.pages.predict import PredictPage
from gui.pages.project import ProjectPage
from gui.pages.login import LoginPage
from gui.pages.home import HomePage
from gui.pages.eval_ import EvalPage
from gui.pages.deploy import DeployPage
from gui.pages.flaw_gen import FlawGenPage
from gui.pages.settings import SettingsPage


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

    # ---- 登录成功 → 跳转主页 ----
    login_page.login_success.connect(
        lambda _u, _r: win.select("home")
    )

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


def _load_user_settings() -> dict:
    """从 configs/user_settings.json 加载持久化设置。

    返回字典，可能包含 theme/language/device/precision 等键。
    文件不存在时返回空字典（使用代码默认值）。
    """
    import json
    import os
    config_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "configs")
    settings_path = os.path.join(config_dir, "user_settings.json")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    setup_logging()

    # 加载持久化设置（主题/语言），回退到默认值
    settings = _load_user_settings()
    set_language(settings.get("language", "ch_CN"))

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AutoVisionAgent")

    theme_mgr = ThemeManager(app)
    theme_mgr.apply(settings.get("theme", "night"))

    win = build_window()
    win.attach_theme(theme_mgr)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
