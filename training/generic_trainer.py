"""通用训练器（FR-B1）。

GenericTrainer 包装训练策略（ITrainStrategy），在 fit() 中驱动训练循环，
支持进度回调、中断、checkpoint 保存与恢复、早停、LR 调度。
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

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

    def _build_scheduler(self, cfg: TrainConfig) -> Any | None:
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
                ReduceLROnPlateau,
                StepLR,
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
        progress: Callable[[float, dict], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
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

        # M10（一轮审查）：同一 trainer 实例二次 fit（非 resume）时
        # _best_metric/_best_epoch 沿用上一会话值，best_metric 语义错乱。
        # 无条件重置，resume 分支再从 checkpoint 覆盖。
        self._best_metric = float("inf")
        self._best_epoch = 0

        # M8（2026-10-05 二轮审查）：随机种子控制——训练可信度三部曲
        # （train/val 划分 + 真 resume + 种子）收尾。seed>0 时统一设
        # random/numpy/torch(+cuda)，使训练可复现；0 保持旧行为（不设种）。
        self._seed_everything(cfg.seed)

        # 断点恢复
        if cfg.resume_from and os.path.exists(cfg.resume_from):
            start_epoch = self._resume(cfg.resume_from, cfg)
            logger.info("从 epoch %d 恢复训练", start_epoch)

        # R4-9: 构建 LR 调度器 + 预热
        scheduler = self._build_scheduler(cfg)
        self._replay_scheduler_steps(scheduler, start_epoch)

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
            # O3（2026-10-05 二轮审查）：逐 epoch 追加 metrics.jsonl——此前
            # history 仅存内存、中断全丢，GUI 曲线只靠实时回调。追加写失败
            # 仅告警（观测件不阻断训练）。
            self._append_metrics_jsonl(cfg, metrics)
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

    @staticmethod
    def _seed_everything(seed: int) -> None:
        """M8：统一设种（random / numpy / torch / cuda）。

        seed<=0 时不设（保持旧行为）；任一库缺失均不影响其余（best-effort，
        缺库场景不影响训练主流程）。留痕设种结果便于复现排查。
        """
        if seed <= 0:
            return
        import random

        random.seed(seed)
        try:
            import numpy as np

            np.random.seed(seed)
        except ImportError:
            pass
        try:
            import torch

            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        except ImportError:
            pass
        logger.info("训练随机种子已设置: seed=%d (random/numpy/torch/cuda)", seed)

    @staticmethod
    def _replay_scheduler_steps(scheduler: Any | None, start_epoch: int) -> None:
        """O2（2026-10-05 二轮审查）：resume 后 LR 调度器步数回放。

        此前全新构建且不回放步数，Cosine 相位从 0 重启，续训前几轮 LR
        回到高位、退火轨迹与首轮不连续。将 last_epoch 对齐到续训起点；
        plateau 型无步数概念（监控式）豁免（W24 规模拆分自主体内抽出）。
        """
        if scheduler is None or start_epoch <= 1:
            return
        try:
            from torch.optim.lr_scheduler import ReduceLROnPlateau

            if isinstance(scheduler, ReduceLROnPlateau):
                return
            scheduler.last_epoch = start_epoch - 1
            logger.debug("LR 调度器步数回放: last_epoch=%d", start_epoch - 1)
        except Exception:
            logger.debug("LR 调度器步数回放失败（非致命）", exc_info=True)

    @staticmethod
    def _append_metrics_jsonl(cfg: TrainConfig, metrics: dict[str, Any]) -> None:
        """O3：单 epoch metrics 追加写 output_dir/metrics.jsonl（best-effort）。"""
        try:
            path = os.path.join(cfg.output_dir, "metrics.jsonl")
            os.makedirs(cfg.output_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(
                    {k: v for k, v in metrics.items()
                     if isinstance(v, (int, float, str, bool))},
                    ensure_ascii=False,
                ) + "\n")
        except (OSError, TypeError, ValueError):
            logger.warning("metrics.jsonl 追加失败（观测件，不阻断训练）",
                           exc_info=True)

    def _train_one_epoch(self, epoch: int, cfg: TrainConfig) -> dict[str, Any]:
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
        self, scheduler: Any | None, cfg: TrainConfig, metrics: dict[str, Any]
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
        self, epoch: int, metrics: dict[str, Any], no_improve: int, cfg: TrainConfig
    ) -> tuple[int, bool]:
        """更新最佳指标并推进早停计数（loss 越小越好；无条件追踪——
        best_metric 是训练产物字段，不应依赖早停是否启用。W4-T1 RED→GREEN 修复）。

        M11（2026-10-05 二轮审查）：监控指标优先级 val_loss > val_map 的
        负值（若提供）> loss。此前只看训练 loss——真训练一次性适配器
        （W58：首轮全量 ultralytics，后续轮返同值）下 loss 恒定，patience>=1
        时必然在第 patience+1 轮误触发早停。适配器未提供 val 指标时保持
        旧行为（监控 loss），但对该场景给出一次性告警提示。

        Returns:
            (新的 no_improve 计数, 是否触发早停)。
        """
        # M11：val 指标优先（P0-1 的 train/val 划分让 val_loss 有了来源）
        current_metric = metrics.get("val_loss")
        if current_metric is None:
            # mAP 场景（越大越好）不在此处理——当前策略协议只产 loss 型
            # 指标，val_map 接入时需扩展方向参数
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
        """R5-11: 定期保存 checkpoint（每 checkpoint_every epoch 或最后一轮）。

        M2（2026-10-05 二轮审查）：原子写——先写 .pt.tmp 成功后 os.replace
        改名，中途崩溃不再留半成品 .pt（含 meta 与权重不一致的组合），
        resume 不会读到坏权重。
        """
        ckpt_interval = getattr(cfg, "checkpoint_every", 5)
        if epoch % ckpt_interval != 0 and epoch != cfg.epochs:
            return

        ckpt_dir = os.path.join(cfg.output_dir, "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)
        ckpt_path = os.path.join(ckpt_dir, f"epoch_{epoch}.pt")
        tmp_path = ckpt_path + ".tmp"
        try:
            self._strategy.save(tmp_path)
            os.replace(tmp_path, ckpt_path)  # M2：原子改名
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
            # M2：清理可能残留的 tmp（半成品不得留在盘上）。
            with contextlib.suppress(OSError):
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
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
                    with contextlib.suppress(OSError):
                        os.remove(meta_path)
        except OSError:
            pass

    @staticmethod
    def _save_meta(ckpt_path: str, epoch: int, cfg: TrainConfig,
                   best_metric: float | None = None,
                   best_epoch: int | None = None) -> None:
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
        """从 checkpoint 恢复训练状态（P0-2：元数据 + 权重双重恢复）。

        优先读取 sidecar ``.meta.json`` 元数据（包含 epoch/best_metric/best_epoch）；
        若不存在则回退到直接解析权重文件中的元字典。

        P0-2（2026-10-05 二轮审查 R2）：此前只恢复 epoch/best 元数据，
        从不装载模型权重——docstring 声称调 strategy.load_state() 但实现
        无任何调用。现通过 ``strategy.load_state(path)`` 实际装载；策略
        不支持或装载失败时**明确告警**"从随机权重续训"（不再静默），
        用户可据此判断续训产物可信度。

        Returns:
            起始 epoch 编号。
        """
        meta_path = ckpt_path + ".meta.json"

        # 1) 优先读取 sidecar 元数据
        meta = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
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

        # 3) P0-2：实际装载模型权重（此前缺失的核心步骤）
        weights_loaded = False
        try:
            weights_loaded = bool(self._strategy.load_state(ckpt_path))
        except Exception:
            logger.exception("strategy.load_state 装载权重失败")
        if weights_loaded:
            logger.info("已从 checkpoint 装载模型权重: %s", ckpt_path)
        else:
            # 明确告警而非静默：续训语义 = 随机权重 + epoch 跳号，产物
            # 可信度由用户知情决定
            logger.warning(
                "策略不支持/未能装载权重（%s）——本次续训将从随机权重"
                "开始（epoch 编号继续），训练产物等效重新训练，请知悉",
                ckpt_path,
            )

        if meta:
            self._best_metric = meta.get("best_metric", float("inf"))
            self._best_epoch = meta.get("best_epoch", 0)
            resumed_epoch = meta.get("epoch", 0)
            logger.info(
                "恢复训练状态: epoch=%d, best_metric=%.4f, best_epoch=%d, "
                "weights_loaded=%s",
                resumed_epoch, self._best_metric, self._best_epoch,
                weights_loaded,
            )
            return resumed_epoch + 1

        logger.warning("无法解析 checkpoint 元数据，从头开始")
        return 1


__all__ = ["GenericTrainer"]
