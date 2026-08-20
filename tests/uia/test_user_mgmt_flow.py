"""W25（FR-004）：首登强制改密 UIA + W24 sweep 联动——两阶段真窗用例。

时序（T2b 调查实证）：登录 → PBKDF2 验证 → must_change=True 在
login_success 之前弹模态改密框（三字段按 top 排序=旧/新/确认）→
确认修改 → 同步删 initial_credentials.txt + must_change=False 落库 →
放行主页。第二阶段重启应用（无 logout 功能）：旧密码被拒 1 次（连续
5 次锁账户 300s，绝不重试）→ 新密码直进主页。

钉死 exe 模式：python 模式 CONFIG_DIR=仓库 configs/，首启会把明文
凭据写进仓库工作树（W23 卫生边界回退）。
还原配方：setup/teardown 均删 users.json + initial_credentials.txt
（always-first-run，下次启动自动重建全新随机密码——比快照恢复更能
自愈上轮残留毒状态）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

try:
    from tests.uia.uia_helpers import (
        _iter_descendants,
        _wait_dialog,
        _wait_dialog_gone,
        click_button,
        find_edit_controls,
        find_main_window,
        read_status_text,
        set_edit_value,
        wait_status,
    )
    from tests.uia.test_pole_dataset_flows import _ensure_logged_in
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        _iter_descendants,
        _wait_dialog,
        _wait_dialog_gone,
        click_button,
        find_edit_controls,
        find_main_window,
        read_status_text,
        set_edit_value,
        wait_status,
    )
    from test_pole_dataset_flows import _ensure_logged_in  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.skipif(
    os.environ.get("AVA_UIA_SOURCE", "exe").lower() != "exe",
    reason="改密用例钉死 exe 模式——python 模式会写仓库 configs/",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXE = REPO_ROOT / "dist" / "AutoVisionAgent" / "AutoVisionAgent.exe"
EXE_CFG = REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs"
CRED_FILE = EXE_CFG / "initial_credentials.txt"
USERS_FILE = EXE_CFG / "users.json"

_NEW_PWD = "UiaTestPwd#2026"  # ≥8 字符（对话框校验下限）


def _reset_first_run_state() -> None:
    """删两文件 → 下次启动走空库首启分支重建（最强还原）。"""
    for f in (USERS_FILE, CRED_FILE):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            logger.warning("清理 %s 失败", f, exc_info=True)


def _parse_initial_pwd() -> str:
    """从首启生成的凭据文件解析初始密码（绝不硬编码）。"""
    for _ in range(6):
        if CRED_FILE.exists():
            m = re.search(
                r"^初始密码:\s*(\S+)\s*$", CRED_FILE.read_text(encoding="utf-8"), re.M
            )
            if m:
                return m.group(1)
        time.sleep(0.5)
    pytest.fail(f"initial_credentials.txt 未生成或无初始密码行: {CRED_FILE}")


def _sort_edits(container) -> list:
    """收集容器内 Edit 控件并按纵坐标排序（QLineEdit 无可靠 Name）。"""
    edits = find_edit_controls(container, timeout=10)
    return sorted(edits, key=lambda c: c.BoundingRectangle.top)


def _click_login_button(win) -> bool:
    """精确点击登录按钮（ButtonControl 且 Name=='登录'）。

    不能用 click_button(win, "登录")：登录页复选框「记住登录状态」
    （CheckBoxControl，在 click_button 的 Button+CheckBox 匹配集内）包含
    子串"登录"，树遍历先命中它——W25 R3 实测点击落在复选框上，槽函数
    零触发、状态栏恒"就绪"。
    """
    deadline = time.time() + 10
    while time.time() < deadline:
        for c in _iter_descendants(win, max_depth=8):
            if type(c).__name__ != "ButtonControl":
                continue
            if (c.Name or "").strip() == "登录":
                try:
                    c.SetFocus()
                except Exception:  # noqa: BLE001
                    pass
                c.Click()
                logger.info("已精确点击'登录'按钮（绕开'记住登录状态'复选框）")
                return True
        time.sleep(0.4)
    logger.error("未找到精确'登录'按钮")
    return False


@pytest.fixture()
def first_run_cfg():
    """always-first-run：setup 杀残留进程+删残留态，teardown 同款收尾。

    先 taskkill 再删文件——残留僵尸进程会持 QLockFile 单实例锁，使新
    实例弹"已在运行"早退、ava_app 错绑僵尸窗口（W25 R2 实测踩坑）。
    """
    try:
        subprocess.run(
            ["taskkill", "/IM", "AutoVisionAgent.exe", "/F"],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass
    _reset_first_run_state()
    yield
    try:
        subprocess.run(
            ["taskkill", "/IM", "AutoVisionAgent.exe", "/F"],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass
    _reset_first_run_state()


def test_first_login_change_password(first_run_cfg, ava_app):
    """初始密码登录→强制改密→凭据文件消失→旧拒新放（重启验证）。

    参数序即 fixture 实例化序：first_run_cfg 必须在 ava_app 之前——
    删除残留态要发生在应用进程启动前（否则 _ensure_default_admin 读
    旧 users.json 非空库分支、不重建凭据文件，首轮实测踩此坑）。
    """
    win = ava_app  # 启动期 LoginPage.__init__ 已重建 admin+凭据文件
    initial_pwd = _parse_initial_pwd()

    # ---------- 第一段：登录 → 改密 ----------
    edits = _sort_edits(win)
    assert len(edits) >= 2, f"登录页应至少 2 个输入框，实得 {len(edits)}"
    assert set_edit_value(edits[0], "admin"), "用户名写入失败"
    assert set_edit_value(edits[1], initial_pwd), "密码写入失败"
    assert _click_login_button(win), "未找到'登录'按钮"

    dlg = _wait_dialog("首次登录", timeout=15)
    if dlg is None:
        pytest.fail(
            "must_change=True 应弹改密框（标题'首次登录——请修改密码'），"
            f"15s 未见；状态栏: {read_status_text(win)!r}"
        )
    dedits = _sort_edits(dlg)
    assert len(dedits) == 3, f"改密框应恰 3 个输入框（旧/新/确认），实得 {len(dedits)}"
    assert set_edit_value(dedits[0], initial_pwd), "旧密码写入失败"
    assert set_edit_value(dedits[1], _NEW_PWD), "新密码写入失败"
    assert set_edit_value(dedits[2], _NEW_PWD), "确认新密码写入失败"
    assert click_button(dlg, "确认修改", 10), "未找到'确认修改'按钮"
    assert _wait_dialog_gone("首次登录", timeout=8), "改密框未关闭"

    status = wait_status(win, "登录成功", timeout=15)
    assert status, "改密成功后应放行主页（状态'登录成功'）"

    # 文件铁证（删除同步发生在 login_success 之前，无需等 sweep）
    assert not CRED_FILE.exists(), (
        "改密成功后 initial_credentials.txt 应被删除（W19 FR-5.2）"
    )
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    assert users["admin"]["must_change"] is False, users["admin"]

    # ---------- 第二段：重启验证旧拒新放 ----------
    subprocess.run(
        ["taskkill", "/IM", "AutoVisionAgent.exe", "/F"],
        capture_output=True, timeout=10,
    )
    time.sleep(1.0)  # QLockFile 陈旧锁自愈窗口
    env = {k: v for k, v in os.environ.items() if k != "AVA_LOG_DIR"}
    proc2 = subprocess.Popen([str(EXE)], cwd=str(EXE.parent), env=env)
    try:
        win2 = find_main_window(timeout=40)
        time.sleep(1.5)

        # 旧密码被拒——只此一次（连续 5 次锁账户 300s 且持久化）
        e2 = _sort_edits(win2)
        assert len(e2) >= 2
        assert set_edit_value(e2[0], "admin")
        assert set_edit_value(e2[1], initial_pwd)
        assert _click_login_button(win2)
        assert wait_status(win2, "密码错误", timeout=15), (
            "旧密码登录应被拒（'密码错误 (N 次剩余)'）"
        )

        # 新密码直进主页（must_change 已 False，不再弹框）
        e3 = _sort_edits(win2)
        assert set_edit_value(e3[0], "admin")
        assert set_edit_value(e3[1], _NEW_PWD)
        assert _click_login_button(win2)
        assert wait_status(win2, "登录成功", timeout=15), "新密码应可登录"
    finally:
        try:
            proc2.terminate()
            try:
                proc2.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc2.kill()
        except Exception:  # noqa: BLE001
            pass
