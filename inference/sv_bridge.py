"""DetectionResult ↔ supervision 桥接与推理结果渲染（W5-T1）。

依据 supervision 方法（sv.Detections 统一结构 + 标注器组合）：
- ``result_to_detections``：本项目 DetectionResult → sv.Detections
  （class_id 按类别名稳定排序映射，类别名挂 data["class_name"] 供标签渲染）。
- ``render_result``：类别配色框 + 类别/置信度标签 + 实例掩码叠加 +
  语义图（无框 2D 掩码）半透明叠加 + 关键点。BGR 输入/输出（cv2 契约）。

无 Qt 依赖，predict 页把 ndarray 转 QImage 显示。
"""
from __future__ import annotations

from typing import Any

import numpy as np


def result_to_detections(result: Any) -> Any:
    """DetectionResult → sv.Detections（缺 sv 时抛 ImportError，由调用方降级）。"""
    import supervision as sv

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        xyxy = np.zeros((0, 4), dtype=np.float32)
    else:
        xyxy = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)

    scores = getattr(result, "scores", None)
    confidence = (
        np.asarray(scores, dtype=np.float32) if scores is not None else None
    )

    labels = [str(x) for x in (getattr(result, "labels", None) or ())]
    class_names = sorted(set(labels))
    class_id = (
        np.array([class_names.index(x) for x in labels], dtype=np.int64)
        if labels else None
    )

    # 掩码：仅当实例掩码数与框数一致时挂载（sv 长度校验约束）；
    # 2D 语义图不在此挂（render_result 单独叠加）
    mask = None
    masks = getattr(result, "masks", None)
    if masks is not None and xyxy.shape[0] > 0:
        m = np.asarray(masks)
        if m.ndim == 3 and m.shape[0] == xyxy.shape[0]:
            mask = m.astype(bool)

    det = sv.Detections(
        xyxy=xyxy, confidence=confidence, class_id=class_id, mask=mask
    )
    if labels:
        det.data["class_name"] = np.array(labels)
    return det


def render_result(
    image_bgr: np.ndarray,
    result: Any,
    thickness: int = 2,
    text_scale: float = 0.5,
) -> np.ndarray:
    """在图像副本上渲染检测结果，返回标注后的 BGR ndarray。"""
    import cv2
    import supervision as sv

    det = result_to_detections(result)
    scene = image_bgr.copy()

    # 语义图（无框或未挂载的 2D 掩码）→ 半透明叠加
    masks = getattr(result, "masks", None)
    if det.mask is None and masks is not None:
        m = np.asarray(masks)
        if m.ndim == 2 and m.any():
            overlay = scene.copy()
            overlay[m > 0] = (80, 220, 100)  # BGR 绿
            scene = cv2.addWeighted(overlay, 0.45, scene, 0.55, 0)

    if len(det) > 0:
        box_ann = sv.BoxAnnotator(
            thickness=thickness,
            color=sv.ColorPalette.DEFAULT,
            color_lookup=sv.ColorLookup.CLASS,
        )
        scene = box_ann.annotate(scene=scene, detections=det)

        names = det.data.get("class_name")
        texts = []
        for i in range(len(det)):
            name = str(names[i]) if names is not None and i < len(names) else "defect"
            conf = det.confidence[i] if det.confidence is not None else None
            texts.append(f"{name} {conf:.0%}" if conf is not None else name)
        label_ann = sv.LabelAnnotator(
            text_scale=text_scale, text_thickness=1
        )
        scene = label_ann.annotate(scene=scene, detections=det, labels=texts)

    if det.mask is not None:
        mask_ann = sv.MaskAnnotator(
            color=sv.ColorPalette.DEFAULT,
            color_lookup=sv.ColorLookup.CLASS,
            opacity=0.4,
        )
        scene = mask_ann.annotate(scene=scene, detections=det)

    # 关键点（pose）：金色实心圆
    kps = getattr(result, "keypoints", None)
    if kps is not None:
        for pt in np.asarray(kps, dtype=np.float32).reshape(-1, 2):
            cv2.circle(scene, (int(pt[0]), int(pt[1])), 3, (255, 214, 10), -1)

    return scene


__all__ = ["render_result", "result_to_detections"]
