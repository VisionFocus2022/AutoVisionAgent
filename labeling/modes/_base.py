"""标注器抽象基类。

提供标注器公共状态管理和 Shape 构建，子类只需实现
on_press / on_move / on_release / preview / commit。
"""
from __future__ import annotations

from collections.abc import Callable

from labeling.base import (
    DEFAULT_COLOR,
    RGBA,
    AnnotationMode,
    ILabeler,
    Point,
    Shape,
)


class AbstractLabeler(ILabeler):
    """标注器基类（模板方法模式）。

    子类通过 self._points 管理当前形状的顶点列表，
    调用 self._build() 构建最终 Shape。

    Args:
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        min_points: 完成标注所需的最少点数。
    """

    mode: AnnotationMode = AnnotationMode.POLYGON

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        min_points: int = 3,
    ) -> None:
        self.label: str = label
        self._color: RGBA = color
        self._min_points: int = min_points
        self._points: list[Point] = []
        self._cursor: Point | None = None
        self._active: bool = False
        # W55·v7 P2-4：操作员感知通道（error 推理失败 / warn 未就绪 /
        # info 零产出），由页面经 controller 注入、转发状态栏
        self._feedback: Callable[[str, str], None] | None = None
        # W56·v7 P1-3：异步推理通道（页面注入；None=同步回退——单测与
        # 非 GUI 消费面保持同步语义）
        self._async_channel = None

    def set_feedback_callback(
        self, cb: Callable[[str, str], None] | None
    ) -> None:
        """注入/清除状态反馈回调（kind, msg）。"""
        self._feedback = cb

    def set_async_channel(self, channel) -> None:
        """注入/清除异步推理通道（W56·v7 P1-3）。

        channel.submit(fn, tag) -> bool：True=受理（结果经 deliver(tag,
        payload) 回投主线程）；False=通道忙（页面已提示，调用方静默返回）。
        None（默认）= 无通道，调用方走同步推理回退（单测/脚本消费面）。
        """
        self._async_channel = channel

    def _notify(self, kind: str, msg: str) -> None:
        """发射反馈——通道自身故障不得反噬标注主流程。"""
        if self._feedback is None:
            return
        try:
            self._feedback(kind, msg)
        except Exception:  # noqa: BLE001
            import logging as _log

            _log.getLogger(__name__).exception("标注器反馈回调异常")

    # ---- 公共辅助 ---- #
    @property
    def points(self) -> tuple[Point, ...]:
        """当前顶点序列（只读副本；era-2 契约：commit 后为空元组）。"""
        return tuple(self._points)

    def _build(
        self, points: tuple[Point, ...] | None = None
    ) -> Shape:
        """构建 Shape 实例。"""
        pts = points if points is not None else tuple(self._points)
        return Shape(
            mode=self.mode,
            points=pts,
            label=self.label,
            color=self._color,
        )

    def _can_commit(self) -> bool:
        """检查是否满足提交条件（点数达标）。"""
        return len(self._points) >= self._min_points

    # ---- ILabeler 实现（子类覆写） ---- #
    def on_press(self, pt: Point) -> None:
        self._active = True
        self._points.append(pt)

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Shape | None:
        return None

    def preview(self) -> Shape | None:
        if not self._active or not self._points:
            return None
        pts = list(self._points)
        if self._cursor is not None:
            pts.append(self._cursor)
        return self._build(tuple(pts))

    def commit(self) -> Shape | None:
        if not self._can_commit():
            return None
        shape = self._build()
        self.reset()
        return shape

    def reset(self) -> None:
        self._points.clear()
        self._cursor = None
        self._active = False


__all__ = ["AbstractLabeler"]
