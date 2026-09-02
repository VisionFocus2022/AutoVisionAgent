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
    """支持的标注模式（2026-09-01 极柱工作流裁剪；W56 增工业两形态）。"""

    POLYGON = "polygon"          # Q — 多边形标注
    RECTANGLE = "rectangle"      # R — 矩形标注
    CUT_LINE = "cut_line"        # C — 切割线（W56：对标 SKolpha cut_line_label）
    OPERATION = "operation"      # O — 操作标注（W56：对标 SKolpha operation_label）
    INTERACTIVE = "interactive"  # I — SAM 点标（点提示分割）
    REGION_SAM = "region_sam"    # J — SAM 矩形标（框选定区分割，W43：拖拽定区+点击分割）
    EDIT = "edit"                # E — 顶点编辑（W55：选中多边形→拖/加点/删点）

    @classmethod
    def manual_modes(cls):
        """返回手动标注模式（非 AI 辅助）。"""
        return (
            cls.POLYGON, cls.RECTANGLE, cls.CUT_LINE, cls.OPERATION,
        )


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
