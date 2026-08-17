"""标注批量处理工具（对标 SKolpha frontend.tools）。

5 个纯函数工具：
1. cut_labelme_json — 标注 JSON 切割（大图切小图时同步切割标注）
2. batch_replace_label — 批量替换标签名
3. label_data_statistics — 标注数据统计（各类别数量/分布）
4. batch_delete_labels — 批量删除标注
5. flip_image_annotation — 图像翻转（含标注坐标同步翻转）

所有函数纯 I/O，无 Qt 依赖，可独立测试。
所有 JSON 落盘均为原子写（同目录 tmp + os.replace）：写盘中途失败或进程
退出不会截断/损坏既有标注文件（P2-2）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from labeling.io_labelme import load_labelme


def _atomic_write_json(path: str, doc: Dict[str, Any]) -> None:
    """原子写 JSON：先写同目录临时文件，再 os.replace 替换目标。

    P2-2：直写是 truncate-then-write，写盘中途失败/进程退出会把目标
    JSON 截断且旧内容已丢。本函数保证任何一步失败都不触碰旧文件：

    - 临时文件与目标同目录（同盘，os.replace 原子性前提），名带 .tmp；
    - 写入参数与直写版一致（utf-8 / ensure_ascii=False / indent=2）；
    - 异常类型与直写版一致上抛（open OSError / dump 原样 / replace OSError），
      上抛前尽力清理残留临时文件。
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        dir=os.path.dirname(path) or ".",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            logger.warning("临时文件清理失败: %s", tmp_path, exc_info=True)
        raise


def cut_labelme_json(
    src_json: str,
    tile_w: int,
    tile_h: int,
    out_dir: str,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
) -> List[str]:
    """将大图的标注 JSON 按瓦片切割为多个小标注 JSON。

    对每个 (tile_w, tile_h) 瓦片，平移 shapes 的坐标到瓦片局部坐标系，
    并保留完全落在瓦片内或与瓦片相交的矩形标注（裁剪到边界）。

    Args:
        src_json: 源 LabelMe JSON 路径。
        tile_w, tile_h: 瓦片宽/高（像素）。
        out_dir: 输出目录。
        image_width, image_height: 图像尺寸（若 JSON 中未指定）。

    Returns:
        生成的 JSON 文件路径列表。
    """
    doc = load_labelme(src_json)
    w = image_width or doc.get("imageWidth", 0)
    h = image_height or doc.get("imageHeight", 0)
    if not w or not h:
        return []

    base_name = os.path.splitext(os.path.basename(src_json))[0]
    os.makedirs(out_dir, exist_ok=True)
    results: List[str] = []

    for ty in range(0, h, tile_h):
        for tx in range(0, w, tile_w):
            tile_shapes = []
            for s in doc.get("shapes", []):
                pts = s.get("points", [])
                if not pts:
                    continue
                # 平移坐标到瓦片局部系
                local_pts = [[p[0] - tx, p[1] - ty] for p in pts]
                # 矩形：检查是否与瓦片相交
                if s.get("shape_type") == "rectangle" and len(local_pts) >= 2:
                    x1, y1 = local_pts[0]
                    x2, y2 = local_pts[1]
                    # 裁剪到瓦片边界
                    cx1 = max(0, min(x1, x2))
                    cy1 = max(0, min(y1, y2))
                    cx2 = min(tile_w, max(x1, x2))
                    cy2 = min(tile_h, max(y1, y2))
                    if cx2 <= cx1 or cy2 <= cy1:
                        continue  # 不相交
                    local_pts = [[cx1, cy1], [cx2, cy2]]
                else:
                    # 多边形/点：检查质心是否在瓦片内
                    cx = sum(p[0] for p in local_pts) / len(local_pts)
                    cy = sum(p[1] for p in local_pts) / len(local_pts)
                    if not (0 <= cx < tile_w and 0 <= cy < tile_h):
                        continue

                new_shape = dict(s)
                new_shape["points"] = local_pts
                tile_shapes.append(new_shape)

            if not tile_shapes:
                continue

            tile_doc = {
                "version": doc.get("version", "5.4.3"),
                "flags": {},
                "shapes": tile_shapes,
                "imagePath": f"{base_name}_{tx}_{ty}.jpg",
                "imageData": None,
                "imageHeight": tile_h,
                "imageWidth": tile_w,
            }
            out_path = os.path.join(out_dir, f"{base_name}_{tx}_{ty}.json")
            _atomic_write_json(out_path, tile_doc)
            results.append(out_path)

    return results


def batch_replace_label(
    json_dir: str,
    old_label: str,
    new_label: str,
) -> int:
    """批量替换标注 JSON 中的标签名。

    Args:
        json_dir: 标注文件目录。
        old_label: 旧标签名。
        new_label: 新标签名。

    Returns:
        修改的文件数。
    """
    count = 0
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            logger.debug("跳过损坏标注文件: %s", path)
            continue
        changed = False
        for s in doc.get("shapes", []):
            if s.get("label") == old_label:
                s["label"] = new_label
                changed = True
        if changed:
            _atomic_write_json(path, doc)
            count += 1
    return count


def label_data_statistics(json_dir: str) -> Dict[str, int]:
    """统计标注数据中各类别的数量分布。

    Args:
        json_dir: 标注文件目录。

    Returns:
        {label_name: count} 字典，按数量降序。
    """
    stats: Dict[str, int] = {}
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            logger.debug("跳过损坏标注文件: %s", path)
            continue
        for s in doc.get("shapes", []):
            label = s.get("label", "unknown")
            stats[label] = stats.get(label, 0) + 1
    # 按数量降序排序
    return dict(sorted(stats.items(), key=lambda x: -x[1]))


def batch_delete_labels(
    json_dir: str,
    labels_to_delete: List[str],
) -> int:
    """批量删除指定标签名的标注。

    Args:
        json_dir: 标注文件目录。
        labels_to_delete: 要删除的标签名列表。

    Returns:
        修改的文件数。
    """
    delete_set = set(labels_to_delete)
    count = 0
    for f in os.listdir(json_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(json_dir, f)
        try:
            doc = load_labelme(path)
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            logger.debug("跳过损坏标注文件: %s", path)
            continue
        original_len = len(doc.get("shapes", []))
        doc["shapes"] = [
            s for s in doc.get("shapes", [])
            if s.get("label") not in delete_set
        ]
        if len(doc["shapes"]) != original_len:
            _atomic_write_json(path, doc)
            count += 1
    return count


def flip_image_annotation(
    json_path: str,
    image_width: int,
    mode: str = "horizontal",
) -> bool:
    """翻转标注坐标（配合图像翻转）。

    Args:
        json_path: LabelMe JSON 文件路径。
        image_width: 原图宽度（水平翻转用）。
        mode: "horizontal"（水平翻转）或 "vertical"（垂直翻转）。

    Returns:
        是否成功修改。
    """
    try:
        doc = load_labelme(json_path)
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        logger.debug("标注文件加载失败: %s", json_path)
        return False

    w = doc.get("imageWidth", image_width)
    h = doc.get("imageHeight", 0)

    for s in doc.get("shapes", []):
        pts = s.get("points", [])
        if mode == "horizontal":
            s["points"] = [[w - p[0], p[1]] for p in pts]
        elif mode == "vertical":
            s["points"] = [[p[0], h - p[1]] for p in pts]

    _atomic_write_json(json_path, doc)
    return True


__all__ = [
    "cut_labelme_json",
    "batch_replace_label",
    "label_data_statistics",
    "batch_delete_labels",
    "flip_image_annotation",
]
