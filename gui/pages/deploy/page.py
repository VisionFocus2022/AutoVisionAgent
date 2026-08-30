"""发布/部署页（FR-D5）— 模型导出 ONNX/TRT + 打包。

对接 exporter/supervised_exporter.py 实现 ONNX 导出 + 量化 + TRT 转换。
"""
from __future__ import annotations

import functools
import logging
import os

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_directory, pick_open_file

logger = logging.getLogger(__name__)


class DeployPage(QWidget):
    """模型发布/部署页。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        self._title = QLabel(tr("模型发布"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        config_box = QFrame()
        form = QFormLayout(config_box)
        form.setSpacing(10)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(tr("选择已训练的 .pt/.pth 模型"))
        self._model_btn = QPushButton(tr("浏览..."))
        model_row = QHBoxLayout()
        model_row.addWidget(self._model_edit)
        model_row.addWidget(self._model_btn)
        form.addRow(tr("源模型"), model_row)

        # R4-8: 任务类型选择（替代文件名作为 TaskType）
        self._task_combo = QComboBox()
        self._task_combo.addItems([
            tr("检测") + " (det)",
            tr("分类") + " (cls)",
            tr("分割") + " (seg)",
            tr("异常检测") + " (abdet)",
        ])
        form.addRow(tr("任务类型"), self._task_combo)

        self._format_combo = QComboBox()
        self._format_combo.addItems(["ONNX", "TensorRT", "ONNX + TensorRT"])
        form.addRow(tr("目标格式"), self._format_combo)

        self._precision_combo = QComboBox()
        self._precision_combo.addItems(["FP32", "FP16", "INT8"])
        form.addRow(tr("精度"), self._precision_combo)

        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText(tr("输出目录"))
        self._out_btn = QPushButton(tr("浏览..."))
        out_row = QHBoxLayout()
        out_row.addWidget(self._out_edit)
        out_row.addWidget(self._out_btn)
        form.addRow(tr("输出目录"), out_row)

        self._dynamic_check = QCheckBox(tr("动态 batch 尺寸"))
        self._dynamic_check.setChecked(True)
        form.addRow(self._dynamic_check)

        root.addWidget(config_box)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        # 按钮
        self._export_btn = QPushButton(tr("导出"))
        self._export_btn.setObjectName("accentButton")
        self._export_btn.setMinimumHeight(40)
        root.addWidget(self._export_btn)
        root.addStretch()

    def _wire(self) -> None:
        self._model_btn.clicked.connect(self._pick_model)
        self._out_btn.clicked.connect(self._pick_outdir)
        self._export_btn.clicked.connect(self._do_export)

    def _pick_model(self) -> None:
        path = pick_open_file(
            self, "选择模型", "PyTorch (*.pt *.pth)"
        )
        if path:
            self._model_edit.setText(path)

    def _pick_outdir(self) -> None:
        path = pick_directory(self, "选择输出目录")
        if path:
            self._out_edit.setText(path)

    def _do_export(self) -> None:
        """执行模型导出，对接 exporter 后端模块。"""
        model_path = self._model_edit.text().strip()
        out_dir = self._out_edit.text().strip()
        if not model_path or not out_dir:
            self.status_changed.emit(tr("请填写模型路径和输出目录"), "warn")
            return
        self.status_changed.emit(tr("导出进行中..."), "info")
        self._export_btn.setEnabled(False)
        self._progress.setValue(10)

        fmt_idx = self._format_combo.currentIndex()
        precision = self._precision_combo.currentText().lower()
        do_trt = fmt_idx in (1, 2)  # TensorRT or ONNX+TRT
        # W14-C2（P2-15）：task_value 与 fmt/precision 同法主线程预读——
        # QComboBox 跨线程只读违 Qt 契约，worker 不得再触碰任何 QWidget
        _TASK_MAP = {0: "det", 1: "cls", 2: "seg", 3: "abdet"}
        task_value = _TASK_MAP.get(self._task_combo.currentIndex(), "det")
        logger.info(
            "模型导出开始: model=%s out=%s task=%s fmt=%s precision=%s",
            model_path, out_dir, task_value,
            self._format_combo.currentText(), precision,
        )

        def _work(task_value):
            try:
                from core.exceptions import ModelExportError
                from exporter.supervised_exporter import SupervisedExporter
                exporter = SupervisedExporter()
                import torch

                self._set_progress_slot(20)

                # P3④：直调 torch.load(weights_only=True) 而不走 _safe_torch_load
                # ——此处需要完整模型对象（而非 state_dict）供 ONNX 导出；
                # weights_only=True 已阻断任意代码执行，安全等价。
                model = torch.load(model_path, map_location="cpu", weights_only=True)
                if isinstance(model, dict) and "model" in model:
                    model = model["model"]
                if not hasattr(model, "eval"):
                    self._eval_failed_export(tr("无法识别的模型格式"))
                    return

                model.eval()

                onnx_path = os.path.join(out_dir, f"{task_value}.onnx")

                self._set_progress_slot(40)
                # W18（v3 P2-7）：export_onnx 显式参数形态——model/task_value
                # 直传，消灭引擎桩（engine stub）包装
                exporter.export_onnx(model, task_value, onnx_path, precision=precision)
                self._set_progress_slot(70)

                results = {"onnx": onnx_path}
                if do_trt:
                    trt_path = os.path.join(out_dir, f"{task_value}.engine")
                    try:
                        exporter.export_tensorrt(onnx_path, trt_path, precision=precision)
                        results["trt"] = trt_path
                    except (OSError, RuntimeError, ValueError, ModelExportError):
                        # W17（v3 P2-1）：TRT 为可选增强，export_tensorrt 抛
                        # ModelExportError（如"TRT engine 构建失败"）本应按注释
                        # 意图容错降级——旧元组不含它会把整个导出打死
                        import logging
                        logging.getLogger(__name__).exception("TensorRT 转换失败（可能未安装 TRT）")
                    self._set_progress_slot(95)

                self._set_progress_slot(100)
                self._export_done_slot(results)
            except (OSError, RuntimeError, ValueError, ModelExportError) as exc:
                # W17（v3 P2-1）：补 ModelExportError（AppError 家族——ONNX 解析
                # 失败等本应走失败槽，旧元组不含则击穿到 run_job 日志层、按钮卡死）
                self._eval_failed_export(str(exc))

        # W15-J3（P2-1）：经 gui.core.jobs.run_job 分发——注册表登记 +
        # 协作取消 + 异常路由；task_value 主线程预读值经 partial 随 worker
        # 入参捕获（W14-C2 形态保持，worker 仍不触碰任何 QWidget）；
        # W17：on_error 兜底——元组外异常也复位导出按钮
        run_job(
            functools.partial(_work, task_value), name="deploy_export",
            on_error=ui_on_error(self, "_on_export_failed"),
        )

    def _set_progress_slot(self, pct: int) -> None:
        """槽：更新进度条（线程安全调用）。"""
        invoke_main(self, "set_progress", pct)

    def _export_done_slot(self, results: dict) -> None:
        """槽：导出完成（主线程调用）。"""
        invoke_main(self, "_on_export_finished", results)

    def _eval_failed_export(self, msg: str) -> None:
        """槽：导出失败（主线程调用）。"""
        invoke_main(self, "_on_export_failed", msg)

    @Slot(dict)
    def _on_export_finished(self, results: dict) -> None:
        """导出完成回调。"""
        self._export_btn.setEnabled(True)
        files = ", ".join(os.path.basename(v) for v in results.values())
        logger.info("模型导出完成: %s", files)
        self.status_changed.emit(tr("导出完成"), files)

        # R4-6: 记录审计日志
        try:
            from core.audit_logger import log_model_export
            from core.session import get_current_user
            _TASK_MAP = {0: "det", 1: "cls", 2: "seg", 3: "abdet"}
            _task = _TASK_MAP.get(self._task_combo.currentIndex(), "det")
            _fmt = ", ".join(results.keys())
            log_model_export(
                user=get_current_user(),
                task=_task,
                format=_fmt,
                path=files,
            )
        except (OSError, ImportError) as exc:
            # W11-P1: 审计写入失败不静默——留 warning 痕迹便于排查
            import logging
            logging.getLogger(__name__).warning("模型导出审计写入失败: %s", exc)

    @Slot(str)
    def _on_export_failed(self, msg: str) -> None:
        """导出失败回调。"""
        self._export_btn.setEnabled(True)
        self._progress.setValue(0)
        self.status_changed.emit(tr("导出失败"), msg[:60])

    @Slot(int)
    def set_progress(self, pct: int) -> None:
        self._progress.setValue(pct)

    def retranslate(self) -> None:
        self._title.setText(tr("模型发布"))
        self._model_edit.setPlaceholderText(tr("选择已训练的 .pt/.pth 模型"))
        self._model_btn.setText(tr("浏览..."))
        # R4-8: 任务类型下拉框 retranslate
        self._task_combo.setItemText(0, tr("检测") + " (det)")
        self._task_combo.setItemText(1, tr("分类") + " (cls)")
        self._task_combo.setItemText(2, tr("分割") + " (seg)")
        self._task_combo.setItemText(3, tr("异常检测") + " (abdet)")
        self._out_edit.setPlaceholderText(tr("输出目录"))
        self._out_btn.setText(tr("浏览..."))
        self._dynamic_check.setText(tr("动态 batch 尺寸"))
        self._export_btn.setText(tr("导出"))
