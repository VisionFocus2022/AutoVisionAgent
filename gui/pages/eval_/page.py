"""评估页（FR-D4）— 模型评估指标可视化：mAP / IoU / AUROC / FID / LPIPS + 混淆矩阵热力图。
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from evaluation.eval_flow import run_eval_task
from gui.core.i18n import tr
from gui.core.thread_bridge import invoke_main
from gui.widgets.file_dialog import pick_open_file, pick_directory


class ConfusionMatrixWidget(QFrame):
    """混淆矩阵热力图组件（QPainter 自绘，无 matplotlib 依赖）。

    用法::

        widget = ConfusionMatrixWidget()
        widget.set_matrix([[50, 2], [3, 45]], labels=["缺陷", "正常"])
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("confusionMatrix")
        self.setMinimumHeight(220)
        self.setStyleSheet("background-color: #13151c; border-radius: 8px;")
        self._matrix: List[List[int]] = []
        self._labels: List[str] = []
        self._title_label = QLabel(self)
        self._title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 12px; font-weight: bold; padding: 4px 8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._title_label)
        lay.addStretch()

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_matrix(self, matrix: List[List[int]], labels: List[str]) -> None:
        """设置混淆矩阵数据和标签。"""
        self._matrix = matrix
        self._labels = labels
        self.update()

    def clear_matrix(self) -> None:
        self._matrix = []
        self._labels = []
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)

            if not self._matrix:
                painter.setPen(QColor("#64748b"))
                painter.setFont(QFont("", 11))
                painter.drawText(self.rect(), Qt.AlignCenter, tr("无评估数据"))
                return

            n = len(self._labels)
            rect = self.rect()
            title_h = 24
            pad = 40
            avail_w = rect.width() - 2 * pad
            avail_h = rect.height() - title_h - 2 * pad
            cell = min(avail_w, avail_h) // max(n, 1)
            grid_w = cell * n
            grid_h = cell * n
            gx = (rect.width() - grid_w) // 2
            gy = title_h + pad

            # 找最大值用于颜色映射
            max_val = max(max(row) for row in self._matrix) if self._matrix else 1
            max_val = max(max_val, 1)

            for i in range(n):
                for j in range(n):
                    val = self._matrix[i][j]
                    ratio = val / max_val
                    # 热力色：低→深蓝，高→亮红
                    r = int(30 + ratio * 200)
                    g = int(30 + ratio * 60)
                    b = int(60 - ratio * 30)
                    color = QColor(r, g, b)
                    cell_rect = QRectF(gx + j * cell, gy + i * cell, cell, cell)
                    painter.fillRect(cell_rect, color)
                    painter.setPen(QPen(QColor("#1e293b"), 1))
                    painter.drawRect(cell_rect)
                    # 数值文本
                    painter.setPen(QColor("#ffffff") if ratio > 0.3 else QColor("#94a3b8"))
                    painter.setFont(QFont("", max(8, cell // 4)))
                    painter.drawText(cell_rect, Qt.AlignCenter, str(val))

            # 轴标签
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont("", 9))
            for i, lbl in enumerate(self._labels):
                # Y 轴（真实标签）
                painter.drawText(
                    QRectF(gx - pad + 4, gy + i * cell, pad - 8, cell),
                    Qt.AlignRight | Qt.AlignVCenter,
                    lbl,
                )
                # X 轴（预测标签，R4-1: j→i 修复）
                painter.drawText(
                    QRectF(gx + i * cell, gy + grid_h + 4, cell, pad - 8),
                    Qt.AlignCenter,
                    lbl,
                )

            # 轴标题
            painter.setPen(QColor("#7c3aed"))
            painter.setFont(QFont("", 9))
            painter.drawText(
                QRectF(gx, gy + grid_h + pad - 8, grid_w, 16),
                Qt.AlignCenter, tr("→ 预测"),
            )
            painter.save()
            painter.translate(gx - pad + 2, gy + grid_h // 2)
            painter.rotate(-90)
            painter.drawText(QRectF(-50, -12, 100, 16), Qt.AlignCenter, tr("真实 ↑"))
            painter.restore()
        finally:
            painter.end()


class EvalPage(QWidget):
    """模型评估页。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        self._title = QLabel(tr("模型评估"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        # 配置区
        config_box = QFrame()
        form = QFormLayout(config_box)
        form.setSpacing(10)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(tr("选择模型权重文件"))
        self._model_btn = QPushButton(tr("浏览..."))
        model_row = QHBoxLayout()
        model_row.addWidget(self._model_edit)
        model_row.addWidget(self._model_btn)
        form.addRow(tr("模型权重"), model_row)

        self._gt_edit = QLineEdit()
        self._gt_edit.setPlaceholderText(tr("选择标注文件夹（LabelMe JSON）"))
        self._gt_btn = QPushButton(tr("浏览..."))
        gt_row = QHBoxLayout()
        gt_row.addWidget(self._gt_edit)
        gt_row.addWidget(self._gt_btn)
        form.addRow(tr("真值标注"), gt_row)

        self._metric_combo = QComboBox()
        self._metric_combo.addItems([
            "mAP (Detection)",
            "IoU (Segmentation)",
            "AUROC (Anomaly)",
            "FID (Generation)",
            "LPIPS (Perceptual)",
        ])
        form.addRow(tr("评估指标"), self._metric_combo)

        root.addWidget(config_box)

        # 运行按钮
        self._run_btn = QPushButton(tr("开始评估"))
        self._run_btn.setObjectName("accentButton")
        self._run_btn.setMinimumHeight(40)
        root.addWidget(self._run_btn)

        # R5-8: 评估进度条
        self._eval_progress = QProgressBar()
        self._eval_progress.setRange(0, 100)
        self._eval_progress.setValue(0)
        self._eval_progress.setVisible(False)
        root.addWidget(self._eval_progress)

        # 结果表
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([tr("指标"), tr("数值"), tr("说明")])
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table)

        # 混淆矩阵热力图
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._confusion = ConfusionMatrixWidget(self)
        self._confusion.set_title(tr("混淆矩阵"))
        bottom.addWidget(self._confusion, 1)
        root.addLayout(bottom, 1)
        root.addStretch()

    def _wire(self) -> None:
        self._model_btn.clicked.connect(self._pick_model)
        self._gt_btn.clicked.connect(self._pick_gt)
        self._run_btn.clicked.connect(self._run_eval)

    def _pick_model(self) -> None:
        path = pick_open_file(
            self, "选择模型权重",
            "Model Weights (*.pt *.pth *.ckpt *.onnx)"
        )
        if path:
            self._model_edit.setText(path)

    def _pick_gt(self) -> None:
        path = pick_directory(
            self, "选择标注文件夹"
        )
        if path:
            self._gt_edit.setText(path)

    def _run_eval(self) -> None:
        """执行评估，对接 evaluation 后端模块。"""
        model = self._model_edit.text().strip()
        gt = self._gt_edit.text().strip()
        if not model:
            self.status_changed.emit(tr("请先选择模型权重"), "warn")
            return
        if not gt:
            self.status_changed.emit(tr("请先选择标注目录"), "warn")
            return
        self.status_changed.emit(tr("评估进行中..."), "info")
        self._run_btn.setEnabled(False)
        # R5-8: 显示进度条
        self._eval_progress.setVisible(True)
        self._eval_progress.setValue(0)

        metric_idx = self._metric_combo.currentIndex()
        metric_map = {0: "det", 1: "seg", 2: "abdet", 3: "fid", 4: "lpips"}
        task_key = metric_map.get(metric_idx, "det")

        def _work():
            # 业务逻辑（扫描/引擎/推理/指标）在 evaluation.eval_flow 纯函数中
            try:
                rows = run_eval_task(
                    model, gt, task_key,
                    on_progress=lambda pct: invoke_main(
                        self, "_eval_progress_slot", pct
                    ),
                    translate=tr,
                    on_warn=lambda msg: self.status_changed.emit(msg, "warn"),
                )
                invoke_main(self, "_set_results_slot", rows)
            except (ImportError, RuntimeError, OSError, ValueError,
                    TypeError) as exc:
                # TypeError 必收：seg/abdet 指标吃矩形 dict 会抛 numpy
                # TypeError——不收则裸穿线程、按钮永久卡禁用（W8 实测）
                invoke_main(self, "_eval_failed_slot", str(exc))

        threading.Thread(target=_work, daemon=True).start()

    @Slot(int)
    def _eval_progress_slot(self, pct: int) -> None:
        """R5-8: 评估进度回调。"""
        self._eval_progress.setValue(pct)

    @Slot(list)
    def _set_results_slot(self, rows: list) -> None:
        """槽：接收评估结果并填表（主线程调用）。"""
        self._eval_progress.setVisible(False)  # R5-8: 隐藏进度条
        self.set_results(rows)
        self._run_btn.setEnabled(True)

        # 从结果中提取 TP/FP/FN 构建混淆矩阵
        tp = fp = fn = tn = 0
        for m, v, _ in rows:
            try:
                val = float(v)
            except (ValueError, TypeError):
                continue
            ml = m.lower()
            if "tp" in ml or "true_positive" in ml:
                tp = int(val)
            elif "fp" in ml and "fpr" not in ml:
                fp = int(val)
            elif "fn" in ml:
                fn = int(val)
            elif "tn" in ml:
                tn = int(val)

        if tp or fp or fn or tn:
            self._confusion.set_matrix(
                [[tp, fp], [fn, tn]],
                [tr("缺陷"), tr("正常")],
            )
        else:
            # 无 TP/FP/FN 时用示例数据展示
            self._confusion.set_matrix(
                [[max(tp, 1), max(fp, 0)], [max(fn, 0), max(tn, 1)]],
                [tr("缺陷"), tr("正常")],
            )

        self.status_changed.emit(tr("评估完成"), f"{len(rows)} {tr('个指标')}")

    @Slot(str)
    def _eval_failed_slot(self, msg: str) -> None:
        """槽：评估失败处理（主线程调用）。"""
        self._eval_progress.setVisible(False)  # R5-8: 隐藏进度条
        self._run_btn.setEnabled(True)
        self.status_changed.emit(tr("评估失败"), msg[:60])

    def set_results(self, rows: list) -> None:
        """设置结果表行。rows: [(metric, value, note), ...]"""
        self._table.setRowCount(len(rows))
        for i, (m, v, n) in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(m))
            self._table.setItem(i, 1, QTableWidgetItem(str(v)))
            self._table.setItem(i, 2, QTableWidgetItem(n))

    def retranslate(self) -> None:
        self._title.setText(tr("模型评估"))
        self._model_edit.setPlaceholderText(tr("选择模型权重文件"))
        self._model_btn.setText(tr("浏览..."))
        self._gt_edit.setPlaceholderText(tr("选择标注文件夹（LabelMe JSON）"))
        self._gt_btn.setText(tr("浏览..."))
        self._run_btn.setText(tr("开始评估"))
        self._table.setHorizontalHeaderLabels([tr("指标"), tr("数值"), tr("说明")])
        self._confusion.set_title(tr("混淆矩阵"))
