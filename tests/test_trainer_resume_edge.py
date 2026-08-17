"""W13-C2 RED→GREEN：resume 起点越过 cfg.epochs 时 fit 不得 NameError。

W12 行为保持重构时发现（当时未修）：checkpoint 元数据已记录 epoch=4，
而新会话 cfg.epochs=3（用户调小了轮数）→ _resume 返回 start_epoch=5 →
``range(5, 4)`` 为空 → 循环体不执行 → 循环后 ``artifact.epochs_completed = epoch``
引用未定义变量 → NameError。训练明明已无 epoch 可跑（本该直接收敛收尾），
却以崩溃收场，调用方（TrainWorker）只看到 failed 而拿不到产物。

同一边界还有 "checkpoint epoch == cfg.epochs"（训练已全部完成再 resume）：
start_epoch = epochs+1，``range(epochs+1, epochs+1)`` 同样为空。

不依赖 torch：走 sidecar ``.meta.json`` 元数据路径即可触发 _resume。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.interfaces_supervised import TaskType, TrainConfig
from training.generic_trainer import GenericTrainer


class _FakeStrategy:
    """假训练策略：记录实际训练过的 epoch；save 真实落盘。"""

    def __init__(self):
        self.epochs_run = []
        self.saved = []

    def train_epoch(self, epoch, cfg):
        self.epochs_run.append(epoch)
        return {"loss": 1.0}

    def save(self, path):
        self.saved.append(str(path))
        Path(path).write_bytes(b"w")

    def get_optimizer(self):
        return None


def _cfg(tmp_path, **kw):
    base = dict(
        task=TaskType.CLS,
        epochs=4,
        lr=0.01,
        output_dir=str(tmp_path / "out"),
        lr_scheduler="none",
        warmup_epochs=0,
        patience=0,
    )
    base.update(kw)
    return TrainConfig(**base)


def _write_ckpt_with_meta(tmp_path, epoch, best_metric=0.5, best_epoch=1):
    """造一个带 sidecar 元数据的 checkpoint（_resume 优先读取该路径）。"""
    ckpt_dir = tmp_path / "out" / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt = ckpt_dir / f"epoch_{epoch}.pt"
    ckpt.write_bytes(b"w")
    (ckpt_dir / f"epoch_{epoch}.pt.meta.json").write_text(
        json.dumps(
            {
                "epoch": epoch,
                "best_metric": best_metric,
                "best_epoch": best_epoch,
                "task": "cls",
            }
        ),
        encoding="utf-8",
    )
    return ckpt


@pytest.mark.unit
def test_resume_start_beyond_epochs_completes_gracefully(tmp_path):
    """checkpoint epoch=4 + cfg.epochs=3 → start_epoch=5 越过终点：
    fit 必须优雅完成——不训练任何 epoch、epochs_completed == start_epoch、
    最终权重照常落盘。修复前：循环后引用未定义的 epoch → NameError。"""
    ckpt = _write_ckpt_with_meta(tmp_path, epoch=4, best_metric=0.5, best_epoch=3)
    strat = _FakeStrategy()
    trainer = GenericTrainer(TaskType.CLS, strat)

    art = trainer.fit(_cfg(tmp_path, epochs=3, resume_from=str(ckpt)))

    assert strat.epochs_run == []  # 无 epoch 可跑，不该进循环
    assert art.epochs_completed == 5  # == start_epoch（epoch 4 已完成，下一轮才是 5）
    assert Path(art.weights_path).exists()  # 终态保存照常
    assert art.metrics == {}  # 本轮无新指标
    assert art.best_metric == pytest.approx(0.5)  # 自 checkpoint 元数据恢复


@pytest.mark.unit
def test_resume_already_fully_trained_boundary(tmp_path):
    """checkpoint epoch == cfg.epochs（4 轮已全部跑完再 resume）：
    start_epoch = 5、range(5, 5) 同样为空——同一边界的另一半。"""
    ckpt = _write_ckpt_with_meta(tmp_path, epoch=4)
    strat = _FakeStrategy()

    art = GenericTrainer(TaskType.CLS, strat).fit(
        _cfg(tmp_path, epochs=4, resume_from=str(ckpt))
    )

    assert strat.epochs_run == []
    assert art.epochs_completed == 5
    assert Path(art.weights_path).exists()


@pytest.mark.unit
def test_resume_before_epochs_still_trains_and_reports(tmp_path):
    """边界回归：start_epoch < epochs 的正常 resume 不受修复影响，
    续训剩余轮次且 epochs_completed == cfg.epochs。"""
    ckpt = _write_ckpt_with_meta(tmp_path, epoch=2)
    strat = _FakeStrategy()

    art = GenericTrainer(TaskType.CLS, strat).fit(
        _cfg(tmp_path, epochs=4, resume_from=str(ckpt))
    )

    assert strat.epochs_run == [3, 4]  # 从 epoch 3 续训
    assert art.epochs_completed == 4
    assert Path(art.weights_path).exists()
