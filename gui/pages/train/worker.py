"""训练后台线程（FR-B2/B3）。

TrainWorker 包装 GenericTrainer.fit 在 QThread 中执行，
通过信号与 UI 层通信，支持强制中断。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from core.interfaces_supervised import TrainArtifact, TrainConfig


class TrainWorker(QThread):
    """训练工作线程。

    W18（P3①）：按无 parent 构造（页面持引用自管生命周期），QThread.finished
    由页面接线"先清引用再 deleteLater"——不要以页面作 parent（窗口析构链会
    连带销毁仍在运行的 QThread）。

    信号：
        progress(float, dict): (epoch_ratio 0~1, metrics_dict) — 实时进度
        finished_sig(TrainArtifact): 训练完成，携带产物
        failed(str): 训练异常信息
    """

    progress = Signal(float, dict)
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
        """在子线程执行训练。"""
        try:

            def _progress(ratio: float, metrics: dict) -> None:
                self.progress.emit(float(ratio), dict(metrics))

            def _should_stop() -> bool:
                return self._stop_flag.is_set()

            artifact: TrainArtifact = self._trainer.fit(
                cfg=self._cfg,
                progress=_progress,
                should_stop=_should_stop,
            )
            self.finished_sig.emit(artifact)

        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def stop(self) -> None:
        """请求强制结束（线程安全）。"""
        self._stop_flag.set()


__all__ = ["TrainWorker"]
