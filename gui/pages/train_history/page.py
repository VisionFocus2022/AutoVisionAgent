"""训练历史页（W1-2，roadmap Wave1 模型资产）。

历次训练记录列表（workspace 根 train_history.jsonl，新者优先）+ 模型卡
（类别表/输入尺寸/指标）+ 一键加载推理（信号经 gui.main 接线到推理页
apply_external_model——镜像 W63 向导交接模式）。

操作模式：选中行 → 工具栏「模型卡 / 加载推理」作用于当前行。
（不用的方案：行内嵌按钮——QTableWidget 单元格控件不入 UIA 可访问树，
exe 实测探针证伪，2026-10-07。）
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.train_history import read_records
from gui.core.i18n import tr

logger = logging.getLogger(__name__)

_COLS = ["时间", "任务", "轮数", "P", "R", "mAP50", "状态"]


class TrainHistoryPage(QWidget):
    """训练历史与模型资产页。"""

    status_changed = Signal(str, str)
    load_requested = Signal(str, str)  # (weights_path, task) → main 接线

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)

        bar = QWidget(self)
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        self.btn_refresh = QPushButton(tr("刷新"), bar)
        self.btn_refresh.clicked.connect(self.refresh)
        h.addWidget(self.btn_refresh)
        self.btn_card = QPushButton(tr("模型卡"), bar)
        self.btn_card.clicked.connect(self._card_for_current)
        h.addWidget(self.btn_card)
        self.btn_load = QPushButton(tr("加载推理"), bar)
        self.btn_load.clicked.connect(self._load_for_current)
        h.addWidget(self.btn_load)
        h.addStretch()
        lay.addWidget(bar)

        self.table = QTableWidget(0, len(_COLS), self)
        self.table.setHorizontalHeaderLabels([tr(c) for c in _COLS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        self.lbl_count = QLabel("", self)
        lay.addWidget(self.lbl_count)
        self.refresh()

    def showEvent(self, event) -> None:
        """进入页面即刷新（训练完成后切来即见新记录，W1-2 DoD）。"""
        super().showEvent(event)
        self.refresh()

    # ------------------------------ 数据渲染 ------------------------------ #
    def refresh(self) -> None:
        """重读历史并渲染（坏行由存储层跳过）。"""
        records = read_records()
        self.table.setRowCount(0)
        for rec in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            m = rec.get("metrics") or {}
            boosted = (rec.get("epochs_requested") or 0) < (
                rec.get("epochs_completed") or 0
            )
            vals = [
                str(rec.get("ts", "")), str(rec.get("task", "")),
                f"{rec.get('epochs_completed', '')}{'+' if boosted else ''}",
                _fmt(m.get("precision")), _fmt(m.get("recall")),
                _fmt(m.get("map50")),
                tr("真实") if rec.get("real") else tr("模拟"),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, rec)
                self.table.setItem(row, col, item)
        if self.table.rowCount():
            self.table.selectRow(0)  # 新记录默认选中（操作零点击起步）
        self.lbl_count.setText(tr("共") + f" {len(records)} " + tr("条"))
        logger.info("训练历史刷新: %d 条", len(records))

    def _current_record(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            self.status_changed.emit(tr("请先选择一条记录"), "!")
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # ------------------------------ 模型卡 ------------------------------ #
    def _card_for_current(self) -> None:
        rec = self._current_record()
        if rec is not None:
            self._show_card(rec)

    def _show_card(self, rec: dict) -> None:
        """模型卡对话框（DoD：类别表 + 输入尺寸必含）。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("模型卡"))
        form = QFormLayout(dlg)
        m = rec.get("metrics") or {}
        classes = rec.get("classes") or []
        rows = [
            (tr("任务"), str(rec.get("task", ""))),
            (tr("骨干"), str(rec.get("backbone", ""))),
            (tr("轮数"), f"{rec.get('epochs_completed', '?')}"
                     f" / {tr('请求')} {rec.get('epochs_requested', '?')}"),
            (tr("类别表"), ", ".join(classes) if classes else tr("未知")),
            (tr("输入尺寸"), str(rec.get("imgsz") or tr("未知"))),
            (tr("指标"), f"P={_fmt(m.get('precision'))} R={_fmt(m.get('recall'))}"
                     f" mAP50={_fmt(m.get('map50'))}"),
            (tr("最佳指标"), str(rec.get("best_metric", ""))),
            (tr("数据集"), str(rec.get("data_yaml", "") or "-")),
            (tr("权重"), str(rec.get("weights_path", "") or "-")),
            (tr("时间"), str(rec.get("ts", ""))),
        ]
        for label, value in rows:
            form.addRow(QLabel(label), QLabel(value))
        btn_close = QPushButton(tr("关闭"), dlg)
        btn_close.clicked.connect(dlg.accept)
        form.addRow(btn_close)
        dlg.exec()

    # ------------------------------ 一键加载 ------------------------------ #
    def _load_for_current(self) -> None:
        rec = self._current_record()
        if rec is not None:
            self._load_to_predict(rec)

    def _load_to_predict(self, rec: dict) -> None:
        path = str(rec.get("weights_path", "") or "")
        task = str(rec.get("task", "") or "")
        if not path or not task:
            self.status_changed.emit(tr("记录缺少权重路径"), "!")
            return
        # 先告知后加载：load_requested 同步执行加载+切页，其"模型已加载"
        # 终态不得被本页的"已请求加载"覆盖（exe 实测探针定位，2026-10-07）
        logger.info("历史一键加载推理: %s (%s)", path, task)
        self.status_changed.emit(tr("已请求加载"), task)
        self.load_requested.emit(path, task)


def _fmt(v) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "-"


__all__ = ["TrainHistoryPage"]
