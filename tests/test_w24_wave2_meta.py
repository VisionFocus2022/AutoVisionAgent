"""W24（v4 第二波 #6 + W23 遗留）：ADR 状态与 UIA 提示语——源码/文档守卫。"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_ADR = REPO_ROOT / "docs" / "adr" / "0002-serving-large-payload-evolution.md"


@pytest.mark.unit
def test_adr0002_declares_frozen_status():
    """v4 P3-2：ADR-0002 状态行须显式声明冻结（跨机场景再启）。

    W24 取证：C# 客户端零 lease/FetchRegion 调用（消费形态=内联+MMF
    直读双路径，Release 不带 lease_id）——PoC 双方向均未接线双端，
    状态行从「已接受」补冻结声明，收敛协议面预期（重开条件见 ADR §决策 4）。
    """
    text = _ADR.read_text(encoding="utf-8")
    assert "冻结" in text, "ADR-0002 状态行缺冻结声明"
    assert "跨机" in text, "冻结声明须标注跨机场景再启"
    assert "W24" in text, "冻结决策须留 W24/v4 P3-2 决策时点"


@pytest.mark.unit
def test_failure_hints_use_mode_aware_log_path():
    """UIA 失败提示语不得写死 logs/autovision.log（W23 后 python 模式日志
    在 AVA_LOG_DIR 会话目录，写死路径指向错误位置）。"""
    helpers = (
        REPO_ROOT / "tests" / "uia" / "uia_helpers.py"
    ).read_text(encoding="utf-8")
    assert "def app_log_path" in helpers, "uia_helpers 应提供 app_log_path()"
    assert "AVA_UIA_SOURCE" in helpers and "AVA_LOG_DIR" in helpers, (
        "app_log_path 应按 AVA_UIA_SOURCE 分支并读取 AVA_LOG_DIR"
    )
    for name in ("test_full_workflow.py", "test_pole_dataset_flows.py"):
        src = (REPO_ROOT / "tests" / "uia" / name).read_text(encoding="utf-8")
        assert "app_log_path" in src, f"{name} 失败提示应引用 app_log_path()"
        assert "logs/autovision.log" not in src, (
            f"{name} 仍写死 logs/autovision.log——python 模式下日志已被"
            f" AVA_LOG_DIR 重定向到会话临时目录"
        )
