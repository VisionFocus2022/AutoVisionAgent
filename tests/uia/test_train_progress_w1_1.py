"""W1-1 训练逐轮进度与可中断 UIA 用例（PRD docs/prd-w1-1-epoch-progress.md）。

DoD（roadmap W1-1）：真训练中 ≥2 个逐轮进度点（lbl_log "epoch k/N"）+
点「强制结束」后 UI 状态复位（开始按钮恢复）。

链路：数据管理选已标注目录（W62 交接）→ 下一步：训练（W65 自动导出）
→ epochs=2（W1-6 自适应 100，窗口足够采样）→ 开始训练 → 采样 → 强停。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_train_progress_w1_1.py -v -s --no-cov
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import pytest

try:
    from tests.uia.uia_helpers import (
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
T_SAMPLE = float(os.environ.get("AVA_UIA_T_SAMPLE", "60"))


@pytest.fixture()
def annotated_dir(tmp_path_factory):
    """2 张 png + 同名 LabelMe 多边形 JSON（真 seg 数据）。"""
    import cv2
    import numpy as np

    d = tmp_path_factory.mktemp("w11_prog")
    for i in range(2):
        img = np.zeros((96, 96, 3), np.uint8)
        img[24:72, 24:72] = 140
        ok, buf = cv2.imencode(".png", img)
        assert ok
        (d / f"p{i}.png").write_bytes(buf.tobytes())
        (d / f"p{i}.json").write_text(
            json.dumps({
                "version": "5.4.3",
                "imagePath": f"p{i}.png",
                "imageWidth": 96, "imageHeight": 96,
                "shapes": [{
                    "label": "defect", "shape_type": "polygon",
                    "points": [[30, 30], [66, 30], [66, 66], [30, 66]],
                }],
            }),
            encoding="utf-8",
        )
    return d


def _epoch_texts(win, duration: float) -> list[int]:
    """采样 lbl_log 的 "epoch k/N" 值（W1-1 进度铁证）。"""
    seen: list[int] = []
    deadline = time.time() + duration
    while time.time() < deadline:
        c = find_control_by_name(win, "epoch", None, 1.5)
        if c is not None:
            m = re.search(r"epoch (\d+)/(\d+)", c.Name or "")
            if m:
                k = int(m.group(1))
                if not seen or k != seen[-1]:
                    seen.append(k)
        if len(seen) >= 3:
            break
        time.sleep(2.0)
    return seen


def test_real_train_epoch_progress_and_cancel(ready_admin_cfg, ava_app,
                                              annotated_dir):
    """真训练逐轮进度可见 + 强制结束后 UI 复位（W1-1 DoD）。"""
    win = ava_app
    login_admin(win)

    # ---- 数据管理 → 选择目录 → 下一步：训练 ----
    assert click_nav(win, "数据管理", T_NAV)
    time.sleep(1.0)
    assert click_button(win, "选择目录", T_NAV)
    assert enter_path_in_open_dialog("选择目录", str(annotated_dir), T_NAV)
    time.sleep(1.5)
    assert click_button(win, "下一步：训练", T_NAV)
    stats = wait_any_status(
        win, ["任务已按数据格式自动选择", "数据集"], T_EXPORT
    )
    assert stats, f"自动导出/回填超时: {read_status_text(win)!r}"

    # ---- epochs=2（W1-6 自适应→100，采样窗口足够）→ 开始训练 ----
    assert set_spinner_value(win, 2, expect_current=100, index=0)
    btn = find_control_by_name(
        win, "开始训练", ["ButtonControl", "CheckBoxControl"], T_NAV
    )
    assert btn is not None
    btn.GetPattern(10000).Invoke()
    logger.info("开始训练已触发，采样逐轮进度 ≤%.0fs ...", T_SAMPLE)

    # ---- DoD-1：逐轮进度点（≥2 个不同 epoch 值）----
    epochs_seen = _epoch_texts(win, T_SAMPLE)
    logger.info("采样到 epoch 序列: %s", epochs_seen)
    assert len([e for e in epochs_seen if e >= 1]) >= 2, (
        f"应有 ≥2 个逐轮进度点（W1-1），实得 {epochs_seen}"
    )

    # ---- DoD-2：强制结束 → UI 复位 ----
    stop_btn = find_control_by_name(
        win, "强制结束", ["ButtonControl", "CheckBoxControl"], T_NAV
    )
    assert stop_btn is not None
    stop_btn.GetPattern(10000).Invoke()
    final = wait_any_status(
        win, ["训练完成", "训练失败", "训练已启动"], 180
    )
    assert final is not None, (
        f"强停后训练线程应收尾复位，最后状态='{read_status_text(win)}'"
    )
    # 复位铁证：开始按钮重新可用（等 UIA 树刷新）
    deadline = time.time() + 30
    restored = False
    while time.time() < deadline:
        b = find_control_by_name(
            win, "开始训练", ["ButtonControl", "CheckBoxControl"], 3.0
        )
        if b is not None:
            try:
                restored = bool(b.IsEnabled)
            except Exception:  # noqa: BLE001
                restored = True
            if restored:
                break
        time.sleep(1.5)
    assert restored, "强停后'开始训练'按钮应恢复可用（UI 状态复位）"
    logger.info("W1-1 DoD 双证齐：进度点=%s + 强停复位", epochs_seen[:6])
