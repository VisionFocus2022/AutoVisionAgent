"""W35（v5 P2-N1 收口）：action_allowed 消费接线——登记≠消费的终局修复。

背景：W29-W34 向 _ACTION_MATRIX 登记 3 个动作但生产调用点 0 处
（v5 攻方复核实锤；W39 增 data_manage.batch_label_edit 共 4 个）。
本波：core/session 增角色持有 + permissions.check_action 统一门控
（拒绝→文案+审计）+ 三个按钮入口消费 + 登录单点设置角色。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
    """未登录按 operator 动作集判定（W39 反转；已登记动作 operator 全允许）。"""
    from core import session
    from gui.core.permissions import check_action

    session.reset_current_role()
    assert check_action("predict.batch_infer") is None, "未登录×已登记(operator 允许) 应放行"

    session.set_current_role("operator")
    try:
        assert check_action("predict.batch_infer") is None, "operator×batch_infer 应放行"
        assert check_action("label.batch_prelabel") is None
    finally:
        session.reset_current_role()


@pytest.mark.unit
def test_check_action_unlogged_follows_operator_matrix(monkeypatch):
    """W39 反转（v6 P2-3）：未登录 × 未登记动作 → 拒绝 + 审计留痕。

    原宽容态「未登录全放行」废弃——与导航未登录=operator 最小集同语义。
    """
    from core import session
    from gui.core.permissions import check_action

    session.reset_current_role()
    try:
        denied = check_action("unregistered_action_w39")
        assert denied is not None, "未登录×未登记动作应拒绝（operator 矩阵）"
    finally:
        session.reset_current_role()


@pytest.mark.unit
def test_check_action_denies_unregistered_with_audit(monkeypatch):
    """未登记动作拒绝：返回文案 + access_denied 审计（拒绝路径留痕）。"""
    from core import audit_logger, session
    from gui.core.permissions import check_action

    denied_log = []
    monkeypatch.setattr(
        audit_logger, "log_access_denied", lambda **kw: denied_log.append(kw)
    )
    session.set_current_role("engineer")
    try:
        msg = check_action("dangerous.unregistered")
        assert msg is not None and "无权限" in msg
        # W39（v6 P3-2）：动作 id 以 action: 前缀入 page 字段——与导航拒绝
        # 的纯 page id（"settings"）在审计流内可区分
        assert denied_log and denied_log[0].get("page") == "action:dangerous.unregistered"
        assert denied_log[0].get("role") == "engineer"
    finally:
        session.reset_current_role()


# ============================== 3. 三个按钮入口消费 ============================== #


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


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
    from core.interfaces_supervised import TaskType
    from gui.pages.predict import video_super_actions as vsa
    from gui.pages.predict.page import PredictPage

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
def test_main_wires_session_role_on_login(qapp):
    """登录成功 → session 角色与 win.set_role 同点单点设置（行为化——
    W39·v6 P3-10：原为子串存在性断言，删调用留 import 仍绿）。"""
    import types

    from PySide6.QtCore import QObject, Signal

    from core import session
    from gui.main import _wire_home_refresh

    class _FakeLogin(QObject):
        login_success = Signal(str, str)

    class _FakeProject(QObject):
        project_opened = Signal(str)

    class _Win:
        def __init__(self):
            self.roles = []
            self.selected = None

        def set_role(self, role):
            self.roles.append(role)

        def select(self, key):
            self.selected = key

    win = _Win()
    login, proj = _FakeLogin(), _FakeProject()
    home = types.SimpleNamespace(
        refresh_recent=lambda *_a, **_k: None,
        refresh_history=lambda: None,
    )
    _wire_home_refresh(win, home, login, proj)

    session.reset_current_role()
    try:
        login.login_success.emit("alice", "operator")
        assert session.get_current_role() == "operator", (
            "session 角色须随登录成功设置（动作门控数据源）"
        )
        assert win.roles == ["operator"], "导航角色须同点设置（同源不漂移）"
        assert win.selected == "home", "登录后应切回主页"
    finally:
        session.reset_current_role()
        # 排水 0ms singleShot（_refresh_home_lists），防定时器泄漏到后续测试
        qapp.processEvents()


# ============================== W39：data_manage 批量写盘工具入控（v6 P2-6） ============================== #


@pytest.mark.unit
def test_data_manage_batch_tools_denied(qapp, monkeypatch):
    """数据管理页三个批量写盘工具（替换/删除/翻转）：动作拒绝 → 早退 +
    状态栏文案，且不触目录选择（漏网收口——operator 可见页上的破坏性操作）。"""
    from gui.pages.data_manage import page as dm_mod
    from gui.pages.data_manage.page import DataManagePage

    monkeypatch.setattr(
        dm_mod, "check_action",
        lambda action: "无权限执行该操作",
    )
    page = DataManagePage()
    page._msgs = []
    page.status_changed.connect(lambda t, a: page._msgs.append((t, a)))

    picked = []
    monkeypatch.setattr(
        page, "_get_ann_dir", lambda: picked.append(1) or ""
    )
    for method in (
        "_tool_replace_label", "_tool_delete_labels", "_tool_flip_annotation",
    ):
        page._msgs.clear()
        getattr(page, method)()
        assert any("无权限" in t for t, _ in page._msgs), (method, page._msgs)
    assert picked == [], "拒绝路径不得触目录选择"
