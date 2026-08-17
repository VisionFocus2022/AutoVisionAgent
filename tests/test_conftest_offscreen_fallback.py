"""tests/conftest.py 无头离屏兜底的双向行为测试（架构审查 P2-27 收尾）。

被测对象：tests/conftest.py 的模块级兜底 —— 无交互桌面
（ctypes GetSystemMetrics(0) <= 0，与 tests/uia/conftest.py 同法）时
``os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")``；有桌面则不动
（保护 UIA 真窗测试）。

方法：importlib 按路径**重新加载** tests/conftest.py（唯一模块名，避免与
pytest 已加载的 conftest 冲突），使模块级代码在 monkeypatch 生效窗口内
重新执行，从而双向证明判据分支：

1. 无桌面路径：GetSystemMetrics→0 + 清 env → 加载后 offscreen 生效；
2. 有桌面路径：GetSystemMetrics>0 → 不覆盖已设值、也不新设；
3. 探测异常（非 Windows / user32 不可用）→ 按无桌面处理（安全默认）。
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
from pathlib import Path

import pytest

# 被测文件：tests 根 conftest（本测试文件的邻居）
CONFTEST_PATH = Path(__file__).resolve().parent / "conftest.py"


def _load_conftest_fresh(unique_name: str):
    """按路径重新执行 tests/conftest.py（模块级兜底逻辑随之重跑）。"""
    spec = importlib.util.spec_from_file_location(unique_name, CONFTEST_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def fresh_module_name() -> str:
    """每次加载用唯一模块名，避免重复加载被 importlib/sys.modules 去重。"""
    seq = getattr(_load_conftest_fresh, "_seq", 0) + 1
    _load_conftest_fresh._seq = seq  # type: ignore[attr-defined]
    return f"_conftest_under_test_{seq}"


def _mock_screen_width(monkeypatch: pytest.MonkeyPatch, width: int) -> None:
    """mock GetSystemMetrics：0 = 无交互桌面（SM_CXSCREEN），>0 = 有桌面。"""
    monkeypatch.setattr(
        ctypes.windll.user32, "GetSystemMetrics", lambda index: width
    )


class TestNoDesktopPath:
    """无桌面路径：GetSystemMetrics(0) <= 0 → setdefault 离屏生效。"""

    def test_headless_sets_offscreen(self, monkeypatch, fresh_module_name):
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        _mock_screen_width(monkeypatch, 0)
        _load_conftest_fresh(fresh_module_name)
        assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"

    def test_headless_does_not_overwrite_explicit_value(
        self, monkeypatch, fresh_module_name
    ):
        """setdefault 语义：用户/调用方已显式指定平台时不强改。"""
        monkeypatch.setenv("QT_QPA_PLATFORM", "minimal")
        _mock_screen_width(monkeypatch, 0)
        _load_conftest_fresh(fresh_module_name)
        assert os.environ["QT_QPA_PLATFORM"] == "minimal"


class TestDesktopPath:
    """有桌面路径：GetSystemMetrics(0) > 0 → 不动环境（保护 UIA 真窗）。"""

    def test_desktop_keeps_preset_value(self, monkeypatch, fresh_module_name):
        monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
        _mock_screen_width(monkeypatch, 1920)
        _load_conftest_fresh(fresh_module_name)
        assert os.environ["QT_QPA_PLATFORM"] == "windows"

    def test_desktop_does_not_set_when_unset(self, monkeypatch, fresh_module_name):
        """有桌面且未设环境变量 → 保持未设（UIA 真窗依赖真平台）。"""
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        _mock_screen_width(monkeypatch, 1920)
        _load_conftest_fresh(fresh_module_name)
        assert "QT_QPA_PLATFORM" not in os.environ


class TestProbeFailurePath:
    """探测异常路径：按无桌面处理（离屏兜底是安全默认方向）。"""

    def test_probe_exception_treated_as_headless(
        self, monkeypatch, fresh_module_name
    ):
        class _NoWindll:
            def __getattr__(self, name: str):
                raise OSError("simulated non-Windows / no user32")

        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        monkeypatch.setattr(ctypes, "windll", _NoWindll())
        _load_conftest_fresh(fresh_module_name)
        assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
