"""推理页批量/序列化工作函数（W27 自 page.py 抽出，仿 data_manage/workers.py）。

纯函数层：无 Qt 依赖（tr 来自 gui.core.i18n 纯 python 模块），可同步单测。
W28 阈值接入与 W33 批量产物扩展（masks/overlay）落点在本模块。
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from core.constants import IMG_EXTS
from gui.core.i18n import tr
from project.paths import resolve_base_root

# R5-2: CSV/Excel 公式注入防护（CWE-1236）
_CSV_INJECTION_CHARS = frozenset("=+-\t\r@")


def sanitize_csv_cell(value: object) -> object:
    """对以危险字符开头的字符串加单引号前缀，防止公式注入。"""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


def boxes_to_jsonable(boxes) -> Optional[list]:
    """numpy (N,4) 框数组 → 纯 Python 嵌套 list（JSON 可序列化）。

    真引擎 boxes 是 ndarray：不得做真值判断（歧义异常），且 list(ndarray)
    仍是 ndarray 行数组、json.dump 必炸——统一经 tolist 转纯 list。
    """
    if boxes is None:
        return None
    if hasattr(boxes, "tolist"):
        return boxes.tolist()
    return [list(b) for b in boxes]


def collect_images(directory: str) -> List[str]:
    """递归收集目录内全部图像路径（保持 os.walk 原序——与抽取前一致，
    数据管理页另有自然排序需求，此处不动序）。"""
    images: List[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(IMG_EXTS):
                images.append(os.path.join(root, f))
    return images


def batch_save_dir(project_dir: Optional[str], scanned_dir: str) -> str:
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


def atomic_write_json(path: str, data: object) -> None:
    """temp + os.replace 原子写 JSON（P2-2：直写会在中途截断既有文件）。

    失败时清理 .tmp 残留后上抛——由调用方的 on_error 兜底回 UI
    （W17 v3 P2-1 附带：写盘段纳入异常路由）。
    """
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
