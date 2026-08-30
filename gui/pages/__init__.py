"""AutoVisionAgent 功能页（对标 SKolpha 页面树）。

M2 完整版：11 页全部实装（era-2 新增 flaw_gen 缺陷生成页，W14 P2-12 补入注册表）。
登录 + 主页 + 标注 + 数据管理 + 训练 + 推理 + 评估 + 发布 + 缺陷生成 + 项目管理 + 设置

页面清单唯一真源：gui/main.py 必须经本注册表导入（tests/test_gui.py 守卫）。
"""
from gui.pages.data_manage import DataManagePage
from gui.pages.deploy import DeployPage
from gui.pages.eval_ import EvalPage
from gui.pages.flaw_gen import FlawGenPage
from gui.pages.home import HomePage
from gui.pages.label.page import LabelPage
from gui.pages.login import LoginPage
from gui.pages.predict import PredictPage
from gui.pages.project import ProjectPage
from gui.pages.settings import SettingsPage
from gui.pages.train import TrainPage

__all__ = [
    "LabelPage",
    "DataManagePage",
    "TrainPage",
    "PredictPage",
    "ProjectPage",
    "LoginPage",
    "HomePage",
    "EvalPage",
    "DeployPage",
    "FlawGenPage",
    "SettingsPage",
]
