"""W1-2 训练历史与模型资产 UIA 用例（PRD docs/prd-w1-2-train-history.md）。

DoD（roadmap W1-2）：训练完成→历史出现→模型卡（类别表/输入尺寸）→
一键加载→推理出结果。

链路：数据管理选已标注目录 → 下一步：训练（自动导出+自动 seg）→
epochs=2（自适应 100）→ 开始训练 → 完成后切「训练历史」→ 新行 + 模型卡
（defect/640 在屏）→ 加载推理 → 推理页「模型已加载」→ 单张推理出「分数」。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_train_history_w1_2.py -v -s --no-cov
"""
from __future__ import annotations

import json
import logging
import os
import time

import pytest

try:
    from tests.uia.uia_helpers import (
        _iter_descendants,
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        set_spinner_value,
        wait_any_status,
    )
except ImportError:  # pragma: no cover - 顶层模式兜底
    from uia_helpers import (  # type: ignore[no-redef]
        _iter_descendants,
        click_button,
        click_nav,
        enter_path_in_open_dialog,
        find_control_by_name,
        login_admin,
        read_status_text,
        set_spinner_value,
        wait_any_status,
    )

logger = logging.getLogger(__name__)

T_NAV = float(os.environ.get("AVA_UIA_T_NAV", "20"))
T_EXPORT = 150.0
T_TRAIN = float(os.environ.get("AVA_UIA_T_TRAIN", "900"))
T_LOAD = 180.0


@pytest.fixture()
def annotated_dir(tmp_path_factory):
    """2 张 png + 同名 LabelMe 多边形 JSON（真 seg 数据）。"""
    import cv2
    import numpy as np

    d = tmp_path_factory.mktemp("w12_hist")
    for i in range(2):
        img = np.zeros((96, 96, 3), np.uint8)
        img[24:72, 24:72] = 140
        ok, buf = cv2.imencode(".png", img)
        assert ok
        (d / f"h{i}.png").write_bytes(buf.tobytes())
        (d / f"h{i}.json").write_text(
            json.dumps({
                "version": "5.4.3",
                "imagePath": f"h{i}.png",
                "imageWidth": 96, "imageHeight": 96,
                "shapes": [{
                    "label": "defect", "shape_type": "polygon",
                    "points": [[30, 30], [66, 30], [66, 66], [30, 66]],
                }],
            }),
            encoding="utf-8",
        )
    return d


def test_train_history_card_and_one_click_infer(ready_admin_cfg, ava_app,
                                                annotated_dir):
    """W1-2 DoD 全链：历史出现→模型卡→一键加载→推理出结果。"""
    win = ava_app
    login_admin(win)

    # ---- 训练（复用向导链：数据管理→下一步：训练→真训练）----
    assert click_nav(win, "数据管理", T_NAV)
    time.sleep(1.0)
    assert click_button(win, "选择目录", T_NAV)
    assert enter_path_in_open_dialog("选择目录", str(annotated_dir), T_NAV)
    time.sleep(1.5)
    assert click_button(win, "下一步：训练", T_NAV)
    stats = wait_any_status(win, ["任务已按数据格式自动选择", "数据集"], T_EXPORT)
    assert stats, f"自动导出超时: {read_status_text(win)!r}"
    assert set_spinner_value(win, 2, expect_current=100, index=0)
    btn = find_control_by_name(win, "开始训练",
                               ["ButtonControl", "CheckBoxControl"], T_NAV)
    assert btn is not None
    btn.GetPattern(10000).Invoke()
    final = wait_any_status(
        win, ["训练完成", "训练失败", "未选择数据集"], T_TRAIN)
    assert final and "完成" in final, f"训练未成功: {final!r}"
    logger.info("训练完成: %s", final)

    # ---- DoD-1：训练历史出现新记录 ----
    assert click_nav(win, "训练历史", T_NAV), "未找到「训练历史」导航"
    time.sleep(1.5)
    assert find_control_by_name(win, "seg", None, 10) is not None, (
        "历史表应出现 seg 记录行"
    )
    logger.info("历史页出现 seg 记录")

    # ---- DoD-2：模型卡含类别表/输入尺寸（工具栏操作作用于选中行——
    # 行内嵌按钮不入 UIA 可访问树，exe 探针实证 2026-10-07）----
    assert click_button(win, "模型卡", T_NAV), "未找到工具栏「模型卡」"
    time.sleep(1.5)
    texts = " ".join(
        (c.Name or "") for c in _iter_descendants(win, max_depth=14)
        if type(c).__name__ in ("TextControl", "EditControl", "WindowControl")
    )
    assert "defect" in texts, f"模型卡应含类别表 defect: {texts[:400]}"
    assert "640" in texts, f"模型卡应含输入尺寸 640: {texts[:400]}"
    logger.info("模型卡含类别表+输入尺寸")
    close = find_control_by_name(win, "关闭", ["ButtonControl"], 5)
    if close is not None:
        close.GetPattern(10000).Invoke()
        time.sleep(0.8)

    # ---- DoD-3：一键加载推理（工具栏）----
    assert click_button(win, "加载推理", T_NAV), "未找到工具栏「加载推理」"
    st = wait_any_status(win, ["模型已加载", "加载失败", "引擎未注册"], T_LOAD)
    assert st and "模型已加载" in st, f"一键加载失败: {st!r}"
    logger.info("一键加载成功: %s", st)

    # ---- DoD-4：推理出结果（单张）----
    assert click_button(win, "单张推理", T_NAV)
    img = sorted(annotated_dir.glob("h*.png"))[0]
    assert enter_path_in_open_dialog("选择图像", str(img), T_NAV)
    st = wait_any_status(win, ["分数", "推理失败"], 120)
    assert st and "分数" in st, f"推理未出结果: {st!r}"
    logger.info("W1-2 DoD 四证齐: 历史行+模型卡+一键加载+推理分数")
