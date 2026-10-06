"""W1-5 初始密码参数化测试（PRD docs/prd-w1-4-w1-5-wave1-tail.md）。

- AC-5①：--init-pwd 生效——users.json 哈希验证通过、无 txt
- AC-5②：不合规参数（短/空）回落随机+txt 并告警
- AC-5③：无参数行为不变（随机+txt，且 txt 内密码可验证登录）
- 解析：--init-pwd <pwd> 与 --init-pwd=<pwd> 双形态
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.auth import verify_password

_PWD = "Install#2026!"


@pytest.fixture()
def cfg_dir(monkeypatch, tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    import gui.pages.login.page as lp

    monkeypatch.setattr(lp, "_CONFIG_DIR", str(d))
    return d




def _txt_pwd(d: Path) -> str:
    """txt 中提取初始密码行（格式：用户名/密码多行文案）。"""
    for line in (d / "initial_credentials.txt").read_text(
            encoding="utf-8").splitlines():
        if line.startswith("初始密码:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("txt 缺初始密码行")

def _verify(pwd: str, admin: dict) -> bool:
    return verify_password(pwd, admin["password_hash"], admin["salt"],
                           admin["iterations"])

def _db(d: Path) -> dict:
    return json.loads((d / "users.json").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_init_pwd_used_and_no_txt(qapp, cfg_dir, monkeypatch):
    from gui.pages.login.page import LoginPage

    LoginPage(init_password=_PWD)
    db = _db(cfg_dir)
    assert "admin" in db and db["admin"]["must_change"] is True
    assert _verify(_PWD, db["admin"]), "参数密码应可验证"
    assert not (cfg_dir / "initial_credentials.txt").exists(), (
        "--init-pwd 生效时不得生成明文 txt"
    )


@pytest.mark.unit
def test_short_init_pwd_falls_back(qapp, cfg_dir, caplog):
    from gui.pages.login.page import LoginPage

    with caplog.at_level("WARNING"):
        LoginPage(init_password="short")
    assert (cfg_dir / "initial_credentials.txt").exists(), "回落随机应写 txt"
    db = _db(cfg_dir)
    assert not _verify("short", db["admin"]), "短密码不得入库"
    assert _verify(_txt_pwd(cfg_dir), db["admin"])
    assert any("长度不足" in r.message for r in caplog.records)


@pytest.mark.unit
def test_default_random_behavior_unchanged(qapp, cfg_dir):
    from gui.pages.login.page import LoginPage

    LoginPage()
    txt = cfg_dir / "initial_credentials.txt"
    assert txt.exists(), "无参数应保持随机+txt 原行为"
    db = _db(cfg_dir)
    assert _verify(_txt_pwd(cfg_dir), db["admin"])


@pytest.mark.unit
def test_existing_db_not_touched(qapp, cfg_dir):
    from gui.pages.login.page import LoginPage

    LoginPage(init_password=_PWD)  # 建库
    snapshot = _db(cfg_dir)["admin"]["password_hash"]
    LoginPage(init_password="Another#2026!")  # 二次构造不改库
    assert _db(cfg_dir)["admin"]["password_hash"] == snapshot


@pytest.mark.unit
def test_parse_init_pwd_forms():
    from gui.main import _parse_init_pwd

    assert _parse_init_pwd(["app", "--init-pwd", "p@ss12345"]) == "p@ss12345"
    assert _parse_init_pwd(["app", "--init-pwd=p@ss12345"]) == "p@ss12345"
    assert _parse_init_pwd(["app"]) is None
    assert _parse_init_pwd(["app", "--init-pwd"]) is None  # 缺值不炸


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
