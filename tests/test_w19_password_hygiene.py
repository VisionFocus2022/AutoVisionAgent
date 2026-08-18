"""W19（v3 第三波 FR-5）：P2-2 密码卫生——初始凭据文件化 + must_change 强制改密 + 日志兜底过滤。

RED 目标行为（docs/prd-wave19-v3-wave3.md FR-5.1~FR-5.4）：
① FR-5.1  _ensure_default_admin 首启：初始密码写 configs/initial_credentials.txt
          （用户名/初始密码/修改提示），日志全文不含明文；
② FR-5.3  must_change=True 登录验证通过 → 强制改密对话框：改密成功才放行
          （新哈希落库、must_change=False）；取消/失败 → 不 emit login_success、
          标志保留；FR-5.2 改密成功后 initial_credentials.txt 幂等删除；
③ FR-5.4  SensitiveRedactFilter：含"初始密码: XXXXX"的 record 掩码为
          [REDACTED]，安装函数覆盖 root 全部 handler（防未来回归兜底）。

存量哈希用低迭代（1000）构造，避免每例多次 600K PBKDF2（沿既有测试先例）。
"""
from __future__ import annotations

import io
import json
import logging
import os
import re

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

USER = "engineer"
PW = "pw123456"
NEW_PW = "newpass1234"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _hash(pw: str, iterations: int = 1_000):
    from core.auth import hash_password

    return hash_password(pw, iterations=iterations)


def _write_db(tmp_path, must_change: bool = False) -> dict:
    pw_hash, salt_hex, iterations = _hash(PW)
    db = {USER: {
        "password_hash": pw_hash,
        "salt": salt_hex,
        "iterations": iterations,
        "role": "engineer",
        "must_change": must_change,
    }}
    (tmp_path / "users.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return db


def _read_db(tmp_path) -> dict:
    return json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))


def _make_page(tmp_path, monkeypatch, qapp):
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    page = login_mod.LoginPage()
    msgs, logged = [], []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page.login_success.connect(lambda u, r: logged.append((u, r)))
    page._msgs, page._logged = msgs, logged
    return page


def _try_login(page, user: str = USER, password: str = PW) -> None:
    page._user_edit.setText(user)
    page._pass_edit.setText(password)
    page._do_login()


def _patch_dialog(monkeypatch, new_hash_record):
    """以假对话框替换模块级 _ChangePasswordDialog（offscreen 下不阻塞 exec）。"""
    from gui.pages.login import page as login_mod

    class _FakeDialog:
        # W19/FR-5.3：exec() 立即返回，结果由 new_hash_record 携带
        def __init__(self, record, parent=None):
            self.new_hash_record = new_hash_record

        def exec(self):  # noqa: A003
            return QDialog.Accepted if self.new_hash_record else QDialog.Rejected

    monkeypatch.setattr(
        login_mod, "_ChangePasswordDialog", _FakeDialog, raising=False
    )


# ============ ① FR-5.1：初始密码文件化，日志零明文 ============ #
@pytest.mark.unit
def test_first_boot_writes_credentials_file_not_plaintext_log(
    qapp, tmp_path, monkeypatch, caplog
):
    """空库首启：密码只落 configs/initial_credentials.txt，日志零明文。"""
    from gui.pages.login import page as login_mod

    monkeypatch.setattr(login_mod, "_CONFIG_DIR", tmp_path)
    with caplog.at_level(logging.INFO, logger="gui.pages.login.page"):
        login_mod.LoginPage()  # 空库首启 → 生成随机初始密码

    cred_path = tmp_path / "initial_credentials.txt"
    assert cred_path.exists(), "初始密码必须落 configs/initial_credentials.txt"
    cred_text = cred_path.read_text(encoding="utf-8")
    assert "admin" in cred_text  # 含用户名
    assert "修改" in cred_text  # 含首次登录后修改提示
    match = re.search(r"初始密码[:：]\s*(\S+)", cred_text)
    assert match, "凭据文件须含『初始密码: xxx』行"

    assert "初始密码已写入" in caplog.text  # 提示通道保留（不含明文）
    leaked = [r.getMessage() for r in caplog.records if match.group(1) in r.getMessage()]
    assert not leaked, "日志全文不得含初始密码明文"


# ============ ② FR-5.3/5.2：must_change 强制拦截 ============ #
@pytest.mark.unit
def test_must_change_success_updates_record_and_deletes_credentials(
    qapp, tmp_path, monkeypatch
):
    """改密成功 → 新哈希可验证、must_change=False 落盘、凭据文件删除、放行登录。"""
    from core.auth import verify_password

    _write_db(tmp_path, must_change=True)
    page = _make_page(tmp_path, monkeypatch, qapp)
    (tmp_path / "initial_credentials.txt").write_text("stale", encoding="utf-8")

    new_hash, new_salt, new_iters = _hash(NEW_PW)
    _patch_dialog(monkeypatch, (new_hash, new_salt, new_iters))

    _try_login(page)
    assert page._logged == [(USER, "engineer")]  # 改密成功才放行
    rec = _read_db(tmp_path)[USER]
    assert rec["must_change"] is False  # 标志清除并落盘
    assert verify_password(
        NEW_PW, rec["password_hash"], rec["salt"], rec["iterations"]
    )
    assert not (tmp_path / "initial_credentials.txt").exists()  # FR-5.2 删除


@pytest.mark.unit
def test_must_change_cancel_keeps_flag_and_blocks_login(
    qapp, tmp_path, monkeypatch
):
    """取消/校验失败 → 不 emit login_success、must_change 保留、凭据文件不删。"""
    _write_db(tmp_path, must_change=True)
    page = _make_page(tmp_path, monkeypatch, qapp)
    (tmp_path / "initial_credentials.txt").write_text("stale", encoding="utf-8")
    _patch_dialog(monkeypatch, None)  # 对话框无产物（取消/校验失败）

    _try_login(page)
    assert page._logged == []  # 不发 login_success
    assert any("未修改密码" in t for t, _ in page._msgs)
    assert _read_db(tmp_path)[USER]["must_change"] is True  # 标志保留
    assert (tmp_path / "initial_credentials.txt").exists()  # 文件不删


# ============ ②补：对话框自身校验路径（不 exec） ============ #
@pytest.mark.unit
def test_change_password_dialog_validation_paths(qapp):
    """旧密校验/新密长度/两次一致三重校验；全过 → 返回可验证的新哈希三元组。"""
    from core.auth import verify_password

    from gui.pages.login.page import _ChangePasswordDialog

    pw_hash, salt_hex, iterations = _hash(PW)
    record = {"password_hash": pw_hash, "salt": salt_hex, "iterations": iterations}
    dlg = _ChangePasswordDialog(record)

    def _fill(old: str, new: str, confirm: str) -> None:
        dlg._old_edit.setText(old)
        dlg._new_edit.setText(new)
        dlg._confirm_edit.setText(confirm)
        dlg._on_accept()

    _fill("wrong-old", NEW_PW, NEW_PW)
    assert dlg.new_hash_record is None
    assert "旧密码" in dlg._error.text()

    _fill(PW, "short", "short")
    assert dlg.new_hash_record is None
    assert "8" in dlg._error.text()

    _fill(PW, NEW_PW, "different1")
    assert dlg.new_hash_record is None
    assert "一致" in dlg._error.text()

    _fill(PW, NEW_PW, NEW_PW)
    assert dlg.new_hash_record is not None
    new_hash, new_salt, new_iters = dlg.new_hash_record
    assert verify_password(NEW_PW, new_hash, new_salt, new_iters)


# ============ ③ FR-5.4：敏感过滤器 + 全 handler 装配 ============ #
@pytest.mark.unit
def test_sensitive_redact_filter_masks_initial_password():
    from gui.main import SensitiveRedactFilter

    f = SensitiveRedactFilter()
    rec = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "初始密码: s3cr3t-t0ken", None, None
    )
    assert f.filter(rec) is True  # 记录放行，msg 已就地掩码
    assert "s3cr3t-t0ken" not in rec.getMessage()
    assert "初始密码: [REDACTED]" in rec.getMessage()

    plain = logging.LogRecord("t", logging.INFO, __file__, 1, "普通日志消息", None, None)
    f.filter(plain)
    assert plain.getMessage() == "普通日志消息"  # 非敏感内容不受影响


@pytest.mark.unit
def test_install_sensitive_filter_covers_all_handlers():
    """_install_sensitive_redact_filter：目标 logger 的全部 handler 输出前已掩码。"""
    from gui.main import _install_sensitive_redact_filter

    logger = logging.getLogger("w19.fr54.install")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    buf = io.StringIO()
    h1 = logging.StreamHandler(buf)
    h2 = logging.StreamHandler(io.StringIO())
    logger.addHandler(h1)
    logger.addHandler(h2)

    _install_sensitive_redact_filter(logger)
    logger.info("首次启动 初始密码: l3aky-val")

    out = buf.getvalue()
    assert "l3aky-val" not in out  # handler 输出前已掩码
    assert "[REDACTED]" in out
