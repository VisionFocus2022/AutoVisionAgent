"""推理页：模型加载 + 单张/批量推理 + 结果表 + 导出（FR-D6 / FR-E3）。

对接 models/supervised/ 引擎注册表，支持 det/seg/abdet 推理。
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from typing import Any, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.interfaces_supervised import DetectionResult, TaskType
from gui.core.i18n import tr
from gui.core.thread_bridge import invoke_main
from gui.widgets.file_dialog import pick_open_file, pick_save_file, pick_directory

from core.constants import IMG_EXTS as _IMG_EXTS

# R5-2: CSV/Excel 公式注入防护（CWE-1236）
_CSV_INJECTION_CHARS = frozenset("=+-\t\r@")


def _sanitize_csv_cell(value: object) -> object:
    """对以危险字符开头的字符串加单引号前缀，防止公式注入。"""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


class PredictPage(QWidget):
    """推理页：加载模型 → 单张/批量推理 → 结果表 → 导出。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._project_dir: Optional[str] = None
        self._models_dir: Optional[str] = None
        self._model_path: Optional[str] = None
        self._engine = None  # ISupervisedTaskEngine 实例
        self._results: List[dict] = []  # 批量结果缓存
        self._batch_cancel = False  # 批量推理取消标志

        self._build_ui()
        self._wire()

    # ============================== UI ============================== #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 顶部工具栏 ----
        bar = QFrame(self)
        bar.setObjectName("toolbar")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

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

        self.btn_single = QPushButton(tr("单张推理"), bar)
        self.btn_single.setProperty("role", "accent")
        h.addWidget(self.btn_single)

        self.btn_batch = QPushButton(tr("批量推理"), bar)
        h.addWidget(self.btn_batch)

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
        root.addWidget(bar)

        # ---- 正文：预览 + 结果表 ----
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

        root.addLayout(body, 1)

    # ============================== 接线 ============================== #
    def _wire(self) -> None:
        self.btn_load_model.clicked.connect(self._load_model)
        self.btn_single.clicked.connect(self._single_infer)
        self.btn_batch.clicked.connect(self._batch_infer)
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
        """加载模型权重。"""
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._model_path = path
        task = self.cmb_task.currentData()
        try:
            # 尝试从注册表获取引擎
            from models.supervised.registry import get_default_registry
            reg = get_default_registry()

            # 卸载旧引擎（释放 GPU 显存）
            if self._engine is not None:
                try:
                    self._engine.unload()
                except (RuntimeError, AttributeError):
                    pass
                self._engine = None
                reg.clear_cache(task=self.cmb_task.currentData())

            if reg.has(task):
                self._engine = reg.get(task)
                # 从配置读取设备，自动检测 GPU 可用性
                _device = "cpu"
                try:
                    from core.config import get_config
                    _device = get_config().inference.device
                except (ImportError, AttributeError):
                    pass
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
        except (RuntimeError, OSError, ValueError) as exc:
            self.lbl_model.setText(tr("加载失败"))
            self.status_changed.emit(tr("模型加载失败"), str(exc)[:40])

    def _single_infer(self) -> None:
        """单张推理（W3-T3: 推理移出 UI 线程，结果经 invoke_main 回主线程）。"""
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
        self._pending_single = None

        def _work():
            try:
                from core.exceptions import SupervisedEngineError
                from core.image_io import imread_unicode
                img = imread_unicode(path)
                if img is None:
                    invoke_main(self, "_single_failed", tr("图像读取失败"))
                    return
                result: DetectionResult = self._engine.infer(img)
                score = float(result.score) if result.score else 0.0
                self._pending_single = (path, result)
                invoke_main(self, "_single_done", os.path.basename(path), score)
            except (RuntimeError, OSError, ValueError,
                    SupervisedEngineError) as exc:
                invoke_main(self, "_single_failed", str(exc)[:40])

        threading.Thread(target=_work, daemon=True).start()

    @Slot(str, float)
    def _single_done(self, basename: str, score: float) -> None:
        """槽：单张推理完成（主线程）——显示结果/记录行/审计。"""
        self.btn_single.setEnabled(True)
        self.btn_single.setText(tr("单张推理"))
        if self._pending_single is None:
            return
        path, result = self._pending_single
        self._pending_single = None

        # 在预览区显示原图 + 叠加检测框
        self._show_result(path, result)
        self._add_result_row(path, result)
        self.status_changed.emit(basename, f"{tr('分数')}: {score:.3f}")

        # R4-6: 记录审计日志 + 检测历史
        try:
            from core.audit_logger import log_detection_complete
            from core.detection_history import get_history
            _task = self.cmb_task.currentData() or "det"
            _count = len(result.boxes) if result.boxes else 0
            log_detection_complete(
                task=_task, image=path, result_count=_count,
            )
            get_history().add_record(
                task=_task,
                image_path=path,
                result_count=_count,
                score_avg=score,
            )
        except Exception:
            pass  # 审计日志失败不影响推理

    @Slot(str)
    def _single_failed(self, err: str) -> None:
        """槽：单张推理失败（主线程）。"""
        self.btn_single.setEnabled(True)
        self.btn_single.setText(tr("单张推理"))
        self.status_changed.emit(tr("推理失败"), err)

    def _batch_infer(self) -> None:
        """批量推理（后台线程执行，避免 UI 冻结）。"""
        if not self._engine:
            self.status_changed.emit(tr("请先加载模型"), "!")
            return
        d = pick_directory(
            self, "选择批量推理目录"
        )
        if not d:
            return

        images: List[str] = []
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(_IMG_EXTS):
                    images.append(os.path.join(root, f))
        if not images:
            self.status_changed.emit(tr("目录无图像"), "!")
            return

        self.table.setRowCount(0)
        self._results.clear()
        self._batch_cancel = False
        self.btn_batch.setEnabled(False)
        self.btn_batch.setText(tr("推理中..."))
        if hasattr(self, "_btn_cancel_batch"):
            self._btn_cancel_batch.setVisible(True)
        if hasattr(self, "_progress"):
            self._progress.setVisible(True)

        ts = int(time.time())
        save_dir = os.path.join(
            self._project_dir or d, "results", f"batchPredict_{ts}"
        )
        os.makedirs(save_dir, exist_ok=True)

        import threading
        engine = self._engine
        total = len(images)

        def _work():
            _BATCH_SIZE = 16
            import logging
            _batch_logger = logging.getLogger(__name__)
            for i in range(0, total, _BATCH_SIZE):
                if self._batch_cancel:
                    break
                batch_paths = images[i:i + _BATCH_SIZE]
                try:
                    if hasattr(engine, "infer_batch"):
                        results = engine.infer_batch(batch_paths)
                        for img_path, result in zip(batch_paths, results):
                            self._batch_add_row(img_path, result)
                    else:
                        from core.image_io import imread_unicode
                        for img_path in batch_paths:
                            if self._batch_cancel:
                                break
                            img = imread_unicode(img_path)
                            if img is None:
                                continue
                            result = engine.infer(img)
                            self._batch_add_row(img_path, result)
                except (RuntimeError, OSError, ValueError):
                    _batch_logger.exception("批量推理失败 (batch %d-%d)", i, i + len(batch_paths))
                # 更新进度
                done = min(i + _BATCH_SIZE, total)
                invoke_main(self, "_batch_set_progress", done, total)

            # 保存批量结果
            out_path = os.path.join(save_dir, "batch_results.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(self._results, f, ensure_ascii=False, indent=2)

            invoke_main(self, "_batch_done", len(self._results), total)

        t = threading.Thread(target=_work, daemon=True)
        t.start()

    def _batch_add_row(self, img_path: str, result: DetectionResult) -> None:
        """线程安全地添加结果行（通过 invokeMethod）。"""
        self._results.append({
            "file": os.path.basename(img_path),
            "path": img_path,
            "task": result.task.value,
            "score": result.score,
            "boxes": list(result.boxes) if result.boxes else None,
            "labels": list(result.labels) if result.labels else None,
        })
        # 延迟到主线程添加表格行（传完整数据避免列错位）
        labels = ", ".join(result.labels) if result.labels else ""
        score = float(result.score or 0.0)
        n = len(result.boxes) if result.boxes else 0
        info = f"{n} {tr('框')}" if n else ""
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

    @Slot(int, int)
    def _batch_done(self, count: int, total: int) -> None:
        self.btn_batch.setEnabled(True)
        self.btn_batch.setText(tr("批量推理"))
        if hasattr(self, "_btn_cancel_batch"):
            self._btn_cancel_batch.setVisible(False)
        if hasattr(self, "_progress"):
            self._progress.setValue(0)
            self._progress.setVisible(False)
        self.status_changed.emit(tr("批量完成"), f"{count}/{total}")
        # 批量推理完成后自动展示统计报表（R3-11）
        if self._results:
            self._show_stats()

    def _batch_cancel_infer(self) -> None:
        self._batch_cancel = True

    def _show_result(self, img_path: str, result: DetectionResult) -> None:
        """在预览区显示带标注的图像。"""
        pm = QPixmap(img_path)
        if pm.isNull():
            return
        if result.boxes:
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
                    for i, (box, lbl, sc) in enumerate(zip(
                        result.boxes, result.labels, result.scores
                    )):
                        x1, y1, _, _ = box
                        painter.drawText(
                            int(x1), int(y1) - 6,
                            f"{lbl} {sc:.2f}"
                        )
            finally:
                painter.end()
        self.preview.setPixmap(
            pm.scaledToWidth(400, Qt.SmoothTransformation)
        )

    def _add_result_row(self, img_path: str, result: DetectionResult) -> None:
        """添加一行到结果表。"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(img_path)))
        labels = ", ".join(result.labels) if result.labels else ""
        self.table.setItem(row, 1, QTableWidgetItem(labels))
        score = f"{result.score:.4f}" if result.score else ""
        self.table.setItem(row, 2, QTableWidgetItem(score))
        n = len(result.boxes) if result.boxes else 0
        info = f"{n} {tr('框')}" if n else ""
        self.table.setItem(row, 3, QTableWidgetItem(info))

    def _export_csv(self) -> None:
        """导出 CSV。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = pick_save_file(
            self, "导出CSV", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "task", "score", "labels"])
            for r in self._results:
                writer.writerow([
                    _sanitize_csv_cell(r["file"]),
                    _sanitize_csv_cell(r["task"]),
                    r.get("score", ""),
                    _sanitize_csv_cell(", ".join(r.get("labels", []) or [])),
                ])
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    def _show_stats(self) -> None:
        """弹出统计报表对话框（R3-11）：总检测数/缺陷数/缺陷率/类别分布。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可统计"), "!")
            return
        total_imgs = len(self._results)
        total_dets = sum(
            len(r.get("boxes") or []) for r in self._results
        )
        defective = sum(
            1 for r in self._results if r.get("boxes")
        )
        defect_rate = (defective / total_imgs * 100) if total_imgs else 0.0

        # 类别分布
        from collections import Counter
        label_counter: Counter = Counter()
        for r in self._results:
            labels = r.get("labels") or []
            for lbl in labels:
                label_counter[str(lbl)] += 1

        # 构建摘要文本
        lines = [
            f"{tr('总图像数')}: {total_imgs}",
            f"{tr('总检测数')}: {total_dets}",
            f"{tr('缺陷图像数')}: {defective}",
            f"{tr('缺陷率')}: {defect_rate:.1f}%",
        ]
        if label_counter:
            lines.append("")
            lines.append(tr("类别分布") + ":")
            for lbl, cnt in label_counter.most_common():
                lines.append(f"  {lbl}: {cnt}")

        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(tr("统计报表"))
        msg.setText("\n".join(lines))
        msg.exec()

        self.status_changed.emit(
            tr("统计"), f"{defective}/{total_imgs} ({defect_rate:.1f}%)"
        )

    def _export_excel(self) -> None:
        """导出 Excel (.xlsx)（R3-11）。openpyxl 不可用时回退到 CSV。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = pick_save_file(
            self, "导出Excel", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            # 回退到 CSV
            self.status_changed.emit(tr("openpyxl未安装，导出CSV"), "!")
            csv_path = path.rsplit(".", 1)[0] + ".csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["file", "task", "score", "labels"])
                for r in self._results:
                    writer.writerow([
                        _sanitize_csv_cell(r["file"]),
                        _sanitize_csv_cell(r["task"]),
                        r.get("score", ""),
                        _sanitize_csv_cell(", ".join(r.get("labels", []) or [])),
                    ])
            self.status_changed.emit(tr("已导出CSV"), os.path.basename(csv_path))
            return

        wb = Workbook()
        ws = wb.active
        ws.title = tr("推理结果")
        # 表头
        headers = [tr("文件"), tr("任务"), tr("分数"), tr("标签"), tr("检测框数")]
        ws.append(headers)
        # 数据行
        for r in self._results:
            ws.append([
                _sanitize_csv_cell(r["file"]),
                _sanitize_csv_cell(r.get("task", "")),
                round(r.get("score", 0) or 0, 4),
                _sanitize_csv_cell(", ".join(r.get("labels", []) or [])),
                len(r.get("boxes") or []),
            ])

        # 统计摘要表
        ws2 = wb.create_sheet(tr("统计"))
        total_imgs = len(self._results)
        total_dets = sum(len(r.get("boxes") or []) for r in self._results)
        defective = sum(1 for r in self._results if r.get("boxes"))
        defect_rate = (defective / total_imgs * 100) if total_imgs else 0.0
        ws2.append([tr("指标"), tr("数值")])
        ws2.append([tr("总图像数"), total_imgs])
        ws2.append([tr("总检测数"), total_dets])
        ws2.append([tr("缺陷图像数"), defective])
        ws2.append([tr("缺陷率"), f"{defect_rate:.1f}%"])

        wb.save(path)
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    def _export_json(self) -> None:
        """导出 JSON。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = pick_save_file(
            self, "导出JSON", "JSON (*.json)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._results, f, ensure_ascii=False, indent=2)
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    def retranslate(self) -> None:
        self.btn_load_model.setText(tr("加载模型"))
        self.btn_single.setText(tr("单张推理"))
        self.btn_batch.setText(tr("批量推理"))
        self.btn_export_csv.setText(tr("导出CSV"))
        self.btn_export_json.setText(tr("导出JSON"))
        self.btn_export_excel.setText(tr("导出Excel"))
        self.btn_stats.setText(tr("统计报表"))


__all__ = ["PredictPage"]
