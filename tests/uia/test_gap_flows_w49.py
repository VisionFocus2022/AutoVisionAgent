"""W49 覆盖缺口用例：flaw_gen/home/operator 门控/deploy 日志锚点。

结合日志铁证（log_evidence.LogAnchor/wait_audit_line，SDW §5.1 通道三）：
- 断言口径：状态栏双态 + UIA 树属性 + **应用日志锚点**（打点先于动作）；
- 失败消息含英文 "timeout"（flaky 路由；autofix-loop 分类闸约定）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

try:
    from tests.uia.log_evidence import LogAnchor, wait_audit_line
    from tests.uia.uia_helpers import (
        click_button,
        click_login_button_precise,
        click_nav,
        find_control_by_name,
        find_edit_controls,
        login_admin,
        set_edit_value,
        sort_login_edits,
        wait_any_status,
        wait_status,
    )
except ImportError:  # pragma: no cover — 顶层模式兜底
    from log_evidence import LogAnchor, wait_audit_line  # type: ignore[no-def]
    from uia_helpers import (  # type: ignore[no-def]
        click_button,
        click_login_button_precise,
        click_nav,
        find_control_by_name,
        find_edit_controls,
        login_admin,
        set_edit_value,
        sort_login_edits,
        wait_any_status,
        wait_status,
    )

_REPO_ROOT = Path(__file__).resolve().parents[2]
# 导航按钮 setCheckable(True) → UIA 暴露为 CheckBoxControl（click_nav/docstring
# 同源）；断言须 Button+CheckBox 双类型，单搜 ButtonControl 会漏导航
_BUTTONS = ["ButtonControl"]
_NAV_TYPES = ["ButtonControl", "CheckBoxControl"]
_TEXTS = ["TextControl", "StaticControl"]
T_NAV = 20.0

_UIA_OP_PWD = "UiaOp#2026"


def _login_as(win, username: str, password: str) -> None:
    """通用账号登录（镜像 login_admin 原语）。"""
    edits = sort_login_edits(win)
    assert len(edits) >= 2, f"登录页应有用户名/密码两输入框 (find timeout), got {len(edits)}"
    assert set_edit_value(edits[0], username), "用户名写入失败"
    assert set_edit_value(edits[1], password), "密码写入失败"
    assert click_login_button_precise(win), "未找到精确'登录'按钮"
    status = wait_any_status(win, ["登录成功", "就绪", "仪表盘"], 15.0)
    assert status is not None, f"{username} 登录未完成 (timeout): 状态栏无登录成功标志"
    time.sleep(1.2)  # set_role 导航可见性同步


@pytest.fixture()
def op_seed():
    """预置 operator 账号（镜像 conftest.ready_admin_cfg，role=operator）。

    参数序须先于 ava_app（应用启动前 users.json 就位）；备份还原同款。
    """
    import sys

    sys.path.insert(0, str(_REPO_ROOT))
    from core.auth import hash_password

    h, s, iters = hash_password(_UIA_OP_PWD)
    db = {"operator": {
        "password_hash": h, "salt": s, "role": "operator",
        "iterations": iters, "must_change": False,
    }}
    cfg_dirs = [
        _REPO_ROOT / "configs",
        _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs",
    ]
    touched: list = []
    try:
        for cfg in cfg_dirs:
            if not cfg.exists():
                continue
            users = cfg / "users.json"
            if users.exists():
                bak = cfg / (users.name + ".uia-bak")
                users.replace(bak)
                touched.append((bak, users))
            users.write_text(
                json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            touched.append((users, None))
        yield
    finally:
        for path, restore_to in reversed(touched):
            try:
                if restore_to is None:
                    path.unlink(missing_ok=True)
                else:
                    path.replace(restore_to)
            except OSError:
                pass


# ================================ 用例 ================================ #


def test_flaw_gen_panel_and_honest_failure(ready_admin_cfg, ava_app):
    """缺陷生成页（此前零覆盖）：面板接线 + 三段诚实失败 + 无 ERROR 日志。"""
    win = ava_app
    anchor = LogAnchor()
    login_admin(win)
    assert click_nav(win, "缺陷生成", T_NAV), "未找到'缺陷生成'导航 (find timeout)"
    time.sleep(1.0)

    # PanelWiring：核心 Caption 在场（§5.4 三用例范式）
    for cap in ("缺陷生成", "OK 模板", "缺陷数据库"):
        found = find_control_by_name(win, cap, _TEXTS, timeout=8.0)
        assert found is not None, f"缺陷生成页 Caption 缺失 (find timeout): {cap}"
    assert find_control_by_name(win, "开始生成", _BUTTONS, 8.0) is not None, \
        "'开始生成'按钮缺失 (find timeout)"

    # 三段诚实失败：全空 → m1；填 OK → m2；填缺陷库 → m3（输出仍空）
    edits = find_edit_controls(win, timeout=10.0)
    assert len(edits) >= 3, f"缺陷生成页应 ≥3 路径输入框 (find timeout), got {len(edits)}"

    assert click_button(win, "开始生成", T_NAV)
    st = wait_status(win, "请先选择 OK 模板目录", 10.0)
    assert st is not None, f"全空应提示 OK 模板目录 (timeout), 最后状态={st!r}"

    assert set_edit_value(edits[0], r"E:/nonexistent_ok_dir")
    assert click_button(win, "开始生成", T_NAV)
    assert wait_status(win, "请先选择缺陷数据库目录", 10.0) is not None, \
        "填 OK 后应提示缺陷数据库目录 (timeout)"

    assert set_edit_value(edits[1], r"E:/nonexistent_flaw_dir")
    assert click_button(win, "开始生成", T_NAV)
    assert wait_status(win, "请先选择输出目录", 10.0) is not None, \
        "填缺陷库后应提示输出目录 (timeout)"

    # 诚实失败（表单校验级）不应产生应用 ERROR 日志
    errs = anchor.error_lines()
    assert not errs, f"表单校验失败不应有 ERROR 日志，实得: {errs[:3]}"


def test_home_dashboard_and_login_audit(ready_admin_cfg, ava_app):
    """主页仪表盘卡片在场 + 登录审计日志锚点（AUDIT 行即时落盘验证）。"""
    win = ava_app
    anchor = LogAnchor()  # 打点先于登录动作（§5.1）
    login_admin(win)
    assert click_nav(win, "主页", T_NAV), "未找到'主页'导航 (find timeout)"
    time.sleep(1.0)

    for cap in ("仪表盘", "项目数", "图像总数", "已训练模型", "GPU 状态"):
        found = find_control_by_name(win, cap, _TEXTS, timeout=8.0)
        assert found is not None, f"仪表盘卡片缺失 (find timeout): {cap}"

    m = wait_audit_line(anchor, "login", user="admin", timeout=15.0)
    assert m is not None, (
        "admin 登录审计锚点未命中 (timeout), "
        f"tail={anchor.tail()[-300:]!r}"
    )
    assert not anchor.error_lines(), "登录/主页流不应有 ERROR 日志"


def test_operator_role_nav_gating(op_seed, ava_app):
    """operator 角色导航门控（§8 运行时证明）：5 页可见 / 6 页不可见 + 审计。"""
    win = ava_app
    anchor = LogAnchor()
    _login_as(win, "operator", _UIA_OP_PWD)

    def _nav_entry(title: str, deadline: float = 8.0):
        """导航按钮精确查找：Name == f"  {title}"（shell.py QPushButton
        f"  {title}" 两空格前缀构造保证；主页快捷按钮无前缀，子串误中
        免疫）+ Button/CheckBox 双类型（setCheckable→CheckBoxControl）。"""
        from uia_helpers import _iter_descendants

        target = f"  {title}"
        end = time.time() + deadline
        while time.time() < end:
            for c in _iter_descendants(win, max_depth=8):
                if type(c).__name__ not in _NAV_TYPES:
                    continue
                try:
                    if (c.Name or "") == target:
                        return c
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.4)
        return None

    for visible in ("主页", "标注", "数据管理", "推理", "评估"):
        assert _nav_entry(visible) is not None, (
            f"operator 应可见导航缺失 (find timeout): {visible}"
        )
    for hidden in ("训练", "发布", "缺陷生成", "项目管理", "设置"):
        found = _nav_entry(hidden, deadline=2.0)
        assert found is None, (
            f"operator 不应见导航却在左栏 (unexpected): {hidden} -> {found}"
        )

    m = wait_audit_line(anchor, "login", user="operator", timeout=15.0)
    assert m is not None, (
        "operator 登录审计锚点未命中 (timeout), "
        f"tail={anchor.tail()[-300:]!r}"
    )


def test_deploy_export_log_anchor(ready_admin_cfg, ava_app, fake_model_path, workspace_dir):
    """发布页导出流日志锚点深化：打点→「模型导出开始」行 + 进行中→失败双态闭环。"""
    win = ava_app
    out_dir = workspace_dir / "models"
    anchor = LogAnchor()
    login_admin(win)
    assert click_nav(win, "发布", T_NAV), "未找到'发布'导航 (find timeout)"
    time.sleep(1.0)

    edits = find_edit_controls(win, timeout=10.0)
    assert len(edits) >= 2, f"发布页应有源模型/输出目录两输入框 (find timeout), got {len(edits)}"
    assert set_edit_value(edits[0], str(fake_model_path)), "模型路径写入失败"
    assert set_edit_value(edits[1], str(out_dir)), "输出目录写入失败"

    assert click_button(win, "导出", T_NAV), "未找到'导出'按钮 (find timeout)"
    assert wait_status(win, "导出进行中", 15.0) is not None, \
        "导出应进入进行中状态 (timeout)"

    m = anchor.wait_line(r"模型导出开始: model=", timeout=20.0)
    assert m is not None, (
        "导出开始日志锚点未命中 (timeout), "
        f"tail={anchor.tail()[-300:]!r}"
    )
    # 假模型（占位字节）→ torch.load 失败 → 诚实失败态
    failed = wait_any_status(win, ["导出失败", "无法识别"], 30.0)
    assert failed is not None, f"假模型导出应诚实失败 (timeout), 最后状态={failed!r}"
