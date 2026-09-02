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

import json
import logging
import os
import tempfile
from typing import Any

from labeling.io_labelme import load_labelme

logger = logging.getLogger(__name__)


def atomic_write_json(path: str, doc: dict[str, Any]) -> None:
    """原子写 JSON：先写同目录临时文件，再 os.replace 替换目标。

    P2-2：直写是 truncate-then-write，写盘中途失败/进程退出会把目标
    JSON 截断且旧内容已丢。本函数保证任何一步失败都不触碰旧文件：

    - 临时文件与目标同目录（同盘，os.replace 原子性前提），mkstemp
      随机名（并发写同一目标不互踩——W39·v6 P2-8：升为全仓单源，
      gui 两处固定 .tmp 名的弱版已删，此处为唯一实现）；
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
    image_width: int | None = None,
    image_height: int | None = None,
) -> list[str]:
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
    results: list[str] = []

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
            atomic_write_json(out_path, tile_doc)
            results.append(out_path)

    return results


def _backup_file(path: str) -> bool:
    """改写前备份原文件为 <name>.json.bak（W58-B：防误操作回滚通道）。

    直写（非原子）——.bak 是尽力而为的回滚件：写失败/中断时主文件
    未动（备份在改写**之前**发生），且不与主写的 os.replace 纪律
    互踩（atomic 测试按主写计数）。失败 → False，调用方跳过该文件
    改写——宁可不动，不无备份地改。
    """
    try:
        with open(path, "rb") as src:
            payload = src.read()
        with open(path + ".bak", "wb") as dst:
            dst.write(payload)
        return True
    except OSError:
        logger.warning("标注备份失败（跳过该文件改写）: %s", path, exc_info=True)
        return False


def batch_replace_label(
    json_dir: str,
    old_label: str,
    new_label: str,
    backup: bool = True,
) -> int:
    """批量替换标注 JSON 中的标签名。

    Args:
        json_dir: 标注文件目录。
        old_label: 旧标签名。
        new_label: 新标签名。
        backup: 改写前生成 .bak 备份（默认开；备份失败该文件跳过）。

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
            if backup and not _backup_file(path):
                continue
            atomic_write_json(path, doc)
            count += 1
    return count


def label_data_statistics(json_dir: str) -> dict[str, dict[str, float]]:
    """统计标注数据：各类别数量与尺寸分布（W58-B：count/total_area/avg_area）。

    面积口径：rectangle=宽×高；其余形态（polygon/linestrip）按鞋带公式
    （linestrip 面积仅供参考）。按数量降序。
    """
    from labeling.geometry import polygon_area

    stats: dict[str, dict[str, float]] = {}
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
            entry = stats.setdefault(label, {"count": 0, "total_area": 0.0})
            # 复核 MEDIUM 修正：坏 points 不得击穿整次统计（一坏文件不
            # 连坐）——转换与计算同入 try，失败按面积 0 计数
            try:
                pts = [
                    (float(p[0]), float(p[1]))
                    for p in (s.get("points") or [])
                ]
                if s.get("shape_type") == "rectangle" and len(pts) >= 2:
                    (x1, y1), (x2, y2) = pts[0], pts[1]
                    area: float = abs(x2 - x1) * abs(y2 - y1)
                else:
                    area = polygon_area(pts)
            except (TypeError, ValueError, IndexError):
                area = 0.0
            entry["count"] += 1
            entry["total_area"] += float(area)
    for entry in stats.values():
        entry["avg_area"] = (
            entry["total_area"] / entry["count"] if entry["count"] else 0.0
        )
    return dict(sorted(stats.items(), key=lambda kv: -kv[1]["count"]))


def batch_delete_labels(
    json_dir: str,
    labels_to_delete: list[str],
    backup: bool = True,
) -> int:
    """批量删除指定标签名的标注。

    Args:
        json_dir: 标注文件目录。
        labels_to_delete: 要删除的标签名列表。
        backup: 改写前生成 .bak 备份（默认开；备份失败该文件跳过）。

    Returns:
        修改的文件数。删除致 shapes=[] 的文件另发 WARNING（可追溯）。
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
            if backup and not _backup_file(path):
                continue
            atomic_write_json(path, doc)
            if not doc["shapes"]:
                logger.warning("删除后标注文件 shapes 为空: %s", path)
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

    atomic_write_json(json_path, doc)
    return True




# ============================== W60：S_Tools 次批（FR-008） ============================== #


def crop_dataset(
    image_dir: str,
    tile_w: int = 640,
    tile_h: int = 640,
    ann_dir: str | None = None,
) -> tuple[int, int]:
    """裁剪数据集：图像+标注配对瓦片切割（W60——补 cut_annotations 缺失的图像侧）。

    输出 {image_dir}/tiles/{stem}_{tx}_{ty}.jpg + 同名 .json（json 仅含
    与瓦片相交的 shape，cut_labelme_json 语义）。json 配对查找：图像同
    目录 > 集中标注目录；无标注图像也切（纯数据集裁剪）。

    Returns:
        (图像瓦片数, 标注瓦片数)。
    """
    from core.constants import IMG_EXTS
    from core.image_io import imread_unicode, imwrite_unicode

    out_dir = os.path.join(image_dir, "tiles")
    os.makedirs(out_dir, exist_ok=True)
    img_tiles = json_tiles = 0
    for f in sorted(os.listdir(image_dir)):
        if not f.lower().endswith(IMG_EXTS):
            continue
        stem, _ = os.path.splitext(f)
        json_path = None
        same_dir = os.path.join(image_dir, stem + ".json")
        if os.path.exists(same_dir):
            json_path = same_dir
        elif ann_dir:
            central = os.path.join(ann_dir, stem + ".json")
            if os.path.exists(central):
                json_path = central
        img = imread_unicode(os.path.join(image_dir, f))
        if img is None:
            logger.warning("图像读取失败（跳过切割）: %s", f)
            continue
        if json_path:
            try:
                json_tiles += len(
                    cut_labelme_json(json_path, tile_w, tile_h, out_dir)
                )
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                logger.warning("标注切割失败（跳过）: %s", json_path)
        h, w = img.shape[:2]
        for ty in range(0, h, tile_h):
            for tx in range(0, w, tile_w):
                tile = img[ty:ty + tile_h, tx:tx + tile_w]
                if tile.size == 0:
                    continue
                if imwrite_unicode(
                    os.path.join(out_dir, f"{stem}_{tx}_{ty}"), tile,
                    ext=".jpg",
                ):
                    img_tiles += 1
    return img_tiles, json_tiles


def rename_image_suffix(image_dir: str, old_ext: str, new_ext: str) -> int:
    """照片尾缀修改：批量改图像扩展名（同名 .json 标注不受影响）。

    大小写不敏感匹配旧后缀；目标名已存在时跳过（不覆盖）。
    """
    old_ext = old_ext.strip()
    new_ext = new_ext.strip()
    old_ext = old_ext if old_ext.startswith(".") else "." + old_ext
    new_ext = new_ext if new_ext.startswith(".") else "." + new_ext
    if old_ext == new_ext:
        return 0  # 完全相同才拒绝——.JPG→.jpg 大小写归一是正当用例
    count = 0
    for f in sorted(os.listdir(image_dir)):
        name, ext = os.path.splitext(f)
        if ext.lower() != old_ext.lower():
            continue
        target = os.path.join(image_dir, name + new_ext)
        # Windows 大小写不敏感盘上 .JPG→.jpg 是同文件改大小写——
        # 豁免自身冲突，仅真异名冲突才跳过
        same_file = (name + new_ext).lower() == f.lower()
        if not same_file and os.path.exists(target):
            logger.warning("目标已存在（跳过重命名）: %s", target)
            continue
        try:
            os.replace(os.path.join(image_dir, f), target)
            count += 1
        except OSError:
            logger.warning("重命名失败（跳过）: %s", f, exc_info=True)
    return count


def clean_dataset(
    image_dir: str,
    ann_dir: str | None = None,
    quarantine: str | None = None,
) -> dict:
    """数据清洗：坏图（零字节/不可解码）与孤立标注扫描。

    Args:
        image_dir: 图像目录。
        ann_dir: 集中标注目录（None=只扫图像目录内同放 json 的孤立态）。
        quarantine: 隔离子目录名（None=仅报告不动文件；给名则把坏件移入
            {image_dir}/{quarantine}/——可逆隔离，不做硬删除）。

    Returns:
        {"corrupt": n, "orphan_json": n, "moved": n}。
    """
    from core.constants import IMG_EXTS
    from core.image_io import imread_unicode

    report = {"corrupt": 0, "orphan_json": 0, "moved": 0}
    bad_files: list[str] = []
    for f in sorted(os.listdir(image_dir)):
        p = os.path.join(image_dir, f)
        if not os.path.isfile(p) or not f.lower().endswith(IMG_EXTS):
            continue
        bad = os.path.getsize(p) == 0
        if not bad:
            try:
                bad = imread_unicode(p) is None
            except (OSError, ValueError):
                bad = True
        if bad:
            report["corrupt"] += 1
            bad_files.append(p)

    orphan_files: list[str] = []
    img_stems = {
        os.path.splitext(f)[0] for f in os.listdir(image_dir)
        if f.lower().endswith(IMG_EXTS)
    }
    scan_dirs = [image_dir]
    if ann_dir and os.path.isdir(ann_dir):
        scan_dirs.append(ann_dir)
    for d in scan_dirs:
        for f in sorted(os.listdir(d)):
            if not f.endswith(".json"):
                continue
            if os.path.splitext(f)[0] in img_stems:
                continue
            report["orphan_json"] += 1
            orphan_files.append(os.path.join(d, f))

    if quarantine:
        qdir = os.path.join(image_dir, quarantine)
        os.makedirs(qdir, exist_ok=True)
        for p in bad_files + orphan_files:
            try:
                os.replace(p, os.path.join(qdir, os.path.basename(p)))
                report["moved"] += 1
            except OSError:
                logger.warning("隔离移动失败（跳过）: %s", p, exc_info=True)
    return report


__all__ = [
    "cut_labelme_json",
    "crop_dataset",
    "clean_dataset",
    "batch_replace_label",
    "label_data_statistics",
    "batch_delete_labels",
    "flip_image_annotation",
    "rename_image_suffix",
]
