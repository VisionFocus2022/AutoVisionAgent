"""训练页：参数配置 + 实时 Loss 曲线 + 可中断训练（FR-D5 / FR-B2 / FR-B3）。

对接 training/generic_trainer.GenericTrainer（通过可插拔 ITrainStrategy）
与 models/supervised/ 注册表。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.interfaces_supervised import TaskType, TrainConfig
from gui.core.i18n import tr
from gui.core.tasks_ui import populate_task_combo
from gui.pages.train.worker import TrainWorker
from gui.widgets.loss_chart import LossChartWidget
from models.supervised.amp_preflight import amp_preflight

logger = logging.getLogger(__name__)


# 多规模配置预设（对标 SKolpha normal/small/large/ultra 变体）
_TRAIN_PRESETS = {
    "normal": {
        "backbone": "yolov8n",
        "batch_size": 8,
        "lr": 0.001,
        "resolution": 640,
    },
    "small": {
        "backbone": "yolov8s",
        "batch_size": 16,
        "lr": 0.002,
        "resolution": 320,
    },
    "large": {
        "backbone": "yolov8l",
        "batch_size": 4,
        "lr": 0.0005,
        "resolution": 1024,
    },
    "ultra": {
        "backbone": "yolov8x",
        "batch_size": 2,
        "lr": 0.0003,
        "resolution": 1280,
    },
}


class TrainPage(QWidget):
    """训练配置与执行页。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._worker: TrainWorker | None = None
        self._build_ui()
        self._wire()

    # ============================== UI ============================== #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 顶部：参数表单 + 操作 ----
        top = QHBoxLayout()
        top.setSpacing(12)

        top.addWidget(self._build_form_panel())
        top.addLayout(self._build_chart_panel(), 1)
        root.addLayout(top, 1)

    def _build_form_panel(self) -> QFrame:
        """左侧参数表单面板：标题 + 配置行 + 操作按钮 + 进度条。"""
        form_frame = QFrame(self)
        form_frame.setFixedWidth(300)
        form_frame.setStyleSheet(
            "QFrame { background-color: #1b1e26; border-radius: 8px; }"
        )
        ff = QVBoxLayout(form_frame)
        ff.setContentsMargins(12, 12, 12, 12)
        ff.setSpacing(8)

        lbl = QLabel(tr("训练配置"), form_frame)
        lbl.setStyleSheet("color: #7c3aed; font-size: 14px; font-weight: bold;")
        ff.addWidget(lbl)

        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignRight)

        self._build_form_basic_rows(form_frame, form)
        self._build_form_train_rows(form_frame, form)
        ff.addLayout(form)

        # 操作按钮
        btn_lay = QHBoxLayout()
        self.btn_start = QPushButton(tr("开始训练"), form_frame)
        self.btn_start.setProperty("role", "accent")
        self.btn_stop = QPushButton(tr("强制结束"), form_frame)
        self.btn_stop.setProperty("role", "danger")
        self.btn_stop.setEnabled(False)
        btn_lay.addWidget(self.btn_start)
        btn_lay.addWidget(self.btn_stop)
        ff.addLayout(btn_lay)

        # 进度条
        self.progress_bar = QProgressBar(form_frame)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        ff.addWidget(self.progress_bar)

        ff.addStretch()
        return form_frame

    def _build_form_basic_rows(self, form_frame: QWidget, form: QFormLayout) -> None:
        """基础配置行：预设/任务/轮数/学习率/批大小/骨干/早停/设备。"""
        # 配置预设（对标 SKolpha 多规模变体）
        self.cmb_preset = QComboBox(form_frame)
        for name in _TRAIN_PRESETS:
            self.cmb_preset.addItem(name, name)
        form.addRow(tr("预设"), self.cmb_preset)
        self.cmb_preset.currentIndexChanged.connect(self._apply_preset)

        self.cmb_task = QComboBox(form_frame)
        # W1: 下拉与引擎注册表实况对齐——全 9 项，缺引擎标"模拟"（首项保持 DET，兼容 UIA 默认）
        # W32：OCR 推理-only（无训练语义）——训练页不列
        populate_task_combo(
            self.cmb_task,
            only_available=False,
            unavailable_suffix="（模拟）",
            unavailable_tooltip="引擎未安装：训练将使用模拟策略（假 loss，仅供流程验证）",
            exclude=(TaskType.OCR,),
        )
        form.addRow(tr("任务"), self.cmb_task)

        self.spin_epochs = QSpinBox(form_frame)
        self.spin_epochs.setRange(1, 10000)
        self.spin_epochs.setValue(100)
        form.addRow(tr("轮数"), self.spin_epochs)

        self.spin_lr = QDoubleSpinBox(form_frame)
        self.spin_lr.setRange(0.000001, 1.0)
        self.spin_lr.setDecimals(6)
        self.spin_lr.setSingleStep(0.0001)
        self.spin_lr.setValue(0.001)
        form.addRow(tr("学习率"), self.spin_lr)

        self.spin_batch = QSpinBox(form_frame)
        self.spin_batch.setRange(1, 512)
        self.spin_batch.setValue(8)
        form.addRow(tr("批大小"), self.spin_batch)

        self.txt_backbone = QLineEdit("yolov8n", form_frame)
        form.addRow(tr("骨干"), self.txt_backbone)

        self.spin_patience = QSpinBox(form_frame)
        self.spin_patience.setRange(1, 200)
        self.spin_patience.setValue(20)
        form.addRow(tr("早停轮数"), self.spin_patience)

        self.cmb_device = QComboBox(form_frame)
        self.cmb_device.addItem("cuda")
        self.cmb_device.addItem("cpu")
        form.addRow(tr("设备"), self.cmb_device)

    def _build_form_train_rows(
        self, form_frame: QWidget, form: QFormLayout
    ) -> None:
        """训练增强行（R5-4）：图像尺寸/LR 调度/预热/混合精度/加载线程。"""
        # R5-4: 补全 TrainConfig 缺失字段
        self.spin_img_size = QSpinBox(form_frame)
        self.spin_img_size.setRange(64, 4096)
        self.spin_img_size.setValue(640)
        form.addRow(tr("图像尺寸"), self.spin_img_size)

        self.cmb_lr_scheduler = QComboBox(form_frame)
        self.cmb_lr_scheduler.addItem(tr("余弦"), "cosine")
        self.cmb_lr_scheduler.addItem(tr("阶跃"), "step")
        self.cmb_lr_scheduler.addItem(tr("平台"), "plateau")
        self.cmb_lr_scheduler.addItem(tr("无"), "none")
        form.addRow(tr("LR 调度"), self.cmb_lr_scheduler)

        self.spin_warmup = QSpinBox(form_frame)
        self.spin_warmup.setRange(0, 50)
        self.spin_warmup.setValue(3)
        form.addRow(tr("预热轮数"), self.spin_warmup)

        self.chk_amp = QCheckBox(form_frame)
        self.chk_amp.setChecked(True)
        form.addRow(tr("混合精度"), self.chk_amp)

        self.spin_workers = QSpinBox(form_frame)
        self.spin_workers.setRange(0, 32)
        self.spin_workers.setValue(4)
        form.addRow(tr("加载线程"), self.spin_workers)

    def _build_chart_panel(self) -> QVBoxLayout:
        """右侧训练曲线图 + 日志区。"""
        right = QVBoxLayout()
        right.setSpacing(8)
        lbl_chart = QLabel(tr("训练曲线"), self)
        lbl_chart.setStyleSheet(
            "color: #7c3aed; font-size: 14px; font-weight: bold;"
        )
        right.addWidget(lbl_chart)

        self.chart = LossChartWidget(self)
        self.chart.add_series("loss", "#ef4444")
        self.chart.set_title(tr("Loss"))
        right.addWidget(self.chart, 1)

        # 训练日志
        self.lbl_log = QLabel(tr("等待开始..."), self)
        self.lbl_log.setStyleSheet(
            "color: #94a3b8; font-size: 12px; padding: 4px;"
        )
        self.lbl_log.setWordWrap(True)
        right.addWidget(self.lbl_log)
        return right

    # ============================== 接线 ============================== #
    def _wire(self) -> None:
        self.btn_start.clicked.connect(self._start_training)
        self.btn_stop.clicked.connect(self._stop_training)

    def _apply_preset(self, idx: int) -> None:
        """应用配置预设到表单控件。"""
        preset_name = self.cmb_preset.itemData(idx) or "normal"
        preset = _TRAIN_PRESETS.get(preset_name, _TRAIN_PRESETS["normal"])
        self.txt_backbone.setText(preset["backbone"])
        self.spin_batch.setValue(preset["batch_size"])
        self.spin_lr.setValue(preset["lr"])
        # R5-4: 预设中的 resolution 写入 img_size
        if "resolution" in preset:
            self.spin_img_size.setValue(preset["resolution"])
        self.status_changed.emit(tr("预设"), preset_name)

    # ============================== 行为 ============================== #
    def _build_config(self) -> TrainConfig:
        """从表单构造 TrainConfig（R5-4: 补全全部字段）。"""
        raw_task = self.cmb_task.currentData()
        task = raw_task if isinstance(raw_task, TaskType) else TaskType(raw_task)
        return TrainConfig(
            task=task,
            epochs=self.spin_epochs.value(),
            lr=self.spin_lr.value(),
            batch_size=self.spin_batch.value(),
            backbone=self.txt_backbone.text().strip() or "yolov8n",
            patience=self.spin_patience.value(),
            device=self.cmb_device.currentText(),
            # R5-4: 补全缺失字段
            img_size=self.spin_img_size.value(),
            lr_scheduler=self.cmb_lr_scheduler.currentData(),
            warmup_epochs=self.spin_warmup.value(),
            amp=self.chk_amp.isChecked(),
            workers=self.spin_workers.value(),
        )

    def _start_training(self) -> None:
        """启动训练线程。"""
        # 检查旧线程是否仍在运行
        if self._worker is not None and self._worker.isRunning():
            self.status_changed.emit(tr("请等待上一轮训练结束"), "!")
            return

        cfg = self._build_config()
        # W31 AMP 预检：cuda 侧 fp16 前向+反向有限性探针；失败=警告+回退
        # FP32（cpu/lite 静默跳过，不随包 checkamp.pt 资产）
        if cfg.amp:
            ok, reason = amp_preflight(cfg.device)
            if not ok:
                logger.warning("AMP 预检失败，训练回退 FP32: %s", reason)
                self.status_changed.emit(tr("AMP 预检失败，已回退 FP32"), reason[:40])
                self.chk_amp.setChecked(False)
                import dataclasses

                cfg = dataclasses.replace(cfg, amp=False)
        self.chart.clear_all()
        self.chart.add_series("loss", "#ef4444")
        self.progress_bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_log.setText(tr("训练中..."))

        # 构建训练器（延迟导入避免循环依赖）
        try:
            trainer = self._make_trainer(cfg)
        except Exception as exc:
            self._on_failed(str(exc))
            return

        # W18（P3①）：无 parent 构造——页面持 self._worker 引用自管生命周期。
        # 以页面作 parent 会在窗口析构链上连带销毁（可能在仍运行时的）QThread
        # （"QThread: Destroyed while thread is still running" 崩溃路径）。
        self._worker = TrainWorker(trainer, cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_sig.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        # W18（P3①）：QThread.finished → 先清页面引用、再 deleteLater（顺序
        # 关键：closeEvent 的 getattr(self, "_worker").isRunning() 若拿到已
        # deleteLater 的 C++ 包装，PySide6 会抛 RuntimeError——引用先清，
        # closeEvent 只会见到 None）。
        worker = self._worker

        def _on_thread_finished() -> None:
            if getattr(self, "_worker", None) is worker:
                self._worker = None
            worker.deleteLater()

        qt_finished = getattr(worker, "finished", None)  # 测试替身可无该信号
        if qt_finished is not None:
            qt_finished.connect(_on_thread_finished)
        self._worker.start()

        # W18（P3① 留痕）：训练开始 INFO——操作 + 关键参数（日志可见性）
        logger.info(
            "训练开始: task=%s, epochs=%d, batch_size=%d, backbone=%s, device=%s",
            cfg.task.value, cfg.epochs, cfg.batch_size, cfg.backbone, cfg.device,
        )
        self.status_changed.emit(tr("训练已启动"), cfg.task.value)

    def _make_trainer(self, cfg: TrainConfig):
        """根据任务类型构建训练器（策略模式）。

        优先尝试真实引擎训练；W1: 引擎未注册 / 引擎无 train_epoch 两条
        假 loss 路径均显式警告后再回退模拟策略（消灭静默假 loss）。
        """
        from training.generic_trainer import GenericTrainer

        # 尝试从注册表获取引擎并构建真实训练策略
        # registry 直连为 GUI 正式形态（v3 P2-7）
        try:
            from models.supervised.registry import get_default_registry
            reg = get_default_registry()
            if reg.has(cfg.task):
                engine = reg.get(cfg.task)
                if hasattr(engine, "train_epoch"):
                    return GenericTrainer(cfg.task, EngineTrainStrategy(engine, cfg))
                self._warn_simulated(tr("引擎不支持逐轮训练，使用模拟训练"))
            else:
                self._warn_simulated(tr("任务引擎未注册，使用模拟训练"))
        except (ImportError, RuntimeError, OSError):
            import logging
            logging.getLogger(__name__).exception("引擎不可用，回退到模拟训练策略")
            self._warn_simulated(tr("引擎不可用，使用模拟训练"))

        # 回退：模拟训练策略（用于 UI 验证 / 无 GPU 环境）
        class _SimStrategy:
            """模拟训练策略：返回递减 loss（用于 UI 验证）。"""
            task = cfg.task
            _ep = 0

            def train_epoch(self, epoch: int, cfg: TrainConfig):
                self._ep = epoch
                import math
                loss = 1.0 * math.exp(-epoch * 0.05)
                return {"loss": round(loss, 4)}

            def save(self, path: str) -> None:
                pass

            def get_optimizer(self):
                """R5-3: 返回 None 避免 LR 调度器 AttributeError。"""
                return None

        return GenericTrainer(cfg.task, _SimStrategy())

    def _warn_simulated(self, message: str) -> None:
        """R5-3/W1：进入模拟训练模式时显式警告（状态栏 + 日志区，不静默）。"""
        self.status_changed.emit(message, "warn")
        self.lbl_log.setText(tr("警告：") + message)

    def _stop_training(self) -> None:
        """请求强制结束。"""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.lbl_log.setText(tr("正在停止..."))
            self.status_changed.emit(tr("训练中止"), "...")
            # 等待线程退出（最多 5 秒）
            self._worker.wait(5000)

    def _on_progress(self, ratio: float, metrics: dict) -> None:
        """进度回调（主线程，经信号槽）。"""
        pct = int(ratio * 100)
        self.progress_bar.setValue(pct)
        if "loss" in metrics:
            self.chart.append("loss", metrics["loss"])
            self.chart.update()
        # 显示关键指标
        parts = [f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                 for k, v in metrics.items()]
        self.lbl_log.setText(f"epoch {int(ratio * self.spin_epochs.value())}: "
                             + "  ".join(parts))
        self.status_changed.emit(tr("训练中"), f"{pct}%")

    def _on_finished(self, artifact) -> None:
        """训练完成回调。"""
        # W18（P3① 留痕）：训练完成 INFO——操作 + 关键参数（日志可见性）
        logger.info(
            "训练完成: task=%s, epochs_completed=%s",
            artifact.task.value, getattr(artifact, "epochs_completed", None),
        )
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.lbl_log.setText(
            tr("训练完成") + f": {artifact.epochs_completed} " + tr("轮")
        )
        self.status_changed.emit(tr("训练完成"), artifact.task.value)
        # W14-C3（P2-11③）：训练完成审计接线——log_train_complete 此前
        # 全仓 0 调用（docstring 宣称记录训练，实际无消费者）；user 取
        # 会话当前用户（core.session，登录页写入），artifact 字段可得则传。
        try:
            from core.audit_logger import log_train_complete
            from core.session import get_current_user

            log_train_complete(
                user=get_current_user(),
                task=artifact.task.value,
                epochs=int(getattr(artifact, "epochs_completed", 0) or 0),
                best_metric=float(getattr(artifact, "best_metric", 0.0) or 0.0),
                weights_path=str(getattr(artifact, "weights_path", "") or ""),
            )
        except (ImportError, OSError, TypeError, ValueError):
            logger.exception("训练完成审计写入失败")

    def _on_failed(self, msg: str) -> None:
        """训练失败回调。"""
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_log.setText(tr("训练失败") + f": {msg}")
        self.status_changed.emit(tr("训练失败"), "ERROR")

    def retranslate(self) -> None:
        self.btn_start.setText(tr("开始训练"))
        self.btn_stop.setText(tr("强制结束"))


__all__ = ["TrainPage", "EngineTrainStrategy"]


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
