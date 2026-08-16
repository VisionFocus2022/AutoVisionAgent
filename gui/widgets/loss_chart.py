"""Loss 曲线图组件（自绘 QPainter 折线，无 pyqtgraph 依赖）。

实时显示训练 loss 与可选的 metric（如 accuracy/IoU）。
支持多条曲线、自动缩放、网格线与轴标签。
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

# 颜色方案：暗色主题适配
_GRID_COLOR = QColor("#2d3340")
_AXIS_COLOR = QColor("#475569")
_TEXT_COLOR = QColor("#94a3b8")

# 多曲线颜色
_SERIES_COLORS = [
    QColor("#ef4444"),  # 红 — loss
    QColor("#22c55e"),  # 绿 — accuracy
    QColor("#3b82f6"),  # 蓝 — val_loss
    QColor("#f59e0b"),  # 橙 — val_accuracy
]

_PAD_LEFT = 48   # Y 轴标签宽度
_PAD_BOTTOM = 28  # X 轴标签高度
_PAD_TOP = 12
_PAD_RIGHT = 12


class LossChartWidget(QFrame):
    """实时 Loss 曲线图（QPainter 自绘）。

    用法::

        chart = LossChartWidget()
        chart.add_series("loss", color="#ef4444")
        chart.append("loss", 0.85)
        chart.update()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("lossChart")
        self.setMinimumHeight(200)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background-color: #13151c; border-radius: 8px;")

        # 数据：series_name → deque of (epoch, value)
        self._series: Dict[str, Deque[Tuple[int, float]]] = {}
        self._colors: Dict[str, QColor] = {}
        self._max_points: int = 500  # 最大保留点数
        self._y_min: float = 0.0
        self._y_max: float = 1.0
        self._x_max: int = 1

        # 标签
        self._title: str = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel(self)
        self._title_label.setStyleSheet(
            "color: #cbd5e1; font-size: 12px; font-weight: bold; padding: 4px 8px;"
        )
        lay.addWidget(self._title_label)
        lay.addStretch()

    def set_title(self, title: str) -> None:
        self._title = title
        self._title_label.setText(title)

    def add_series(self, name: str, color: str = "") -> None:
        """添加一条曲线。"""
        self._series[name] = deque(maxlen=self._max_points)
        if color:
            self._colors[name] = QColor(color)
        else:
            idx = len(self._series) - 1
            self._colors[name] = _SERIES_COLORS[idx % len(_SERIES_COLORS)]

    def append(self, name: str, value: float, epoch: int = -1) -> None:
        """追加数据点。epoch=-1 时自动递增。"""
        if name not in self._series:
            self.add_series(name)
        if epoch < 0:
            dq = self._series[name]
            epoch = (dq[-1][0] + 1) if dq else 1
        self._series[name].append((epoch, value))
        # 更新缩放范围
        self._recalc_scale()

    def clear_all(self) -> None:
        """清空所有曲线。"""
        for dq in self._series.values():
            dq.clear()
        self._y_min = 0.0
        self._y_max = 1.0
        self._x_max = 1
        self.update()

    def _recalc_scale(self) -> None:
        """根据数据自动计算 Y 轴范围。"""
        all_vals: List[float] = []
        max_epoch = 1
        for dq in self._series.values():
            for ep, val in dq:
                all_vals.append(val)
                max_epoch = max(max_epoch, ep)
        if all_vals:
            self._y_min = min(all_vals)
            self._y_max = max(all_vals)
            # 留 10% padding
            rng = self._y_max - self._y_min
            if rng < 1e-9:
                rng = 1.0
            self._y_min -= rng * 0.1
            self._y_max += rng * 0.1
            self._x_max = max_epoch

    # ----------------------------- 绘制 ----------------------------- #
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = self.rect()
            title_h = 24
            plot_rect = QRectF(
                _PAD_LEFT,
                _PAD_TOP + title_h,
                rect.width() - _PAD_LEFT - _PAD_RIGHT,
                rect.height() - _PAD_TOP - _PAD_BOTTOM - title_h,
            )

            # 背景
            painter.fillRect(plot_rect, QColor("#0f1117"))

            # 网格
            self._draw_grid(painter, plot_rect)
            # 曲线
            self._draw_series(painter, plot_rect)
            # 轴标签
            self._draw_axes(painter, plot_rect)
        finally:
            painter.end()

    def _draw_grid(self, painter: QPainter, r: QRectF) -> None:
        pen = QPen(_GRID_COLOR, 1, Qt.DashLine)
        painter.setPen(pen)
        # 水平线（5 等分）
        for i in range(5):
            y = r.top() + r.height() * i / 4
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        # 垂直线（最多 10 等分）
        steps = min(10, max(1, self._x_max))
        for i in range(steps + 1):
            x = r.left() + r.width() * i / steps
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _draw_series(self, painter: QPainter, r: QRectF) -> None:
        for name, dq in self._series.items():
            if len(dq) < 2:
                continue
            color = self._colors.get(name, _SERIES_COLORS[0])
            pen = QPen(color, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            poly = QPolygonF()
            for epoch, val in dq:
                x = r.left()
                if self._x_max > 1:
                    x += r.width() * (epoch - 1) / (self._x_max - 1)
                y_norm = (val - self._y_min) / (
                    self._y_max - self._y_min + 1e-9
                )
                y_norm = max(0.0, min(1.0, y_norm))
                y = r.bottom() - r.height() * y_norm
                poly.append(QPointF(x, y))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(poly)

    def _draw_axes(self, painter: QPainter, r: QRectF) -> None:
        painter.setPen(QPen(_AXIS_COLOR, 1))
        # 边框
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)

        # Y 轴标签
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(_TEXT_COLOR, 1))
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            val = self._y_min + (self._y_max - self._y_min) * i / 4
            label = f"{val:.3f}" if abs(val) > 0.001 else f"{val:.0f}"
            painter.drawText(
                QRectF(0, y - 8, _PAD_LEFT - 4, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                label,
            )

        # X 轴标签
        steps = min(5, max(1, self._x_max))
        for i in range(steps + 1):
            x = r.left() + r.width() * i / steps
            epoch = 1 + (self._x_max - 1) * i / steps
            painter.drawText(
                QRectF(x - 20, r.bottom() + 4, 40, 16),
                Qt.AlignCenter,
                f"{int(epoch)}",
            )

        # 图例
        leg_x = r.right() - 100
        leg_y = r.top() + 8
        for i, (name, _dq) in enumerate(self._series.items()):
            color = self._colors.get(name, _SERIES_COLORS[0])
            painter.setPen(QPen(color, 2))
            painter.drawLine(
                QPointF(leg_x, leg_y + i * 14 + 4),
                QPointF(leg_x + 16, leg_y + i * 14 + 4),
            )
            painter.setPen(QPen(_TEXT_COLOR, 1))
            painter.drawText(
                QRectF(leg_x + 20, leg_y + i * 14 - 4, 80, 16),
                Qt.AlignLeft,
                name,
            )


__all__ = ["LossChartWidget"]
