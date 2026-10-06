"""W1-3 模拟训练显式化测试（PRD docs/prd-w1-3-simulated-explicit.md）。

- AC-1 守护：逐引擎 hasattr(train_epoch) ⇔ REAL_TRAIN_TASKS
- AC-2 下拉：模拟任务灰显+后缀"（模拟训练）"；det/seg 无
- AC-3 启动：确认拒绝→零状态变更；放行→原流程
"""
from __future__ import annotations

import pytest

from core.interfaces_supervised import TaskType, TrainConfig
from models.supervised.registry import (
    REAL_TRAIN_TASKS,
    get_engine,
    task_supports_real_training,
)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.unit
class TestAc1RealTrainGuard:
    def test_every_engine_matches_registry_set(self):
        """全任务（除推理-only OCR）逐引擎核验真训练通道与集合一致。"""
        from models.supervised.engines import register_all_engines

        register_all_engines()  # 惰性注册显式触发（UI 侧经 registered_tasks）
        for task in TaskType:
            if task is TaskType.OCR:
                continue
            engine = get_engine(task)
            has = hasattr(engine, "train_epoch")
            assert has == task_supports_real_training(task), (
                f"{task.value}: hasattr(train_epoch)={has} 与 "
                f"REAL_TRAIN_TASKS 判定不符——新引擎实装后请同步集合"
            )

    def test_current_set_is_det_seg(self):
        assert frozenset({TaskType.DET, TaskType.SEG}) == REAL_TRAIN_TASKS


@pytest.mark.unit
class TestAc2ComboSimulatedStyle:
    def test_simulated_task_grayed_with_suffix(self, qapp):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QComboBox

        from gui.core.tasks_ui import populate_task_combo

        combo = QComboBox()
        simulated = frozenset(
            t for t in TaskType
            if t not in REAL_TRAIN_TASKS and t is not TaskType.OCR
        )
        populate_task_combo(
            combo, only_available=False,
            unavailable_suffix="（未装引擎·模拟）",
            simulated=simulated, exclude=(TaskType.OCR,),
        )
        by_task = {
            combo.itemData(i): i for i in range(combo.count())
        }
        # cls：引擎在但模拟训练 → 灰前景 + 后缀
        cls_idx = by_task[TaskType.CLS]
        assert "（模拟训练）" in combo.itemText(cls_idx)
        assert combo.itemData(cls_idx, Qt.ForegroundRole) is not None
        # det/seg：真训练 → 无模拟后缀、无灰显
        for t in (TaskType.DET, TaskType.SEG):
            idx = by_task[t]
            assert "（模拟训练）" not in combo.itemText(idx)
            assert combo.itemData(idx, Qt.ForegroundRole) is None


@pytest.mark.unit
class TestAc3StartConfirmGate:
    def _page(self, qapp, monkeypatch, confirm):
        from gui.pages.train import page as train_mod

        monkeypatch.setattr(train_mod, "TrainWorker", type("W", (), {}))
        monkeypatch.setattr(
            train_mod.TrainPage, "_confirm_simulated", lambda self: confirm
        )
        page = train_mod.TrainPage()
        msgs = []
        page.status_changed.connect(lambda t, a: msgs.append((t, a)))
        return page, msgs

    def test_will_be_simulated_matrix(self, qapp, monkeypatch):
        page, _ = self._page(qapp, monkeypatch, confirm=True)
        # det + 无数据集 → 模拟（W58 回退形态）
        assert page._will_be_simulated(
            TrainConfig(task=TaskType.DET, data_yaml="")
        )
        # det + 有数据集 → 真
        assert not page._will_be_simulated(
            TrainConfig(task=TaskType.DET, data_yaml="x.yaml")
        )
        # cls + 有数据集 → 仍模拟（无真通道）
        assert page._will_be_simulated(
            TrainConfig(task=TaskType.CLS, data_yaml="x.yaml")
        )

    def test_declined_confirm_zero_state_change(self, qapp, monkeypatch):
        """确认拒绝：不启动、不禁按钮、不锁表单、状态'已取消'。〔非 happy〕"""
        page, msgs = self._page(qapp, monkeypatch, confirm=False)
        monkeypatch.setattr(page, "_make_trainer", lambda cfg: (_ for _ in ()).throw(
            AssertionError("确认被拒后不得构建训练器")))
        page._start_training()
        assert page.btn_start.isEnabled() is True, "按钮不应被禁用"
        assert page.btn_stop.isEnabled() is False
        assert not any(t == "训练已启动" for t, _ in msgs)
        assert any("已取消" in t for t, _ in msgs)

    def test_accepted_confirm_proceeds(self, qapp, monkeypatch):
        from test_gui_train_page import FakeWorker

        page, msgs = self._page(qapp, monkeypatch, confirm=True)
        monkeypatch.setattr("gui.pages.train.page.TrainWorker", FakeWorker)
        monkeypatch.setattr(page, "_make_trainer", lambda cfg: object())
        page._start_training()
        assert any(t == "训练已启动" for t, _ in msgs)
