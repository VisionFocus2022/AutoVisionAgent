"""W69：检测任务真训练通道 + 数据格式自动选任务（RED→GREEN）。

回归背景：用户截图——检测任务 100 轮秒完、loss 曲线教科书级光滑=模拟
训练。根因：W58 只给分割（SegYoloEngine→_YoloSegBase.train_epoch）建了
真通道，DetYoloEngine 无 train_epoch，检测任务必落「引擎不支持逐轮训练」
模拟回退；且任务下拉默认停在检测，与多边形数据集（分割格式）双重错配。

三件套（方案 A）：① DetYoloEngine 补 train_epoch（继承 ultralytics 训练
基座，det 权重解析不带 -seg 后缀，缺省回退随包 yolo26n.pt 离线可用）；
② 数据集回填时按标签格式自动选任务（>5 列=分割，5 列=检测）；
③ 开始训练守卫：任务与数据格式不符自动纠正+警告。
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ============================== ① det 真训练通道 ============================== #

@pytest.mark.unit
def test_det_engine_has_train_epoch():
    """检测引擎必须具备逐轮训练能力（W58 缺口补齐）。"""
    import models.supervised.engines.det_yolo  # noqa: F401  # 注册副作用
    from core.interfaces_supervised import TaskType
    from models.supervised.registry import get_default_registry

    engine = get_default_registry().get(TaskType.DET)
    assert hasattr(engine, "train_epoch"), (
        "DetYoloEngine 缺 train_epoch——检测任务仍会静默落模拟训练"
    )


@pytest.mark.unit
def test_resolve_backbone_det_falls_back_bundled_yolo26n(monkeypatch, tmp_path):
    """det 骨干 yolov8n 无本地权重 → 回退随包 yolo26n.pt（离线可用）。"""
    from models.supervised.engines import _yolo_seg_base as base_mod

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    bundled = tmp_path / "yolo26n.pt"
    bundled.write_bytes(b"w")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    resolved = base_mod._resolve_backbone("yolov8n", seg=False)
    assert resolved == str(bundled)


@pytest.mark.unit
def test_ensure_amp_asset_frozen_copies_from_meipass(monkeypatch, tmp_path):
    """W70：冻结态 AMP 检查资产（yolo26n.pt）从 _MEIPASS 落运行 CWD。

    ultralytics check_amp 按 CWD 找资产，miss 即联网下载——弱网悬挂
    训练（W70 exe 实证）；幂等：已在 CWD 则零操作。
    """
    from models.supervised.engines import _yolo_seg_base as base_mod

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    meipass = tmp_path / "internal"
    meipass.mkdir()
    (meipass / "yolo26n.pt").write_bytes(b"amp-asset")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert base_mod._ensure_amp_asset() is True
    assert (empty_cwd / "yolo26n.pt").read_bytes() == b"amp-asset"
    # 幂等
    assert base_mod._ensure_amp_asset() is False


@pytest.mark.unit
def test_ensure_amp_asset_dev_noop(monkeypatch, tmp_path):
    """源码模式零操作（不往开发仓根落文件）。"""
    from models.supervised.engines import _yolo_seg_base as base_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert base_mod._ensure_amp_asset() is False
    assert not (tmp_path / "yolo26n.pt").exists()


@pytest.mark.unit
def test_resolve_backbone_seg_default_unchanged(monkeypatch, tmp_path):
    """seg=True（默认）行为不回归：yolov8n → yolov8n-seg.pt。"""
    from models.supervised.engines import _yolo_seg_base as base_mod

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    bundled = tmp_path / "yolov8n-seg.pt"
    bundled.write_bytes(b"w")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert base_mod._resolve_backbone("yolov8n") == str(bundled)


@pytest.mark.e2e
def test_det_real_train_channel_smoke(tmp_path):
    """端到端冒烟：det 引擎在 2 图矩形数据集上真训练 1 epoch（cpu）。"""
    import cv2

    import models.supervised.engines.det_yolo  # noqa: F401  # 注册副作用
    from core.interfaces_supervised import TaskType, TrainConfig
    from models.supervised.registry import get_default_registry

    img_dir = tmp_path / "dataset" / "images"
    lbl_dir = tmp_path / "dataset" / "labels"
    img_dir.mkdir(parents=True)
    lbl_dir.mkdir()
    for i in range(2):
        img = np.zeros((160, 160, 3), np.uint8)
        img[40:120, 40:120] = 200
        ok, buf = cv2.imencode(".png", img)
        assert ok
        (img_dir / f"d{i}.png").write_bytes(buf.tobytes())
        # det 行：cls cx cy w h（5 列）
        (lbl_dir / f"d{i}.txt").write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
    yaml_path = tmp_path / "dataset" / "data.yaml"
    yaml_path.write_text(
        f"path: {tmp_path / 'dataset'}\ntrain: images\nval: images\n"
        "nc: 1\nnames:\n  0: defect\n",
        encoding="utf-8",
    )

    cfg = TrainConfig(
        task=TaskType.DET,
        epochs=1,
        batch_size=2,
        img_size=320,
        device="cpu",
        workers=0,
        backbone="yolov8n",
        output_dir=str(tmp_path / "out"),
        data_yaml=str(yaml_path),
    )
    engine = get_default_registry().get(TaskType.DET)
    metrics = engine.train_epoch(0, cfg)
    assert "loss" in metrics

    out_pt = tmp_path / "out" / "det_final.pt"
    engine.save(str(out_pt))
    assert out_pt.is_file(), f"det 真训练产物缺失: {out_pt}"
    assert out_pt.stat().st_size > 100 * 1024, (
        f"det 权重过小疑似假产物: {out_pt.stat().st_size}"
    )


# ============================== ② 标签格式自动选任务 ============================== #

def _mk_dataset(tmp_path, tokens: int):
    """导出器布局（images/ + labels/）+ 指定列数的标签行。"""
    base = tmp_path / "ds"
    (base / "images").mkdir(parents=True)
    (base / "labels").mkdir(parents=True)
    line = " ".join(["0"] + ["0.5"] * (tokens - 1))
    (base / "labels" / "a.txt").write_text(line + "\n", encoding="utf-8")
    yaml_path = base / "data.yaml"
    yaml_path.write_text(
        "train: images\nval: images\nnc: 1\nnames:\n  0: defect\n",
        encoding="utf-8",
    )
    return yaml_path


@pytest.mark.unit
def test_apply_external_dataset_autosets_seg(qapp, tmp_path):
    """分割格式（>5 列）数据集 → 任务自动切「分割」并状态告知。"""
    from core.interfaces_supervised import TaskType
    from gui.pages.train.page import TrainPage

    yaml_path = _mk_dataset(tmp_path, tokens=6)
    page = TrainPage()
    got = []
    page.status_changed.connect(lambda t, a: got.append((t, a)))

    page.apply_external_dataset(str(yaml_path))

    assert page.cmb_task.currentData() == TaskType.SEG, (
        "分割格式数据集应自动选分割任务"
    )
    assert any("任务" in t for t, _ in got)


@pytest.mark.unit
def test_apply_external_dataset_autosets_det(qapp, tmp_path):
    """检测格式（5 列）数据集 → 任务切「检测」。"""
    from core.interfaces_supervised import TaskType
    from gui.pages.train.page import TrainPage

    yaml_path = _mk_dataset(tmp_path, tokens=5)
    page = TrainPage()
    page.apply_external_dataset(str(yaml_path))

    assert page.cmb_task.currentData() == TaskType.DET


# ============================== ③ 启动守卫自动纠正 ============================== #

@pytest.mark.unit
def test_correct_task_for_dataset(qapp, tmp_path):
    """任务与数据格式不符 → 纠正为数据格式（模拟用户截图的 det+seg 场景）。"""
    from core.interfaces_supervised import TaskType, TrainConfig
    from gui.pages.train.page import TrainPage

    yaml_path = _mk_dataset(tmp_path, tokens=6)  # seg 格式
    page = TrainPage()
    page.txt_data.setText(str(yaml_path))

    cfg = TrainConfig(task=TaskType.DET, data_yaml=str(yaml_path))
    corrected, note = page._correct_task_for_dataset(cfg)

    assert corrected.task == TaskType.SEG, "det+seg 数据应纠正为分割"
    assert "分割" in note


@pytest.mark.unit
def test_correct_task_noop_when_match(qapp, tmp_path):
    """任务与数据格式一致 → 原样返回（零干扰）。"""
    from core.interfaces_supervised import TaskType, TrainConfig
    from gui.pages.train.page import TrainPage

    yaml_path = _mk_dataset(tmp_path, tokens=5)
    page = TrainPage()
    page.txt_data.setText(str(yaml_path))

    cfg = TrainConfig(task=TaskType.DET, data_yaml=str(yaml_path))
    corrected, note = page._correct_task_for_dataset(cfg)

    assert corrected.task == TaskType.DET
    assert note == ""
