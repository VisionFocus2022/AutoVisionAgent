"""向导链真训练 UIA 用例：标注 → 下一步：数据管理 → 下一步：训练 →
开始训练 → 真 ultralytics 训练（W70 创建，PRD docs/prd-wizard-chain-real-train.md）。

覆盖本会话全部向导修复的端到端回归：
  W59b 同名 JSON 识别（文件列表 ● 前缀 + 空画布自动载入）
  W62 标注→数据管理目录交接（落地即见缩略图/已标注）
  W63/W65 数据管理→训练交接 + 自动导出补缺（_auto_export/yolo/data.yaml）
  W69 任务按数据格式自动选择（多边形 → 分割）
  W58/W69 真 ultralytics 训练（seg，2 epochs，cuda）+ 真权重产物

被测应用：dist\\AutoVisionAgent\\AutoVisionAgent.exe（默认）或
AVA_UIA_SOURCE=python 源码模式。真训练约 2-4 分钟（含权重冷读）。

运行::

    .venv/Scripts/python.exe -m pytest tests/uia/test_wizard_chain_real_train.py -v -s --no-cov

前提：桌面会话可用；无 AutoVisionAgent 实例在跑；GPU 空闲（训练步）。
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
        app_log_path,
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
        app_log_path,
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
T_EXPORT = 150.0   # W65 自动导出（小数据集秒级，留裕量）
T_TRAIN = float(os.environ.get("AVA_UIA_T_TRAIN", "600"))  # 真训练 2 epochs


@pytest.fixture()
def annotated_dir(tmp_path_factory):
    """2 张 png + 同名 LabelMe 多边形 JSON（向导链起点：已标注状态）。"""
    import cv2
    import numpy as np

    d = tmp_path_factory.mktemp("wizard_ann")
    for i in range(2):
        img = np.zeros((96, 96, 3), np.uint8)
        img[24:72, 24:72] = 140
        ok, buf = cv2.imencode(".png", img)
        assert ok
        (d / f"pole{i}.png").write_bytes(buf.tobytes())
        (d / f"pole{i}.json").write_text(
            json.dumps({
                "version": "5.4.3",
                "imagePath": f"pole{i}.png",
                "imageWidth": 96, "imageHeight": 96,
                "shapes": [{
                    "label": "defect", "shape_type": "polygon",
                    "points": [[30, 30], [66, 30], [66, 66], [30, 66]],
                }],
            }),
            encoding="utf-8",
        )
    return d


def _status(win) -> str:
    try:
        return read_status_text(win)
    except Exception:  # noqa: BLE001
        return "<读取失败>"


def _app_log_tail(n: int = 40) -> str:
    try:
        with open(app_log_path(), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def test_wizard_chain_label_to_real_train(ready_admin_cfg, ava_app,
                                           annotated_dir):
    """向导链端到端：标注（已标注态）→ 数据管理 → 训练 → 真训练铁证。"""
    win = ava_app
    login_admin(win)

    # ---- 步骤1：标注页打开已标注文件夹（W59b 识别 + W62 交接上下文源）----
    logger.info("--- 步骤1：标注页 ---")
    assert click_nav(win, "标注", T_NAV)
    time.sleep(1.0)
    assert click_button(win, "打开文件夹", T_NAV)
    assert enter_path_in_open_dialog("打开文件夹", str(annotated_dir), T_NAV)

    # W59b「已载入」为瞬态（毫秒级被「已加载 N 张」覆盖，离屏实证状态序），
    # 持久证据用文件列表 ● 前缀；自动载入的形状随后经导出链闭环验证
    time.sleep(1.0)
    # 文件列表 ● 前缀标记（W59b）；右侧「标签列表」的形状项（如
    # "#1 [polygon] defect"）是自动载入多边形的伴随铁证，按扩展名分流
    names = []
    for c in _iter_descendants(win, max_depth=10):
        try:
            if type(c).__name__ == "ListItemControl" and c.Name:
                names.append(c.Name)
        except Exception:  # noqa: BLE001
            continue
        if len(names) >= 6:
            break
    files = [n for n in names if n.endswith((".png", ".bmp", ".jpg"))]
    assert len(files) >= 2 and all(n.startswith("●") for n in files[:2]), (
        f"文件列表应有 ● 前缀（W59b），实得: {names[:6]}"
    )
    shape_items = [n for n in names if "polygon" in n or "rectangle" in n]
    logger.info("W59b ● 标记: %s | 自动载入形状: %s", files[:2], shape_items[:2])
    assert shape_items, (
        f"标签列表应出现自动载入的形状项（W59b 自动载入），实得: {names[:6]}"
    )

    # ---- 步骤2：下一步 → 数据管理（W62 目录交接）----
    logger.info("--- 步骤2：下一步 → 数据管理 ---")
    assert click_button(win, "下一步：数据管理", T_NAV)
    time.sleep(2.0)
    assert find_control_by_name(win, "导出训练集",
                                ["ButtonControl"], T_NAV) is not None, (
        "未切到数据管理页（W62 向导导航失效）"
    )
    thumbs = [
        c.Name for c in _iter_descendants(win, max_depth=12)
        if type(c).__name__ == "ListItemControl" and (c.Name or "").endswith(
            (".png", ".bmp", ".jpg")
        )
    ]
    assert len(thumbs) >= 2, (
        f"W62 目录交接后缩略图应≥2（实得 {len(thumbs)}: {thumbs[:3]}）"
    )
    logger.info("W62 交接缩略图: %d 张", len(thumbs))

    # ---- 步骤3：下一步 → 训练（W65 自动导出补缺 + 回填 + W69 自动选任务）----
    logger.info("--- 步骤3：下一步 → 训练（自动导出）---")
    assert click_button(win, "下一步：训练", T_NAV)
    # 「数据集 train=N」为瞬态，终态是 W69 的「任务已按数据格式自动选择」
    # （同一回填钩子先后发出）——等任一即证导出+回填链完成
    stats = wait_any_status(
        win, ["任务已按数据格式自动选择", "数据集"], T_EXPORT
    )
    assert stats is not None, (
        f"自动导出+数据集回填未完成，状态='{_status(win)}'"
    )
    logger.info("W65 自动导出+回填+W69 自动选任务: %s", stats)
    yaml_path = annotated_dir.parent / "_auto_export" / "yolo" / "data.yaml"
    assert yaml_path.is_file(), f"W65 自动导出产物缺失: {yaml_path}"
    # P0-1 起划分布局 labels/{train,val}/*.txt——rglob 兼容新旧两种形态
    labels = list(
        (yaml_path.parent / "labels").rglob("*.txt")
    ) if (yaml_path.parent / "labels").is_dir() else []
    assert len(labels) == 2, (
        f"自动导出应含 2 个标签文件（样本数铁证），实得 {len(labels)}"
    )

    # ---- 步骤4：开始训练（epochs 100→2；任务由 W69 按数据自动=分割）----
    logger.info("--- 步骤4：开始训练（真 ultralytics）---")
    assert set_spinner_value(win, 2, expect_current=100, index=0), (
        "轮数 Spinner 设值失败"
    )
    btn = find_control_by_name(
        win, "开始训练", ["ButtonControl", "CheckBoxControl"], T_NAV
    )
    assert btn is not None, "未找到'开始训练'"
    btn.GetPattern(10000).Invoke()  # Invoke 优先（W64 免鼠标通道）

    final = wait_any_status(
        win,
        ["训练完成", "训练失败", "未选择数据集", "引擎不支持"],
        T_TRAIN,
    )
    assert final is not None, (
        f"训练未结束，最后状态='{_status(win)}'（日志尾见 app_log_path()）"
    )
    assert "完成" in final, (
        f"训练未成功: {final!r}（最后='{_status(win)}'，"
        f"日志尾:\n{_app_log_tail()}"
    )

    # ---- 铁证：真 seg 训练（W69 自动任务）+ 真权重 ----
    log_tail = _app_log_tail()
    assert "训练开始: task=seg" in log_tail, (
        f"应为真 seg 训练（W69 按多边形数据自动选任务），日志尾:\n{log_tail}"
    )
    # W1-6：小数据（N=2≤50）轮数自适应 2→100——完成口径以 epochs_effective
    # 为准（一次性适配器外层计数会低估），并断言自适应留痕在日志
    import re as _re

    m = _re.search(r"epochs_completed=(\d+)", log_tail)
    assert m and int(m.group(1)) == 100, (
        f"W1-6 自适应后应完成 100 epochs，日志尾:\n{log_tail}"
    )
    assert "自适应提升" in log_tail, (
        f"应有小数据自适应提升留痕，日志尾:\n{log_tail}"
    )
    from pathlib import Path
    seg_final = (
        Path(__file__).resolve().parents[2]
        / "dist" / "AutoVisionAgent" / "outputs" / "seg_final.pt"
    )
    if not seg_final.is_file():  # python 源码模式产物在仓根 outputs/
        seg_final = Path(__file__).resolve().parents[2] / "outputs" / \
            "seg_final.pt"
    assert seg_final.is_file(), f"真训练产物缺失: {seg_final}"
    size = seg_final.stat().st_size
    logger.info("真训练铁证: task=seg, 100 epochs(W1-6 自适应), seg_final.pt=%.2f MB",
                size / 1048576)
    assert size > 1024 * 1024, f"权重过小疑似模拟产物: {size}"
