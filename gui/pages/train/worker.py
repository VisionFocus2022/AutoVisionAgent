"""训练后台线程（FR-B2/B3）。

TrainWorker 包装 GenericTrainer.fit 在 QThread 中执行，
通过信号与 UI 层通信，支持强制中断。

W1-4：AMP 预检（cuda fp16 探针）自 UI 线程迁入本线程——冷驱动下预检
可秒级~分钟级阻塞（W67 实测假死案），预检完成后才 fit；失败经
stage_msg 码信号回 UI（页面侧翻译文案+取消勾选），amp=False 经
fit 参数链生效（strategy.train_epoch 消费 fit 传入的 cfg，W58 契约）。
"""
from __future__ import annotations

import dataclasses
import logging
import threading

from PySide6.QtCore import QThread, Signal

from core.interfaces_supervised import TrainArtifact, TrainConfig

logger = logging.getLogger(__name__)


class TrainWorker(QThread):
    """训练工作线程。

    W18（P3①）：按无 parent 构造（页面持引用自管生命周期），QThread.finished
    由页面接线"先清引用再 deleteLater"——不要以页面作 parent（窗口析构链会
    连带销毁仍在运行的 QThread）。

    信号：
        progress(float, dict): (epoch_ratio 0~1, metrics_dict) — 实时进度
        stage_msg(str, str): (code, detail) — 阶段事件（如 amp_fallback），
            UI 侧翻译文案（worker 无 i18n 上下文）
        finished_sig(TrainArtifact): 训练完成，携带产物
        failed(str): 训练异常信息
    """

    progress = Signal(float, dict)
    stage_msg = Signal(str, str)
    finished_sig = Signal(object)  # TrainArtifact
    failed = Signal(str)

    def __init__(
        self,
        trainer,  # GenericTrainer / ITaskTrainer
        cfg: TrainConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._trainer = trainer
        self._cfg = cfg
        self._stop_flag = threading.Event()

    def run(self) -> None:
        """在子线程执行训练（W1-4：先 AMP 预检后 fit）。"""
        try:
            cfg = self._amp_preflight_or_fallback(self._cfg)

            def _progress(ratio: float, metrics: dict) -> None:
                self.progress.emit(float(ratio), dict(metrics))

            def _should_stop() -> bool:
                return self._stop_flag.is_set()

            artifact: TrainArtifact = self._trainer.fit(
                cfg=cfg,
                progress=_progress,
                should_stop=_should_stop,
            )
            self.finished_sig.emit(artifact)

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _amp_preflight_or_fallback(self, cfg: TrainConfig) -> TrainConfig:
        """W31/W1-4：cuda fp16 预检（worker 线程）；失败回退 FP32。

        cpu/lite 等场景 amp_preflight 自身静默跳过（不随包 checkamp 资产）。
        """
        if not cfg.amp:
            return cfg
        logger.info("AMP 预检开始(worker): device=%s", cfg.device)
        from models.supervised.amp_preflight import amp_preflight

        ok, reason = amp_preflight(cfg.device)
        logger.info("AMP 预检结束: ok=%s reason=%s", ok, reason)
        if ok:
            return cfg
        logger.warning("AMP 预检失败，训练回退 FP32: %s", reason)
        self.stage_msg.emit("amp_fallback", reason[:40])
        return dataclasses.replace(cfg, amp=False)

    def stop(self) -> None:
        """请求强制结束（线程安全）。"""
        self._stop_flag.set()


__all__ = ["TrainWorker"]
