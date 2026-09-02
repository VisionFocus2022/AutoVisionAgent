"""W57-A（FR-004）：任务级训练模板 loader 与 TrainConfig 扩展。

对标 SKolpha TrainConfigs（Fernet 加密模板 + my_* 参数 30+）——AVA 复刻
「任务级默认 + UI 覆盖」能力面，模板为**明文 YAML**（加密为反面教材，
docs/skolpha-forensics-wave1.md §5）。

覆盖：AugmentationConfig 默认值与不可变 / TrainConfig 扩展向后兼容 /
模板加载（解析、tuple 转换、键） / 未知字段诚实报告 / 坏文件与缺目录容错 /
仓内正式模板盘点（≥9 任务码、明文、TaskType 全有效）。
"""
from __future__ import annotations

import pytest

from core.interfaces_supervised import AugmentationConfig, TaskType, TrainConfig
from training.train_templates import (
    REPO_TEMPLATE_DIR,
    load_templates,
    validate_raw,
)

# ============================== AugmentationConfig ============================== #


@pytest.mark.unit
def test_augmentation_config_defaults():
    """默认值 = 设计基线（ImageNet 口径 + SKolpha 关键参数对标值）。"""
    aug = AugmentationConfig()
    assert aug.hflip == 0.5
    assert aug.vflip == 0.0
    assert aug.rotate_max == 10
    assert aug.translate == 0.1
    assert aug.crop_scale == (0.8, 1.2)
    assert aug.mean == (0.485, 0.456, 0.406)
    assert aug.std == (0.229, 0.224, 0.225)
    assert aug.split_ratio == 0.8
    assert aug.data_expansion == 0


@pytest.mark.unit
def test_augmentation_config_frozen():
    aug = AugmentationConfig()
    with pytest.raises(Exception):  # noqa: B017  # FrozenInstanceError 系
        aug.hflip = 0.9


@pytest.mark.unit
def test_train_config_augmentation_backward_compatible():
    """旧构造（不传 augmentation）= None，零行为变化。"""
    cfg = TrainConfig(task=TaskType.DET)
    assert cfg.augmentation is None


# ============================== 模板加载 ============================== #


@pytest.mark.unit
def test_load_templates_parses_files(tmp_path):
    (tmp_path / "det_normal.yaml").write_text(
        "task: det\nvariant: normal\nbackbone: yolov8s\nimg_size: 640\n"
        "batch_size: 16\nlr: 0.002\n"
        "augmentation:\n"
        "  hflip: 0.3\n"
        "  crop_scale: [0.9, 1.1]\n"
        "  mean: [0.5, 0.5, 0.5]\n",
        encoding="utf-8",
    )
    (tmp_path / "pseg_normal.yaml").write_text(
        "task: pseg\nvariant: normal\nbackbone: yolov8n-seg\nimg_size: 640\n",
        encoding="utf-8",
    )
    templates = load_templates(str(tmp_path))
    assert set(templates.keys()) == {("det", "normal"), ("pseg", "normal")}

    det = templates[("det", "normal")]
    assert det.task is TaskType.DET
    assert det.backbone == "yolov8s"
    assert det.batch_size == 16
    assert det.lr == 0.002
    assert det.img_size == 640
    # list → tuple 归一（不可变惯例）
    assert det.augmentation.crop_scale == (0.9, 1.1)
    assert det.augmentation.mean == (0.5, 0.5, 0.5)
    # 未给字段用默认
    assert det.augmentation.hflip == 0.3
    assert det.augmentation.rotate_max == 10

    # 未给 augmentation 段 → 整段默认
    assert templates[("pseg", "normal")].augmentation == AugmentationConfig()


@pytest.mark.unit
def test_validate_raw_reports_unknown_fields():
    raw = {
        "task": "det", "variant": "normal", "backbone": "yolov8n",
        "my_scale_factor": 3,  # 未知顶层字段（SKolpha my_* 风格示例）
        "augmentation": {"hflip": 0.5, "mosaic_prob": 0.8},  # 未知增强字段
    }
    unknown = validate_raw(raw)
    assert "my_scale_factor" in unknown
    assert "augmentation.mosaic_prob" in unknown


@pytest.mark.unit
def test_load_templates_unknown_field_still_loads(tmp_path):
    (tmp_path / "det_normal.yaml").write_text(
        "task: det\nvariant: normal\nbackbone: yolov8n\nmy_scale_factor: 3\n",
        encoding="utf-8",
    )
    templates = load_templates(str(tmp_path))
    assert ("det", "normal") in templates  # 未知字段告警不中断


@pytest.mark.unit
def test_load_templates_missing_dir_returns_empty(tmp_path):
    assert load_templates(str(tmp_path / "nope")) == {}


@pytest.mark.unit
def test_load_templates_corrupt_file_skipped(tmp_path):
    (tmp_path / "det_normal.yaml").write_text(
        "task: det\nvariant: normal\nbackbone: yolov8n\n", encoding="utf-8"
    )
    (tmp_path / "bad.yaml").write_text(
        "task: [unclosed\n  bad yaml", encoding="utf-8"
    )
    templates = load_templates(str(tmp_path))
    assert set(templates.keys()) == {("det", "normal")}


@pytest.mark.unit
def test_load_templates_invalid_task_skipped(tmp_path):
    (tmp_path / "notatask_normal.yaml").write_text(
        "task: notatask\nvariant: normal\nbackbone: x\n", encoding="utf-8"
    )
    assert load_templates(str(tmp_path)) == {}


# ============================== 仓内正式模板盘点 ============================== #


@pytest.mark.unit
def test_repo_templates_cover_all_trainable_tasks():
    """≥9 可训练任务码全覆盖（ocr 推理-only 除外）+ 明文（无密文形态）。"""
    templates = load_templates(str(REPO_TEMPLATE_DIR))
    trainable = {
        t.value for t in TaskType
        if t is not TaskType.OCR  # ocr 训练页不列（W32 推理-only）
    }
    covered = {task for task, _variant in templates}
    assert trainable <= covered, (
        f"任务码缺模板: {sorted(trainable - covered)}（盘点={sorted(covered)}）"
    )


@pytest.mark.unit
def test_repo_templates_are_plaintext():
    for f in REPO_TEMPLATE_DIR.glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "gAAAAA" not in text, f"{f.name} 含 Fernet 密文形态"

