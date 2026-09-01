"""标注控制器 — 协调标注器与画布交互。

负责鼠标事件分发到当前标注器、模式切换、标签管理。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView

from labeling.base import DEFAULT_COLOR, AnnotationMode, Point, Shape
from labeling.canvas import AnnotationCanvas
from labeling.geometry import hit_vertex, nearest_edge_point, point_in_polygon
from labeling.modes import make_labeler

_logger = logging.getLogger(__name__)


class AnnotationController:
    """标注控制器。

    安装到 QGraphicsView 上拦截鼠标事件，分发到当前标注器。

    Args:
        canvas: 标注画布场景。
        mode: 初始标注模式。
        label: 初始标签名。
    """

    def __init__(
        self,
        canvas: AnnotationCanvas,
        mode: AnnotationMode = AnnotationMode.POLYGON,
        label: str = "defect",
    ) -> None:
        self._canvas = canvas
        self._mode: AnnotationMode = mode
        self._label: str = label
        self._labeler = None
        self._view: QGraphicsView | None = None
        # W55 编辑模式：拖动中的顶点索引（None=未拖动）
        self._edit_drag_vertex: int | None = None
        self._make_labeler()

    # ============================== 模式/标签 ============================== #
    @property
    def mode(self) -> AnnotationMode:
        return self._mode

    def set_mode(self, mode: AnnotationMode) -> None:
        """切换标注模式。"""
        if mode == self._mode and self._labeler is not None:
            return
        if self._mode is AnnotationMode.EDIT and mode is not AnnotationMode.EDIT:
            # W55：离开编辑模式清拖动态与选中
            self._edit_drag_vertex = None
            self._canvas.clear_selection()
        self._mode = mode
        self._make_labeler()

    def set_label(self, label: str) -> None:
        """设置当前标签名。"""
        self._label = label
        if self._labeler is not None:
            self._labeler.label = label

    @property
    def label(self) -> str:
        return self._label

    def _make_labeler(self) -> None:
        """构造当前模式的标注器。"""
        try:
            self._labeler = make_labeler(
                self._mode, self._label, DEFAULT_COLOR
            )
        except (ValueError, TypeError):
            _logger.warning("标注器 %s 构造失败", self._mode)
            self._labeler = None

    # ============================== 安装 ============================== #
    def install(self, view: QGraphicsView) -> None:
        """安装到 QGraphicsView（兼容旧接口，推荐改用 set_controller）。

        历史实现通过 monkey-patch view 的 mousePressEvent/mouseMoveEvent/
        mouseReleaseEvent 来接管事件，但 PySide6 的 C++ vtable 事件分发
        不保证会查找 Python 实例属性，导致鼠标事件无法可靠拦截。

        现已改为由 _ZoomableView 子类化重写鼠标事件并委托给
        on_mouse_press/move/release 公开方法。本方法仅设置 _view 引用
        以保持向后兼容（如 _to_scene_point 仍需 view）。
        """
        self._view = view
        view.setMouseTracking(True)

    # ============================== 坐标转换 ============================== #
    def _to_scene_point(self, view: QGraphicsView, event) -> Point | None:
        """将视图坐标转为场景坐标。"""
        pos = view.mapToScene(event.pos())
        return (float(pos.x()), float(pos.y()))

    # ============================== 鼠标事件（公开 API） ============================== #
    # 由 _ZoomableView 子类的 mousePressEvent/mouseMoveEvent/mouseReleaseEvent
    # 直接调用，避免 monkey-patch 在 PySide6 中不可靠的问题。
    def on_mouse_press(self, event) -> None:
        if self._view is None:
            return
        pt = self._to_scene_point(self._view, event)
        if pt is None:
            return
        if self._mode is AnnotationMode.EDIT:
            # W55：编辑模式接管鼠标（labeler=None），不经绘制路径
            if event.button() == Qt.LeftButton:
                self._edit_press_left(pt)
            elif event.button() == Qt.RightButton:
                self._edit_press_right(pt)
            return
        if event.button() == Qt.LeftButton and self._labeler is not None:
            self._labeler.on_press(pt)
            # 关键点/矩形/画笔在 release 时完成，检查是否有即时结果
            shape = self._labeler.preview()
            self._canvas._redraw()
            if shape:
                self._draw_preview(shape)
        elif event.button() == Qt.RightButton:
            self.handle_commit()

    def on_mouse_move(self, event) -> None:
        if self._view is None:
            return
        pt = self._to_scene_point(self._view, event)
        if pt is None:
            return
        if self._mode is AnnotationMode.EDIT:
            if self._edit_drag_vertex is not None:
                self._canvas.move_vertex(self._edit_drag_vertex, pt)
            return
        if self._labeler is None:
            return
        self._labeler.on_move(pt)
        self._canvas._redraw()
        shape = self._labeler.preview()
        if shape:
            self._draw_preview(shape)

    def on_mouse_release(self, event) -> None:
        if self._view is None:
            return
        if self._mode is AnnotationMode.EDIT:
            self._edit_drag_vertex = None  # W55：拖动结束
            return
        if self._labeler is None:
            return
        if event.button() == Qt.LeftButton:
            pt = self._to_scene_point(self._view, event)
            if pt is not None:
                shape = self._labeler.on_release(pt)
                if shape is not None:
                    self._commit_shape(shape)

    def on_mouse_double_click(self, event) -> None:
        """双击事件（W55：EDIT 模式下=在最近边插入顶点；其他模式不消费）。"""
        if self._view is None or self._mode is not AnnotationMode.EDIT:
            return
        pt = self._to_scene_point(self._view, event)
        if pt is not None:
            self._edit_double_click(pt)

    # ============================== 便捷 API（点元组，绕开 Qt 事件） ============================== #
    # 供单元测试与脚本化调用使用，不需要 view 与 QMouseEvent。
    # 直接以场景坐标驱动 labeler，行为等价于 on_mouse_* 但跳过坐标转换。
    def handle_press(self, pt: Point) -> None:
        """按下（左键）— 直接以场景坐标驱动 labeler。"""
        if self._mode is AnnotationMode.EDIT:
            self._edit_press_left(pt)
            return
        if self._labeler is None:
            return
        self._labeler.on_press(pt)
        shape = self._labeler.preview()
        self._canvas._redraw()
        if shape:
            self._draw_preview(shape)

    def handle_move(self, pt: Point) -> None:
        """移动 — 直接以场景坐标驱动 labeler。"""
        if self._mode is AnnotationMode.EDIT:
            if self._edit_drag_vertex is not None:
                self._canvas.move_vertex(self._edit_drag_vertex, pt)
            return
        if self._labeler is None:
            return
        self._labeler.on_move(pt)
        self._canvas._redraw()
        shape = self._labeler.preview()
        if shape:
            self._draw_preview(shape)

    def handle_release(self, pt: Point) -> None:
        """释放（左键）— 直接以场景坐标驱动 labeler，完成形状提交。"""
        if self._mode is AnnotationMode.EDIT:
            self._edit_drag_vertex = None
            return
        if self._labeler is None:
            return
        shape = self._labeler.on_release(pt)
        if shape is not None:
            self._commit_shape(shape)

    # ------------------ W55 编辑模式便捷 API（点元组，测试/脚本化） ------------------ #

    def handle_right_press(self, pt: Point) -> bool:
        """右键（EDIT 模式）— 命中顶点则删除；返回是否删除成功。"""
        return self._edit_press_right(pt)

    def handle_double_click(self, pt: Point) -> bool:
        """双击（EDIT 模式）— 在最近边投影点插入顶点；返回是否插入。"""
        return self._edit_double_click(pt)

    def _selected_polygon(self) -> Shape | None:
        idx = self._canvas.selected_index
        if idx is None:
            return None
        shape = self._canvas.shapes[idx]
        if shape.mode is not AnnotationMode.POLYGON or len(shape.points) < 3:
            return None
        return shape

    def _edit_press_left(self, pt: Point) -> None:
        """编辑模式左键：命中顶点→开始拖动；命中形状→选中；空白→取消。"""
        shape = self._selected_polygon()
        if shape is not None:
            v = hit_vertex(list(shape.points), pt)
            if v is not None:
                self._edit_drag_vertex = v
                self._canvas.begin_vertex_edit()  # 拖前快照：一次拖动=一步 undo
                _logger.info("W55 顶点拖动开始: vertex=%s pt=%s", v, pt)
                return
        for i, s in enumerate(self._canvas.shapes):
            if s.mode is AnnotationMode.POLYGON and point_in_polygon(
                pt, list(s.points)
            ):
                self._canvas.select_shape(i)
                _logger.info("W55 编辑选中: shape=%s pt=%s", i, pt)
                return
        self._canvas.clear_selection()

    def _edit_press_right(self, pt: Point) -> bool:
        """编辑模式右键：命中选中形状顶点→删除（保底 ≥3 点）。"""
        shape = self._selected_polygon()
        if shape is None:
            return False
        v = hit_vertex(list(shape.points), pt)
        if v is None:
            return False
        return self._canvas.remove_vertex(v)

    def _edit_double_click(self, pt: Point) -> bool:
        """编辑模式双击：最近边投影点插入顶点。"""
        shape = self._selected_polygon()
        if shape is None:
            return False
        got = nearest_edge_point(list(shape.points), pt)
        if got is None:
            return False
        pos, proj = got
        return self._canvas.insert_vertex(pos, proj)

    def _draw_preview(self, shape: Shape) -> None:
        """在画布上绘制预览标注（半透明）。"""
        self._canvas._draw_shape(shape)

    # ============================== 提交/取消 ============================== #
    def handle_commit(self) -> None:
        """确认提交当前标注（回车/右键触发）。"""
        if self._labeler is None:
            return
        shape = self._labeler.commit()
        if shape is not None:
            self._commit_shape(shape)
        else:
            # AI 模式可能通过 commit 逐个返回队列中的形状
            while True:
                shape = self._labeler.commit()
                if shape is None:
                    break
                self._commit_shape(shape)

    def cancel(self) -> None:
        """取消当前标注操作。"""
        if self._labeler is not None:
            self._labeler.reset()
        if self._mode is AnnotationMode.EDIT:
            # W55：编辑模式下 Esc=取消选中（无进行中绘制）
            self._canvas.clear_selection()
            return
        self._canvas._redraw()

    def attach_interactive(self, adapter, image=None) -> bool:
        """为交互式模式注入 SAM 适配器与当前帧（W4-T3 / P2-6）。

        仅在当前模式为 INTERACTIVE 且标注器支持注入时生效。

        Returns:
            是否注入成功。
        """
        # W43：REGION_SAM 同享 SAM 注入通道（INTERACTIVE 行为不变）
        # W46·B：SAM_BRUSH 补齐——W44 建模式时漏加，笔刷在 GUI 装配链
        # 永远拿不到 adapter（单测直接注 set_adapter 不经此路，UIA 真窗
        # 测试擒获；BrushSamLabeler 有 set_adapter/set_image 同契约）
        _SAM_ATTACH_MODES = (
            AnnotationMode.INTERACTIVE, AnnotationMode.REGION_SAM,
            AnnotationMode.SAM_BRUSH,
        )
        if self._mode not in _SAM_ATTACH_MODES or self._labeler is None:
            return False
        if not hasattr(self._labeler, "set_adapter"):
            return False
        self._labeler.set_adapter(adapter)
        if image is not None:
            self._labeler.set_image(image)
        return True

    def attach_detector(self, detector, image=None, on_result=None) -> bool:
        """为 AUTO 模式注入检测回调与当前帧（W44·C：SAM AMG 接入通道）。

        仅在当前模式为 AUTO 且标注器支持 set_detector 时生效；
        on_result（W55 · FR-002）：透传到 AutoLabeler 结果回调，
        0 形状时页面据此发诚实降级提示（None=不接）。
        """
        if self._mode is not AnnotationMode.AUTO or self._labeler is None:
            return False
        if not hasattr(self._labeler, "set_detector"):
            return False
        self._labeler.set_detector(detector)
        if image is not None:
            self._labeler.set_image(image)
        if on_result is not None and hasattr(self._labeler, "set_result_hook"):
            self._labeler.set_result_hook(on_result)
        return True

    def _commit_shape(self, shape: Shape) -> None:
        """将标注添加到画布。"""
        self._canvas.add_shape(
            mode=shape.mode,
            label=shape.label,
            points=list(shape.points),
        )


__all__ = ["AnnotationController"]
