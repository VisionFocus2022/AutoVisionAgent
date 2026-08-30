"""SAM3 标注适配器（W46 · transformers 后端）。

Meta SAM 3（2025-11 文本概念 + 几何提示分割）经 transformers
Sam3Model/Sam3Processor 接入（sdpa 注意力，无需 flash-attn）。与
SamAdapter（SAM v1，segment-anything）保持同构鸭子方法面——modes 层
零感知后端差异，SamSessionMixin 按装配分支二选一。

transformers 5.12.1 能力边界（实现期源码实证，grep input_points=0）：
- 无 point 提示 → predict_point 以点击为中心的 _CLICK_BOX_R 小盒代偿
  （盒提示语义=引导非裁剪，小盒仍可分割整对象）；背景点击（label=0）
  无对应提示，诚实返回空；
- 无 logits 迭代 mask_input → predict_points 忽略该参（笔刷精修退化为
  笔划外包盒提示，返回 logits=None）；
- 文本概念提示（PCS）→ build_amg_detector 以 label 为概念文本全图
  分割（AUTO 模式复用 W44 通道，controller 零改动）。

图像契约：BGR ndarray（与 imread_unicode/SamAdapter 一致），前向前
内部转 RGB（SAM3 文本塔对色序敏感）。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

import numpy as np

_logger = logging.getLogger(__name__)

try:
    from labeling.geometry import simplify_polyline
except ImportError:  # pragma: no cover — 与 sam_adapter 同款降级守卫
    _logger.warning("labeling.geometry 不可用，使用简化轮廓")
    def simplify_polyline(points, epsilon=2.0):
        return points

try:
    from labeling.base import Shape, AnnotationMode
except ImportError:  # pragma: no cover
    _logger.warning("labeling.base 不可用，使用桩定义")
    from enum import Enum
    class AnnotationMode(Enum):
        POLYGON = "polygon"
        RECTANGLE = "rectangle"
    class Shape:  # type: ignore[no-redef]
        pass

# 点击代偿盒半边长（px）：盒提示引导分割，不需覆盖整对象
_CLICK_BOX_R = 16
# 笔划外包盒外扩边距（px）
_BRUSH_MARGIN = 8
def _mask_to_polygon(mask: np.ndarray, epsilon: float = 2.0) -> List[Tuple[float, float]]:
    """二值掩码 → 最大轮廓 → ε 折点多边形（与 SamAdapter 同管线）。"""
    import cv2

    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    pts = [(float(p[0][0]), float(p[0][1])) for p in largest]
    return simplify_polyline(pts, epsilon=epsilon)


class Sam3Adapter:
    """SAM3 适配器（延迟导入 transformers，与 SamAdapter 同方法面）。"""

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._device: str = "cpu"
        self._cached_image_hash: Optional[int] = None
        # W21 同款引用快路径：SAM3 无独立 embedding API（编码在前向内），
        # 缓存仅免去重复 tobytes 哈希
        self._cached_image_ref: Optional[np.ndarray] = None

    def load(self, model_dir: str, device: str = "cuda") -> None:
        """从 transformers 格式模型目录加载（config.json + model.safetensors）。"""
        from transformers import Sam3Model, Sam3Processor

        model = Sam3Model.from_pretrained(model_dir)
        processor = Sam3Processor.from_pretrained(model_dir)
        model.to(device=device)
        model.eval()
        self._model, self._processor, self._device = model, processor, device

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    def set_image(self, image: np.ndarray) -> None:
        """登记当前图像（引用/哈希双快路径；编码延迟到首次前向）。"""
        if not self.loaded:
            raise RuntimeError("SAM3 未加载权重")
        if image is self._cached_image_ref:
            return
        h = hash(image.tobytes())
        if h == self._cached_image_hash:
            self._cached_image_ref = image
            return
        self._cached_image_hash = h
        self._cached_image_ref = image

    # ---------------------------------------------------------------- 核心

    def _run_instances(
        self,
        image: np.ndarray,
        text: Optional[str] = None,
        boxes: Optional[List[List[List[float]]]] = None,
    ) -> Tuple[List[np.ndarray], List[float]]:
        """单次前向 → (实例掩码列表, 分数列表)（原图尺寸，numpy）。

        测试接缝：单测直接替换本方法注入合成实例。
        """
        import torch

        rgb = np.ascontiguousarray(image[..., ::-1])
        inputs = self._processor(
            images=rgb, text=text, input_boxes=boxes, return_tensors="pt"
        )
        inputs = {
            k: (v.to(self._device) if hasattr(v, "to") else v)
            for k, v in inputs.items()
        }
        with torch.inference_mode():
            outputs = self._model(**inputs)
        results = self._processor.post_process_instance_segmentation(
            outputs, target_sizes=[image.shape[:2]]
        )
        first = results[0]
        masks = [np.asarray(m) for m in first["masks"].detach().cpu().numpy()]
        scores = [float(s) for s in first["scores"].detach().cpu().numpy()]
        return masks, scores

    def _best_mask_near(
        self, masks: List[np.ndarray], anchor: Tuple[float, float]
    ) -> Optional[np.ndarray]:
        """质心离锚点最近的实例掩码（None=无实例）——W52 点击/W53 区域共用。

        W52（点击口径 162 图）：比全局 argmax 分数 mean 0.521→0.546、
        零产出 10→1；W53（区域口径 162 图 · GT bbox m=0）：0.739→0.755、
        零产出 4→0——点击意图下「离点击最近」比「全局最高分」贴合目标。
        """
        if not masks:
            return None

        def _dist(i: int) -> float:
            ys, xs = np.nonzero(masks[i])
            if len(xs) == 0:
                return 1e18
            return float(
                ((xs.mean() - anchor[0]) ** 2 + (ys.mean() - anchor[1]) ** 2) ** 0.5
            )

        return masks[min(range(len(masks)), key=_dist)]

    def _best_polygon_near(
        self, masks: List[np.ndarray], anchor: Tuple[float, float]
    ) -> List[Tuple[float, float]]:
        """实例选择 v2（W52 · 162 图实测）：质心离锚点最近者。

        （W47 12 图小样本曾误判此杠杆中性，162 图翻案。）
        """
        best = self._best_mask_near(masks, anchor)
        return _mask_to_polygon(best) if best is not None else []

    def _best_polygon(
        self, masks: List[np.ndarray], scores: List[float]
    ) -> List[Tuple[float, float]]:
        if not masks:
            return []
        best = masks[int(np.argmax(scores))] if scores else masks[0]
        return _mask_to_polygon(best)

    # ---------------------------------------------------------------- 提示面

    def predict_point(
        self,
        image: np.ndarray,
        point: Tuple[float, float],
        label: int = 1,
    ) -> List[Tuple[float, float]]:
        """点击预测：点 → 代偿盒提示 → 最佳实例多边形。

        label=1 前景；label=0 背景——SAM3 无背景点提示，返回空（诚实降级）。
        """
        self.set_image(image)
        if label == 0:
            return []
        x, y = point
        h, w = image.shape[:2]
        r = _CLICK_BOX_R
        box = (
            max(x - r, 0), max(y - r, 0),
            min(x + r, w - 1), min(y + r, h - 1),
        )
        masks, scores = self._run_instances(image, boxes=[[list(box)]])
        # W52：点击场景实例选择=质心最近（离点击最近），非 argmax 分数
        return self._best_polygon_near(masks, (x, y))

    def predict_box(
        self,
        image: np.ndarray,
        box: Tuple[float, float, float, float],
    ) -> List[Tuple[float, float]]:
        """框选预测：盒提示直通 → 最佳实例多边形。"""
        self.set_image(image)
        masks, scores = self._run_instances(image, boxes=[[list(box)]])
        return self._best_polygon(masks, scores)

    def predict_point_in_box(
        self,
        image: np.ndarray,
        point: Tuple[float, float],
        box: Tuple[float, float, float, float],
        label: int = 1,
    ) -> List[Tuple[float, float]]:
        """区域分割（W43 语义）：盒提示 + 掩码∩矩形硬约束。

        SAM3 无点提示——区域内对象由盒语义引导（区域通常含单一目标）；
        实例选择=质心离点击最近（W53 · val 162 GT bbox m=0 实测
        0.739→0.755、零产出 4→0，与 predict_point v2 同语义）；
        掩码级硬求交保留：折点严格不越界。
        """
        self.set_image(image)
        masks, scores = self._run_instances(image, boxes=[[list(box)]])
        if not masks:
            return []
        best = self._best_mask_near(masks, point).astype(np.uint8)
        x1, y1, x2, y2 = (int(v) for v in box)
        clipped = np.zeros_like(best)
        y_lo, y_hi = max(y1, 0), min(y2 + 1, best.shape[0])
        x_lo, x_hi = max(x1, 0), min(x2 + 1, best.shape[1])
        clipped[y_lo:y_hi, x_lo:x_hi] = best[y_lo:y_hi, x_lo:x_hi]
        return _mask_to_polygon(clipped)

    def predict_points(
        self,
        image: np.ndarray,
        points: List[Tuple[float, float]],
        labels: List[int],
        box: Optional[Tuple[float, float, float, float]] = None,
        mask_input: Any = None,
    ) -> Tuple[List[Tuple[float, float]], Any]:
        """多点提示（笔刷）：笔划点外包盒 ∪ box → 多边形。

        mask_input（上轮 logits 迭代）transformers 后端不支持——忽略，
        返回 logits=None（docstring 声明的诚实降级）。
        """
        self.set_image(image)
        if not points:
            return [], None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        m = _BRUSH_MARGIN
        h, w = image.shape[:2]
        x1, y1 = max(min(xs) - m, 0), max(min(ys) - m, 0)
        x2, y2 = min(max(xs) + m, w - 1), min(max(ys) + m, h - 1)
        if box is not None:
            x1, y1 = min(x1, box[0]), min(y1, box[1])
            x2, y2 = max(x2, box[2]), max(y2, box[3])
        masks, scores = self._run_instances(
            image, boxes=[[[x1, y1, x2, y2]]]
        )
        return self._best_polygon(masks, scores), None

    def build_amg_detector(
        self,
        iou_thresh: float = 0.3,
        min_area: int = 64,
        max_masks: int = 64,
        label: str = "defect",
    ):
        """文本概念全图分割 detector（W44 AMG 通道复用，签名鸭子兼容）。

        SAM3 后端下 iou_thresh 语义 = 实例分数阈值（真机实测：极柱域
        有效实例大量落在 0.3-0.5 带，默认 0.3 对齐 post_process 阈值，
        0.5 会滤掉过半真实例）；label 即概念文本提示（label 输入框=
        概念提示词，空值回落 "defect"）。概念词必须贴域——W47 以极柱
        GT 实测（12 图对照标注）：唯一有效词 "scratch"（精确率 32%/
        GT 覆盖 57%，阈值 0.3），"mark" 次之（11%/68%）；"hole" 高分
        实例全为误检（精确率 0%），"pole"/"defect"/"dent"/"flaw" 零
        命中。分数高≠命中 GT——以 scripts/eval_sam3_accuracy.py 复测。
        """
        text = (label or "").strip() or "defect"

        def _detector(image):
            masks, scores = self._run_instances(image, text=text)
            kept = [
                (m, s) for m, s in zip(masks, scores)
                if s >= iou_thresh and int(np.count_nonzero(m)) >= min_area
            ]
            kept.sort(key=lambda p: int(np.count_nonzero(p[0])), reverse=True)
            if len(kept) > max_masks:
                _logger.warning(
                    "SAM3 概念分割 %d 个超上限 %d，已截断（面积最小者丢弃）",
                    len(kept), max_masks,
                )
                kept = kept[:max_masks]
            shapes: List[Shape] = []
            for mask, _s in kept:
                poly = _mask_to_polygon(mask)
                if len(poly) >= 3:
                    shapes.append(Shape(
                        mode=AnnotationMode.POLYGON,
                        points=tuple(poly),
                        label=label,
                    ))
            return shapes

        return _detector

    def to_shapes(
        self,
        image: np.ndarray,
        points: List[Tuple[Tuple[float, float], int]],
    ) -> List[Shape]:
        """批量点击预测 → Shape 列表（与 SamAdapter 同语义）。"""
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


__all__ = ["Sam3Adapter"]
