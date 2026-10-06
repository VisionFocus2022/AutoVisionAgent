"""大图分块推理（Tiling / Sliding Window）。

工业图像常达 4000x3000+，直接送入模型会 OOM 或精度下降。
本模块将大图切分为 tile_size x tile_size 的瓦片，逐瓦片推理后合并结果。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


def _gaussian_weight(size: int, sigma: float = 0.25):
    """生成高斯权重核（用于 overlap 区域的加权合并）。"""
    import numpy as np
    coords = np.arange(size) - size / 2
    g1d = np.exp(-(coords ** 2) / (2 * (size * sigma) ** 2))
    g2d = np.outer(g1d, g1d)
    return g2d / g2d.max()


def compute_tiles(
    img_h: int,
    img_w: int,
    tile_size: int = 1024,
    overlap: int = 128,
) -> list[tuple[int, int, int, int]]:
    """计算瓦片网格坐标。

    Args:
        img_h: 图像高度。
        img_w: 图像宽度。
        tile_size: 瓦片边长（正方形）。
        overlap: 相邻瓦片的重叠像素。

    Returns:
        [(x1, y1, x2, y2), ...] 瓦片坐标列表（原图绝对坐标）。

    Raises:
        ValueError: M6（P1）——参数非法（overlap >= tile_size 时 step<=0
            会导致内层 while 死循环挂死；tile_size <= 0 同理）。
    """
    if tile_size <= 0:
        raise ValueError(f"tile_size 必须 > 0，收到 {tile_size}")
    if not 0 <= overlap < tile_size:
        raise ValueError(
            f"overlap 必须满足 0 <= overlap < tile_size"
            f"（收到 overlap={overlap}, tile_size={tile_size}，"
            f"否则步长非正会死循环）"
        )
    step = tile_size - overlap
    tiles = []

    y = 0
    while y < img_h:
        y2 = min(y + tile_size, img_h)
        x = 0
        while x < img_w:
            x2 = min(x + tile_size, img_w)
            tiles.append((x, y, x2, y2))
            if x2 >= img_w:
                break
            x += step
        if y2 >= img_h:
            break
        y += step

    return tiles


def tile_infer(
    image: np.ndarray,
    engine,
    tile_size: int = 1024,
    overlap: int = 128,
    threshold: float = 0.5,
    merge_iou: float = 0.45,
) -> list:
    """对大图执行 sliding-window 分块推理。

    Args:
        image: 大图 numpy array (H, W, C)。
        engine: 有监督引擎实例（需已 load）。
        tile_size: 瓦片边长。
        overlap: 相邻瓦片重叠像素。
        threshold: 检测阈值。
        merge_iou: 跨瓦片 NMS 的 IoU 阈值（用于合并重叠区域的重复检测）。

    Returns:
        合并后的检测结果列表（坐标已映射回原图绝对坐标）。
    """
    if image is None or not hasattr(image, "shape"):
        return []

    h, w = image.shape[:2]

    # 小图直接推理
    if h <= tile_size and w <= tile_size:
        result = engine.infer(image, threshold=threshold)
        return [result] if result else []

    tiles = compute_tiles(h, w, tile_size, overlap)
    logger.info("大图 %dx%d 切分为 %d 个瓦片 (%dx%d + overlap %d)",
                w, h, len(tiles), tile_size, tile_size, overlap)

    all_results = []

    all_boxes, all_meta, _result_cls = _infer_all_tiles(
        image, tiles, engine, threshold
    )

    # 跨瓦片 NMS：消除重叠区域的重复检测框
    # O6（P1，2026-10-05 二轮审查）：按类别分组抑制——工业多类别缺陷常
    # 空间共现（裂纹旁伴生气孔），全局 IoU 抑制会误删低分类别的重叠框。
    if all_boxes and merge_iou > 0:
        all_boxes, keep_idx = _nms(
            all_boxes,
            [m["score"] for m in all_meta],
            merge_iou,
            labels=[m.get("label") for m in all_meta],
        )
        all_meta = [all_meta[i] for i in keep_idx]

    # 重建合并后的 DetectionResult 列表
    # M5（P1）：显式记录结果类型，不依赖 for 循环变量泄漏（此前 type(result)
    # 绑定的是最后一个成功瓦片的结果类型，行为碰巧正确但脆弱）
    if all_boxes:
        import numpy as _np
        task = all_meta[0]["task"] if all_meta else None
        merged = _result_cls(
            task=task,
            boxes=_np.array(all_boxes),
            scores=tuple(m["score"] for m in all_meta),
            labels=tuple(m["label"] for m in all_meta),
            extra={
                "tiles_total": len(tiles),
                "tiles_ok": len(all_meta),
                "merged": True,
            },
        )
        all_results.append(merged)

    return all_results


def _infer_all_tiles(image, tiles, engine, threshold):
    """逐瓦片推理并汇集（W24 规模拆分，自 tile_infer 抽出）。

    坐标映射回原图绝对坐标；单瓦片异常仅留痕继续（可观测性字段由
    调用方 tiles_total/tiles_ok 呈现）。返回 (all_boxes, all_meta,
    result_cls)——result_cls 为首个成功结果类型（M5：不依赖循环变量
    泄漏）。
    """
    import numpy as _np  # noqa: F401  拆分缝：_infer_all_tiles 内使用

    all_boxes = []
    all_meta = []
    result_cls = None

    for x1, y1, x2, y2 in tiles:
        tile = image[y1:y2, x1:x2]
        if tile.size == 0:
            continue
        try:
            result = engine.infer(tile, threshold=threshold)
            if result and result.boxes is not None:
                result_cls = type(result)
                boxes = _np.asarray(result.boxes).copy()
                if len(boxes) > 0:
                    # 将瓦片内坐标映射回原图绝对坐标
                    boxes[:, 0] += x1
                    boxes[:, 1] += y1
                    boxes[:, 2] += x1
                    boxes[:, 3] += y1
                    n = len(boxes)
                    scores = _np.asarray(result.scores) if result.scores else \
                             _np.full(n, result.score)
                    for i in range(n):
                        all_boxes.append(boxes[i])
                        all_meta.append({
                            "task": result.task,
                            "score": float(scores[i]) if i < len(scores) else result.score,
                            "label": result.labels[i] if i < len(result.labels) else "unknown",
                            "tile": (x1, y1, x2, y2),
                        })
        except Exception:
            logger.exception("瓦片推理失败 (%d,%d,%d,%d)", x1, y1, x2, y2)

    return all_boxes, all_meta, result_cls


def _nms(boxes: list, scores: list, iou_threshold: float = 0.45,
         labels: list | None = None):
    """非极大值抑制（NMS），返回保留的 boxes 和索引。

    O6（P1，2026-10-05 二轮审查）：``labels`` 提供时按类别分组抑制
    （class-aware NMS）——只在同类别框之间做 IoU 抑制，不同类别空间
    共现的框互不干扰；``labels`` 为 None 时退回全局抑制（旧行为，
    兼容既有调用方）。

    Args:
        boxes: [(x1, y1, x2, y2), ...] 列表或 numpy 数组。
        scores: 对应的置信度列表。
        iou_threshold: IoU 超过此阈值则抑制低分框。
        labels: 对应的类别标签列表（可选）。

    Returns:
        (kept_boxes, kept_indices)
    """
    if len(boxes) == 0:
        return [], []

    if labels is not None and len(labels) == len(boxes):
        # class-aware：分组索引 → 各组独立 NMS → 合并保持原始索引
        groups: dict = {}
        for idx, lbl in enumerate(labels):
            groups.setdefault(lbl, []).append(idx)
        keep: list[int] = []
        for group_idx in groups.values():
            g_boxes = [boxes[i] for i in group_idx]
            g_scores = [scores[i] for i in group_idx]
            _, g_keep = _nms_global(g_boxes, g_scores, iou_threshold)
            keep.extend(group_idx[i] for i in g_keep)
        keep.sort()
        return [boxes[i] for i in keep], keep
    return _nms_global(boxes, scores, iou_threshold)


def _nms_global(boxes: list, scores: list, iou_threshold: float = 0.45):
    """全局 NMS（同类内抑制，_nms 的原始实现）。"""
    import numpy as np

    if len(boxes) == 0:
        return [], []

    boxes_arr = np.asarray(boxes, dtype=np.float64)
    scores_arr = np.asarray(scores, dtype=np.float64)

    x1 = boxes_arr[:, 0]
    y1 = boxes_arr[:, 1]
    x2 = boxes_arr[:, 2]
    y2 = boxes_arr[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores_arr.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break

        # 计算当前最高分框与其余框的 IoU
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter_area = inter_w * inter_h

        union = areas[i] + areas[order[1:]] - inter_area
        iou = inter_area / np.maximum(union, 1e-8)

        # 保留 IoU 低于阈值的框
        remaining = np.where(iou <= iou_threshold)[0]
        order = order[remaining + 1]

    kept_boxes = [boxes[i] for i in keep]
    return kept_boxes, keep


def should_tile(image: np.ndarray, threshold_size: int = 2048) -> bool:
    """判断图像是否需要分块推理。

    Args:
        image: 图像数组。
        threshold_size: 超过此尺寸则启用 tiling。

    Returns:
        bool: 是否需要 tiling。
    """
    if image is None or not hasattr(image, "shape"):
        return False
    h, w = image.shape[:2]
    return h > threshold_size or w > threshold_size


def tile_infer_sv(
    image: np.ndarray,
    engine,
    slice_wh: int = 640,
    overlap_wh: int = 100,
    iou_threshold: float = 0.45,
    threshold: float = 0.5,
) -> list:
    """sv.InferenceSlicer 后端滑窗推理（W6-T1，对标 supervision 方法）。

    与 :func:`tile_infer` 同契约：小图直推；瓦片内坐标经 sv 合并
    （OverlapFilter.NON_MAX_SUPPRESSION）后映射回原图绝对坐标；
    返回含单个合并 DetectionResult 的列表（extra 记录 backend="sv"）。

    依赖 supervision（惰性导入）；切片回调复用 sv_bridge 桥接。
    """
    import numpy as np
    import supervision as sv

    from core.interfaces_supervised import TaskType
    from inference.sv_bridge import result_to_detections

    if image is None or not hasattr(image, "shape"):
        return []
    h, w = image.shape[:2]
    if h <= slice_wh and w <= slice_wh:
        result = engine.infer(image, threshold=threshold)
        return [result] if result else []

    holder = {"task": None}

    def _callback(slice_img):
        result = engine.infer(slice_img, threshold=threshold)
        det = result_to_detections(result)
        if len(det) and holder["task"] is None:
            holder["task"] = result.task
        return det

    slicer = sv.InferenceSlicer(
        callback=_callback,
        slice_wh=slice_wh,
        overlap_wh=overlap_wh,
        overlap_filter=sv.OverlapFilter.NON_MAX_SUPPRESSION,
        iou_threshold=iou_threshold,
    )
    merged = slicer(image)

    n = len(merged)
    if n == 0:
        return []
    from core.interfaces_supervised import DetectionResult

    names = merged.data.get("class_name")
    labels = tuple(
        str(names[i]) if names is not None and i < len(names) else "unknown"
        for i in range(n)
    )
    scores = (
        tuple(float(c) for c in merged.confidence)
        if merged.confidence is not None else None
    )
    return [
        DetectionResult(
            task=holder["task"] or TaskType.DET,
            boxes=np.asarray(merged.xyxy, dtype=np.float32),
            scores=scores,
            labels=labels,
            extra={
                "backend": "sv",
                "slice_wh": slice_wh,
                "overlap_wh": overlap_wh,
                "merged": True,
            },
        )
    ]


__all__ = [
    "tile_infer",
    "tile_infer_sv",
    "compute_tiles",
    "should_tile",
]
