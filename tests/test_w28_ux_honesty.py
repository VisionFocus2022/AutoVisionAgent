"""W28（W26 计划 P1）：flaw_gen 三修 + 主页 refresh_recent 生产接线。

flaw_gen（对标审查信任债三处）：
1. 「本页建设中」横幅（55-60）——SGAN 引擎 W2 已真化，横幅是过期话术。
2. 生成模式死下拉（101-104）——"随机混合/指定缺陷类型"持久化选择但
   引擎 infer 从不消费，纯装饰。
3. engine.load device 硬编码 "cpu"（186）——改 resolve_device 契约
   （W19/W21 同款，有 GPU 的机器白费）。

主页：refresh_recent/refresh_history 生产态从未被调用——最近项目列表
与检测历史统计恒空/恒旧（登录成功与项目打开两处接线）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

REPO_ROOT = Path(__file__).resolve().parents[1]
FLAW_GEN = REPO_ROOT / "gui" / "pages" / "flaw_gen" / "page.py"
MAIN_PY = REPO_ROOT / "gui" / "main.py"


# ============================== flaw_gen 三修 ============================== #


@pytest.mark.unit
def test_flaw_gen_no_stale_banner():
    """删除「本页建设中」横幅（SGAN 引擎已真化，横幅为过期话术）。"""
    src = FLAW_GEN.read_text(encoding="utf-8")
    assert "本页建设中" not in src, "flaw_gen 不得再宣称建设中（W2 已实装）"


@pytest.mark.unit
def test_flaw_gen_no_dead_mode_combo():
    """删除生成模式死下拉（选择从未传给引擎，纯装饰）。"""
    src = FLAW_GEN.read_text(encoding="utf-8")
    assert "_mode_combo" not in src, "生成模式下拉无消费方——应删除或接线"


@pytest.mark.unit
def test_flaw_gen_load_uses_resolve_device():
    """engine.load device 走 resolve_device 契约（W19/W21 同款源码守卫）。"""
    src = FLAW_GEN.read_text(encoding="utf-8")
    load_lines = [ln for ln in src.splitlines() if "engine.load(" in ln]
    assert load_lines, "flaw_gen 应有 engine.load( 调用"
    assert any("resolve_device" in ln for ln in load_lines), (
        f"SGAN 加载须走 resolve_device 契约，实际: {load_lines}"
    )


# ============================== 主页接线 ============================== #


@pytest.mark.unit
def test_main_wires_home_recent_and_history_refresh():
    """gui/main.py 生产态接线：登录成功/项目打开 → 刷新最近项目与检测历史。"""
    src = MAIN_PY.read_text(encoding="utf-8")
    assert "refresh_recent(" in src, "refresh_recent 必须有生产调用方（现恒空列表）"
    assert "refresh_history(" in src, "refresh_history 必须有生产调用方（现恒旧统计）"
