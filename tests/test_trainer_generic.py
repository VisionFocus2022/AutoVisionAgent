"""training/generic_trainer 单元测试（W4-T1：13% → 补测）。

用假 ITrainStrategy（无 GPU）驱动 fit 全路径：进度/中断/早停/预热/
LR 调度/checkpoint 滚动/断点恢复（sidecar 优先 + torch 权重内元数据回退）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402
from training.generic_trainer import GenericTrainer  # noqa: E402


class FakeStrategy:
    """假训练策略：记录 epoch/lr/save，loss 序列可脚本化。"""

    def __init__(self, losses=None):
        self.losses = list(losses or [])
        self.epochs_run = []
        self.lrs_at_epoch = []
        self.saved = []
        self._optimizer = None

    def train_epoch(self, epoch, cfg):
        self.epochs_run.append(epoch)
        if self._optimizer is not None:
            self.lrs_at_epoch.append(self._optimizer.param_groups[0]["lr"])
        idx = min(epoch, len(self.losses)) - 1
        return {"loss": self.losses[idx]}

    def save(self, path):
        self.saved.append(str(path))
        Path(path).write_bytes(b"w")

    def get_optimizer(self):
        return self._optimizer


def _cfg(tmp_path, **kw):
    base = dict(
        task=TaskType.CLS,
        epochs=4,
        lr=0.01,
        output_dir=str(tmp_path / "out"),
        lr_scheduler="none",
        warmup_epochs=0,
        patience=0,
        checkpoint_every=2,
        max_checkpoints=2,
    )
    base.update(kw)
    return TrainConfig(**base)


@pytest.mark.unit
def test_fit_runs_all_epochs_and_reports(tmp_path):
    strat = FakeStrategy(losses=[1.0, 0.8, 0.6, 0.4])
    trainer = GenericTrainer(TaskType.CLS, strat)
    seen = []

    art = trainer.fit(_cfg(tmp_path), progress=lambda r, m: seen.append((r, m["epoch"])))

    assert strat.epochs_run == [1, 2, 3, 4]
    assert [round(r, 3) for r, _ in seen] == [0.25, 0.5, 0.75, 1.0]
    assert art.epochs_completed == 4
    assert art.best_metric == pytest.approx(0.4)
    assert art.weights_path.endswith("cls_final.pt")
    assert Path(art.weights_path).exists()
    assert art.metrics["epoch"] == 4


@pytest.mark.unit
def test_fit_early_stops_on_patience(tmp_path):
    # loss 持平：patience=2 → 第 3 轮触发早停（epoch1 最优，2/3 无改善）
    strat = FakeStrategy(losses=[1.0, 1.0, 1.0, 1.0, 1.0])
    cfg = _cfg(tmp_path, epochs=10, patience=2)
    trainer = GenericTrainer(TaskType.CLS, strat)
    art = trainer.fit(cfg)

    assert strat.epochs_run == [1, 2, 3]
    assert art.epochs_completed == 3
    assert trainer._best_epoch == 1
    assert trainer._best_metric == pytest.approx(1.0)


@pytest.mark.unit
def test_fit_user_interrupt(tmp_path):
    strat = FakeStrategy(losses=[1.0, 0.9])
    cfg = _cfg(tmp_path, epochs=10)
    art = GenericTrainer(TaskType.CLS, strat).fit(
        cfg, should_stop=lambda: len(strat.epochs_run) >= 2
    )
    assert strat.epochs_run == [1, 2]
    assert Path(art.weights_path).exists()  # 中断后仍保存最终权重


@pytest.mark.unit
def test_checkpoint_rolling_keeps_recent(tmp_path):
    strat = FakeStrategy(losses=[1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    cfg = _cfg(tmp_path, epochs=9, checkpoint_every=3, max_checkpoints=2)
    GenericTrainer(TaskType.CLS, strat).fit(cfg)

    ckpt_dir = Path(cfg.output_dir) / "checkpoints"
    epochs_kept = sorted(
        int(p.stem.split("_")[1]) for p in ckpt_dir.glob("epoch_*.pt")
    )
    assert epochs_kept == [6, 9]  # 滚动保留最近 2 个
    # sidecar 元数据随权重保留/清理
    assert (ckpt_dir / "epoch_9.pt.meta.json").exists()
    assert not (ckpt_dir / "epoch_3.pt.meta.json").exists()
    meta = json.loads((ckpt_dir / "epoch_9.pt.meta.json").read_text(encoding="utf-8"))
    assert meta["epoch"] == 9
    assert meta["task"] == "cls"


@pytest.mark.unit
def test_resume_from_sidecar_meta(tmp_path):
    ckpt_dir = tmp_path / "out" / "checkpoints"
    ckpt_dir.mkdir(parents=True)
    ckpt = ckpt_dir / "epoch_4.pt"
    ckpt.write_bytes(b"w")
    (ckpt_dir / "epoch_4.pt.meta.json").write_text(
        json.dumps({"epoch": 4, "best_metric": 0.5, "best_epoch": 3, "task": "cls"}),
        encoding="utf-8",
    )

    strat = FakeStrategy(losses=[0.5, 0.4, 0.3])
    trainer = GenericTrainer(TaskType.CLS, strat)
    trainer.fit(_cfg(tmp_path, epochs=6, resume_from=str(ckpt)))

    assert strat.epochs_run[0] == 5  # 从 epoch 5 续训
    assert strat.epochs_run == [5, 6]
    assert trainer._best_metric == pytest.approx(0.3)  # 0.5 恢复后仍被继续刷新


@pytest.mark.unit
def test_resume_falls_back_to_torch_meta(tmp_path):
    ckpt_dir = tmp_path / "out" / "checkpoints"
    ckpt_dir.mkdir(parents=True)
    ckpt = ckpt_dir / "epoch_2.pt"
    torch.save({"epoch": 2, "best_metric": 0.4, "best_epoch": 1}, str(ckpt))

    strat = FakeStrategy(losses=[0.4, 0.35])
    trainer = GenericTrainer(TaskType.CLS, strat)
    trainer.fit(_cfg(tmp_path, epochs=3, resume_from=str(ckpt)))

    assert strat.epochs_run[0] == 3


@pytest.mark.unit
def test_resume_without_meta_starts_from_one(tmp_path):
    bad = tmp_path / "junk.pt"
    bad.write_bytes(b"not a checkpoint")
    strat = FakeStrategy(losses=[1.0, 0.9])
    GenericTrainer(TaskType.CLS, strat).fit(
        _cfg(tmp_path, epochs=2, resume_from=str(bad))
    )
    assert strat.epochs_run == [1, 2]


@pytest.mark.unit
def test_linear_warmup_scales_lr(tmp_path):
    strat = FakeStrategy(losses=[1.0, 0.9, 0.8, 0.7])
    strat._optimizer = torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], lr=0.01)
    cfg = _cfg(tmp_path, epochs=4, lr=0.01, warmup_epochs=4)
    GenericTrainer(TaskType.CLS, strat).fit(cfg)

    # epoch N 的 lr = lr * N / warmup_epochs（线性 0→base）
    assert strat.lrs_at_epoch[0] == pytest.approx(0.01 * 1 / 4)
    assert strat.lrs_at_epoch[1] == pytest.approx(0.01 * 2 / 4)


@pytest.mark.unit
def test_step_scheduler_decays_lr(tmp_path):
    strat = FakeStrategy(losses=[1.0, 0.9, 0.8, 0.9, 0.7, 0.6])
    strat._optimizer = torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], lr=0.01)
    cfg = _cfg(tmp_path, epochs=6, lr=0.01, lr_scheduler="step")
    GenericTrainer(TaskType.CLS, strat).fit(cfg)

    # StepLR step_size=max(1, 6//3)=2, gamma=0.1：第 3 个 epoch 起 lr 应显著下降
    assert strat.lrs_at_epoch[0] == pytest.approx(0.01)
    assert strat.lrs_at_epoch[2] < strat.lrs_at_epoch[0]


@pytest.mark.unit
def test_scheduler_skipped_without_optimizer(tmp_path):
    # 策略不暴露优化器：调度器/预热路径应安全跳过（不崩、照常训练）
    strat = FakeStrategy(losses=[1.0, 0.9])
    cfg = _cfg(tmp_path, epochs=2, lr_scheduler="cosine", warmup_epochs=2)
    art = GenericTrainer(TaskType.CLS, strat).fit(cfg)
    assert strat.epochs_run == [1, 2]
    assert art.epochs_completed == 2
