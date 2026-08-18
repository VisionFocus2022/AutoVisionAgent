"""W18（v3 P2-7）：GUI 进程 registry 直连正式化守卫。

用户拍板（2026-08-17）：承认 registry 直连为 GUI 正式形态，dispatcher 降级
serving 进程专用（多引擎 LRU 显存治理）。gui/ 包内不得再出现：
- dispatcher 三关键词（industrial_vision_platform / get_dispatcher /
  VisionModelDispatcher）——label 页零样本桥已删（W18）；
- _EngineStub——deploy 页导出已改显式参数（W18），无需引擎桩包装。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_GUI_ROOT = Path(__file__).resolve().parent.parent / "gui"

_FORBIDDEN = (
    "industrial_vision_platform",
    "get_dispatcher",
    "VisionModelDispatcher",
    "_EngineStub",
)


def _gui_sources() -> list:
    return [p for p in sorted(_GUI_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def test_gui_sources_discovered():
    """前置健全性：gui/ 下确有源码（守卫不空转）。"""
    sources = _gui_sources()
    assert len(sources) > 10, f"gui/ 源码发现异常: {len(sources)} 个文件"
    assert any(p.name == "page.py" for p in sources)


@pytest.mark.parametrize("keyword", _FORBIDDEN)
def test_gui_package_free_of_dispatcher_and_engine_stub(keyword):
    """gui/ 全部 .py 源码中 dispatcher 三关键词与 _EngineStub 零命中。"""
    offenders = [
        str(p.relative_to(_GUI_ROOT))
        for p in _gui_sources()
        if keyword in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"gui/ 中残留 {keyword!r}（v3 P2-7：dispatcher 为 serving 专用，"
        f"GUI 为 registry 直连）: {offenders}"
    )
