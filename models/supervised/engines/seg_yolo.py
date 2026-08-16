"""
实例分割引擎（ultralytics YOLOv8-Seg）— FR-A3 · TD-01 去重（W2 自兄弟树移植）

注意：ultralytics 为 AGPL-3.0 许可（R-5，已由项目决策接受）。
去重：load/infer 逻辑提取到 _YoloSegBase。
"""
from __future__ import annotations

from core.interfaces_supervised import TaskType
from models.supervised import register_engine
from models.supervised.engines._yolo_seg_base import _YoloSegBase


@register_engine(TaskType.SEG)
class SegYoloEngine(_YoloSegBase):
    """YOLOv8-Seg 实例分割引擎。"""

    def __init__(self) -> None:
        super().__init__(TaskType.SEG)


__all__ = ["SegYoloEngine"]
