"""视觉数据集 + DataLoader 管线。

提供基于 torch.utils.data.Dataset 的实现，支持检测/分割/分类标注格式。
配合 DataLoader 实现多进程预取 + pin_memory，消除 CPU I/O 瓶颈。
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class VisionDataset:
    """视觉数据集（torch.utils.data.Dataset 兼容，但无硬 PyTorch 依赖）。

    支持 LabelMe 标注格式，按图像-标注对加载。
    """

    def __init__(
        self,
        image_dir: str,
        annotation_dir: str = "",
        img_exts: tuple = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"),
        transform: Callable | None = None,
        max_items: int = 0,
    ) -> None:
        self._image_dir = image_dir
        self._annotation_dir = annotation_dir or image_dir
        self._img_exts = img_exts
        self._transform = transform
        self._items: list[tuple[str, str]] = []
        self._scan(max_items)

    def _scan(self, max_items: int) -> None:
        """扫描目录，配对图像与标注文件。"""
        for f in sorted(os.listdir(self._image_dir)):
            if f.lower().endswith(self._img_exts):
                img_path = os.path.join(self._image_dir, f)
                stem = os.path.splitext(f)[0]
                ann_path = os.path.join(self._annotation_dir, f"{stem}.json")
                if not os.path.exists(ann_path):
                    ann_path = ""
                self._items.append((img_path, ann_path))
                if max_items and len(self._items) >= max_items:
                    break

        logger.info("VisionDataset: %d 个样本 (%s)", len(self._items), self._image_dir)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, idx: int) -> dict:
        """返回 (image, annotation) 字典。"""
        img_path, ann_path = self._items[idx]

        # 加载图像（W1: 中文路径安全；读失败显式报错，不让 None 静默流入训练数据）
        from core.image_io import imread_unicode
        image = imread_unicode(img_path)
        if image is None:
            raise ValueError(f"图像读取失败: {img_path}")
        try:
            import cv2
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        except ImportError:
            pass  # PIL 路径读出的已是 RGB

        # 加载标注
        # O1（P1，2026-10-05 二轮审查）：标注 JSON 损坏时此前仅 logger.exception
        # 后静默降级为空 boxes 的"无缺陷"负样本——缺陷检测中关键正样本标注
        # 损坏会被当成背景教坏模型。现改为：标注文件存在但解析失败 → 抛错
        # 让 DataLoader 跳过该样本（torch 原生 skip 机制）并在 warning 留痕，
        # 而非伪造空标注混入训练。
        annotation = {"boxes": [], "labels": [], "shapes": []}
        if ann_path and os.path.exists(ann_path):
            try:
                with open(ann_path, encoding="utf-8") as f:
                    ann = json.load(f)
                shapes = ann.get("shapes", [])
                for s in shapes:
                    if s.get("shape_type") == "rectangle" and len(s.get("points", [])) >= 2:
                        pts = s["points"]
                        annotation["boxes"].append([
                            pts[0][0], pts[0][1],
                            pts[1][0] if len(pts) > 1 else pts[0][0],
                            pts[1][1] if len(pts) > 1 else pts[0][1],
                        ])
                        annotation["labels"].append(s.get("label", "unknown"))
                        annotation["shapes"].append(s)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
                logger.warning(
                    "标注损坏，跳过该样本（不降级为空标注负样本）: %s", ann_path,
                    exc_info=True,
                )
                raise ValueError(
                    f"标注文件损坏（已跳过，请修复后重新训练）: {ann_path}"
                ) from None

        # 应用 transform
        if self._transform:
            image = self._transform(image)

        return {
            "image": image,
            "annotation": annotation,
            "path": img_path,
        }


# M1（2026-10-05 二轮审查）：_TorchVisionDataset 原是 create_dataloader
# 内的局部类——Windows spawn 模式下 num_workers>0 需 pickle dataset，
# 子进程反序列化局部类必崩（Can't pickle local object）。现延迟构建一次
# 并缓存到模块级 _TORCH_DATASET_CLS（进程内可 pickle；spawn 子进程首次
# import 本模块时会重新执行此构建，类身份在各进程内自洽）。
_TORCH_DATASET_CLS: type | None = None


def _get_torch_dataset_cls(dataset: VisionDataset) -> type:
    """构建（并缓存）torch Dataset 包装类（模块级，spawn 可 pickle）。"""
    global _TORCH_DATASET_CLS
    if _TORCH_DATASET_CLS is not None:
        return _TORCH_DATASET_CLS
    from torch.utils.data import Dataset as TorchDataset

    class TorchVisionDatasetWrapper(TorchDataset):
        """模块级包装类（M1：自 dataset/vision_dataset.py 可导入）。"""

        def __init__(self, ds):
            self._ds = ds

        def __len__(self):
            return len(self._ds)

        def __getitem__(self, idx):
            return self._ds[idx]

    _TORCH_DATASET_CLS = TorchVisionDatasetWrapper
    return _TORCH_DATASET_CLS


def create_dataloader(
    dataset: VisionDataset,
    batch_size: int = 8,
    num_workers: int = 4,
    shuffle: bool = True,
    pin_memory: bool = True,
) -> Any:
    """创建 DataLoader（延迟导入 torch，避免无 torch 环境报错）。

    消费 core/config.py 中 InferenceConfig 的 num_workers / batch_size。
    M1：包装类经 _get_torch_dataset_cls 模块级构建——Windows spawn 多
    worker 下可 pickle（此前局部类在子进程反序列化必崩）。
    """
    try:
        from torch.utils.data import DataLoader

        wrapper_cls = _get_torch_dataset_cls(dataset)
        return DataLoader(
            wrapper_cls(dataset),
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=num_workers,
            pin_memory=pin_memory,
            collate_fn=_collate_fn,
            # R4-15: 避免 epoch 切换重启 worker 进程
            persistent_workers=num_workers > 0,
            prefetch_factor=4 if num_workers > 0 else None,
        )
    except ImportError:
        logger.warning("PyTorch 不可用，返回简单批量迭代器")
        return _SimpleBatchIterator(dataset, batch_size, shuffle)


def _collate_fn(batch: list) -> dict:
    """自定义 collate：保持变长 boxes 列表。"""
    return {
        "images": [b["image"] for b in batch],
        "annotations": [b["annotation"] for b in batch],
        "paths": [b["path"] for b in batch],
    }


class _SimpleBatchIterator:
    """无 PyTorch 时的简单批量迭代器。"""

    def __init__(self, dataset: VisionDataset, batch_size: int, shuffle: bool) -> None:
        self._dataset = dataset
        self._batch_size = batch_size
        self._shuffle = shuffle

    def __iter__(self):
        import random
        indices = list(range(len(self._dataset)))
        if self._shuffle:
            random.shuffle(indices)
        for i in range(0, len(indices), self._batch_size):
            batch_idx = indices[i:i + self._batch_size]
            batch = [self._dataset[j] for j in batch_idx]
            yield _collate_fn(batch)

    def __len__(self) -> int:
        return (len(self._dataset) + self._batch_size - 1) // self._batch_size


__all__ = [
    "VisionDataset",
    "create_dataloader",
]
