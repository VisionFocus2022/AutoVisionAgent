"""W57-B（FR-004）：训练页模板 UI（下拉回填 + 增强面板 + 诚实提示）。

覆盖：模板下拉盘点（仓内 11 份） / 选择回填表单（骨干/尺寸/批/学习率/任务）
/ 无模板不改表单 / TrainConfig 反映增强段 / 引擎不消费增强段的诚实提示 /
既有预设回归。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import AugmentationConfig, TaskType, TrainConfig  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def train_page(qapp):
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    yield page
    page.deleteLater()


def _status_log(page):
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    return msgs


# ============================== 模板下拉与回填 ============================== #


@pytest.mark.unit
def test_template_combo_lists_repo_templates(train_page):
    """下拉含「无模板」占位 + 仓内全部模板（≥11 份）。"""
    count = train_page.cmb_template.count()
    assert count >= 12  # 1 占位 + 11 模板
    assert train_page.cmb_template.itemData(0) is None  # 占位项


@pytest.mark.unit
def test_apply_template_backfills_form(train_page):
    """选 det/large → 骨干/尺寸/批/学习率/任务下拉全部回填。"""
    combo = train_page.cmb_template
    target = None
    for i in range(combo.count()):
        if combo.itemData(i) == ("det", "large"):
            target = i
            break
    assert target is not None, "det/large 模板未入下拉"

    combo.setCurrentIndex(target)
    assert train_page.txt_backbone.text() == "yolov8l"
    assert train_page.spin_img_size.value() == 1024
    assert train_page.spin_batch.value() == 4
    assert abs(train_page.spin_lr.value() - 0.0005) < 1e-9
    assert train_page.cmb_task.currentData() is TaskType.DET


@pytest.mark.unit
def test_apply_none_template_keeps_form(train_page):
    """占位项（无模板）不改表单。"""
    combo = train_page.cmb_template
    for i in range(combo.count()):
        if combo.itemData(i) == ("det", "large"):
            combo.setCurrentIndex(i)
            break
    before = train_page.txt_backbone.text()

    combo.setCurrentIndex(0)
    assert train_page.txt_backbone.text() == before


@pytest.mark.unit
def test_template_apply_emits_status(train_page):
    msgs = _status_log(train_page)
    combo = train_page.cmb_template
    for i in range(combo.count()):
        if combo.itemData(i) == ("pseg", "normal"):
            combo.setCurrentIndex(i)
            break
    assert any(t == "模板" for t, _a in msgs), f"应发模板状态提示，got {msgs[-3:]}"


# ============================== TrainConfig 增强段 ============================== #


@pytest.mark.unit
def test_build_config_includes_augmentation(train_page):
    """表单增强面板 → TrainConfig.augmentation（字段反映）。"""
    train_page.spin_aug_hflip.setValue(0.7)
    train_page.spin_aug_rotate.setValue(15)
    train_page.spin_aug_split.setValue(0.9)

    train_page.cmb_task.setCurrentIndex(0)  # det（首项契约）
    cfg = train_page._build_config()
    assert isinstance(cfg.augmentation, AugmentationConfig)
    assert cfg.augmentation.hflip == 0.7
    assert cfg.augmentation.rotate_max == 15
    assert abs(cfg.augmentation.split_ratio - 0.9) < 1e-9
    # 未动字段保持默认
    assert cfg.augmentation.vflip == 0.0


# ============================== 诚实提示 ============================== #


@pytest.mark.unit
def test_augmentation_hint_fires_when_engine_ignores(train_page):
    """增强段非空 + 引擎不消费 → 状态栏诚实提示（当前引擎忽略增强参数）。"""
    cfg = TrainConfig(task=TaskType.DET, augmentation=AugmentationConfig())
    msgs = _status_log(train_page)
    train_page._hint_augmentation_support(cfg)
    assert any("忽略增强参数" in a for _t, a in msgs), (
        f"应发引擎忽略增强提示，got {msgs}"
    )


@pytest.mark.unit
def test_augmentation_hint_silent_without_aug(train_page):
    cfg = TrainConfig(task=TaskType.DET)  # augmentation=None
    msgs = _status_log(train_page)
    train_page._hint_augmentation_support(cfg)
    assert msgs == []


# ============================== 既有预设回归 ============================== #


@pytest.mark.unit
def test_legacy_preset_still_works(train_page):
    """内置预设（W33 语义）不受模板行影响。"""
    combo = train_page.cmb_preset
    for i in range(combo.count()):
        if combo.itemData(i) == "small":
            combo.setCurrentIndex(i)
            break
    assert train_page.txt_backbone.text() == "yolov8s"
    assert train_page.spin_batch.value() == 16


@pytest.mark.unit
def test_template_augmentation_flows_into_config(train_page):
    """复核 MEDIUM 修正：模板增强段不再断链——面板外字段（mean/std）随行进
    TrainConfig，可调字段进面板。"""
    combo = train_page.cmb_template
    for i in range(combo.count()):
        if combo.itemData(i) == ("pseg", "normal"):
            combo.setCurrentIndex(i)
            break
    assert train_page.spin_aug_expansion.value() == 1  # 模板 data_expansion 进面板

    cfg = train_page._build_config()
    assert cfg.augmentation is not None
    assert cfg.augmentation.data_expansion == 1
    assert abs(cfg.augmentation.mean[0] - 0.2209) < 1e-4  # 面板外字段来自模板
    assert cfg.augmentation.split_ratio == 0.8

    # 切回占位 → 模板基底清空（全默认）
    combo.setCurrentIndex(0)
    cfg2 = train_page._build_config()
    assert cfg2.augmentation is not None
    assert cfg2.augmentation.mean == (0.485, 0.456, 0.406)
