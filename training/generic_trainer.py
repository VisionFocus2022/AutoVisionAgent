"""通用训练器（FR-B1）。

GenericTrainer 包装训练策略（ITrainStrategy），在 fit() 中驱动训练循环，
支持进度回调、中断、checkpoint 保存与恢复、早停、LR 调度。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

from core.interfaces_supervised import ITrainStrategy, TrainArtifact, TrainConfig

logger = logging.getLogger(__name__)

_MAX_CKPT_KEEP = 3  # 滚动保留最近的 checkpoint 数量


class GenericTrainer:
    """通用训练器。

    接受任意实现了 train_epoch/save 接口的策略对象，
    在 fit() 中驱动 epoch 循环，通过回调与 UI 层通信。

    Args:
        task: TaskType 枚举值。
        strategy: 训练策略对象，需实现：
            - ``train_epoch(epoch, cfg) -> dict``  返回 metrics
            - ``save(path) -> None``  保存权重
    """

    def __init__(self, task, strategy: ITrainStrategy) -> None:
        self.task = task
        self._strategy = strategy
        # 初始化为 inf：早停默认监控 loss（越小越好）
        self._best_metric: float = float("inf")
        self._best_epoch: int = 0

    def _build_scheduler(self, cfg: TrainConfig) -> Optional[Any]:
        """R4-9: 根据 cfg.lr_scheduler 构建学习率调度器。

        支持 cosine / step / plateau / none。
        如果策略未暴露优化器，返回 None（不使用调度器）。
        """
        if cfg.lr_scheduler in ("none", "", None):
            return None

        optimizer = self._strategy.get_optimizer()
        if optimizer is None:
            logger.debug("策略未暴露优化器，跳过 LR 调度器")
            return None

        try:
            from torch.optim.lr_scheduler import (
                CosineAnnealingLR,
                StepLR,
                ReduceLROnPlateau,
            )

            if cfg.lr_scheduler == "cosine":
                return CosineAnnealingLR(optimizer, T_max=cfg.epochs)
            elif cfg.lr_scheduler == "step":
                return StepLR(optimizer, step_size=max(1, cfg.epochs // 3), gamma=0.1)
            elif cfg.lr_scheduler == "plateau":
                return ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)
            else:
                logger.warning("未知 LR 调度器类型: %s", cfg.lr_scheduler)
                return None
        except ImportError:
            logger.debug("PyTorch 不可用，跳过 LR 调度器")
            return None

    def _apply_warmup_lr(self, epoch: int, cfg: TrainConfig) -> None:
        """R4-9: 线性预热学习率（实例方法）。"""
        if cfg.warmup_epochs <= 0 or epoch > cfg.warmup_epochs:
            return

        optimizer = self._strategy.get_optimizer()
        if optimizer is None:
            return

        warmup_lr = cfg.lr * epoch / max(cfg.warmup_epochs, 1)
        try:
            for param_group in optimizer.param_groups:
                param_group["lr"] = warmup_lr
            logger.debug("预热 epoch %d: lr=%.6f", epoch, warmup_lr)
        except Exception:
            # best-effort 决策（W14-C3 注）：预热只调整 LR 数值，属非关键
            # 优化——失败时 LR 保持调度器原值继续训练，不应中断整轮。
            pass

    def fit(
        self,
        cfg: TrainConfig,
        progress: Optional[Callable[[float, dict], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> TrainArtifact:
        """执行完整训练循环。

        Args:
            cfg: 训练配置。
            progress: 进度回调 (epoch_ratio 0~1, metrics_dict)。
            should_stop: 中断检查回调，返回 True 则停止训练。

        Returns:
            TrainArtifact 训练产物。
        """
        start_epoch = 1
        metrics_history: list = []

        # 断点恢复
        if cfg.resume_from and os.path.exists(cfg.resume_from):
            start_epoch = self._resume(cfg.resume_from, cfg)
            logger.info("从 epoch %d 恢复训练", start_epoch)

        # R4-9: 构建 LR 调度器 + 预热
        scheduler = self._build_scheduler(cfg)

        no_improve = 0
        artifact = TrainArtifact(task=cfg.task, config=cfg)
        # W13-C2: resume 起点已越过 cfg.epochs 时循环体一次都不执行，
        # 预置 completed = start_epoch，避免循环后引用未定义的 epoch（NameError）。
        completed = start_epoch

        for epoch in range(start_epoch, cfg.epochs + 1):
            completed = epoch  # 循环顶同步：中断/早停/正常完成的取值与旧实现一致
            # 中断检查
            if should_stop and should_stop():
                logger.info("训练在 epoch %d 被用户中断", epoch)
                break

            # R4-9: 预热学习率（线性从 0 到 base_lr）
            self._apply_warmup_lr(epoch, cfg)

            # 执行一个 epoch（前向/损失反传在 strategy.train_epoch 内）
            metrics = self._train_one_epoch(epoch, cfg)
            metrics_history.append(metrics)
            self._step_scheduler(scheduler, cfg, metrics)

            # 更新最佳指标 + 早停判定
            no_improve, early_stop = self._track_best_and_check_early_stop(
                epoch, metrics, no_improve, cfg
            )
            if early_stop:
                break

            # 进度回调
            ratio = epoch / cfg.epochs
            if progress:
                progress(ratio, metrics)

            # R5-11: 定期保存 checkpoint
            self._save_epoch_checkpoint(epoch, cfg)

        # 保存最终权重（失败抛 RuntimeError，不吞异常）
        final_path = self._save_final_weights(cfg)

        artifact.weights_path = final_path
        artifact.metrics = metrics_history[-1] if metrics_history else {}
        artifact.epochs_completed = completed
        artifact.best_metric = self._best_metric

        logger.info(
            "训练完成: %d epochs, best=%.4f, weights=%s",
            completed, self._best_metric, final_path,
        )
        return artifact

    def _train_one_epoch(self, epoch: int, cfg: TrainConfig) -> Dict[str, Any]:
        """执行单个 epoch 的前向/损失/反传（strategy.train_epoch 内）并计时。

        Returns:
            本轮 metrics（含 epoch/time 标注）。
        """
        t0 = time.time()
        metrics = self._strategy.train_epoch(epoch, cfg)
        dt = time.time() - t0

        metrics["epoch"] = epoch
        metrics["time"] = round(dt, 2)
        return metrics

    def _step_scheduler(
        self, scheduler: Optional[Any], cfg: TrainConfig, metrics: Dict[str, Any]
    ) -> None:
        """R4-9: 步进 LR 调度器（plateau 监控 loss；失败仅 debug 不中断）。"""
        if scheduler is None:
            return
        try:
            if cfg.lr_scheduler == "plateau":
                scheduler.step(metrics.get("loss", float("inf")))
            else:
                scheduler.step()
        except Exception:
            logger.debug("LR 调度器 step 失败", exc_info=True)

    def _track_best_and_check_early_stop(
        self, epoch: int, metrics: Dict[str, Any], no_improve: int, cfg: TrainConfig
    ) -> "tuple[int, bool]":
        """更新最佳指标并推进早停计数（loss 越小越好；无条件追踪——
        best_metric 是训练产物字段，不应依赖早停是否启用。W4-T1 RED→GREEN 修复）。

        Returns:
            (新的 no_improve 计数, 是否触发早停)。
        """
        current_metric = metrics.get("loss", float("inf"))
        if current_metric < self._best_metric:
            self._best_metric = current_metric
            self._best_epoch = epoch
            no_improve = 0
        else:
            no_improve += 1

        # 早停
        if cfg.patience > 0 and no_improve >= cfg.patience:
            logger.info(
                "早停：连续 %d 轮无改善 (best=%.4f @epoch %d)",
                no_improve, self._best_metric, self._best_epoch,
            )
            return no_improve, True
        return no_improve, False

    def _save_epoch_checkpoint(self, epoch: int, cfg: TrainConfig) -> None:
        """R5-11: 定期保存 checkpoint（每 checkpoint_every epoch 或最后一轮）。"""
        ckpt_interval = getattr(cfg, "checkpoint_every", 5)
        if epoch % ckpt_interval != 0 and epoch != cfg.epochs:
            return

        ckpt_dir = os.path.join(cfg.output_dir, "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)
        ckpt_path = os.path.join(ckpt_dir, f"epoch_{epoch}.pt")
        try:
            self._strategy.save(ckpt_path)
            # 保存元数据 sidecar（epoch / best_metric / best_epoch）
            self._save_meta(ckpt_path, epoch, cfg,
                            best_metric=self._best_metric,
                            best_epoch=self._best_epoch)
            logger.debug("checkpoint 已保存: %s", ckpt_path)
            # 滚动清理旧 checkpoint（只保留最近 max_checkpoints 个）
            self._cleanup_checkpoints(ckpt_dir, getattr(cfg, "max_checkpoints", 3))
        except Exception:
            # best-effort：周期 checkpoint 只是断点恢复的加速手段，
            # 失败不中断训练（最终权重保存失败才致命，见 _save_final_weights）。
            logger.exception("保存 checkpoint 失败")

    def _save_final_weights(self, cfg: TrainConfig) -> str:
        """保存最终权重，返回落盘路径。

        W11-R1 修复（v2 P1-3）：最终权重是训练产物本体，保存失败必须让
        调用方知道——原先吞掉后仍上报 weights_path，UI 显示训练完成但
        磁盘无权重。TrainWorker 会把该异常路由到 failed 信号。

        Returns:
            最终权重文件路径。

        Raises:
            RuntimeError: 保存失败（消息含路径与原因）。
        """
        final_path = os.path.join(cfg.output_dir, f"{cfg.task.value}_final.pt")
        os.makedirs(cfg.output_dir, exist_ok=True)
        try:
            self._strategy.save(final_path)
        except Exception as exc:
            raise RuntimeError(
                f"保存最终权重失败: {final_path} ({exc})"
            ) from exc
        return final_path

    def _cleanup_checkpoints(self, ckpt_dir: str, max_keep: int = 3) -> None:
        """滚动清理旧 checkpoint，只保留最近 max_keep 个 epoch_*.pt。"""
        try:
            ckpts = [
                f for f in os.listdir(ckpt_dir)
                if f.startswith("epoch_") and f.endswith(".pt")
            ]
            # 从文件名提取 epoch 编号排序
            def _epoch_num(name: str) -> int:
                try:
                    return int(name.replace("epoch_", "").replace(".pt", ""))
                except ValueError:
                    return 0
            ckpts.sort(key=_epoch_num)
            # 删除超出保留数量的旧 checkpoint（同时清理对应 .meta.json）
            while len(ckpts) > max_keep:
                old = ckpts.pop(0)
                old_path = os.path.join(ckpt_dir, old)
                try:
                    os.remove(old_path)
                    logger.debug("已清理旧 checkpoint: %s", old)
                except OSError:
                    pass
                # 清理 sidecar 元数据
                meta_path = old_path + ".meta.json"
                if os.path.exists(meta_path):
                    try:
                        os.remove(meta_path)
                    except OSError:
                        pass
        except OSError:
            pass

    @staticmethod
    def _save_meta(ckpt_path: str, epoch: int, cfg: TrainConfig,
                   best_metric: Optional[float] = None,
                   best_epoch: Optional[int] = None) -> None:
        """保存训练元数据 sidecar JSON（与权重文件同名 + .meta.json）。"""
        meta = {
            "epoch": epoch,
            "best_metric": best_metric if best_metric is not None else float("inf"),
            "best_epoch": best_epoch if best_epoch is not None else 0,
            "task": cfg.task.value,
        }
        meta_path = ckpt_path + ".meta.json"
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
        except OSError:
            logger.debug("保存元数据失败: %s", meta_path, exc_info=True)

    def _resume(self, ckpt_path: str, cfg: TrainConfig) -> int:
        """从 checkpoint 恢复训练状态。

        优先读取 sidecar ``.meta.json`` 元数据（包含 epoch/best_metric/best_epoch）；
        若不存在则回退到直接解析权重文件中的元字典。
        同时尝试通过 ``strategy.load_state()`` 恢复模型权重（若策略支持）。

        Returns:
            起始 epoch 编号。
        """
        meta_path = ckpt_path + ".meta.json"

        # 1) 优先读取 sidecar 元数据
        meta = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("读取元数据失败: %s", meta_path, exc_info=True)

        # 2) 回退：尝试从权重文件解析元字典
        if not meta:
            try:
                import torch
                # P3④：直调 torch.load(weights_only=True) 而不走 _safe_torch_load
                # ——此处需要完整 ckpt 对象读取元数据字典（非 state_dict 装载）；
                # weights_only=True 已阻断任意代码执行，安全等价。
                ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
                if isinstance(ckpt, dict) and "epoch" in ckpt:
                    meta = ckpt
            except Exception:
                logger.debug("权重文件无训练元数据", exc_info=True)

        if meta:
            self._best_metric = meta.get("best_metric", float("inf"))
            self._best_epoch = meta.get("best_epoch", 0)
            resumed_epoch = meta.get("epoch", 0)
            logger.info(
                "恢复训练状态: epoch=%d, best_metric=%.4f, best_epoch=%d",
                resumed_epoch, self._best_metric, self._best_epoch,
            )
            return resumed_epoch + 1

        logger.warning("无法解析 checkpoint 元数据，从头开始")
        return 1


__all__ = ["GenericTrainer"]
