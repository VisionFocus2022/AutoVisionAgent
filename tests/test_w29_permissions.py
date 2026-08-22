"""W29（W26 计划 P1）：角色权限最小面——纯函数矩阵 + 导航过滤 + 审计闭环。

背景：角色自 W18 稳定枚举且登录审计在案，但 gui/main.py 登录处理器
字面丢弃 role（零消费）；登录页角色下拉纯装饰。本波把角色推进到
「存储+审计+消费」最小闭环：页面可见性 + 被拒访问审计。

诚实边界：操作护栏非安全边界（users.json 本地可编辑）——防误操作，
不防恶意本地用户（见 gui/core/permissions.py docstring）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
PERMISSIONS = REPO_ROOT / "gui" / "core" / "permissions.py"

_ALL_11_PAGES = {
    "home", "label", "data_manage", "train", "predict",
    "eval", "deploy", "flaw_gen", "project", "settings",
}  # login 页不计入矩阵（恒允许）


# ============================== 1. 纯函数矩阵（FR-1/3/4） ============================== #


@pytest.mark.unit
def test_permissions_module_is_pure_no_qt():
    """permissions.py 零 Qt 依赖（纯函数层，可同步单测/复用非 GUI 场景）。"""
    assert PERMISSIONS.is_file(), "gui/core/permissions.py 应存在（W29）"
    tree = ast.parse(PERMISSIONS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("PySide6") for a in node.names), (
                f"permissions.py 不得 import Qt: {[a.name for a in node.names]}"
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("PySide6"), (
                f"permissions.py 不得 from-import Qt: {node.module}"
            )


@pytest.mark.unit
def test_operator_page_matrix():
    """operator：现场操作页可见；系统/工程/发布页不可见（最小特权）。"""
    from gui.core.permissions import page_allowed, ROLE_OPERATOR

    allowed = {"home", "label", "data_manage", "predict", "eval"}
    for page in _ALL_11_PAGES:
        expected = page in allowed
        assert page_allowed(ROLE_OPERATOR, page) is expected, (
            f"operator × {page}: 期望 {expected}"
        )


@pytest.mark.unit
def test_engineer_page_matrix():
    """engineer：train/eval/deploy 可见；settings（系统配置）不可见。"""
    from gui.core.permissions import page_allowed, ROLE_ENGINEER

    assert page_allowed(ROLE_ENGINEER, "settings") is False
    for page in ("train", "eval", "deploy", "predict", "label"):
        assert page_allowed(ROLE_ENGINEER, page) is True


@pytest.mark.unit
def test_admin_sees_all_pages():
    """admin：11 页全 True（UIA 离线=admin 全可见的矩阵基础）。"""
    from gui.core.permissions import page_allowed, ROLE_ADMIN

    for page in _ALL_11_PAGES:
        assert page_allowed(ROLE_ADMIN, page) is True, f"admin × {page}"


@pytest.mark.unit
def test_login_page_always_allowed_and_unknown_page_denied():
    """登录页恒允许（认证入口）；未知页 id 默认拒绝。"""
    from gui.core.permissions import page_allowed

    for role in ("admin", "engineer", "operator"):
        assert page_allowed(role, "login") is True
        assert page_allowed(role, "no_such_page") is False


@pytest.mark.unit
def test_unknown_role_falls_to_minimal_set():
    """未知/异常角色 → operator 最小集（默认最小特权，不放大）。"""
    from gui.core.permissions import page_allowed, ROLE_OPERATOR

    for page in _ALL_11_PAGES:
        assert page_allowed("intruder", page) is page_allowed(ROLE_OPERATOR, page)
    assert page_allowed(None, "settings") is False  # type: ignore[arg-type]


@pytest.mark.unit
def test_action_allowed_unregistered_action_denies_all():
    """W29 最小面：动作清单不冻结——未注册动作三角色全拒（后续波次
    冻结动作集时逐波登记，漏登记=显式拒绝而非静默放行）。"""
    from gui.core.permissions import action_allowed

    for role in ("admin", "engineer", "operator"):
        assert action_allowed(role, "unregistered_action_xyz") is False


@pytest.mark.unit
def test_role_constants_are_canonical_source():
    """角色常量稳定枚举（login 页自此 import 自本模块——真源唯一）。"""
    from gui.core import permissions as perms

    assert (perms.ROLE_ADMIN, perms.ROLE_ENGINEER, perms.ROLE_OPERATOR) == (
        "admin", "engineer", "operator",
    )
    assert set(perms.ROLES) == {"admin", "engineer", "operator"}


# ============================== 2. MainWindow 消费接线（FR-2） ============================== #


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_set_role_filters_nav_visibility(qapp):
    """set_role 即时同步导航按钮可见性（AC-7）。"""
    from gui.core.permissions import ROLE_ADMIN, ROLE_OPERATOR
    from gui.core.shell import MainWindow

    win = MainWindow("t-perm")
    try:
        win.add_page("home", "home", "主页", win._pages.get("home") or _dummy_widget(win))
        win.add_page("settings", "settings", "设置", _dummy_widget(win))

        win.set_role(ROLE_OPERATOR)
        # isVisibleTo(win)：离屏未 show 的窗口下判「窗口可见则控件可见」
        assert win._nav_buttons["settings"].isVisibleTo(win) is False
        assert win._nav_buttons["home"].isVisibleTo(win) is True

        win.set_role(ROLE_ADMIN)
        assert win._nav_buttons["settings"].isVisibleTo(win) is True
    finally:
        win.deleteLater()


def _dummy_widget(parent):
    from PySide6.QtWidgets import QLabel

    return QLabel("x", parent)


@pytest.mark.unit
def test_select_denied_does_not_switch_and_audits(qapp, monkeypatch):
    """拒绝访问：不切页 + 状态栏含拒绝文案 + 审计 access_denied（AC-4）。"""
    from core import audit_logger
    from gui.core.permissions import ROLE_OPERATOR
    from gui.core.shell import MainWindow

    denied = []
    monkeypatch.setattr(
        audit_logger, "log_access_denied",
        lambda **kw: denied.append(kw),
    )

    win = MainWindow("t-perm2")
    try:
        win.add_page("home", "home", "主页", _dummy_widget(win))
        win.add_page("settings", "settings", "设置", _dummy_widget(win))
        win.set_role(ROLE_OPERATOR)
        win.select("home")

        statuses = []
        win.set_status = lambda t, a="": statuses.append((t, a))
        win.select("settings")

        assert win._stack.currentWidget() is win._pages["home"], "拒绝时不得切页"
        assert any("无权限" in t or "无权限" in a for t, a in statuses), (
            f"状态栏应含拒绝文案，got: {statuses}"
        )
        assert denied and denied[0].get("page") == "settings", (
            f"审计应记 access_denied(page=settings)，got: {denied}"
        )
    finally:
        win.deleteLater()


@pytest.mark.unit
def test_select_allowed_before_login_is_permissive(qapp):
    """未登录态（role=None）保持宽容——W29 消费点锚定登录成功处（PRD §5）。"""
    from gui.core.shell import MainWindow

    win = MainWindow("t-perm3")
    try:
        win.add_page("home", "home", "主页", _dummy_widget(win))
        win.select("home")
        assert win._stack.currentWidget() is win._pages["home"]
    finally:
        win.deleteLater()


# ============================== 3. 登录链路角色语义（FR-5/6） ============================== #


@pytest.mark.unit
def test_offline_mode_emits_admin_role(qapp, tmp_path, monkeypatch):
    """离线模式 = 本机单工位完整权限 → emit ("offline","admin")。

    「受限」指无 License 单工位，非页面裁剪——operator 角色会裁掉
    settings/project/train 等 UIA 全量导航的 9 页。
    """
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    (tmp_path / "license.key").write_text("", encoding="utf-8")
    page = login_mod.LoginPage()
    logged = []
    page.login_success.connect(lambda u, r: logged.append((u, r)))

    page._do_offline()
    assert logged == [("offline", "admin")]


@pytest.mark.unit
def test_login_page_has_no_decorative_role_combo(qapp, tmp_path, monkeypatch):
    """装饰性角色下拉删除（选择从未被 _do_login 消费——虚假控件）。"""
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    page = login_mod.LoginPage()
    assert not hasattr(page, "_role_combo"), "角色下拉应删除（角色真源=users.json）"


@pytest.mark.unit
def test_main_consumes_role_on_login():
    """gui/main.py 登录成功处理器消费 role（set_role 接线，源码守卫）。"""
    src = (REPO_ROOT / "gui" / "main.py").read_text(encoding="utf-8")
    assert re.search(r"set_role\s*\(", src), (
        "登录成功处理器须调用 win.set_role(role)（替换字面丢弃）"
    )


@pytest.mark.unit
def test_login_page_reexports_role_constants():
    """login 页 ROLE_* 改 import 自 permissions 并保 re-export（既有 import 路径兼容）。"""
    from gui.pages.login import page as login_mod
    from gui.core.permissions import ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR

    assert login_mod.ROLE_ADMIN is ROLE_ADMIN
    assert login_mod.ROLE_ENGINEER is ROLE_ENGINEER
    assert login_mod.ROLE_OPERATOR is ROLE_OPERATOR
