"""W11-R1 RED→GREEN：最终权重保存失败不得被吞（架构审查 v2 P1-3）。

修复前：fit 捕获最终权重保存异常后仅 logger.exception，仍把
artifact.weights_path 指向不存在的文件并上报“训练完成”——
UI 显示成功但磁盘上没有权重，后续 predict/deploy 全部踩空。

修复后：最终权重保存失败 raise RuntimeError（消息含 final_path 与原因），
由 TrainWorker.failed 路由到 UI；周期 checkpoint 保存保持 best-effort
（失败仅记日志，不中断训练）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.interfaces_supervised import TaskType, TrainConfig
from training.generic_trainer import GenericTrainer


class _SaveFailStrategy:
    """假策略：train_epoch 恒定 loss；save 可按路径子串选择性抛 OSError。"""

    def __init__(self, fail_on: str = "_final.pt"):
        self.fail_on = fail_on
        self.epochs_run = []
        self.saved = []

    def train_epoch(self, epoch, cfg):
        self.epochs_run.append(epoch)
        return {"loss": 1.0}

    def save(self, path):
        p = str(path)
        self.saved.append(p)
        if self.fail_on in p:
            raise OSError("disk full")
        Path(p).write_bytes(b"w")  # 成功路径真实落盘（同族 FakeStrategy 做法）

    def get_optimizer(self):
        return None


def _cfg(tmp_path, **kw):
    base = dict(
        task=TaskType.CLS,
        epochs=2,
        lr=0.01,
        output_dir=str(tmp_path / "out"),
        lr_scheduler="none",
        warmup_epochs=0,
        patience=0,
    )
    base.update(kw)
    return TrainConfig(**base)


@pytest.mark.unit
def test_final_save_failure_raises_runtime_error_with_path_and_cause(tmp_path):
    """最终权重保存抛 OSError → fit 必须 raise RuntimeError，
    消息含最终权重路径与原始原因，而非吞掉后照常返回产物。"""
    strat = _SaveFailStrategy(fail_on="_final.pt")
    trainer = GenericTrainer(TaskType.CLS, strat)
    final_path = os.path.join(str(tmp_path / "out"), "cls_final.pt")

    with pytest.raises(RuntimeError) as ei:
        trainer.fit(_cfg(tmp_path))

    assert final_path in str(ei.value)  # 消息含最终权重路径
    assert "disk full" in str(ei.value)  # 消息含原始原因


@pytest.mark.unit
def test_final_save_failure_leaves_no_bogus_artifact(tmp_path):
    """保存失败时最终权重文件确实不存在——证明 raise 前没有谎报产物。"""
    strat = _SaveFailStrategy(fail_on="_final.pt")
    trainer = GenericTrainer(TaskType.CLS, strat)

    with pytest.raises(RuntimeError):
        trainer.fit(_cfg(tmp_path))

    assert not Path(os.path.join(str(tmp_path / "out"), "cls_final.pt")).exists()
    # 周期 checkpoint 不受影响（最后一轮 epoch 2 恒保存，成功落盘）
    assert Path(os.path.join(str(tmp_path / "out"), "checkpoints", "epoch_2.pt")).exists()


@pytest.mark.unit
def test_checkpoint_save_failure_is_best_effort(tmp_path):
    """周期 checkpoint 保存失败保持 best-effort：仅记日志、不中断训练，
    最终权重仍正常保存并返回产物。"""
    strat = _SaveFailStrategy(fail_on=os.sep + "checkpoints" + os.sep)
    art = GenericTrainer(TaskType.CLS, strat).fit(_cfg(tmp_path, checkpoint_every=1))

    assert strat.epochs_run == [1, 2]  # 训练未中断
    assert art.epochs_completed == 2
    assert Path(art.weights_path).exists()  # 最终权重照常落盘
