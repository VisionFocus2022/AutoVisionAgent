"""推理页：模型加载 + 单张/批量推理 + 结果表 + 导出（FR-D6 / FR-E3）。

对接 models/supervised/ 引擎注册表，支持 det/seg/abdet 推理。
"""
from __future__ import annotations

import contextlib
import logging
import os

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult
from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.permissions import check_action  # W35：动作门控
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.pages.predict.export_actions import ExportActionsMixin  # W24 规模拆分
from gui.pages.predict.video_super_actions import VideoSuperActionsMixin  # W34
from gui.pages.predict.workers import (
    batch_save_dir,
    collect_images,
    result_to_record,
    row_display_fields,
)
from gui.widgets.file_dialog import (
    pick_directory,
    pick_open_file,
    pick_save_file,  # noqa: F401  测试缝：既有 monkeypatch 经本模块名引用（export_actions._pick_save_file 转发解析）
)
from inference.sv_bridge import render_result  # W33：批量叠加图（页面级绑定保测试缝）

logger = logging.getLogger(__name__)


class PredictPage(VideoSuperActionsMixin, ExportActionsMixin, QWidget):
    """推理页：加载模型 → 单张/批量推理 → 结果表 → 导出。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._project_dir: str | None = None
        self._models_dir: str | None = None
        self._model_path: str | None = None
        self._engine = None  # ISupervisedTaskEngine 实例
        self._results: list[dict] = []  # 批量结果缓存
        self._batch_cancel = False  # 批量推理取消标志
        # P1-R4：单张推理请求 ID 与结果槽（跨线程传递契约，见 _single_infer
        # docstring）——请求 ID 单调递增，_single_done 校验后才消费结果，
        # 防止"快速连点两次推理时第一次结果被第二次静默覆盖丢失"
        self._single_req_id: int = 0
        self._pending_single: tuple[int, str, DetectionResult] | None = None
        # W21：预览原始图（全分辨率）——按预览区自适应缩放，resize 时重适配
        self._preview_source: QPixmap | None = None

        self._build_ui()
        self._wire()

    # ============================== UI ============================== #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 顶部工具栏 ----
        root.addWidget(self._build_toolbar())

        # ---- 正文：预览 + 结果表 ----
        root.addLayout(self._build_body(), 1)

    def _build_toolbar(self) -> QFrame:
        """顶部工具栏：推理组（任务/模型/单张/批量）+ 导出/统计组。"""
        bar = QFrame(self)
        bar.setObjectName("toolbar")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self._build_toolbar_infer_group(bar, h)
        self._build_toolbar_export_group(bar, h)
        return bar

    def _build_toolbar_infer_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏推理组：任务下拉 + 模型加载 + 单张/批量 + 取消/进度。"""
        self.cmb_task = QComboBox(bar)
        # W1: 推理页只列已注册引擎的任务（旧下拉恰好只含缺失的 det/seg/abdet）
        from gui.core.tasks_ui import populate_task_combo
        populate_task_combo(self.cmb_task, only_available=True)
        h.addWidget(self.cmb_task)

        self.btn_load_model = QPushButton(tr("加载模型"), bar)
        h.addWidget(self.btn_load_model)

        self.lbl_model = QLabel(tr("未加载"), bar)
        self.lbl_model.setStyleSheet("color: #94a3b8; font-size: 12px;")
        h.addWidget(self.lbl_model)

        sep1 = QFrame(bar)
        sep1.setFixedWidth(1)
        sep1.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep1)

        # W28：推理阈值（引擎 infer/infer_batch 已支持，GUI 此前从未传参）
        self.lbl_threshold = QLabel(tr("阈值"), bar)
        h.addWidget(self.lbl_threshold)
        self.spin_threshold = QDoubleSpinBox(bar)
        self.spin_threshold.setObjectName("thresholdSpin")
        self.spin_threshold.setRange(0.01, 0.99)
        self.spin_threshold.setDecimals(2)
        self.spin_threshold.setSingleStep(0.05)
        self.spin_threshold.setValue(0.5)
        h.addWidget(self.spin_threshold)

        # W33：对象类型过滤（SKolpha「阈值+对象类型」双参收尾；空=全部）
        self.edit_label_filter = QLineEdit(bar)
        self.edit_label_filter.setObjectName("labelFilterEdit")
        self.edit_label_filter.setPlaceholderText(tr("对象类型过滤（逗号分隔，空=全部）"))
        self.edit_label_filter.setFixedWidth(150)
        h.addWidget(self.edit_label_filter)

        # W33：批量叠加结果图开关（可选产物）
        self.chk_overlay = QCheckBox(tr("叠加图"), bar)
        self.chk_overlay.setObjectName("overlayChk")
        h.addWidget(self.chk_overlay)

        self.btn_single = QPushButton(tr("单张推理"), bar)
        self.btn_single.setProperty("role", "accent")
        h.addWidget(self.btn_single)

        self.btn_batch = QPushButton(tr("批量推理"), bar)
        h.addWidget(self.btn_batch)

        # W34：逐帧视频超分（零新依赖；插帧 non-goal）
        self.btn_video_super = QPushButton(tr("视频超分"), bar)
        self.btn_video_super.setProperty("tool", True)
        h.addWidget(self.btn_video_super)

        self._btn_cancel_batch = QPushButton(tr("取消"), bar)
        self._btn_cancel_batch.setVisible(False)
        self._btn_cancel_batch.setStyleSheet("color: #ff6b6b;")
        h.addWidget(self._btn_cancel_batch)

        from PySide6.QtWidgets import QProgressBar
        self._progress = QProgressBar(bar)
        self._progress.setFixedWidth(120)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        h.addWidget(self._progress)

    def _build_toolbar_export_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏导出组：CSV/JSON/Excel 导出 + 统计报表。"""
        sep2 = QFrame(bar)
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep2)

        self.btn_export_csv = QPushButton(tr("导出CSV"), bar)
        h.addWidget(self.btn_export_csv)
        self.btn_export_json = QPushButton(tr("导出JSON"), bar)
        h.addWidget(self.btn_export_json)
        self.btn_export_excel = QPushButton(tr("导出Excel"), bar)
        h.addWidget(self.btn_export_excel)

        sep3 = QFrame(bar)
        sep3.setFixedWidth(1)
        sep3.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep3)

        self.btn_stats = QPushButton(tr("统计报表"), bar)
        self.btn_stats.setProperty("tool", True)
        h.addWidget(self.btn_stats)

        h.addStretch()

    def _build_body(self) -> QHBoxLayout:
        """正文：左预览 + 右结果表。"""
        body = QHBoxLayout()
        body.setSpacing(10)

        # 左：预览
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "background-color: #0f1117; border-radius: 8px; color: #64748b;"
        )
        self.preview.setText(tr("选择图像进行推理"))
        self.preview.setMinimumWidth(400)
        body.addWidget(self.preview, 1)

        # 右：结果表
        right = QVBoxLayout()
        right.setSpacing(6)
        lbl = QLabel(tr("推理结果"), self)
        lbl.setStyleSheet("color: #7c3aed; font-size: 13px; font-weight: bold;")
        right.addWidget(lbl)

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("文件"), tr("类别"), tr("分数"), tr("信息")
        ])
        self.table.setStyleSheet(
            "QTableWidget { background-color: #13151c; border-radius: 8px; }"
            "QHeaderView::section { background-color: #1b1e26; }"
        )
        right.addWidget(self.table, 1)
        body.addLayout(right, 0)

        right_frame = QFrame(self)
        right_frame.setFixedWidth(380)
        rl = QVBoxLayout(right_frame)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(right)
        body.addWidget(right_frame)
        return body

    # ============================== 接线 ============================== #
    def _wire(self) -> None:
        self.btn_load_model.clicked.connect(self._load_model)
        self.btn_single.clicked.connect(self._single_infer)
        self.btn_batch.clicked.connect(self._batch_infer)
        self.btn_video_super.clicked.connect(self._video_super)
        self._btn_cancel_batch.clicked.connect(self._batch_cancel_infer)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_stats.clicked.connect(self._show_stats)

    # ============================== 行为 ============================== #
    def set_project_dir(self, path: str) -> None:
        """设置项目根目录。"""
        self._project_dir = path
        models = os.path.join(path, "models")
        if os.path.isdir(models):
            self._models_dir = models

    def _load_model(self) -> None:
        """加载模型权重。

        P0-3（2026-10-05 二轮审查 R3）：推理任务进行中禁止换模型——
        批量/单张推理的 worker 线程正持有 self._engine 做 infer，此处
        unload() 旧引擎会造成子线程 use-after-unload（崩溃或 CUDA 非法
        访存）。入口守卫 + 按钮态双保险。
        """
        # 入口守卫：任何推理 job 在册时拒绝加载（防旁路入口）
        from gui.core.jobs import active_jobs

        busy = [n for n in active_jobs() if n.startswith("predict_")]
        if busy:
            self.status_changed.emit(
                tr("推理进行中，禁止更换模型"), "!"
            )
            return
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._model_path = path
        task = self.cmb_task.currentData()
        try:
            # 尝试从注册表获取引擎——registry 直连为 GUI 正式形态（v3 P2-7）
            from models.supervised.registry import get_default_registry
            reg = get_default_registry()

            # 卸载旧引擎（释放 GPU 显存）
            if self._engine is not None:
                with contextlib.suppress(RuntimeError, AttributeError):
                    self._engine.unload()
                self._engine = None
                reg.clear_cache(task=self.cmb_task.currentData())

            if reg.has(task):
                self._engine = reg.get(task)
                # 设备解析（W13 C1）：设置页持久化的 user_settings.device 优先
                # → 无则 "cuda" → cuda 时校验 torch.cuda.is_available()，
                #   torch ImportError 回退 cpu（四分支链语义保持）
                _device = "cpu"
                try:
                    from gui.core.settings_io import get_device
                    _device = get_device() or "cuda"
                except (ImportError, OSError, ValueError):
                    _device = "cuda"
                if _device == "cuda":
                    try:
                        import torch
                        if not torch.cuda.is_available():
                            _device = "cpu"
                    except ImportError:
                        _device = "cpu"
                self._engine.load(path, device=_device)
            else:
                self._engine = None
                self.status_changed.emit(
                    tr("引擎未注册"), task.value
                )
                self.lbl_model.setText(tr("引擎未注册"))
                return
            self.lbl_model.setText(os.path.basename(path))
            self.status_changed.emit(tr("模型已加载"), task.value)
        except (RuntimeError, OSError, ValueError,
                SupervisedEngineError) as exc:
            # W28 审计折入：坏 checkpoint 时引擎 load 抛 SupervisedEngineError
            # （AppError 子类）——旧元组漏收则逃出槽函数且引擎残留半加载态
            # O9（P1，2026-10-05 二轮审查）：except 分支必须清理残留的半加载
            # 引擎——此前 self._engine 仍是 reg.get(task) 返回的实例（非空），
            # 用户失败后直接点"单张推理"会通过引擎预检然后 infer 崩溃。
            self.lbl_model.setText(tr("加载失败"))
            self.status_changed.emit(tr("模型加载失败"), str(exc)[:40])
            if self._engine is not None:
                with contextlib.suppress(RuntimeError, AttributeError):
                    self._engine.unload()
                self._engine = None
                with contextlib.suppress(Exception):
                    from models.supervised.registry import get_default_registry
                    get_default_registry().clear_cache(task=task)
                logger.info("已清理半加载引擎（加载失败路径）")

    def _threshold(self) -> float:
        """当前推理阈值（单张/批量共用，W28）。"""
        return round(self.spin_threshold.value(), 2)

    def _single_infer(self) -> None:
        """单张推理（W3-T3: 推理移出 UI 线程，结果经 invoke_main 回主线程）。

        P1-R4 跨线程传递契约（2026-10-05 二轮审查）：
        worker 写 self._pending_single = (req_id, path, result) 后调
        invoke_main 排队 _single_done；QueuedConnection 的排队顺序提供
        happens-before（同请求的写先于主线程读）。请求 ID 单调递增，
        _single_done 只消费"最新请求"的结果——旧请求迟到的回调被 ID
        校验拒绝，不再出现结果静默覆盖。btn_single 在推理期间禁用，
        正常路径本就无并发；该守卫覆盖取消/异常竞态的边界窗口。
        """
        if not self._engine:
            self.status_changed.emit(tr("请先加载模型"), "!")
            return
        path = pick_open_file(
            self, "选择图像",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if not path:
            return

        self.btn_single.setEnabled(False)
        self.btn_single.setText(tr("推理中..."))
        # P0-3：单张推理中禁用换模型（use-after-unload 防护，与批量一致）
        self.btn_load_model.setEnabled(False)
        self._single_req_id += 1
        req_id = self._single_req_id
        self._pending_single = None
        threshold = self._threshold()  # W28 审计折入：UI 线程捕获（与批量对齐）

        def _work():
            try:
                from core.image_io import imread_unicode
                img = imread_unicode(path)
                if img is None:
                    invoke_main(self, "_single_failed", tr("图像读取失败"))
                    return
                result: DetectionResult = self._engine.infer(
                    img, threshold=threshold
                )
                score = float(result.score) if result.score else 0.0
                self._pending_single = (req_id, path, result)
                invoke_main(self, "_single_done", os.path.basename(path), score)
            except (RuntimeError, OSError, ValueError,
                    SupervisedEngineError) as exc:
                invoke_main(self, "_single_failed", str(exc)[:40])

        # W17（v3 P2-1）：on_error 兜底——元组外异常（如 numpy TypeError）也复位按钮
        run_job(_work, name="predict_single", on_error=ui_on_error(self, "_single_failed"))

    @Slot(str, float)
    def _single_done(self, basename: str, score: float) -> None:
        """槽：单张推理完成（主线程）——显示结果/记录行/审计。

        P1-R4：请求 ID 校验——仅当 pending 结果属于最新请求时消费；
        旧请求迟到的结果丢弃并留痕（可见性而非静默吞）。
        """
        self.btn_single.setEnabled(True)
        self.btn_single.setText(tr("单张推理"))
        self.btn_load_model.setEnabled(True)  # P0-3：恢复换模型入口
        if self._pending_single is None:
            return
        pending_id, path, result = self._pending_single
        if pending_id != self._single_req_id:
            logger.warning(
                "丢弃过期单张推理结果 (req %d != 当前 %d): %s",
                pending_id, self._single_req_id, path,
            )
            self._pending_single = None
            return
        self._pending_single = None

        # 在预览区显示原图 + 叠加检测框
        self._show_result(path, result)
        self._add_result_row(path, result)
        self.status_changed.emit(basename, f"{tr('分数')}: {score:.3f}")

        # R4-6: 记录审计日志 + 检测历史
        try:
            from core.audit_logger import log_detection_complete
            from core.detection_history import get_history
            from core.session import get_current_user
            _task = self.cmb_task.currentData() or "det"
            _count = len(result.boxes) if result.boxes is not None else 0
            log_detection_complete(
                user=get_current_user(),
                task=_task, image=path, result_count=_count,
            )
            get_history().add_record(
                task=_task,
                image_path=path,
                result_count=_count,
                score_avg=score,
            )
        except Exception:
            # W39·v6 P3-3：审计/历史写失败不阻塞推理，但须留痕可排查
            # （原裸 pass——全仓最弱审计失败路径，与 train/deploy/login 不一致）
            logger.exception("单张推理审计/检测历史写入失败（不阻塞推理）")

    @Slot(str)
    def _single_failed(self, err: str) -> None:
        """槽：单张推理失败（主线程）。"""
        self.btn_single.setEnabled(True)
        self.btn_single.setText(tr("单张推理"))
        self.btn_load_model.setEnabled(True)  # P0-3：失败路径同样恢复
        self.status_changed.emit(tr("推理失败"), err)

    def _batch_infer(self) -> None:
        """批量推理（后台线程执行，避免 UI 冻结）。"""
        # W39（v6 P3-1）：门控置于按钮入口首行（与 check_action docstring
        # 约定一致——原置于引擎预检后，被拒用户先见"请先加载模型"）
        denied = check_action("predict.batch_infer")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        if not self._engine:
            self.status_changed.emit(tr("请先加载模型"), "!")
            return
        d = pick_directory(
            self, "选择批量推理目录"
        )
        if not d:
            return

        images = collect_images(d)
        if not images:
            self.status_changed.emit(tr("目录无图像"), "!")
            return

        logger.info("批量推理开始: %s（%d 张）", d, len(images))
        self.table.setRowCount(0)
        self._results.clear()
        self._batch_cancel = False
        self.btn_batch.setEnabled(False)
        self.btn_batch.setText(tr("推理中..."))
        self.btn_load_model.setEnabled(False)  # P0-3：批量推理中禁用换模型
        if hasattr(self, "_btn_cancel_batch"):
            self._btn_cancel_batch.setVisible(True)
        if hasattr(self, "_progress"):
            self._progress.setVisible(True)

        save_dir = batch_save_dir(self._project_dir, d)

        # W33：对象类型过滤（空=全部）+ 叠加图开关（UI 线程一次捕获）
        labels_filter = {
            s.strip() for s in self.edit_label_filter.text().split(",") if s.strip()
        } or None
        save_overlay = self.chk_overlay.isChecked()

        # W33：批处理体（_work/_process/收尾写盘）抽至 batch_runner——
        # 规模守卫 800/100 双线；overlay_renderer 传模块级绑定保测试缝
        from gui.pages.predict.batch_runner import run_batch

        run_batch(
            self, engine=self._engine, images=images, save_dir=save_dir,
            threshold=self._threshold(), labels_filter=labels_filter,
            save_overlay=save_overlay,
            overlay_renderer=render_result if save_overlay else None,
        )

    def _batch_add_row(self, img_path: str, result: DetectionResult) -> None:
        """线程安全地添加结果行（通过 invokeMethod）。"""
        self._results.append(result_to_record(img_path, result))
        # 延迟到主线程添加表格行（传完整数据避免列错位）
        labels, score, info = row_display_fields(result)
        invoke_main(self, "_batch_add_row_main", img_path, labels, score, info)

    # ---- Qt slot 桥接（主线程执行）----

    @Slot(int, int)
    def _batch_set_progress(self, done: int, total: int) -> None:
        if hasattr(self, "_progress"):
            self._progress.setValue(int(done / total * 100) if total else 0)
        self.status_changed.emit(tr("推理中"), f"{done}/{total}")

    @Slot(str, str, float, str)
    def _batch_add_row_main(self, img_path: str, labels: str, score: float, info: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(img_path)))
        self.table.setItem(row, 1, QTableWidgetItem(labels))
        self.table.setItem(row, 2, QTableWidgetItem(f"{score:.3f}"))
        self.table.setItem(row, 3, QTableWidgetItem(info))

    @Slot(int, int, bool)
    def _batch_done(self, count: int, total: int, cancelled: bool = False) -> None:
        logger.info("批量推理完成: %d/%d (cancelled=%s)", count, total, cancelled)
        self.btn_batch.setEnabled(True)
        self.btn_batch.setText(tr("批量推理"))
        self.btn_load_model.setEnabled(True)  # P0-3：恢复换模型入口
        if hasattr(self, "_btn_cancel_batch"):
            self._btn_cancel_batch.setVisible(False)
        if hasattr(self, "_progress"):
            self._progress.setValue(0)
            self._progress.setVisible(False)
        if cancelled:
            # W28 审计折入：取消要有显式反馈——旧实现照常报"批量完成"并弹
            # 统计，用户误以为 batch_results.json 已落盘（按钮恢复≠用户知情）
            self.status_changed.emit(
                tr("批量已取消"), tr("结果未落盘，可在表内导出")
            )
            return
        self.status_changed.emit(tr("批量完成"), f"{count}/{total}")
        # 批量推理完成后自动展示统计报表（R3-11）
        if self._results:
            self._show_stats()

    # ---- W34：视频超分四方法混入自 VideoSuperActionsMixin ----
    # （_video_super/_video_super_progress/_video_super_done/
    #   _video_super_failed 见 video_super_actions.py——invoke_main
    #   槽名派发经 MRO 命中 Mixin，行为不变）

    def _batch_cancel_infer(self) -> None:
        self._batch_cancel = True

    @Slot(str)
    def _batch_failed(self, err: str) -> None:
        """槽：批量推理异常兜底（W17 on_error）——恢复按钮/隐藏进度并报错。"""
        logger.error("批量推理异常终止: %s", err)
        self.btn_batch.setEnabled(True)
        self.btn_batch.setText(tr("批量推理"))
        self.btn_load_model.setEnabled(True)  # P0-3：失败路径同样恢复
        if hasattr(self, "_btn_cancel_batch"):
            self._btn_cancel_batch.setVisible(False)
        if hasattr(self, "_progress"):
            self._progress.setValue(0)
            self._progress.setVisible(False)
        self.status_changed.emit(tr("推理失败"), err[:60])

    def _show_result(self, img_path: str, result: DetectionResult) -> None:
        """在预览区显示带标注的图像（W5: supervision 渲染，缺库回退旧画法）。"""
        try:
            import cv2 as _cv2
            from PySide6.QtGui import QImage

            from core.image_io import imread_unicode
            from inference.sv_bridge import render_result

            img = imread_unicode(img_path)  # BGR（imread_unicode 契约）
            if img is not None:
                annotated = render_result(img, result)
                h, w = annotated.shape[:2]
                rgba = _cv2.cvtColor(annotated, _cv2.COLOR_BGR2RGBA)
                qimg = QImage(
                    rgba.tobytes(), w, h, rgba.strides[0], QImage.Format_RGBA8888
                ).copy()
                pm = QPixmap.fromImage(qimg)
                self._set_preview_pixmap(pm)
                return
            # 图读不出（罕见）：降级走 Qt 原路径
        except ImportError:
            import logging
            logging.getLogger(__name__).warning(
                "supervision 未安装，预览回退为简化画法（pip install supervision）"
            )
        except (RuntimeError, ValueError) as exc:
            import logging
            logging.getLogger(__name__).warning("sv 渲染失败，回退旧画法: %s", exc)

        pm = QPixmap(img_path)
        if pm.isNull():
            return
        pm = self._draw_legacy(pm, result)
        self._set_preview_pixmap(pm)

    # ---- W21：预览自适应（竖图不再被固定 scaledToWidth(400) 裁切）---- #
    def _set_preview_pixmap(self, pm: QPixmap) -> None:
        """记录原始图并立即按当前预览区缩放展示。"""
        self._preview_source = pm
        self._apply_preview_pixmap()

    def _apply_preview_pixmap(self) -> None:
        """原始图等比缩放至预览区（留 8px 边距），无源图时无操作。"""
        pm = self._preview_source
        if pm is None or pm.isNull():
            return
        w = max(self.preview.width() - 8, 1)
        h = max(self.preview.height() - 8, 1)
        self.preview.setPixmap(
            pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event) -> None:  # noqa: N802  # Qt 命名
        """窗口尺寸变化 → 预览图重适配（放大不留旧小图、缩小不裁切）。"""
        super().resizeEvent(event)
        self._apply_preview_pixmap()

    @staticmethod
    def _draw_legacy(pm: QPixmap, result: DetectionResult) -> QPixmap:
        """旧版 QPainter 简化画法（supervision 缺失时的真实降级路径）。"""
        # 真引擎 boxes 为 numpy 数组——不得做真值判断（歧义异常，W7 修复）
        if result.boxes is None or len(result.boxes) == 0:
            return pm
        painter = QPainter(pm)
        try:
            pen = QPen(QColor("#ef4444"), 3)
            painter.setPen(pen)
            for box in result.boxes:
                x1, y1, x2, y2 = box
                painter.drawRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))
            # 绘制标签
            if result.labels and result.scores:
                painter.setPen(QColor("#22c55e"))
                font = painter.font()
                font.setPointSize(10)
                painter.setFont(font)
                # 平行元组按最短截断绘制（引擎异常长度时不炸 UI 绘制路径）
                for box, lbl, sc in zip(result.boxes, result.labels, result.scores, strict=False):
                    x1, y1, _, _ = box
                    painter.drawText(
                        int(x1), int(y1) - 6,
                        f"{lbl} {sc:.2f}"
                    )
        finally:
            painter.end()
        return pm

    def _add_result_row(self, img_path: str, result: DetectionResult) -> None:
        """添加一行到结果表。"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(img_path)))
        labels = ", ".join(result.labels) if result.labels else ""
        self.table.setItem(row, 1, QTableWidgetItem(labels))
        score = f"{result.score:.4f}" if result.score else ""
        self.table.setItem(row, 2, QTableWidgetItem(score))
        n = len(result.boxes) if result.boxes is not None else 0
        info = f"{n} {tr('框')}" if n else ""
        self.table.setItem(row, 3, QTableWidgetItem(info))

    # W24 规模拆分：_export_csv/_show_stats/_export_excel/_export_json 的
    # 实现移至 ExportActionsMixin（本类继承命中，勿在此定义同名存根——
    # 会按 MRO 优先遮蔽 Mixin 实现）。

    def retranslate(self) -> None:
        self.btn_load_model.setText(tr("加载模型"))
        self.lbl_threshold.setText(tr("阈值"))
        self.edit_label_filter.setPlaceholderText(tr("对象类型过滤（逗号分隔，空=全部）"))
        self.chk_overlay.setText(tr("叠加图"))
        self.btn_single.setText(tr("单张推理"))
        self.btn_batch.setText(tr("批量推理"))
        self.btn_video_super.setText(tr("视频超分"))  # L1：去重复行
        self.btn_export_csv.setText(tr("导出CSV"))
        self.btn_export_json.setText(tr("导出JSON"))
        self.btn_export_excel.setText(tr("导出Excel"))
        self.btn_stats.setText(tr("统计报表"))


__all__ = ["PredictPage"]
