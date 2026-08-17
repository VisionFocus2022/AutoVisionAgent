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
