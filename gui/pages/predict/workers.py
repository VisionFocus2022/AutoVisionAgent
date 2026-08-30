"""推理页批量/序列化工作函数（W27 自 page.py 抽出，仿 data_manage/workers.py）。

纯函数层：无 Qt 依赖（tr 来自 gui.core.i18n 纯 python 模块），可同步单测。
W28 阈值接入与 W33 批量产物扩展（masks/overlay）落点在本模块。
"""
from __future__ import annotations

import os
import time

from core.constants import IMG_EXTS
from gui.core.i18n import tr
from labeling.batch_tools import (
    atomic_write_json as atomic_write_json,  # W39·v6 P2-8：原子写单源（显式再导出，batch_runner/tests 自本模块导入）
)
from project.paths import resolve_base_root

# R5-2: CSV/Excel 公式注入防护（CWE-1236）
_CSV_INJECTION_CHARS = frozenset("=+-\t\r@")


def sanitize_csv_cell(value: object) -> object:
    """对以危险字符开头的字符串加单引号前缀，防止公式注入。"""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


def boxes_to_jsonable(boxes) -> list | None:
    """numpy (N,4) 框数组 → 纯 Python 嵌套 list（JSON 可序列化）。

    真引擎 boxes 是 ndarray：不得做真值判断（歧义异常），且 list(ndarray)
    仍是 ndarray 行数组、json.dump 必炸——统一经 tolist 转纯 list。
    """
    if boxes is None:
        return None
    if hasattr(boxes, "tolist"):
        return boxes.tolist()
    return [list(b) for b in boxes]


def collect_images(directory: str) -> list[str]:
    """递归收集目录内全部图像路径（保持 os.walk 原序——与抽取前一致，
    数据管理页另有自然排序需求，此处不动序）。"""
    images: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(IMG_EXTS):
                images.append(os.path.join(root, f))
    return images


def batch_save_dir(project_dir: str | None, scanned_dir: str) -> str:
    """批量推理结果目录：{项目根 or workspace 根}/results/batchPredict_{ts}。

    W28 落盘卫生：无项目时回退 workspace 根（resolve_base_root 单源），
    绝不写进被扫描数据集目录本身（污染源数据）。scanned_dir 参数保留
    仅为调用方签名兼容。
    """
    ts = int(time.time())
    root = project_dir or resolve_base_root()
    return os.path.join(root, "results", f"batchPredict_{ts}")


def result_to_record(img_path: str, result) -> dict:
    """DetectionResult → 批量结果缓存记录（JSON 可序列化）。"""
    return {
        "file": os.path.basename(img_path),
        "path": img_path,
        "task": result.task.value,
        "score": result.score,
        "boxes": boxes_to_jsonable(result.boxes),
        "labels": list(result.labels) if result.labels else None,
    }


def row_display_fields(result) -> tuple:
    """结果表行显示三字段 (labels, score, info)。"""
    labels = ", ".join(result.labels) if result.labels else ""
    score = float(result.score or 0.0)
    n = len(result.boxes) if result.boxes is not None else 0
    info = f"{n} {tr('框')}" if n else ""
    return labels, score, info


# ============================== W33：过滤与产物 ============================== #


def filter_result_by_labels(result, allowed_labels):
    """对象类型过滤（W33）：boxes/labels/scores/masks 协同保留。

    allowed_labels 为 None/空集 → 原样返回（SKolpha「阈值+对象类型」
    双参对标的收尾——阈值 W28 已接）。
    """
    if not allowed_labels:
        return result
    keep = [i for i, lab in enumerate(result.labels or ()) if lab in allowed_labels]
    from core.interfaces_supervised import DetectionResult

    return DetectionResult(
        task=result.task,
        boxes=tuple(result.boxes[i] for i in keep) if result.boxes else (),
        labels=tuple(result.labels[i] for i in keep),
        scores=tuple(result.scores[i] for i in keep) if result.scores else (),
        masks=result.masks[keep] if result.masks is not None else None,
        score=result.score,
    )


def save_batch_artifacts(save_dir: str, img_path: str, result, overlay=None) -> None:
    """批量产物补齐（W33）：masks RLE 持久化 + 调用方渲染好的叠加图。

    - result.masks 非 None 且非空 → masks_{stem}.npz（逐实例 RLE，可经
      core.mask_codec.decode_mask_rle 恢复——现状批量 seg masks 丢失）；
    - overlay（BGR ndarray）非 None → overlay_{stem}.jpg；
    - 失败只记 WARNING 不炸整批（产物是增益件，批结果 JSON 仍原子落盘）。
    """
    try:
        stem = os.path.splitext(os.path.basename(img_path))[0]
        if getattr(result, "masks", None) is not None and len(result.masks):
            import numpy as np

            from core.mask_codec import encode_mask_rle

            rle = {
                f"mask_{i}": np.frombuffer(
                    encode_mask_rle(m), dtype=np.uint8
                )
                for i, m in enumerate(result.masks)
            }
            os.makedirs(save_dir, exist_ok=True)
            np.savez_compressed(os.path.join(save_dir, f"masks_{stem}.npz"), **rle)
        if overlay is not None:
            from core.image_io import imwrite_unicode

            os.makedirs(save_dir, exist_ok=True)
            imwrite_unicode(
                os.path.join(save_dir, f"overlay_{stem}"), overlay, ext=".jpg"
            )
    except (OSError, ValueError, RuntimeError):
        import logging

        logging.getLogger(__name__).warning(
            "批量产物写盘失败（跳过，批结果 JSON 不受影响）: %s",
            img_path, exc_info=True,
        )
