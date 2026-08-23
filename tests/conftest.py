"""tests 根 conftest —— 无头环境 Qt 离屏集中兜底（架构审查 P2-27 收尾）。

背景：QT_QPA_PLATFORM=offscreen 此前靠 28 个测试文件逐文件
setdefault（如 tests/test_gui.py 顶部），新 GUI 测试文件漏写将在门禁机
弹真窗、无头环境崩。本文件在 pytest 收集任何测试模块（即任何可能的
Qt import）之前被加载，集中兜底：

- 无交互桌面（ctypes GetSystemMetrics(0) <= 0，与 tests/uia/conftest.py
  同法；无头 CI / 纯 SSH 控制台 / 非 Windows 下成立）→
  ``os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")``；
- 有桌面 → 不动环境（保护 UIA 真窗测试走真平台；tests/uia 默认已
  --ignore，仅手动运行）。

探测失败（无 windll / user32 不可用）按无桌面处理：误设 offscreen 的
代价是渲染走内存，漏设的代价是弹真窗或无头崩溃，前者远轻于后者。

既有 28 处逐文件 setdefault 保留不动（显式无害，语义与本兜底一致）。
双向行为测试：tests/test_conftest_offscreen_fallback.py。
"""
from __future__ import annotations

import os


def _has_interactive_desktop() -> bool:
    """是否存在交互桌面会话（无头 CI/纯 SSH 控制台下 GetSystemMetrics 返回 0）。"""
    try:
        import ctypes

        return ctypes.windll.user32.GetSystemMetrics(0) > 0
    except Exception:  # noqa: BLE001  # 非 Windows / user32 不可用 → 按无桌面
        return False


def _apply_offscreen_fallback(has_desktop: bool) -> None:
    """无桌面时 setdefault 离屏；有桌面不动。判据可注入，供双向测试。"""
    if not has_desktop:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# 模块加载期执行：pytest 在收集任何测试模块（可能的 Qt import）之前加载本文件
_apply_offscreen_fallback(_has_interactive_desktop())


def pytest_sessionfinish(session, exitstatus) -> None:
    """无头平台下会话收尾有序析构 Qt 对象树（W19 主审）。

    背景：offscreen 平台下解释器卸载期随机原生堆损坏（实证 0xC0000374，
    用例全过但退出码 127/3；exit_guard × format_export 合跑触发、单文件
    不触发、minimal 平台不触发）。根因形态：会话泄漏的顶层 QWidget 与
    QApplication 在卸载期乱序析构。收尾时先逐个析构顶层 widget（每轮
    重查 topLevelWidgets——删父会级联析构子 wrapper，快照列表中的失效
    wrapper 再删即 double-free，isValid 防护），最后析构 QApplication，
    让 C++ 对象树在 DLL 卸载前有序销毁。仅无头平台生效；真窗平台
    （UIA）不受影响。
    """
    if os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal"):
        return
    try:
        import shiboken6
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        app.processEvents()
        for _ in range(200):
            pending = [
                w for w in app.topLevelWidgets() if shiboken6.isValid(w)
            ]
            if not pending:
                break
            try:
                shiboken6.delete(pending[0])
            except Exception:  # noqa: BLE001  # 单个失败继续清余下对象
                break
        shiboken6.delete(app)
    except Exception:  # noqa: BLE001  # 收尾兜底：任何失败不得改写退出码语义
        pass


# ============================== W39·v6 P3-16：FakeThread 单源收敛 ============================== #
# 原 21 个测试文件逐字复制此类与夹具（gui/core/jobs.py:20 记载接缝约束）；
# 本处为唯一定义，各文件本地副本已删，夹具经 pytest 自动发现生效。

import threading

import pytest


class FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def fake_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", FakeThread)
