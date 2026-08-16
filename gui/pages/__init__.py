"""AutoVisionAgent 功能页（对标 SKolpha 页面树）。

M2 完整版：10 页全部实装。
登录 + 主页 + 标注 + 数据管理 + 训练 + 推理 + 评估 + 发布 + 项目管理 + 设置
"""
from gui.pages.label.page import LabelPage
from gui.pages.data_manage import DataManagePage
from gui.pages.train import TrainPage
from gui.pages.predict import PredictPage
from gui.pages.project import ProjectPage
from gui.pages.login import LoginPage
from gui.pages.home import HomePage
from gui.pages.eval_ import EvalPage
from gui.pages.deploy import DeployPage
from gui.pages.settings import SettingsPage

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
    "SettingsPage",
]
