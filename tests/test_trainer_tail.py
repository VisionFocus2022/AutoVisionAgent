"""training/generic_trainer.py 尾巴补测（W14-C4：87% → 目标 ≥93%）。

覆盖权威 missing 行清单（定向 coverage 实测）：
63/66-73（LR 调度器四型构建 + 未知类型告警 + torch 缺失回退）、89-90
（预热 param_groups 异常吞）、191（plateau 按监控值步进）、194-195
（调度器 step 异常吞）、280-281（checkpoint 文件名坏编号回退 0）、
290-291/297-300（清理阶段 remove/listdir OSError 全吞 + sidecar 元数据
清理）、317-318（_save_meta OSError debug）、338-339（_resume 元数据
坏 JSON 告警回退）。
"""
from __future__ import annotations

import json
import logging
import os
import sys

import pytest

torch = pytest.importorskip("torch")

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402
from training.generic_trainer import GenericTrainer  # noqa: E402


class _Strategy:
    """最小策略：train_epoch/save 可脚本化，optimizer 可注入。"""

    def __init__(self, optimizer=None):
        self._optimizer = optimizer
        self.saved = []

    def train_epoch(self, epoch, cfg):
        return {"loss": 1.0}

    def save(self, path):
        self.saved.append(str(path))
        with open(path, "wb") as f:
            f.write(b"w")

    def get_optimizer(self):
        return self._optimizer


def _cfg(**kw):
    base = dict(
        task=TaskType.CLS,
        epochs=2,
        lr=0.01,
        output_dir="./outputs_unused",
        lr_scheduler="none",
        warmup_epochs=0,
        patience=0,
    )
    base.update(kw)
    return TrainConfig(**base)


def _real_optimizer():
    return torch.optim.SGD(
        [torch.nn.Parameter(torch.zeros(2, requires_grad=True))], lr=0.1
    )


# ============================== LR 调度器构建 ============================== #
@pytest.mark.unit
def test_build_scheduler_cosine():
    sched = GenericTrainer(TaskType.CLS, _Strategy(_real_optimizer())
                           )._build_scheduler(_cfg(lr_scheduler="cosine"))
    assert isinstance(sched, torch.optim.lr_scheduler.CosineAnnealingLR)


@pytest.mark.unit
def test_build_scheduler_step():
    sched = GenericTrainer(TaskType.CLS, _Strategy(_real_optimizer())
                           )._build_scheduler(_cfg(lr_scheduler="step"))
    assert isinstance(sched, torch.optim.lr_scheduler.StepLR)


@pytest.mark.unit
def test_build_scheduler_plateau():
    sched = GenericTrainer(TaskType.CLS, _Strategy(_real_optimizer())
                           )._build_scheduler(_cfg(lr_scheduler="plateau"))
    assert isinstance(sched, torch.optim.lr_scheduler.ReduceLROnPlateau)


@pytest.mark.unit
def test_build_scheduler_unknown_type_warns_and_returns_none(caplog):
    trainer = GenericTrainer(TaskType.CLS, _Strategy(_real_optimizer()))
    with caplog.at_level(logging.WARNING, logger="training.generic_trainer"):
        sched = trainer._build_scheduler(_cfg(lr_scheduler="bogus"))
    assert sched is None
    assert any("未知 LR 调度器类型" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_build_scheduler_no_optimizer_returns_none():
    assert GenericTrainer(TaskType.CLS, _Strategy(None)
                          )._build_scheduler(_cfg(lr_scheduler="cosine")) is None


@pytest.mark.unit
def test_build_scheduler_torch_lr_scheduler_import_error(monkeypatch):
    """torch.optim.lr_scheduler 不可导入 → ImportError 吞掉返回 None（:71-73）。"""
    monkeypatch.setitem(sys.modules, "torch.optim.lr_scheduler", None)
    assert GenericTrainer(TaskType.CLS, _Strategy(_real_optimizer())
                          )._build_scheduler(_cfg(lr_scheduler="cosine")) is None


# ============================== 预热异常分支 ============================== #
@pytest.mark.unit
def test_apply_warmup_lr_param_groups_error_swallowed():
    """param_groups 属性抛错 → 静默跳过（尽力而为，:89-90）。"""

    class _BadOpt:
        @property
        def param_groups(self):
            raise RuntimeError("no param groups")

    trainer = GenericTrainer(TaskType.CLS, _Strategy(_BadOpt()))
    trainer._apply_warmup_lr(1, _cfg(warmup_epochs=3))  # 不得抛


# ============================== 调度器步进 ============================== #
@pytest.mark.unit
def test_step_scheduler_plateau_monitors_loss():
    """plateau 型按 metrics.loss 步进，其余无参步进（:191）。"""
    stepped = []

    class _Fake:
        def step(self, metric=None):
            stepped.append(metric)

    GenericTrainer(TaskType.CLS, _Strategy())._step_scheduler(
        _Fake(), _cfg(lr_scheduler="plateau"), {"loss": 0.42}
    )
    assert stepped == [0.42]

    GenericTrainer(TaskType.CLS, _Strategy())._step_scheduler(
        _Fake(), _cfg(lr_scheduler="cosine"), {"loss": 0.42}
    )
    assert stepped == [0.42, None]  # 非 plateau：无监控值


@pytest.mark.unit
def test_step_scheduler_error_swallowed(caplog):
    class _Boom:
        def step(self, *a, **kw):
            raise ValueError("scheduler boom")

    with caplog.at_level(logging.DEBUG, logger="training.generic_trainer"):
        GenericTrainer(TaskType.CLS, _Strategy())._step_scheduler(
            _Boom(), _cfg(lr_scheduler="cosine"), {}
        )
    assert any("LR 调度器 step 失败" in r.getMessage() for r in caplog.records)


# ============================== checkpoint 滚动清理 ============================== #
def _make_ckpt(d, name, with_meta=False):
    p = d / name
    p.write_bytes(b"w")
    if with_meta:
        (d / (name + ".meta.json")).write_text("{}", encoding="utf-8")
    return p


@pytest.mark.unit
def test_cleanup_checkpoints_keeps_newest_and_prunes_meta(tmp_path):
    """坏编号文件回退序号 0 最先淘汰；对应 sidecar .meta.json 一并清理
    （:280-281、:293-296）。"""
    d = tmp_path / "ckpts"
    d.mkdir()
    _make_ckpt(d, "epoch_bad.pt")                    # 坏编号 → _epoch_num=0
    _make_ckpt(d, "epoch_1.pt", with_meta=True)
    keep = _make_ckpt(d, "epoch_2.pt", with_meta=True)
    _make_ckpt(d, "unrelated.txt")                   # 非 epoch_*.pt 不动

    GenericTrainer._cleanup_checkpoints(
        GenericTrainer(TaskType.CLS, _Strategy()), str(d), max_keep=1
    )
    assert not (d / "epoch_bad.pt").exists()
    assert not (d / "epoch_1.pt").exists()
    assert not (d / "epoch_1.pt.meta.json").exists()  # sidecar 同步清理
    assert keep.exists() and (d / "epoch_2.pt.meta.json").exists()
    assert (d / "unrelated.txt").exists()


@pytest.mark.unit
def test_cleanup_checkpoints_remove_failure_swallowed(tmp_path, monkeypatch):
    """旧 checkpoint 删除失败（OSError）→ 吞掉继续清（:290-291）。"""
    d = tmp_path / "ckpts"
    d.mkdir()
    _make_ckpt(d, "epoch_1.pt")
    _make_ckpt(d, "epoch_2.pt")
    _make_ckpt(d, "epoch_3.pt")
    orig_remove = os.remove
    monkeypatch.setattr(
        os, "remove",
        lambda p: (_ for _ in ()).throw(OSError("remove boom"))
        if os.path.basename(p) == "epoch_1.pt" else orig_remove(p),
    )
    GenericTrainer._cleanup_checkpoints(
        GenericTrainer(TaskType.CLS, _Strategy()), str(d), max_keep=1
    )  # 不得抛
    assert (d / "epoch_1.pt").exists()  # 删除失败的保留
    assert not (d / "epoch_2.pt").exists()  # 其余照常清
    assert (d / "epoch_3.pt").exists()  # 最近一个保留


@pytest.mark.unit
def test_cleanup_checkpoints_meta_remove_failure_swallowed(
    tmp_path, monkeypatch
):
    """sidecar 元数据删除失败 → 吞掉（:297-298）。"""
    d = tmp_path / "ckpts"
    d.mkdir()
    _make_ckpt(d, "epoch_1.pt", with_meta=True)
    _make_ckpt(d, "epoch_2.pt")
    orig_remove = os.remove
    monkeypatch.setattr(
        os, "remove",
        lambda p: (_ for _ in ()).throw(OSError("meta boom"))
        if p.endswith(".meta.json") else orig_remove(p),
    )
    GenericTrainer._cleanup_checkpoints(
        GenericTrainer(TaskType.CLS, _Strategy()), str(d), max_keep=1
    )  # 不得抛
    assert not (d / "epoch_1.pt").exists()
    assert (d / "epoch_1.pt.meta.json").exists()  # 元数据删除失败但流程继续


@pytest.mark.unit
def test_cleanup_checkpoints_listdir_failure_swallowed(tmp_path, monkeypatch):
    """目录列举失败（OSError）→ 整体吞掉不炸（:299-300）。"""
    d = tmp_path / "ckpts"
    d.mkdir()
    _make_ckpt(d, "epoch_1.pt")
    monkeypatch.setattr(os, "listdir",
                        lambda p: (_ for _ in ()).throw(OSError("listdir boom")))
    GenericTrainer._cleanup_checkpoints(
        GenericTrainer(TaskType.CLS, _Strategy()), str(d), max_keep=1
    )  # 不得抛
    assert (d / "epoch_1.pt").exists()


# ============================== 元数据保存/恢复异常 ============================== #
@pytest.mark.unit
def test_save_meta_oserror_logged_not_raised(tmp_path, monkeypatch, caplog):
    """元数据写盘失败 → debug 记录不炸（best-effort sidecar，:317-318）。"""
    def _dump_boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", _dump_boom)
    with caplog.at_level(logging.DEBUG, logger="training.generic_trainer"):
        GenericTrainer._save_meta(
            str(tmp_path / "x.pt"), 3, _cfg(), best_metric=0.5, best_epoch=2
        )
    assert any("保存元数据失败" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_resume_corrupt_meta_json_warns_and_starts_over(
    tmp_path, caplog
):
    """.meta.json 是坏 JSON → 告警回退权重文件解析，再失败 → 从头开始
    （:338-339）。"""
    ckpt = tmp_path / "epoch_9.pt"
    ckpt.write_bytes(b"not-a-torch-file")  # 权重回退解析也必然失败
    (tmp_path / "epoch_9.pt.meta.json").write_text("{invalid json", encoding="utf-8")

    trainer = GenericTrainer(TaskType.CLS, _Strategy())
    with caplog.at_level(logging.WARNING, logger="training.generic_trainer"):
        assert trainer._resume(str(ckpt), _cfg()) == 1  # 从头开始
    assert any("读取元数据失败" in r.getMessage() for r in caplog.records)
