"""标注基础设施核心定义。

定义标注模式枚举、Shape 数据类、标注器协议/抽象基类。
被 io_labelme / canvas / controller / modes 全链路依赖。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

# ---- 类型别名 ---- #

Point = tuple[float, float]
RGBA = tuple[int, int, int, int]

DEFAULT_COLOR: RGBA = (52, 152, 219, 255)


class AnnotationMode(Enum):
    """支持的标注模式（对标 SKolpha Q/R/P/K/W/I）。"""

    POLYGON = "polygon"          # Q — 多边形标注
    RECTANGLE = "rectangle"      # R — 矩形标注
    BRUSH = "brush"              # P — 画笔标注
    KEYPOINT = "keypoint"        # K — 关键点标注
    AUTO = "auto"                # W — AI 自动标注
    INTERACTIVE = "interactive"  # I — SAM 交互式标注
    REGION_SAM = "region_sam"    # J — SAM 区域分割（W43：拖拽定区+点击分割）
    SAM_BRUSH = "sam_brush"      # B — SAM 笔刷精修（W44：笔划点提示+logits 迭代）

    @classmethod
    def manual_modes(cls):
        """返回手动标注模式（非 AI 辅助）。"""
        return (cls.POLYGON, cls.RECTANGLE, cls.BRUSH, cls.KEYPOINT)


@dataclass
class Shape:
    """单个标注形状。

    Attributes:
        mode: 标注模式。
        points: 坐标点列表 [(x1, y1), ...]。
        label: 类别/缺陷名。
        color: RGBA 描边色。
        group_id: 分组 ID（可选）。
        flags: 附加标志 [(flag_name, bool), ...]。
    """

    mode: AnnotationMode = AnnotationMode.POLYGON
    points: tuple[Point, ...] = ()
    label: str = ""
    color: RGBA = DEFAULT_COLOR
    group_id: int | None = None
    flags: tuple[tuple[str, bool], ...] = ()


class ILabeler(ABC):
    """标注器协议（策略模式接口）。

    每种标注模式对应一个 ILabeler 实现，由 AnnotationController 调用。
    """

    mode: AnnotationMode
    label: str

    @abstractmethod
    def on_press(self, pt: Point) -> None:
        """鼠标按下。"""

    @abstractmethod
    def on_move(self, pt: Point) -> None:
        """鼠标移动。"""

    @abstractmethod
    def on_release(self, pt: Point) -> Shape | None:
        """鼠标释放，返回完成的 Shape 或 None。"""

    @abstractmethod
    def preview(self) -> Shape | None:
        """返回当前进行中的预览 Shape（供画布实时绘制）。"""

    @abstractmethod
    def commit(self) -> Shape | None:
        """确认提交当前形状（回车/双击触发）。"""

    @abstractmethod
    def reset(self) -> None:
        """重置到初始状态（取消当前操作）。"""


__all__ = [
    "Point",
    "RGBA",
    "DEFAULT_COLOR",
    "AnnotationMode",
    "Shape",
    "ILabeler",
]
