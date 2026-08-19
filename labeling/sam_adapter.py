"""SAM 交互/AI 预标注适配器（FR-C2/C3）。

封装 segment-anything 的 SamPredictor，提供：
- 点击/框 → mask → 多边形轮廓
- AI 全自动预标注（零样本 IDetector 或有监督引擎）

mask embedding 缓存：同图只算一次（R-6/R-8）。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

import numpy as np

_logger = logging.getLogger(__name__)

# 延迟导入：labeling.geometry 和 labeling.base 可能尚未实现
try:
    from labeling.geometry import simplify_polyline
except ImportError:
    _logger.warning("labeling.geometry 不可用，使用简化轮廓")
    def simplify_polyline(points, epsilon=2.0):
        return points

try:
    from labeling.base import Shape, AnnotationMode
except ImportError:
    _logger.warning("labeling.base 不可用，使用桩定义")
    from enum import Enum
    class AnnotationMode(Enum):
        POLYGON = "polygon"
        RECTANGLE = "rectangle"
    class Shape:  # type: ignore[no-redef]
        pass


class SamAdapter:
    """SAM 适配器（延迟加载 segment-anything）。"""

    def __init__(self, model_type: str = "vit_b") -> None:
        self._model_type = model_type
        self._predictor: Any = None
        self._cached_image_hash: Optional[int] = None
        # W21：缓存命中的图像对象引用——同对象走 is 快路径，省去每次
        # 点击的整图 tobytes 哈希（1600x1600 图 ~7.7MB/次）
        self._cached_image_ref: Optional[np.ndarray] = None

    def load(self, checkpoint: str, device: str = "cuda") -> None:
        """加载 SAM 权重。"""
        from segment_anything import sam_model_registry, SamPredictor

        sam = sam_model_registry[self._model_type](checkpoint=checkpoint)
        sam.to(device=device)
        self._predictor = SamPredictor(sam)

    @property
    def loaded(self) -> bool:
        return self._predictor is not None

    def set_image(self, image: np.ndarray) -> None:
        """设置当前图像（含 embedding 缓存）。

        W21 快路径：同对象（is）直接命中；等值新对象经一次哈希命中后
        更新引用，后续同对象不再哈希。换图正常重算 embedding。
        """
        if not self.loaded:
            raise RuntimeError("SAM 未加载权重")
        if image is self._cached_image_ref:
            return
        h = hash(image.tobytes())
        if h == self._cached_image_hash:
            self._cached_image_ref = image  # 等值命中：升级为对象快路径
            return
        self._predictor.set_image(image)
        self._cached_image_hash = h
        self._cached_image_ref = image

    def predict_point(
        self,
        image: np.ndarray,
        point: Tuple[float, float],
        label: int = 1,
    ) -> List[Tuple[float, float]]:
        """
        点击预测：单个前景点 → mask → 多边形顶点。

        Args:
            image: HxWx3 numpy array.
            point: (x, y) 点击坐标。
            label: 1=前景, 0=背景。

        Returns:
            多边形顶点列表 [(x1,y1), ...]（经 Douglas-Peucker 简化）。
        """
        self.set_image(image)
        import cv2

        masks, scores, _ = self._predictor.predict(
            point_coords=np.array([point]),
            point_labels=np.array([label]),
            multimask_output=True,
        )
        best = masks[np.argmax(scores)]
        contours, _ = cv2.findContours(
            best.astype(np.uint8), cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return []
        largest = max(contours, key=cv2.contourArea)
        pts = [(float(p[0][0]), float(p[0][1])) for p in largest]
        return simplify_polyline(pts, epsilon=2.0)

    def predict_box(
        self,
        image: np.ndarray,
        box: Tuple[float, float, float, float],
    ) -> List[Tuple[float, float]]:
        """
        框选预测：bbox → mask → 多边形顶点。
        """
        self.set_image(image)
        import cv2

        masks, scores, _ = self._predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.array(box)[None, :],
            multimask_output=False,
        )
        best = masks[0]
        contours, _ = cv2.findContours(
            best.astype(np.uint8), cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return []
        largest = max(contours, key=cv2.contourArea)
        pts = [(float(p[0][0]), float(p[0][1])) for p in largest]
        return simplify_polyline(pts, epsilon=2.0)

    def to_shapes(
        self,
        image: np.ndarray,
        points: List[Tuple[Tuple[float, float], int]],
    ) -> List[Shape]:
        """
        批量点击预测 → Shape 列表。

        Args:
            image: HxWx3.
            points: [((x,y), label), ...]

        Returns:
            Shape 列表（多边形模式）。
        """
        shapes: List[Shape] = []
        for (pt, lbl) in points:
            poly = self.predict_point(image, pt, lbl)
            if len(poly) >= 3:
                shapes.append(Shape(
                    mode=AnnotationMode.POLYGON,
                    label="auto",
                    points=tuple(poly),
                ))
        return shapes


__all__ = ["SamAdapter"]
