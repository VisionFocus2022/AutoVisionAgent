"""W18 / P2-8：角色稳定枚举化（admin/engineer/operator）+ 显示层解耦。

RED 目标行为：
① 旧中文角色值（"管理员"/"工程师"/"操作员"）在登录读取路径经 _migrate_role
   归一为稳定枚举；已是枚举直通；缺失/未知回退 operator；
② 角色下拉 addItem(display, userData=枚举)——currentData() 取枚举，显示文本
   与持久值解耦（语言切换只改显示，枚举/落库值不变）；
③ 新注册（首启默认 admin）写盘 role == "admin"（与语言无关）；
④ login_success 信号第二参收到枚举字符串（含离线模式）。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


USER = "engineer"
PW = "pw123456"
_ROLES = ("admin", "engineer", "operator")


def _write_db(tmp_path, role):
    from core.auth import hash_password

    pw_hash, salt_hex, iterations = hash_password(PW, iterations=1_000)
    db = {USER: {
        "password_hash": pw_hash,
        "salt": salt_hex,
        "iterations": iterations,
        "role": role,
        "must_change": False,
    }}
    (tmp_path / "users.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_db(tmp_path):
    return json.loads(
        (tmp_path / "users.json").read_text(encoding="utf-8")
    )


def _make_page(tmp_path, monkeypatch, qapp, role="管理员"):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    _write_db(tmp_path, role)
    page = login_mod.LoginPage()
    logged = []
    page.login_success.connect(lambda u, r: logged.append((u, r)))
    page._logged = logged
    return page


def _try_login(page, user=USER, password=PW):
    page._user_edit.setText(user)
    page._pass_edit.setText(password)
    page._do_login()


# ============================== ① 旧中文值迁移 ============================== #
@pytest.mark.unit
@pytest.mark.parametrize(
    "legacy,expected",
    [("管理员", "admin"), ("工程师", "engineer"), ("操作员", "operator")],
)
def test_legacy_chinese_role_migrated_on_login(
    qapp, tmp_path, monkeypatch, legacy, expected
):
    """users.json 存中文旧值 → 登录读取路径归一为枚举。"""
    page = _make_page(tmp_path, monkeypatch, qapp, role=legacy)
    _try_login(page)
    assert page._logged == [(USER, expected)]


@pytest.mark.unit
def test_migrate_role_enum_passthrough_and_fallback(qapp):
    """枚举直通；缺失/未知值回退 operator（默认角色缺省）。"""
    from gui.pages.login.page import ROLE_OPERATOR, _migrate_role

    assert _migrate_role("admin") == "admin"      # 已是枚举直通
    assert _migrate_role("engineer") == "engineer"
    assert _migrate_role("operator") == "operator"
    assert _migrate_role("神仙") == ROLE_OPERATOR  # 未知回退
    assert _migrate_role(None) == ROLE_OPERATOR    # 缺失回退


# ==================== ② 装饰性角色下拉（W29 已删） ==================== #
# 原 test_role_combo_current_data_enum_and_display_decoupled 随下拉一并
# 删除——该下拉从未被 _do_login 消费（虚假控件），角色真源=users.json；
# 枚举/显示解耦语义仍由 _migrate_role（①）与 ③④ 的落库/信号断言守护。


# ====================== ③ 新注册写盘 role == 枚举 ====================== #
@pytest.mark.unit
def test_default_admin_registration_writes_enum_role(
    qapp, tmp_path, monkeypatch
):
    """首启默认 admin 注册写盘 role == "admin"；en_US 下同样落枚举。"""
    from gui.core.i18n import set_language

    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    login_mod.LoginPage()  # 空库首启（ch_CN）
    assert _read_db(tmp_path)["admin"]["role"] == "admin"

    en_dir = tmp_path / "en_boot"
    en_dir.mkdir()
    monkeypatch.setattr(login_mod, "_CONFIG_DIR", en_dir)
    set_language("en_US")
    try:
        login_mod.LoginPage()  # 空库首启（en_US）
    finally:
        set_language("ch_CN")
    assert _read_db(en_dir)["admin"]["role"] == "admin"


# ====================== ④ login_success 收到枚举 ====================== #
@pytest.mark.unit
def test_login_success_emits_enum_role(qapp, tmp_path, monkeypatch):
    """登录成功信号第二参为枚举字符串（新式存储值直通）。"""
    page = _make_page(tmp_path, monkeypatch, qapp, role="operator")
    _try_login(page)
    assert page._logged == [(USER, "operator")]
    assert isinstance(page._logged[0][1], str)


@pytest.mark.unit
def test_offline_mode_emits_enum_role(qapp, tmp_path, monkeypatch):
    """离线模式 login_success 收到枚举 "admin"。

    W29 语义迁移：离线=本机单工位完整权限（原 operator 会把 UIA 全量
    导航的 9 页裁掉）；「受限」指无 License 单工位，非页面裁剪。
    """
    page = _make_page(tmp_path, monkeypatch, qapp)
    (tmp_path / "license.key").write_text("", encoding="utf-8")
    page._do_offline()
    assert page._logged == [("offline", "admin")]
