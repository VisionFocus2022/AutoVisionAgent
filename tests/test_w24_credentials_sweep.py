"""W24（v4 P3-7）：首启凭据残留下次启动补删——sweep_residual_initial_credentials。

缺口（v4 P3-7，对抗工程师发现）：改密成功即删 configs/initial_credentials.txt
（gui/pages/login/page.py:_remove_initial_credentials），但 os.remove 失败
（Windows 文件占用）仅记日志、无重试/无下次启动补扫 → 明文凭据文件可
长存。W24 落地：登录页构造时补扫——admin 已改密（must_change=False）
则补删，未改密则保留（登录流程仍强制改密，文件内容自附提示），
os.remove 失败告警保留（下次启动再试）。
"""
import json
import os
from pathlib import Path

import pytest


def _make_env(tmp_path: Path, *, creds: bool, users: dict | None) -> Path:
    """构造 configs 目录形态（凭据文件/users.json 按参数）。"""
    if creds:
        (tmp_path / "initial_credentials.txt").write_text(
            "AutoVisionAgent 首次启动——默认管理员账户\n", encoding="utf-8"
        )
    if users is not None:
        (tmp_path / "users.json").write_text(
            json.dumps(users, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path


@pytest.mark.unit
def test_sweep_absent_when_no_file(tmp_path):
    from gui.pages.login.page import sweep_residual_initial_credentials

    assert sweep_residual_initial_credentials(str(tmp_path)) == "absent"
    assert not (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_deletes_when_admin_already_changed(tmp_path):
    """改密已完成（must_change=False）+ 文件残留（此前删除失败）→ 补删。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(
        tmp_path,
        creds=True,
        users={"admin": {"password_hash": "x", "must_change": False}},
    )
    assert sweep_residual_initial_credentials(str(tmp_path)) == "deleted"
    assert not (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_keeps_when_must_change_still_pending(tmp_path):
    """未改密（must_change=True）→ 保留（登录流程仍会强制改密后删）。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(
        tmp_path,
        creds=True,
        users={"admin": {"password_hash": "x", "must_change": True}},
    )
    assert sweep_residual_initial_credentials(str(tmp_path)) == "kept_pending_change"
    assert (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_remove_failure_warns_and_keeps(tmp_path, monkeypatch):
    """os.remove 失败（Windows 占用）→ 告警保留，返回 remove_failed。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(
        tmp_path,
        creds=True,
        users={"admin": {"password_hash": "x", "must_change": False}},
    )

    def _boom(path, *a, **kw):
        raise OSError("被占用")

    monkeypatch.setattr(os, "remove", _boom)
    assert sweep_residual_initial_credentials(str(tmp_path)) == "remove_failed"
    assert (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_keeps_when_users_db_missing(tmp_path):
    """users.json 缺失/不可读 → 状态未知，保守保留（凭据仍可首次使用）。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(tmp_path, creds=True, users=None)
    assert sweep_residual_initial_credentials(str(tmp_path)) == "kept_pending_change"
    assert (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    ["[]", '[{}]', '"corrupted"', "12345"],
    ids=["list", "list-of-dict", "str-top", "int-top"],
)
def test_sweep_keeps_when_users_db_non_dict_shape(tmp_path, payload):
    """users.json 为合法 JSON 非字典形态 → 保守保留（不得 AttributeError
    逃出——W24 对抗验证员 MEDIUM：逃逸经 __init__ 直达 main() 启动即崩）。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    (tmp_path / "initial_credentials.txt").write_text("x", encoding="utf-8")
    (tmp_path / "users.json").write_text(payload, encoding="utf-8")
    assert (
        sweep_residual_initial_credentials(str(tmp_path))
        == "kept_pending_change"
    )
    assert (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_deletes_when_admin_record_non_dict(tmp_path):
    """admin 记录为非字典（legacy/损坏）→ 视为无挂起改密，补删凭据文件。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(tmp_path, creds=True, users={"admin": "legacy_or_corrupt"})
    assert sweep_residual_initial_credentials(str(tmp_path)) == "deleted"
    assert not (tmp_path / "initial_credentials.txt").exists()


@pytest.mark.unit
def test_sweep_remove_race_file_gone_returns_absent(tmp_path, monkeypatch):
    """exists→remove 间文件被外部删除（TOCTOU）→ absent 而非 remove_failed
    （W24 对抗验证员 low：状态误标 + exception 级日志噪音）。"""
    from gui.pages.login.page import sweep_residual_initial_credentials

    _make_env(
        tmp_path,
        creds=True,
        users={"admin": {"password_hash": "x", "must_change": False}},
    )

    def _gone(path, *a, **kw):
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "remove", _gone)
    assert sweep_residual_initial_credentials(str(tmp_path)) == "absent"


@pytest.mark.unit
def test_login_page_init_wires_sweep():
    """源码守卫（AST）：LoginPage.__init__ 内调用 sweep_residual_initial_credentials()。

    W24 对抗验证员 observation：字符串计数是位置盲的（调用挪走仍绿）——
    升级为 AST 定位 __init__ 方法体内的调用点（镜像 W21 find_main_window
    语义钉住手法）。
    """
    import ast

    src_path = Path(__file__).resolve().parents[1] / "gui" / "pages" / "login" / "page.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    inits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "LoginPage"
        for item in node.body
        if isinstance(item, ast.FunctionDef) and item.name == "__init__"
    ]
    assert len(inits) == 1, "应恰有一个 LoginPage.__init__"
    calls = [
        n
        for n in ast.walk(inits[0])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "sweep_residual_initial_credentials"
        and not n.args
    ]
    assert calls, "LoginPage.__init__ 应无参调用 sweep_residual_initial_credentials()"
