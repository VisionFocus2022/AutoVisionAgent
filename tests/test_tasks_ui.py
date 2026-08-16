"""任务下拉与引擎注册表对齐测试（W1-T4，P1-1 第一步：宣称诚实化）。

架构审查发现：train/predict/eval 下拉恰好只暴露缺失的 det/seg/abdet，
已实现的 6 个引擎反而不可从 GUI 到达；且两条模拟训练假 loss 路径静默。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")  # 无 PySide6 则跳过本模块

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _registry():
    from models.supervised.engines import register_all_engines
    from models.supervised.registry import get_default_registry
    register_all_engines()
    return get_default_registry()


# ============================ populate_task_combo ============================ #

@pytest.mark.unit
def test_populate_lists_all_9_with_annotation(qapp):
    from gui.core.tasks_ui import populate_task_combo

    combo = QComboBox()
    items = populate_task_combo(combo, only_available=False, unavailable_suffix="（模拟）")
    assert combo.count() == len(TaskType) == 9
    assert combo.itemData(0) is TaskType.DET  # UIA 兼容：首项保持 DET
    reg = _registry()
    for i, (task, available) in enumerate(items):
        assert combo.itemData(i) is task
        assert available == reg.has(task)
        if not available:
            assert "模拟" in combo.itemText(i), f"{task} 缺引擎须有标注"
        else:
            assert "模拟" not in combo.itemText(i)


@pytest.mark.unit
def test_populate_available_only_matches_registry(qapp):
    from gui.core.tasks_ui import populate_task_combo

    reg = _registry()
    combo = QComboBox()
    items = populate_task_combo(combo, only_available=True)
    assert len(items) == len(reg.list()) >= 6
    assert all(available for _, available in items)
    assert {t for t, _ in items} == set(reg.list())


# ============================ 页面接线 ============================ #

@pytest.mark.unit
def test_train_page_combo_all_9_det_first(qapp):
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    combo = page.cmb_task
    assert combo.count() == 9
    assert combo.itemData(0) is TaskType.DET
    assert "模拟" in combo.itemText(0)  # det 引擎缺失 → 标注


@pytest.mark.unit
def test_predict_page_combo_registered_only(qapp):
    from gui.pages.predict.page import PredictPage

    reg = _registry()
    page = PredictPage()
    combo = page.cmb_task
    assert combo.count() == len(reg.list())
    for i in range(combo.count()):
        assert reg.has(combo.itemData(i)), f"第{i}项 {combo.itemData(i)} 未注册却出现在推理页"


# ============================ 模拟训练显式警告 ============================ #

@pytest.mark.unit
def test_make_trainer_warns_when_engine_not_registered(qapp):
    """引擎未注册（如 DET）走模拟策略时必须发出可见警告（W1 前为静默）。"""
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    messages: list[tuple[str, str]] = []
    page.status_changed.connect(lambda text, accent: messages.append((text, accent)))
    trainer = page._make_trainer(TrainConfig(task=TaskType.DET))
    assert trainer is not None
    assert any("模拟" in text for text, _ in messages), \
        f"引擎缺失路径未警告，收到: {messages!r}"


@pytest.mark.unit
def test_make_trainer_warns_when_engine_lacks_train_epoch(qapp):
    """引擎已注册但不支持逐轮训练（6 个现役引擎均如此）也必须警告。"""
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    messages: list[tuple[str, str]] = []
    page.status_changed.connect(lambda text, accent: messages.append((text, accent)))
    trainer = page._make_trainer(TrainConfig(task=TaskType.CLS))
    assert trainer is not None
    assert any("模拟" in text for text, _ in messages), \
        f"引擎无 train_epoch 路径未警告，收到: {messages!r}"


@pytest.mark.unit
def test_make_trainer_no_warning_suppressed_when_real_training_possible(qapp):
    """有 train_epoch 的引擎走真策略时不得弹模拟警告（防警告噪声）。"""
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    messages: list[tuple[str, str]] = []
    page.status_changed.connect(lambda text, accent: messages.append((text, accent)))

    class _TrainableEngine:
        task = TaskType.CLS

        def train_epoch(self, epoch, cfg):
            return {"loss": 0.5}

        def save(self, path):
            pass

    import models.supervised.registry as reg_mod
    reg = reg_mod.get_default_registry()
    orig_has, orig_get = reg.has, reg.get
    try:
        reg.has = lambda t: True if t is TaskType.CLS else orig_has(t)
        reg.get = lambda t: _TrainableEngine() if t is TaskType.CLS else orig_get(t)
        trainer = page._make_trainer(TrainConfig(task=TaskType.CLS))
        assert trainer is not None
        assert not any("模拟" in text for text, _ in messages), \
            f"真训练路径不应警告，收到: {messages!r}"
    finally:
        reg.has, reg.get = orig_has, orig_get
