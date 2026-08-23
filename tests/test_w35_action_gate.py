"""W35（v5 P2-N1 收口）：action_allowed 消费接线——登记≠消费的终局修复。

背景：W29/W30/W33/W34 向 _ACTION_MATRIX 登记 4 个动作但生产调用点 0
处（v5 攻方复核实锤）。本波：core/session 增角色持有 + permissions.check_action
统一门控（拒绝→文案+审计）+ 三个按钮入口消费 + 登录单点设置角色。
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]


# ============================== 1. session 角色持有 ============================== #


@pytest.mark.unit
def test_session_role_roundtrip():
    from core import session

    session.reset_current_role()
    assert session.get_current_role() is None  # 未登录宽容态
    session.set_current_role("engineer")
    assert session.get_current_role() == "engineer"
    session.reset_current_role()
    assert session.get_current_role() is None


# ============================== 2. check_action 门控 ============================== #


@pytest.mark.unit
def test_check_action_permits_unlogged_and_registered(monkeypatch):
    """未登录宽容放行；已登记动作按矩阵判定（三角色全允许的动作）。"""
    from core import session
    from gui.core.permissions import check_action

    session.reset_current_role()
    assert check_action("predict.batch_infer") is None, "未登录应宽容放行"

    session.set_current_role("operator")
    try:
        assert check_action("predict.batch_infer") is None, "operator×batch_infer 应放行"
        assert check_action("label.batch_prelabel") is None
    finally:
        session.reset_current_role()


@pytest.mark.unit
def test_check_action_denies_unregistered_with_audit(monkeypatch):
    """未登记动作拒绝：返回文案 + access_denied 审计（拒绝路径留痕）。"""
    from core import session, audit_logger
    from gui.core.permissions import check_action

    denied_log = []
    monkeypatch.setattr(
        audit_logger, "log_access_denied", lambda **kw: denied_log.append(kw)
    )
    session.set_current_role("engineer")
    try:
        msg = check_action("dangerous.unregistered")
        assert msg is not None and "无权限" in msg
        assert denied_log and denied_log[0].get("page") == "dangerous.unregistered"
        assert denied_log[0].get("role") == "engineer"
    finally:
        session.reset_current_role()


# ============================== 3. 三个按钮入口消费 ============================== #


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)


@pytest.mark.unit
def test_label_batch_prelabel_denied(qapp, monkeypatch):
    """标注页批量预标注：动作拒绝 → 早退 + 状态栏文案。"""
    from gui.pages.label import page as label_mod
    from gui.pages.label.page import LabelPage

    monkeypatch.setattr(
        label_mod, "check_action",
        lambda action: "无权限执行该操作" if action == "label.batch_prelabel" else None,
    )
    page = LabelPage()
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    picked = []

    def _sentinel(*a, **k):
        picked.append(1)
        return ""

    monkeypatch.setattr(label_mod, "pick_directory", _sentinel)
    page._batch_prelabel()
    assert picked == [], "拒绝路径不得触目录对话框"
    assert any("无权限" in t for t, _ in page._msgs), page._msgs


@pytest.mark.unit
def test_predict_batch_infer_denied(qapp, monkeypatch):
    """推理页批量推理：动作拒绝 → 早退 + 状态栏文案。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage

    monkeypatch.setattr(
        pred_mod, "check_action",
        lambda action: "无权限执行该操作" if action == "predict.batch_infer" else None,
    )
    page = PredictPage()
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    picked = []

    def _sentinel(*a, **k):
        picked.append(1)
        return ""

    monkeypatch.setattr(pred_mod, "pick_directory", _sentinel)
    page._engine = object()  # 引擎在场（证明早退发生在动作门控而非引擎预检）
    page._batch_infer()
    assert picked == [], "拒绝路径不得触目录对话框"
    assert any("无权限" in t for t, _ in page._msgs), page._msgs


@pytest.mark.unit
def test_video_super_denied(qapp, monkeypatch):
    """视频超分：动作拒绝 → 早退（不触视频文件对话框）。"""
    from gui.pages.predict import page as pred_mod
    from gui.pages.predict.page import PredictPage
    from gui.pages.predict import video_super_actions as vsa
    from core.interfaces_supervised import TaskType

    monkeypatch.setattr(
        vsa, "check_action",
        lambda action: "无权限执行该操作" if action == "predict.video_super" else None,
    )
    page = PredictPage()
    page._engine = object()
    # 切到 SUPER 任务（越过任务预检，证明早退在动作门控）
    idx = next(i for i in range(page.cmb_task.count())
               if page.cmb_task.itemData(i) is TaskType.SUPER)
    page.cmb_task.setCurrentIndex(idx)
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    picked = []

    def _sentinel(*a, **k):
        picked.append(1)
        return ""

    monkeypatch.setattr(vsa, "pick_open_file", _sentinel)
    page._video_super()
    assert picked == [], "拒绝路径不得触文件对话框"
    assert any("无权限" in t for t, _ in page._msgs), page._msgs


# ============================== 4. 登录单点接线 ============================== #


@pytest.mark.unit
def test_main_wires_session_role_on_login():
    """gui/main 登录成功处理器单点设置 session 角色（与 win.set_role 同点）。"""
    src = (REPO_ROOT / "gui" / "main.py").read_text(encoding="utf-8")
    assert "set_current_role" in src, "登录处理器须同步 session 角色（动作门控数据源）"
