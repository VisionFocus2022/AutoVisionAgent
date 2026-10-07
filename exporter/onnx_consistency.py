"""ONNX 导出一致性校验 + 模型卡随包（W2-1，roadmap Wave2 部署可信）。

导出的 ONNX 是否忠于原 pt？同图同阈双端推理（ultralytics YOLO 原生
支持 onnxruntime 后端加载——后处理同源，免手写 NMS），逐图贪心 IoU
框匹配，汇总匹配率；低于阈值=显式失败（部署红字，不静默）。模型卡
复用 W1-2 训练历史字段（classes/imgsz/metrics），与 onnx 同目录落盘。

纯后端模块（无 Qt 依赖）；predictor 可注入（测试缝）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MIN_MATCH_RATE = 0.95
_IOU_MATCH_T = 0.5
_SAMPLE_LIMIT = 6


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def compare_boxes(ref: list, cand: list, iou_t: float = _IOU_MATCH_T) -> float:
    """cand 框集对 ref 的贪心匹配率（每 ref 框至多配一 cand）。

    空对空=1.0（双端同无检出的一致）；ref 空 cand 非空=0.0（幻觉框）。
    """
    if not ref:
        return 1.0 if not cand else 0.0
    used = set()
    matched = 0
    for r in ref:
        best_j, best_v = -1, iou_t
        for j, c in enumerate(cand):
            if j in used:
                continue
            v = _iou(r, c)
            if v >= best_v:
                best_v, best_j = v, j
        if best_j >= 0:
            used.add(best_j)
            matched += 1
    return matched / len(ref)


def _default_predictor(weights: str, threshold: float) -> Callable:
    from ultralytics import YOLO

    model = YOLO(weights)

    def _predict(image_path: str) -> list:
        r = model.predict(image_path, conf=threshold, verbose=False,
                          device="cpu")[0]
        return [tuple(float(v) for v in b.xyxy[0]) for b in r.boxes]

    return _predict


def sample_images_from_history(pt_path: str, limit: int = _SAMPLE_LIMIT):
    """训练历史记录的 data_yaml → 图像目录采样；无记录→None。"""
    from core.train_history import read_records

    pt_abs = os.path.abspath(pt_path)
    for rec in read_records():
        if os.path.abspath(str(rec.get("weights_path", "") or "")) == pt_abs:
            yaml_p = str(rec.get("data_yaml", "") or "")
            if yaml_p and os.path.isfile(yaml_p):
                img_dir = os.path.join(
                    os.path.dirname(os.path.abspath(yaml_p)),
                    "images", "train",
                )
                if os.path.isdir(img_dir):
                    files = sorted(
                        f for f in os.listdir(img_dir)
                        if f.lower().endswith((".png", ".jpg", ".bmp"))
                    )[:limit]
                    return [os.path.join(img_dir, f) for f in files]
    return None


def onnx_consistency_check(
    pt_path: str,
    onnx_path: str,
    images: list[str] | None = None,
    threshold: float = 0.5,
    min_match: float = MIN_MATCH_RATE,
    predictor: Callable[[str, float], Callable] | None = None,
) -> dict[str, Any]:
    """pt vs onnx 同图推理一致性（W2-1 FR-1）。

    Returns: {ok, match_rate, n_images, detail}——任何故障转显式失败
    dict（ok=False + error 字段），绝不静默、不向调用方抛出。
    """
    try:
        if not os.path.isfile(pt_path):
            return _fail(f"pt 权重不存在: {pt_path}")
        if not os.path.isfile(onnx_path):
            return _fail(f"onnx 不存在: {onnx_path}")
        imgs = images or sample_images_from_history(pt_path)
        synthetic = False
        if not imgs:
            synthetic = True
            imgs = [_synthetic_image()]
        make = predictor or _default_predictor
        pred_pt = make(pt_path, threshold)
        pred_onnx = make(onnx_path, threshold)
        rates = []
        for img in imgs:
            rates.append(compare_boxes(pred_pt(img), pred_onnx(img)))
        rate = sum(rates) / len(rates) if rates else 1.0
        detail = f"n={len(imgs)}" + ("（合成图，无历史数据集）" if synthetic else "")
        logger.info("ONNX 一致性校验: rate=%.3f %s (pt=%s onnx=%s)",
                    rate, detail, pt_path, onnx_path)
        return {"ok": rate >= min_match, "match_rate": round(rate, 4),
                "n_images": len(imgs), "detail": detail}
    except Exception as exc:  # noqa: BLE001  # 校验件：故障显式回传不炸导出链
        logger.exception("ONNX 一致性校验异常")
        return _fail(str(exc))


def safe_load_model(model_path: str):
    """torch 安全加载（W2-1 真缺陷修复：ultralytics 权重兼容）。

    torch≥2.6 ``weights_only=True`` 默认拒绝 ultralytics 检查点
    （DetectionModel 不在 safe globals——发布页此前对真训练权重导出
    直接失败）。失败时按检查点实际引用**逐个放行**（解析报错中的
    GLOBAL 名→import→add_safe_globals→重载，收敛循环）：本仓库自训
    权重引用面 = ultralytics.nn.* / torch.nn 容器 / builtins 容器，
    全是库自有类而非任意可调用——安全姿态仍是"白名单反序列化"，
    非 weights_only=False。
    """
    import importlib
    import re

    import torch

    for _attempt in range(64):
        try:
            obj = torch.load(model_path, map_location="cpu", weights_only=True)
            # ultralytics 检查点为 dict（model/ema/...）；EMA 优先于裸 model
            if isinstance(obj, dict):
                obj = obj.get("ema") or obj.get("model") or obj
            if hasattr(obj, "float") and hasattr(obj, "eval"):
                # AMP 训练权重是 Half——ONNX fp32 导出链需 FP32（W2-1 真缺陷
                # 二号：默认 AMP 训出的模型此前导出必炸类型不匹配）
                obj = obj.float()
            return obj
        except Exception as exc:  # noqa: BLE001  # 每轮解析一个缺失全局
            m = re.search(r"Unsupported global: GLOBAL ([\w.]+)", str(exc))
            if not m:
                raise
            mod_name, _, attr = m.group(1).rpartition(".")
            try:
                mod = importlib.import_module(mod_name)
                torch.serialization.add_safe_globals([getattr(mod, attr)])
            except (ImportError, AttributeError) as imp_err:
                raise exc from imp_err
    raise RuntimeError(
        f"safe_load_model 全局放行收敛失败（64 轮）: {model_path}"
    )


def _fail(error: str) -> dict[str, Any]:
    return {"ok": False, "match_rate": None, "n_images": 0, "error": error}


def _synthetic_image() -> str:
    import tempfile

    import cv2
    import numpy as np

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cv2.imwrite(path, np.full((480, 640, 3), 128, np.uint8))
    return path


def write_model_card(pt_path: str, onnx_path: str, task: str) -> str:
    """模型卡 JSON 随包（W2-1 FR-2）——历史记录字段优先，缺省降级最小卡。

    Returns: 卡片路径（<onnx 同目录>/<onnx stem>_model_card.json）。
    """
    from core.train_history import read_records

    card: dict[str, Any] = {
        "task": task,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pt_path": os.path.abspath(pt_path),
        "onnx_path": os.path.abspath(onnx_path),
    }
    pt_abs = os.path.abspath(pt_path)
    for rec in read_records():
        if os.path.abspath(str(rec.get("weights_path", "") or "")) == pt_abs:
            for k in ("backbone", "imgsz", "classes", "best_metric",
                      "metrics", "epochs_completed", "epochs_requested", "ts"):
                if rec.get(k) not in (None, ""):
                    card[f"train_{k}"] = rec[k]
            card["train_ts"] = rec.get("ts")
            break
    card_path = os.path.splitext(onnx_path)[0] + "_model_card.json"
    with open(card_path, "w", encoding="utf-8") as fh:
        json.dump(card, fh, ensure_ascii=False, indent=2)
    logger.info("模型卡已随包: %s", card_path)
    return card_path


__all__ = [
    "MIN_MATCH_RATE", "compare_boxes", "onnx_consistency_check",
    "sample_images_from_history", "write_model_card", "safe_load_model",
]
