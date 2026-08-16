"""主题 auto 语义测试（W4-T4，架构审查 P2-9）。

现状：settings 保存时把 auto 硬折成 night；main 启动直接 apply("auto")
会落进 daytime QSS 分支——auto 从未真正"随系统"。
契约：resolve_theme(auto) → 按系统配色（Light→daytime / Dark·Unknown→night），
night/daytime 原样透传；ThemeManager.apply 对任意输入先解析。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _patch_scheme(monkeypatch, scheme):
    """把 QGuiApplication.styleHints().colorScheme() 替换为固定值。"""
    from PySide6.QtGui import QGuiApplication

    class _Hints:
        def colorScheme(self):
            return scheme

    class _FakeGui:
        @staticmethod
        def styleHints():
            return _Hints()

    monkeypatch.setattr("PySide6.QtGui.QGuiApplication", _FakeGui)
    return _FakeGui


@pytest.mark.unit
def test_resolve_theme_passthrough():
    from gui.core.theme import resolve_theme

    assert resolve_theme("night") == "night"
    assert resolve_theme("daytime") == "daytime"


@pytest.mark.unit
def test_resolve_auto_light_is_daytime(qapp, monkeypatch):
    from gui.core.theme import resolve_theme

    _patch_scheme(monkeypatch, Qt.ColorScheme.Light)
    assert resolve_theme("auto") == "daytime"


@pytest.mark.unit
def test_resolve_auto_dark_and_unknown_are_night(qapp, monkeypatch):
    from gui.core.theme import resolve_theme

    _patch_scheme(monkeypatch, Qt.ColorScheme.Dark)
    assert resolve_theme("auto") == "night"

    _patch_scheme(monkeypatch, Qt.ColorScheme.Unknown)
    assert resolve_theme("auto") == "night"


@pytest.mark.unit
def test_manager_apply_resolves_auto(qapp, monkeypatch):
    """ThemeManager.apply('auto') 不得再落进 daytime QSS 分支。"""
    from gui.core.theme import ThemeManager

    _patch_scheme(monkeypatch, Qt.ColorScheme.Dark)
    mgr = ThemeManager(qapp)
    mgr.apply("auto")
    assert mgr.theme == "night"
    assert mgr.theme in ("night", "daytime")  # 永不残留 "auto"
