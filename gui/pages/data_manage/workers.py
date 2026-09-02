"""数据管理页重活 worker 函数（W3-T3，架构审查 P1-3）。

从 UI 线程移出的纯 IO 工作：导入复制、数据集划分、批量标注工具扫描。
全部为无 Qt 依赖的纯函数（可同步单测），由页面在 worker 线程调用。
"""
from __future__ import annotations

import json
import os
import random
import shutil

from core.constants import IMG_EXTS


def import_images(src: str, dst_dir: str) -> int:
    """从 src 递归收集图像复制到 dst_dir（跳过同名），返回复制数。"""
    imported = 0
    for root, _dirs, files in os.walk(src):
        for f in files:
            if f.lower().endswith(IMG_EXTS):
                src_f = os.path.join(root, f)
                dst_f = os.path.join(dst_dir, f)
                if not os.path.exists(dst_f):
                    shutil.copy2(src_f, dst_f)
                    imported += 1
    return imported


def split_dataset(
    image_dir: str,
    r_train: float,
    r_val: float,
    r_test: float,
    mode: str,
) -> tuple[int, int, int]:
    """按比例把 image_dir 顶层图像划分到 train/val/test 子目录。

    mode: copy / move / symlink（失败回退复制）/ list（仅写文件列表）。
    返回 (n_train, n_val, n_test)。
    """
    images = [
        os.path.join(image_dir, f)
        for f in os.listdir(image_dir)
        if f.lower().endswith(IMG_EXTS)
    ]
    if not images:
        return (0, 0, 0)
    random.shuffle(images)
    n = len(images)
    n_train = int(n * r_train)
    n_val = int(n * r_val)
    splits = {
        "train": images[:n_train],
        "val": images[n_train : n_train + n_val],
        "test": images[n_train + n_val :],
    }
    for split, imgs in splits.items():
        split_dir = os.path.join(image_dir, split)
        os.makedirs(split_dir, exist_ok=True)
        for img in imgs:
            dst = os.path.join(split_dir, os.path.basename(img))
            if os.path.exists(dst):
                continue
            if mode == "copy":
                shutil.copy2(img, dst)
            elif mode == "move":
                shutil.move(img, dst)
            elif mode == "symlink":
                try:
                    os.symlink(os.path.abspath(img), dst)
                except (OSError, NotImplementedError):
                    shutil.copy2(img, dst)
            elif mode == "list":
                list_path = os.path.join(split_dir, "file_list.txt")
                with open(list_path, "a", encoding="utf-8") as fh:
                    fh.write(img + "\n")
    return (n_train, n_val, len(splits["test"]))


def collect_display_images(
    image_dir: str,
) -> tuple[list[str], dict[str, str], int]:
    """收集数据管理页展示用图像（W20-2：顶层=活动数据集语义）。

    返回 ``(paths, display_names, hidden_count)``：

    - 顶层有图：活动集 = 顶层图像；直接子目录（如划分出的 train/val/test
      副本）不进列表、只汇总 hidden_count——修复复制模式划分后根目录与
      子目录副本同屏重复（统计也随之翻倍）的"混乱"观感；
    - 顶层无图而直接子目录有图（移动模式划分后/外部预划分数据集）：
      按相对路径 ``子目录/文件名`` 分组展示，避免空屏且同名可区分。
    """
    top: list[str] = [
        os.path.join(image_dir, f)
        for f in os.listdir(image_dir)
        if f.lower().endswith(IMG_EXTS)
    ]
    if top:
        hidden = 0
        for sub in os.listdir(image_dir):
            sub_path = os.path.join(image_dir, sub)
            if os.path.isdir(sub_path):
                hidden += sum(
                    1
                    for f in os.listdir(sub_path)
                    if f.lower().endswith(IMG_EXTS)
                )
        return top, {p: os.path.basename(p) for p in top}, hidden
    grouped: list[str] = []
    names: dict[str, str] = {}
    for sub in sorted(os.listdir(image_dir)):
        sub_path = os.path.join(image_dir, sub)
        if not os.path.isdir(sub_path):
            continue
        for f in os.listdir(sub_path):
            if f.lower().endswith(IMG_EXTS):
                p = os.path.join(sub_path, f)
                grouped.append(p)
                names[p] = f"{sub}/{f}"
    return grouped, names, 0


def replace_labels(ann_dir: str, old: str, new: str) -> int:
    """批量替换标签名，返回修改文件数。"""
    from labeling.batch_tools import batch_replace_label

    return batch_replace_label(ann_dir, old, new)


def delete_labels(ann_dir: str, labels: list[str]) -> int:
    """批量删除指定标签的标注，返回修改文件数。"""
    from labeling.batch_tools import batch_delete_labels

    return batch_delete_labels(ann_dir, labels)


def label_statistics(ann_dir: str) -> dict[str, dict[str, float]]:
    """标注数据统计（各类别数量 + 尺寸分布：count/total_area/avg_area）。"""
    from labeling.batch_tools import label_data_statistics

    return label_data_statistics(ann_dir)


def count_annotated(images: list[str], ann_dir: str | None) -> int:
    """ANN-1: 按同名 .json 匹配统计已标注图像数。

    匹配优先级：图像同目录同名 .json > 集中标注目录同名 .json，
    兼容 LabelMe 同目录混放与 annotations/ 集中两种约定。
    """
    count = 0
    for img in images:
        stem = os.path.splitext(img)[0]
        if os.path.exists(stem + ".json") or ann_dir and os.path.exists(
            os.path.join(ann_dir, os.path.basename(stem) + ".json")
        ):
            count += 1
    return count


def flip_annotations(ann_dir: str, mode: str) -> int:
    """翻转标注坐标（从 JSON 读真实图像尺寸，缺尺寸跳过），返回成功数。"""
    from labeling.batch_tools import flip_image_annotation

    count = 0
    for f in os.listdir(ann_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(ann_dir, f)
        w = h = 0
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            w = doc.get("imageWidth", 0)
            h = doc.get("imageHeight", 0)
        except (OSError, json.JSONDecodeError):
            pass
        if w == 0 and mode == "horizontal":
            continue  # 缺少宽度信息时跳过水平翻转，避免坐标错误
        if h == 0 and mode == "vertical":
            continue  # 缺少高度信息时跳过垂直翻转
        if flip_image_annotation(path, w, mode):
            count += 1
    return count


def cut_annotations(ann_dir: str, tile_w: int, tile_h: int) -> int:
    """切割标注 JSON 到 tiles/ 子目录，返回生成瓦片数。"""
    from labeling.batch_tools import cut_labelme_json

    out_dir = os.path.join(ann_dir, "tiles")
    total = 0
    for f in os.listdir(ann_dir):
        if f.endswith(".json"):
            total += len(
                cut_labelme_json(os.path.join(ann_dir, f), tile_w, tile_h, out_dir)
            )
    return total


def crop_dataset(image_dir: str, tile_w: int, tile_h: int,
                 ann_dir: str | None = None) -> tuple[int, int]:
    """裁剪数据集（W60：图像+标注配对瓦片）。"""
    from labeling.batch_tools import crop_dataset as _crop

    return _crop(image_dir, tile_w=tile_w, tile_h=tile_h, ann_dir=ann_dir)


def rename_image_suffix(image_dir: str, old_ext: str, new_ext: str) -> int:
    """照片尾缀修改（W60）。"""
    from labeling.batch_tools import rename_image_suffix as _rename

    return _rename(image_dir, old_ext, new_ext)


def clean_dataset(image_dir: str, ann_dir: str | None = None,
                  quarantine: str | None = None) -> dict:
    """数据清洗（W60：坏图/孤立标注扫描与隔离）。"""
    from labeling.batch_tools import clean_dataset as _clean

    return _clean(image_dir, ann_dir=ann_dir, quarantine=quarantine)


__all__ = [
    "import_images",
    "clean_dataset",
    "crop_dataset",
    "rename_image_suffix",
    "split_dataset",
    "replace_labels",
    "delete_labels",
    "label_statistics",
    "flip_annotations",
    "cut_annotations",
]
