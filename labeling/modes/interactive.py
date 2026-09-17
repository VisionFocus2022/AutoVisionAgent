"""SAM 交互式标注模式（快捷键 I，FR-C2）。

点击图像 → SamAdapter 预测 mask → 多边形 Shape。
依赖 segment-anything（延迟导入）；未加载权重时点击无效。

交互流程：
1. set_image(ndarray) 设置当前帧
2. on_press(pt) 点击 → SAM predict_point → 缓存多边形
3. preview() 返回缓存的进行中 Shape（供画布实时预览）
4. commit() 确认提交（回车/双击）→ 返回 Shape
5. 连续点击：每次 on_press 刷新 mask，旧缓存被替换
"""
from __future__ import annotations

from typing import Any

from labeling.base import DEFAULT_COLOR, RGBA, AnnotationMode, Point, Shape
from labeling.modes._base import AbstractLabeler


class InteractiveLabeler(AbstractLabeler):
    """SAM 交互式标注器：点击 → mask → 多边形。

    Args:
        label: 缺陷/类别名。
        color: 描边色 RGBA。
        sam_adapter: SamAdapter 实例（需已 load + set_image）。
            若为 None，on_press 无操作（优雅降级）。
        image: 当前帧 ndarray（HxWx3）。
            若为 None，需在 on_press 前调 set_image。
    """

    mode = AnnotationMode.INTERACTIVE

    def __init__(
        self,
        label: str,
        color: RGBA = DEFAULT_COLOR,
        sam_adapter: Any = None,
        image: Any = None,
        **_options: object,
    ) -> None:
        super().__init__(label, color, min_points=3)
        self._adapter = sam_adapter
        self._image = image
        self._pending: Shape | None = None

    # ---- 外部注入 ---- #
    def set_adapter(self, adapter: Any) -> None:
        """注入/替换 SamAdapter。"""
        self._adapter = adapter

    def set_image(self, image: Any) -> None:
        """设置当前帧（标注控制器在图片切换时调用）。"""
        self._image = image

    # ---- ILabeler 实现 ---- #
    def on_press(self, pt: Point) -> None:
        if self._adapter is None or self._image is None:
            # W55·v7 P2-4：未加载/预热中不再静默无操作
            self._notify("warn", "SAM 未就绪（未加载权重或预热中）")
            return
        self._active = True
        if self._async_channel is not None:
            # W56·v7 P1-3：worker 线程推理（GUI 不冻结）；忙时页面已提示
            self._async_channel.submit(
                lambda: self._adapter.predict_point(self._image, pt), "press"
            )
            return
        try:
            poly = self._adapter.predict_point(self._image, pt)
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).exception("SAM 交互预测失败")
            self._notify("error", f"SAM 交互预测失败: {exc}")
            return
        self._accept_poly(poly)

    def _accept_poly(self, poly) -> None:
        if len(poly) >= 3:
            # W46·B：显式 POLYGON——_build 会带工具模式（INTERACTIVE），
            # LabelMe 导出器拒收致保存裸穿（UIA 真窗擒获）；形状类型与
            # 工具模式解耦，对齐 region_sam/brush_sam 提交语义
            self._pending = Shape(
                mode=AnnotationMode.POLYGON,
                points=tuple((float(p[0]), float(p[1])) for p in poly),
                label=self.label,
                color=self._color,
            )

    def deliver(self, tag: str, payload) -> None:
        """异步推理结果回投（主线程，W56·v7 P1-3；payload 为点列表）。"""
        if tag == "press":
            self._active = True
            self._accept_poly(payload)

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Shape | None:
        return None

    def preview(self) -> Shape | None:
        return self._pending

    def commit(self) -> Shape | None:
        """确认当前 SAM 预测的多边形（双击/回车触发）。"""
        shape = self._pending
        self._pending = None
        self._active = False
        self._points.clear()
        self._cursor = None
        return shape

    def reset(self) -> None:
        super().reset()
        self._pending = None


__all__ = ["InteractiveLabeler"]
