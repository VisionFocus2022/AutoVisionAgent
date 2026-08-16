"""数据管理页重活 worker 函数（W3-T3，架构审查 P1-3）。

从 UI 线程移出的纯 IO 工作：导入复制、数据集划分、批量标注工具扫描。
全部为无 Qt 依赖的纯函数（可同步单测），由页面在 worker 线程调用。
"""
from __future__ import annotations

import json
import os
import random
import shutil
from typing import Dict, List, Tuple

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
) -> Tuple[int, int, int]:
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


def replace_labels(ann_dir: str, old: str, new: str) -> int:
    """批量替换标签名，返回修改文件数。"""
    from labeling.batch_tools import batch_replace_label

    return batch_replace_label(ann_dir, old, new)


def delete_labels(ann_dir: str, labels: List[str]) -> int:
    """批量删除指定标签的标注，返回修改文件数。"""
    from labeling.batch_tools import batch_delete_labels

    return batch_delete_labels(ann_dir, labels)


def label_statistics(ann_dir: str) -> Dict[str, int]:
    """标注数据统计（各类别数量分布）。"""
    from labeling.batch_tools import label_data_statistics

    return label_data_statistics(ann_dir)


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
            with open(path, "r", encoding="utf-8") as fh:
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


__all__ = [
    "import_images",
    "split_dataset",
    "replace_labels",
    "delete_labels",
    "label_statistics",
    "flip_annotations",
    "cut_annotations",
]
