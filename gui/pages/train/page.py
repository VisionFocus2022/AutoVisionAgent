"""训练页：参数配置 + 实时 Loss 曲线 + 可中断训练（FR-D5 / FR-B2 / FR-B3）。

对接 training/generic_trainer.GenericTrainer（通过可插拔 ITrainStrategy）
与 models/supervised/ 注册表。
"""
from __future__ import annotations

import dataclasses
import logging
import os

from PySide6.QtCore import Qt, Signal, Slot
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
from dataset.format_export import candidate_label_dirs, label_txt_files
from gui.core.i18n import tr
from gui.core.tasks_ui import populate_task_combo
from gui.pages.train.strategy import EngineTrainStrategy  # W1-1 拆分（规模守卫）
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

    request_page = Signal(str)  # W59c：「下一步」向导导航
    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._worker: TrainWorker | None = None
        self._active_engine = None  # W1-1：真训练引擎引用（停止联动）
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
        # W59c：训练完成→推理（加载产物批量推理）；权限门随 shell.select
        self.btn_goto_predict = QPushButton(tr("下一步：推理"), form_frame)
        self.btn_goto_predict.clicked.connect(
            lambda: self.request_page.emit("predict"))
        btn_lay.addWidget(self.btn_goto_predict)
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
        # W1: 下拉与引擎注册表实况对齐——全 9 项，缺引擎标"未装引擎"（首项保持 DET，兼容 UIA 默认）
        # W32：OCR 推理-only（无训练语义）——训练页不列
        # W1-3：非真训练任务（引擎在≠能真训练）灰显+后缀"（模拟训练）"
        from models.supervised.registry import REAL_TRAIN_TASKS

        populate_task_combo(
            self.cmb_task,
            only_available=False,
            unavailable_suffix="（未装引擎·模拟）",
            unavailable_tooltip="引擎未安装：训练将使用模拟策略（假 loss，仅供流程验证）",
            simulated=frozenset(
                t for t in TaskType
                if t not in REAL_TRAIN_TASKS and t is not TaskType.OCR
            ),
            exclude=(TaskType.OCR,),
        )
        form.addRow(tr("任务"), self.cmb_task)

        # W58 真训练通道（PRD FR-1）：数据集 data.yaml 选择行——导出训练集
        # 产物；空=训练页拦截回退模拟（诚实警告，见 _build_trainer）
        self.txt_data = QLineEdit(form_frame)
        self.txt_data.setPlaceholderText(tr("未选择（模拟训练）"))
        btn_data = QPushButton(tr("浏览"), form_frame)
        btn_data.clicked.connect(self._browse_data_yaml)
        data_row = QWidget(form_frame)
        h_data = QHBoxLayout(data_row)
        h_data.setContentsMargins(0, 0, 0, 0)
        h_data.addWidget(self.txt_data, 1)
        h_data.addWidget(btn_data)
        form.addRow(tr("数据集"), data_row)

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
    def _browse_data_yaml(self) -> None:
        """选择训练数据集清单（data.yaml，数据管理页导出训练集产物）。"""
        from gui.widgets.file_dialog import pick_open_file

        path = pick_open_file(
            self, tr("选择数据集"), "Dataset YAML (*.yaml *.yml)"
        )
        if path:
            self.txt_data.setText(path)
            self._echo_dataset_stats(path)

    def apply_external_dataset(self, yaml_path: str) -> None:
        """应用外部传入的数据集清单（W63：数据管理「下一步」向导交接）。

        与 _browse_data_yaml 同语义（填入+统计回显），无对话框——
        真实训练仍需显式点「开始训练」，此处只带上下文不触发任何重活。
        """
        self.txt_data.setText(yaml_path)
        self._echo_dataset_stats(yaml_path)

    def _echo_dataset_stats(self, yaml_path: str) -> None:
        """数据集样本统计回显（W59b · PRD FR-2）：train/val 各 N 张。

        只数文件不解析标签（轻量）；{split} 与 {split}/images 两目录形态
        均认；清单缺键/路径无效/文件不可读诚实提示。
        W69：顺带按标签格式自动选任务（>5 列=分割，5 列=检测）——杜绝
        「多边形数据集配检测任务」的静默假训练错配。
        """
        try:
            from yaml import safe_load

            with open(yaml_path, encoding="utf-8") as fh:
                doc = safe_load(fh) or {}
            base = os.path.dirname(os.path.abspath(yaml_path))
            parts: list[str] = []
            train_dir = ""
            for split in ("train", "val"):
                rel = doc.get(split)
                if not isinstance(rel, str):
                    continue
                for cand in (
                    os.path.join(base, rel),
                    os.path.join(base, rel, "images"),
                ):
                    if os.path.isdir(cand):
                        if split == "train":
                            train_dir = cand
                        n = sum(
                            1 for f in os.listdir(cand)
                            if f.lower().endswith(
                                (".png", ".jpg", ".jpeg", ".bmp")
                            )
                        )
                        parts.append(f"{split}={n}")
                        break
            if parts:
                self.status_changed.emit(tr("数据集"), " ".join(parts))
            else:
                self.status_changed.emit(
                    tr("数据集清单读取失败"), "train/val 键缺失或路径无效"
                )
            # W69：任务自动识别（统计回显是浏览/向导两条路的公共漏斗）
            fmt = self._detect_label_format(train_dir)
            if fmt is not None:
                self._set_task_combo(fmt)
        except (OSError, ValueError) as exc:
            self.status_changed.emit(tr("数据集清单读取失败"), str(exc)[:60])

    def _detect_label_format(self, train_dir: str) -> str | None:
        """从训练目录推断标签格式：'seg'（>5 列）/ 'det'（5 列）/ None。

        导出器按标注几何写行：矩形=5 列 det 行，多边形=6+ 列 seg 行。
        P0-1 起导出为划分布局 images/{train,val} + labels/{train,val}——
        标签在 labels/train/ 子目录；旧平铺 labels/*.txt 兼容（W1-1 批
        实证修复：平铺假设在布局升级后静默回退 det，多边形数据跑成检测）。
        """
        for labels_dir in candidate_label_dirs(train_dir):
            files = label_txt_files(labels_dir)
            for path in files:
                try:
                    with open(path, encoding="utf-8") as fh:
                        for line in fh:
                            tokens = line.split()
                            if not tokens:
                                continue
                            if len(tokens) > 5:
                                return "seg"
                            if len(tokens) == 5:
                                return "det"
                            return None  # 畸形行（<5 列）不猜
                except OSError:
                    continue
        return None

    def _set_task_combo(self, fmt: str) -> None:
        """把任务下拉设为与数据格式一致并状态告知（W69）。"""
        target = TaskType.SEG if fmt == "seg" else TaskType.DET
        if self.cmb_task.currentData() == target:
            return
        for i in range(self.cmb_task.count()):
            if self.cmb_task.itemData(i) == target:
                self.cmb_task.setCurrentIndex(i)
                name = tr("分割") if fmt == "seg" else tr("检测")
                self.status_changed.emit(
                    tr("任务已按数据格式自动选择"), name
                )
                return

    def _correct_task_for_dataset(self, cfg: TrainConfig):
        """W69 启动守卫：任务与数据格式不符 → 纠正任务并返回提示。

        Returns:
            (cfg, note)——note 非空时调用方发状态警告；数据格式未知时
            原样返回（不猜）。
        """
        fmt = self._detect_label_format_from_yaml(cfg.data_yaml)
        if fmt is None:
            return cfg, ""
        target = TaskType.SEG if fmt == "seg" else TaskType.DET
        if cfg.task is target:
            return cfg, ""
        name = tr("分割") if fmt == "seg" else tr("检测")
        return (
            dataclasses.replace(cfg, task=target),
            tr("任务与数据集格式不符，已自动纠正为") + name,
        )

    def _detect_label_format_from_yaml(self, yaml_path: str) -> str | None:
        """从 data.yaml 解析 train 图像目录后探标签格式（守卫用）。"""
        if not yaml_path or not os.path.isfile(yaml_path):
            return None
        try:
            from yaml import safe_load

            with open(yaml_path, encoding="utf-8") as fh:
                doc = safe_load(fh) or {}
            rel = doc.get("train")
            if not isinstance(rel, str):
                return None
            base = os.path.dirname(os.path.abspath(yaml_path))
            for cand in (
                os.path.join(base, rel),
                os.path.join(base, rel, "images"),
            ):
                if os.path.isdir(cand):
                    return self._detect_label_format(cand)
            return None
        except (OSError, ValueError):
            return None

    def _will_be_simulated(self, cfg: TrainConfig | None = None) -> bool:
        """本次启动是否将走模拟训练（W1-3：任务无真通道 或 未选数据集）。"""
        cfg = cfg or self._build_config()
        from models.supervised.registry import task_supports_real_training

        return (not task_supports_real_training(cfg.task)) or not (
            getattr(cfg, "data_yaml", "") or ""
        )

    def _confirm_simulated(self) -> bool:
        """模拟训练显式确认框（W1-3）。测试缝：覆写本方法绕开模态框。"""
        return _confirm_simulated_dialog(self)

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
            data_yaml=self.txt_data.text().strip(),
        )

    def _start_training(self) -> None:
        """启动训练线程。"""
        # W67 留痕：入口即记（此前点击→预检→建训练器全链零日志，卡住无从
        # 定位——用户实测「一直在等待开始」即 AMP 预检在 UI 线程卡 CUDA）
        logger.info("训练启动流程进入")
        # 检查旧线程是否仍在运行
        if self._worker is not None and self._worker.isRunning():
            self.status_changed.emit(tr("请等待上一轮训练结束"), "!")
            return

        cfg = self._build_config()
        # W69 启动守卫：任务与数据集标签格式不符（如检测+多边形数据）→
        # 自动纠正——此前该错配会让真通道失效/训练报错，用户侧表现为假训练
        import dataclasses

        cfg, note = self._correct_task_for_dataset(cfg)
        if note:
            self.status_changed.emit(note, "!")
        # W1-3 显式确认：模拟训练（任务无真通道 或 未选数据集）在一切
        # 状态变更前过用户确认——拒绝=零状态变更直接返回（按钮/表单原样）
        if self._will_be_simulated(cfg) and not self._confirm_simulated():
            self.status_changed.emit(tr("已取消"), tr("模拟训练需确认"))
            logger.info("模拟训练确认被拒，未启动")
            return
        # W67：反馈前置——AMP 预检（CUDA fp16 探针）跑在 UI 线程，冷驱动/
        # 上下文竞争时可秒级~分钟级阻塞；先亮状态禁按钮再探，杜绝静默假死
        self.chart.clear_all()
        self.chart.add_series("loss", "#ef4444")
        self.progress_bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        # M17（2026-10-05 二轮审查）：训练期间锁定表单——_on_progress 用
        # 当前 spin_epochs 值反推 epoch，训练中改表单会让日志行 epoch
        # 错乱；改了也只影响下次启动但用户无感知。锁定全部配置控件组。
        self._set_form_enabled(False)
        self.lbl_log.setText(tr("训练中..."))
        # W31 AMP 预检：cuda 侧 fp16 前向+反向有限性探针；失败=警告+回退
        # FP32（cpu/lite 静默跳过，不随包 checkamp.pt 资产）
        if cfg.amp:
            logger.info("AMP 预检开始: device=%s", cfg.device)
            ok, reason = amp_preflight(cfg.device)
            logger.info("AMP 预检结束: ok=%s reason=%s", ok, reason)
            if not ok:
                logger.warning("AMP 预检失败，训练回退 FP32: %s", reason)
                self.status_changed.emit(tr("AMP 预检失败，已回退 FP32"), reason[:40])
                self.chk_amp.setChecked(False)
                import dataclasses

                cfg = dataclasses.replace(cfg, amp=False)

        # 构建训练器（延迟导入避免循环依赖）
        # O10（2026-10-05 二轮审查）：except 元组收窄——裸 Exception 会把
        # _make_trainer 内的编码 bug（AttributeError 等）也变成"训练失败"
        # 文案，掩盖真实缺陷。_on_failed 已补 logger.exception 留痕。
        try:
            trainer = self._make_trainer(cfg)
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            logger.exception("_make_trainer 构建失败")
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
                    # W58 真训练通道：真引擎还需选定数据集（data.yaml）——
                    # 未选时诚实回退模拟，避免 train_epoch 纵深防御抛错
                    if cfg.data_yaml:
                        # W1-1：逐轮进度钩子（回调在工作线程→invoke_main
                        # 派发主线程槽）+ 持引用供停止联动
                        self._active_engine = engine
                        if hasattr(engine, "set_progress_callback"):
                            engine.set_progress_callback(self._emit_epoch_progress)
                        return GenericTrainer(cfg.task, EngineTrainStrategy(engine, cfg))
                    self._warn_simulated(tr("未选择数据集，使用模拟训练"))
                else:
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

    def _set_form_enabled(self, enabled: bool) -> None:
        """M17（2026-10-05 二轮审查）：训练期间锁定/恢复表单配置控件。

        训练中改 spin_epochs 等会让 _on_progress 的 epoch 反推错乱，且
        用户无感知"改了只影响下次启动"。锁定的是配置输入面（btn_start/
        btn_stop 由训练状态机单独管理，不在此列）。
        """
        for attr in (
            "cmb_task", "spin_epochs", "spin_batch", "spin_lr",
            "edit_dataset", "chk_amp", "cmb_device", "cmb_scheduler",
            "spin_patience",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(enabled)

    def _stop_training(self) -> None:
        """请求停止（P1-R5：协作式，不再 UI 线程阻塞 wait）。

        此前 self._worker.wait(5000) 在主线程同步等训练线程至多 5 秒：
        fit() 处于长 epoch 中不检查 stop_flag 时 UI 冻结，且"正在停止..."
        文案在 wait 之后才可能渲染（事件循环已停转）。

        现改为：置 stop 标志 → 禁用停止按钮防重复点击 → 状态栏即时反馈。
        线程退出由 finished_sig/failed 信号正常回调 _on_finished/_on_failed
        复位 UI（协作取消依赖 fit 循环周期性检查 should_stop）。
        """
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            # W1-1：真训练一次性适配器下 should_stop 只在外层轮间隙生效=
            # 内部 ultralytics 全程收不到——同步请求引擎破环（下一内部
            # epoch 边界置 trainer.stop）
            engine = getattr(self, "_active_engine", None)
            if engine is not None and hasattr(engine, "request_stop"):
                engine.request_stop()
            self.btn_stop.setEnabled(False)  # 防重复点击（完成回调统一复位）
            self.lbl_log.setText(tr("已请求停止，等待当前轮结束..."))
            self.status_changed.emit(tr("训练停止中"), "...")

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

    def _emit_epoch_progress(self, info: dict) -> None:
        """W1-1：引擎逐轮回调（训练工作线程）→ invoke_main 派发主线程。"""
        from gui.core.thread_bridge import invoke_main

        invoke_main(self, "_on_epoch_progress_ui", dict(info))

    @Slot(dict)
    def _on_epoch_progress_ui(self, info: dict) -> None:
        """W1-1：逐轮进度落地（主线程）——进度条/曲线/剩余时间。"""
        k, total = info.get("epoch", 0), max(info.get("total", 1), 1)
        pct = min(int(k / total * 100), 99)
        self.progress_bar.setValue(pct)
        loss = info.get("loss")
        if loss is not None:
            self.chart.append("loss", loss)
            self.chart.update()
        eta = info.get("eta_s")
        eta_txt = ""
        if isinstance(eta, (int, float)) and eta > 0:
            mm, ss = divmod(int(eta), 60)
            eta_txt = f" · 剩余 {mm}:{ss:02d}"
        self.lbl_log.setText(f"epoch {k}/{total}{eta_txt}")
        self.status_changed.emit(tr("训练中"), f"{pct}%")

    def _on_finished(self, artifact) -> None:
        """训练完成回调。"""
        # W18（P3① 留痕）：训练完成 INFO——操作 + 关键参数（日志可见性）
        metrics = getattr(artifact, "metrics", None) or {}
        # W1-6：一次性适配器的 epochs_effective 反映真实内部轮数（小数据
        # 自适应提升时外层计数会低估）；P/R/mAP50 让"训练没学"肉眼可见
        n_epochs = metrics.get("epochs_effective") or artifact.epochs_completed
        pr_text = _format_final_metrics(metrics)
        logger.info(
            "训练完成: task=%s, epochs_completed=%s, metrics=%s",
            artifact.task.value, n_epochs, pr_text or "n/a",
        )
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_form_enabled(True)  # M17：训练结束恢复表单
        self.progress_bar.setValue(100)
        self.lbl_log.setText(
            tr("训练完成") + f": {n_epochs} " + tr("轮")
            + (f"  {pr_text}" if pr_text else "")
        )
        self.status_changed.emit(
            tr("训练完成"), artifact.task.value + (f" {pr_text}" if pr_text else "")
        )
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
        """训练失败回调（O10：补 logger.exception 留痕——此前仅 UI 文案，
        日志不可见，失败根因无迹可查）。"""
        logger.error("训练失败: %s", msg, exc_info=True)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_form_enabled(True)  # M17：失败路径同样恢复表单
        self.lbl_log.setText(tr("训练失败") + f": {msg}")
        self.status_changed.emit(tr("训练失败"), "ERROR")

    def retranslate(self) -> None:
        self.btn_start.setText(tr("开始训练"))
        self.btn_stop.setText(tr("强制结束"))


def _confirm_simulated_dialog(parent) -> bool:
    """模拟训练显式确认框（W1-3 拆自页面方法）。自定义中文按钮不依赖 Qt 翻译。"""
    from PySide6.QtWidgets import QMessageBox

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(tr("模拟训练确认"))
    msg.setText(tr("即将执行模拟训练：该任务未实装真训练或未选择数据集，训练过程为假 loss 模拟，不会产生可用的真实模型。"))
    btn_go = msg.addButton(tr("继续模拟训练"), QMessageBox.YesRole)
    msg.addButton(tr("取消"), QMessageBox.NoRole)
    msg.setDefaultButton(btn_go)
    msg.exec()
    return msg.clickedButton() is btn_go


def _format_final_metrics(metrics: dict | None) -> str:
    """末轮 val 指标 → 完成状态文案（W1-6）。

    三键齐全才格式化（部分指标显示半截比不显示更误导）；任何形态
    异常返回空串——显示层不挡训练完成路径。
    """
    try:
        return (
            f"P={metrics['precision']:.2f} R={metrics['recall']:.2f}"
            f" mAP50={metrics['map50']:.2f}"
        )
    except (KeyError, TypeError, ValueError):
        return ""



