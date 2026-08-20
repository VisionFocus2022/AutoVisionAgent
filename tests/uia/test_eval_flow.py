"""W25（FR-003）：eval 评估页 UIA——评估 UI 链路首条覆盖（此前 eval_flow
仅单测层覆盖，页面链路未验证）。

路径输入首选免对话框直填（T2a：eval 页恰 2 个 QLineEdit，模型框在前、
标注目录框在后——按 BoundingRectangle.top 排序分配，绕开两枚同名
"浏览..."按钮的配对问题）。
"""
from __future__ import annotations

import logging
import time

import pytest

try:
    from tests.uia.uia_helpers import (
        click_button,
        click_nav,
        find_control_by_name,
        find_edit_controls,
        set_edit_value,
        wait_any_status,
    )
    from tests.uia.test_pole_dataset_flows import _ensure_logged_in
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        click_button,
        click_nav,
        find_control_by_name,
        find_edit_controls,
        set_edit_value,
        wait_any_status,
    )
    from test_pole_dataset_flows import _ensure_logged_in  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

T_NAV = 20
T_EVAL = 120  # 引擎冷加载 + 逐 JSON 推理（实测热态 <1s、冷态 ~10-20s）


@pytest.mark.usefixtures("ava_app")
def test_eval_det_metrics(ava_app, tiny_det_model_path, eval_gt_dir):
    """det 评估：填模型+标注目录 → 开始评估 → 指标表展示 + 完成状态。"""
    win = ava_app
    _ensure_logged_in(win)

    assert click_nav(win, "评估", T_NAV), "无法切换到评估页"
    time.sleep(1.0)
    assert find_control_by_name(win, "开始评估", None, T_NAV) is not None, (
        "评估页未就绪（'开始评估'按钮不在场）"
    )

    # 直填两个路径框（当前页 UIA 只暴露当前页控件，模型框在前）
    edits = find_edit_controls(win, timeout=T_NAV)
    assert len(edits) >= 2, f"评估页应至少 2 个路径输入框，实得 {len(edits)}"
    edits_sorted = sorted(edits, key=lambda c: c.BoundingRectangle.top)
    assert set_edit_value(edits_sorted[0], str(tiny_det_model_path)), "模型路径写入失败"
    assert set_edit_value(edits_sorted[1], str(eval_gt_dir)), "标注目录写入失败"

    assert click_button(win, "开始评估", T_NAV), "未找到'开始评估'按钮"
    status = wait_any_status(win, ["评估完成", "评估失败"], T_EVAL)
    assert status and "评估完成" in status, f"评估未成功: {status!r}"
    assert "2 个指标" in status, f"指标计数异常（应 2 个）: {status!r}"

    # 指标表锚：det 指标行恒含 class_0 与 mAP（真引擎零检出值 0.0000）
    assert find_control_by_name(win, "mAP", None, 10) is not None, "指标表缺 mAP 行"
    assert find_control_by_name(win, "class_0", None, 10) is not None, (
        "指标表缺 class_0 行"
    )
