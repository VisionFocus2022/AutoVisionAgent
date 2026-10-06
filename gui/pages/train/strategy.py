"""真实引擎训练策略（W1 起 page.py 内实现，W1-1 批拆出——规模守卫 800）。

EngineTrainStrategy 对接有监督引擎的 train_epoch（真训练）；引擎缺
train_epoch 时回退模拟 loss。与 page.py 零行为变更，纯物理拆分。
"""
from __future__ import annotations

import logging

from core.interfaces_supervised import TrainConfig

logger = logging.getLogger(__name__)


class EngineTrainStrategy:
    """真实引擎训练策略：对接有监督引擎的 train 方法。

    若引擎提供 train() 方法则调用真实训练；否则回退到模拟策略。
    """

    def __init__(self, engine, cfg: TrainConfig) -> None:
        self.task = cfg.task
        self._engine = engine
        self._cfg = cfg
        self._epoch = 0

    def train_epoch(self, epoch: int, cfg: TrainConfig):
        """执行一轮真实训练。"""
        self._epoch = epoch
        if hasattr(self._engine, "train_epoch"):
            metrics = self._engine.train_epoch(epoch, cfg)
            return metrics if isinstance(metrics, dict) else {"loss": float(metrics)}
        # 引擎不支持逐轮训练，回退
        import math
        return {"loss": round(1.0 * math.exp(-epoch * 0.05), 4)}

    def save(self, path: str) -> None:
        """保存训练权重。"""
        if hasattr(self._engine, "save"):
            self._engine.save(path)

    def load_state(self, path: str) -> bool:
        """P0-2（2026-10-05 二轮审查 R2）：从 checkpoint 恢复引擎权重。

        引擎提供 load() 则调用（返回 True）；否则返回 False，trainer
        将告警"从随机权重续训"。
        """
        if hasattr(self._engine, "load"):
            try:
                self._engine.load(path, device=getattr(self._engine, "_device", "cpu"))
                return True
            except Exception:
                logger.exception("EngineTrainStrategy.load_state 装载失败: %s", path)
                return False
        return False

    def get_optimizer(self):
        """R5-4: 返回引擎的优化器（供 LR 调度器使用）。

        优先从引擎获取；若引擎暴露 _model，则按 cfg 构建 SGD。
        """
        if hasattr(self._engine, "get_optimizer"):
            return self._engine.get_optimizer()
        model = getattr(self._engine, "_model", None)
        cfg = self._cfg
        if model is not None and hasattr(model, "parameters"):
            try:
                import torch.optim as optim
                return optim.SGD(
                    model.parameters(),
                    lr=cfg.lr,
                    momentum=cfg.momentum,
                    weight_decay=cfg.weight_decay,
                )
            except (ImportError, RuntimeError):
                pass
        return None


__all__ = ["EngineTrainStrategy"]
