"""login 页注册流与账户安全路径测试（W8-T4：67% → 洼地填平）。

覆盖 _do_register 许可证导入三态（成功/失败/取消）、连续失败 5 次锁定并
持久化、锁定期拒绝、锁定期过恢复登录并清除锁定、must_change 首登翻转、
低迭代哈希自动迁移（600K）、_ensure_default_admin 首启随机密码 admin、
加载容错。存量哈希用低迭代（1000）构造，避免每例多次 600K PBKDF2。
"""
from __future__ import annotations

import json
import os
import time as _time

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


def _write_db(tmp_path):
    from core.auth import hash_password

    pw_hash, salt_hex, iterations = hash_password(PW, iterations=1_000)
    db = {USER: {
        "password_hash": pw_hash,
        "salt": salt_hex,
        "iterations": iterations,
        "role": "工程师",
        "must_change": False,
    }}
    (tmp_path / "users.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return db


def _read_db(tmp_path):
    return json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))


def _make_page(tmp_path, monkeypatch, qapp, with_user=True):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    if with_user:
        _write_db(tmp_path)
    page = login_mod.LoginPage()
    msgs, logged = [], []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page.login_success.connect(lambda u, r: logged.append((u, r)))
    page._msgs = msgs
    page._logged = logged
    return page


def _try_login(page, user=USER, password=PW):
    page._user_edit.setText(user)
    page._pass_edit.setText(password)
    page._do_login()


# ============================== 注册许可证（_do_register） ============================== #
@pytest.mark.unit
def test_register_license_imports_key(qapp, tmp_path, monkeypatch):
    src = tmp_path / "my.key"
    src.write_text("LICENSE-XYZ", encoding="utf-8")
    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_open_file", lambda *a, **k: str(src)
    )
    page = _make_page(tmp_path, monkeypatch, qapp)
    page._do_register()
    dest = tmp_path / "license.key"
    assert dest.read_text(encoding="utf-8") == "LICENSE-XYZ"
    assert any(t == "许可证导入成功" for t, _ in page._msgs)


@pytest.mark.unit
def test_register_license_copy_failure(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_open_file",
        lambda *a, **k: str(tmp_path / "missing.key"),
    )
    page = _make_page(tmp_path, monkeypatch, qapp)
    page._do_register()
    assert any(t == "许可证导入失败" for t, _ in page._msgs)
    assert not (tmp_path / "license.key").exists()


@pytest.mark.unit
def test_register_cancelled_touches_nothing(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gui.widgets.file_dialog.pick_open_file", lambda *a, **k: ""
    )
    page = _make_page(tmp_path, monkeypatch, qapp)
    page._do_register()
    assert not (tmp_path / "license.key").exists()
    assert page._msgs == []


# ============================== 登录校验与锁定 ============================== #
@pytest.mark.unit
def test_login_input_validation(qapp, tmp_path, monkeypatch):
    page = _make_page(tmp_path, monkeypatch, qapp)

    page._user_edit.clear()
    page._pass_edit.clear()
    page._do_login()
    assert any("请输入用户名" in t for t, _ in page._msgs)

    page._user_edit.setText(USER)
    page._pass_edit.clear()
    page._do_login()
    assert any("请输入密码" in t for t, _ in page._msgs)

    _try_login(page, user="nobody")
    assert any("用户不存在" in t for t, _ in page._msgs)
    assert page._logged == []


@pytest.mark.unit
def test_login_lockout_after_five_failures_persisted(qapp, tmp_path, monkeypatch):
    page = _make_page(tmp_path, monkeypatch, qapp)

    for i in range(5):
        _try_login(page, password="wrong")
    assert any("锁定" in t for t, _ in page._msgs)

    db = _read_db(tmp_path)[USER]
    assert db["lockout_until"] > _time.time()  # 锁定持久化
    assert db["fail_count"] == 0               # 计数归零

    # 锁定期内：正确密码也不得进入
    page._msgs.clear()
    _try_login(page)
    assert any("账户已锁定" in t for t, _ in page._msgs)
    assert page._logged == []


@pytest.mark.unit
def test_login_lockout_expires_and_clears(qapp, tmp_path, monkeypatch):
    page = _make_page(tmp_path, monkeypatch, qapp)
    for _ in range(5):
        _try_login(page, password="wrong")
    lock_until = _read_db(tmp_path)[USER]["lockout_until"]

    # 跳到锁定期之后：登录成功且清除锁定字段
    monkeypatch.setattr(_time, "time", lambda: lock_until + 1)
    _try_login(page)
    assert page._logged == [(USER, "engineer")]  # W18: 旧值"工程师"迁移为枚举
    assert "lockout_until" not in _read_db(tmp_path)[USER]


# ============================== 迁移与首登改密 ============================== #
@pytest.mark.unit
def test_login_migrates_legacy_hash_to_600k(qapp, tmp_path, monkeypatch):
    from core.auth import verify_password

    page = _make_page(tmp_path, monkeypatch, qapp)  # 库内 iterations=1000
    _try_login(page)
    assert page._logged == [(USER, "engineer")]  # W18: 枚举迁移

    rec = _read_db(tmp_path)[USER]
    assert rec["iterations"] == 600_000  # 迁移到 OWASP 2023 迭代
    assert verify_password(PW, rec["password_hash"], rec["salt"], 600_000)


@pytest.mark.unit
def test_login_must_change_flag_flipped(qapp, tmp_path, monkeypatch):
    """W19（v3 第三波 FR-5.3）后语义：must_change 用户须改密成功才放行。

    旧行为=提示即清标志并登录；本波改为强制拦截（取消/失败路径见
    tests/test_w19_password_hygiene.py）。此处以假对话框模拟改密成功。
    """
    _write_db(tmp_path)  # 先落默认记录，取其哈希三元组
    db = _read_db(tmp_path)
    db[USER]["must_change"] = True
    (tmp_path / "users.json").write_text(
        json.dumps(db, ensure_ascii=False), encoding="utf-8"
    )

    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)

    class _FakeDialog:
        # 改密成功：返回可验证的新哈希三元组（offscreen 不阻塞 exec）
        def __init__(self, record, parent=None):
            h, s, i = login_mod._hash_password("brand-new-pw", iterations=1_000)
            self.new_hash_record = (h, s, i)

        def exec(self):  # noqa: A003
            return 1  # QDialog.Accepted

    monkeypatch.setattr(login_mod, "_ChangePasswordDialog", _FakeDialog)
    page = login_mod.LoginPage()
    msgs, logged = [], []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page.login_success.connect(lambda u, r: logged.append((u, r)))

    _try_login(page)
    assert logged == [(USER, "engineer")]  # W18: 枚举迁移；改密成功放行
    assert _read_db(tmp_path)[USER]["must_change"] is False


# ============================== 默认 admin 与容错 ============================== #
@pytest.mark.unit
def test_ensure_default_admin_first_boot_random(qapp, tmp_path, monkeypatch):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    login_mod.LoginPage()  # 空库首启
    db = _read_db(tmp_path)
    assert set(db) == {"admin"}
    rec = db["admin"]
    assert rec["role"] == "admin"  # W18/P2-8: 落稳定枚举
    assert rec["must_change"] is True
    assert rec["iterations"] == 600_000

    # 二次启动：已有库不得覆盖（admin 仍唯一）
    login_mod.LoginPage()
    assert set(_read_db(tmp_path)) == {"admin"}


@pytest.mark.unit
def test_load_users_db_invalid_json_returns_empty(qapp, tmp_path, monkeypatch):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    (tmp_path / "users.json").write_text("{broken", encoding="utf-8")
    page = login_mod.LoginPage()
    assert page._load_users_db() == {}


# ==================== W13-C3 追加：登录审计 + 会话用户接线 ==================== #
def _audit_logins():
    """读取真实 audit 单例缓冲中的 login 条目。"""
    from core.audit_logger import get_audit_logger

    return [e for e in get_audit_logger()._buffer if e["action"] == "login"]


@pytest.mark.unit
def test_login_success_sets_session_user_and_audits(qapp, tmp_path, monkeypatch):
    """W13-C3：登录成功 → set_current_user(登录名) + 恰落一条 login 审计。

    RED：login 页 docstring 宣称记录登录，但此前登录事件全程无审计
    （0 条），且全仓无会话用户持有者（恒 "system"）。
    """
    from core.audit_logger import get_audit_logger
    from core.session import get_current_user, reset_current_user

    reset_current_user()
    get_audit_logger()._buffer.clear()
    try:
        page = _make_page(tmp_path, monkeypatch, qapp)
        _try_login(page)
        assert page._logged == [(USER, "engineer")]  # W18: 枚举迁移
        # 会话当前用户 = 登录名
        assert get_current_user() == USER
        # 恰落一条 login 审计，user=登录名
        logins = _audit_logins()
        assert len(logins) == 1
        assert logins[0]["user"] == USER
    finally:
        reset_current_user()


@pytest.mark.unit
def test_offline_mode_sets_offline_user_and_audits(qapp, tmp_path, monkeypatch):
    """W13-C3：离线模式确认进入 → 会话 "offline" + 恰落一条 login 审计。

    RED：_do_offline 此前无 set_current_user、无审计。
    """
    from core.audit_logger import get_audit_logger
    from core.session import get_current_user, reset_current_user

    reset_current_user()
    get_audit_logger()._buffer.clear()
    try:
        page = _make_page(tmp_path, monkeypatch, qapp)
        # license.key 在场 → 无确认对话框，直接进入离线模式
        (tmp_path / "license.key").write_text("LICENSE-XYZ", encoding="utf-8")
        page._do_offline()
        assert page._logged and page._logged[0][0] == "offline"
        # 会话当前用户 = offline
        assert get_current_user() == "offline"
        # 恰落一条 login 审计，user=offline
        logins = _audit_logins()
        assert len(logins) == 1
        assert logins[0]["user"] == "offline"
    finally:
        reset_current_user()


# ============ W14-C3 追加：初始密码单通道（P2-17 部分）+ 角色稳定枚举（P2-23→W18/P2-8） ============ #
@pytest.mark.unit
def test_default_admin_password_not_printed_to_stdout(qapp, tmp_path, monkeypatch, caplog):
    """RED（P2-17 部分）：初始密码此前 logger.info + print 双通道——
    msg 含明文初始密码，stdout 会进终端历史/重定向文件；只留 logger。"""
    import builtins
    import logging

    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    printed = []

    def _capture_print(*args, **kwargs):
        printed.append(" ".join(str(a) for a in args))

    monkeypatch.setattr(builtins, "print", _capture_print)
    with caplog.at_level(logging.INFO, logger="gui.pages.login.page"):
        login_mod.LoginPage()  # 空库首启 → 生成随机初始密码

    leaked = [c for c in printed if "初始密码" in c]
    assert not leaked, "初始密码不得 print 到 stdout（仅 logger 通道）"
    assert "初始密码" in caplog.text  # logger 通道保留


@pytest.mark.unit
def test_default_admin_role_stable_enum_across_languages(qapp, tmp_path, monkeypatch):
    """W18/P2-8（取代 P2-23 的 tr 统一方案）：角色落稳定枚举 "admin"，
    与界面语言彻底解耦——en_US 首启落库值与 ch_CN 完全一致。"""
    from gui.core.i18n import set_language

    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    set_language("en_US")
    try:
        login_mod.LoginPage()  # 空库首启
    finally:
        set_language("ch_CN")
    db = _read_db(tmp_path)
    assert db["admin"]["role"] == "admin"  # 枚举稳定，不随语言漂移
