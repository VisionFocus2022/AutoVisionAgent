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

from typing import Any, Optional

from labeling.base import AnnotationMode, DEFAULT_COLOR, RGBA, Point, Shape
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
        self._pending: Optional[Shape] = None

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
            return
        self._active = True
        try:
            poly = self._adapter.predict_point(self._image, pt)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception("SAM 交互预测失败")
            return
        if len(poly) >= 3:
            self._pending = self._build(tuple(poly))

    def on_move(self, pt: Point) -> None:
        self._cursor = pt

    def on_release(self, pt: Point) -> Optional[Shape]:
        return None

    def preview(self) -> Optional[Shape]:
        return self._pending

    def commit(self) -> Optional[Shape]:
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
