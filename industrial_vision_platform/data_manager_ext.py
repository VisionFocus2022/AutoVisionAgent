"""DataManager 项目目录模型扩展（FR-E4，仅加方法不改既有签名）。

提供 DataManager 与 project/ 模块之间的桥接：
- 按项目目录扫描图像
- 统计标注文件
- recent 列表管理

用法::

    from industrial_vision_platform.data_manager_ext import DataManagerExt
    ext = DataManagerExt(data_manager, base_root="/path/to/projects")
    ext.import_to_project(project_dir, src_dir)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# 延迟导入：project 模块可能尚未完整实现
try:
    from project.models import ProjectId, ProjectLayout, parse_project_dirname
    from project.counter import TaskCounter
    from project.store import FileSystemProjectStore
    from project import recent as recent_mod
except ImportError:
    _logger.warning("project 模块不可用，DataManagerExt 功能将受限")
    ProjectId = str  # type: ignore[assignment,misc]
    ProjectLayout = dict  # type: ignore[assignment,misc]
    parse_project_dirname = None  # type: ignore[assignment]
    class TaskCounter:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): pass
        def next_id(self, task: str = "") -> int: return 0
    class FileSystemProjectStore:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): pass
    class recent_mod:  # type: ignore[no-redef]
        @staticmethod
        def add_recent(path: str) -> None: pass
        @staticmethod
        def load_recent() -> list: return []
        @staticmethod
        def save_recent(items: list) -> None: pass


from core.constants import IMG_EXTS as _IMG_EXTS


class DataManagerExt:
    """
    DataManager 项目管理扩展。

    将 DataManager 的数据导入/导出能力与 project/ 目录模型对接，
    提供项目级的数据操作和统计。
    """

    def __init__(
        self,
        data_manager,  # industrial_vision_platform.DataManager 实例
        base_root: str,
        counter: Optional[TaskCounter] = None,
    ) -> None:
        self._dm = data_manager
        self._base_root = base_root
        os.makedirs(base_root, exist_ok=True)
        self._store = FileSystemProjectStore(base_root)
        # 优先复用 store 内部的计数器，确保状态一致
        self._counter = counter or self._store._counter

    # ============================== 项目操作 ============================== #
    def create_project(
        self,
        name: str,
        task: str,
        label: str = "",
        tag: str = "",
    ) -> Tuple[str, ProjectLayout]:
        """
        创建规范项目目录。

        Args:
            name: 项目名称。
            task: 任务类型（det/seg/abdet/...）。
            label: 可选标签。
            tag: 可选标签。

        Returns:
            (dirname, layout)
        """
        from core.interfaces_supervised import TaskType
        task_type = TaskType(task) if isinstance(task, str) else task
        project_id, layout = self._store.create_project(name, task_type)
        # 补充写入可选的 label/tag 元数据
        if label or tag:
            meta_path = os.path.join(layout.root, "project_meta.json")
            meta: dict = {}
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
            if label:
                meta["label"] = label
            if tag:
                meta["tag"] = tag
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
        recent_mod.add_recent(self._base_root, project_id.to_dirname())
        return project_id.to_dirname(), layout

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目（含元数据）。"""
        projects = []
        for pid in self._store.list_projects():
            meta = self._store.load_meta(pid) or {}
            layout = self._store.get_layout(pid)
            projects.append({
                "dirname": pid.to_dirname(),
                "name": pid.name,
                "task": pid.task.value,
                "seq": pid.seq,
                "created": meta.get("created") or "",
                "label": meta.get("label", ""),
                "tag": meta.get("tag", ""),
                "path": layout.root,
            })
        return projects

    def recent_projects(self) -> List[str]:
        """获取最近项目列表。"""
        return recent_mod.recent_list(self._base_root)

    # ============================== 图像操作 ============================== #
    def import_to_project(
        self,
        project_dir: str,
        src_dir: str,
        class_name: str = "OK",
    ) -> Dict[str, Any]:
        """
        将外部图像导入项目的 images/ 目录。

        Args:
            project_dir: 项目根目录。
            src_dir: 源图像目录。
            class_name: 子类别目录名。

        Returns:
            dict: 导入统计。
        """
        images_dir = os.path.join(project_dir, "images", class_name)
        os.makedirs(images_dir, exist_ok=True)

        imported = 0
        failed = 0
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                if f.lower().endswith(_IMG_EXTS):
                    src = os.path.join(root, f)
                    dst = os.path.join(images_dir, f)
                    if not os.path.exists(dst):
                        try:
                            shutil.copy2(src, dst)
                            imported += 1
                        except OSError:
                            failed += 1
                    else:
                        imported += 1  # 已存在视为成功
        return {"imported": imported, "failed": failed}

    def get_project_stats(self, project_dir: str) -> Dict[str, Any]:
        """
        获取项目的数据统计。

        Returns:
            dict: {
                "total_images": int,
                "annotated": int,
                "classes": {name: count},
                "splits": {"train": int, "val": int, "test": int},
            }
        """
        images_dir = os.path.join(project_dir, "images")
        annotations_dir = os.path.join(project_dir, "annotations")

        # 总图像数
        total = 0
        classes: Dict[str, int] = {}
        if os.path.isdir(images_dir):
            for item in os.listdir(images_dir):
                item_path = os.path.join(images_dir, item)
                if os.path.isdir(item_path):
                    count = sum(
                        1 for f in os.listdir(item_path)
                        if f.lower().endswith(_IMG_EXTS)
                    )
                    classes[item] = count
                    total += count
                elif item.lower().endswith(_IMG_EXTS):
                    total += 1

        # 标注数
        annotated = 0
        if os.path.isdir(annotations_dir):
            annotated = sum(
                1 for f in os.listdir(annotations_dir)
                if f.endswith(".json")
            )

        # 划分统计
        splits: Dict[str, int] = {}
        for split in ("train", "val", "test"):
            split_dir = os.path.join(project_dir, split)
            if os.path.isdir(split_dir):
                count = sum(
                    1 for f in os.listdir(split_dir)
                    if f.lower().endswith(_IMG_EXTS)
                )
                splits[split] = count

        return {
            "total_images": total,
            "annotated": annotated,
            "classes": classes,
            "splits": splits,
        }

    def split_project_dataset(
        self,
        project_dir: str,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
    ) -> Dict[str, int]:
        """
        在项目目录下划分 train/val/test。

        Returns:
            dict: {"train": int, "val": int, "test": int}
        """
        if abs(train_ratio + val_ratio + test_ratio - 1.0) > 0.001:
            raise ValueError("ratios must sum to 1.0")

        import random
        images_dir = os.path.join(project_dir, "images")
        all_images: List[str] = []
        for root, _dirs, files in os.walk(images_dir):
            for f in files:
                if f.lower().endswith(_IMG_EXTS):
                    all_images.append(os.path.join(root, f))

        if not all_images:
            return {"train": 0, "val": 0, "test": 0}

        random.shuffle(all_images)
        n = len(all_images)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        splits = {
            "train": all_images[:n_train],
            "val": all_images[n_train:n_train + n_val],
            "test": all_images[n_train + n_val:],
        }

        for split_name, imgs in splits.items():
            split_dir = os.path.join(project_dir, split_name)
            os.makedirs(split_dir, exist_ok=True)
            for img in imgs:
                dst = os.path.join(split_dir, os.path.basename(img))
                if not os.path.exists(dst):
                    shutil.move(img, dst)

        return {k: len(v) for k, v in splits.items()}

    def delete_project(self, dirname: str) -> bool:
        """删除项目。"""
        pid = parse_project_dirname(dirname)
        if not pid:
            return False
        path = pid.to_path(self._base_root)
        if os.path.isdir(path):
            shutil.rmtree(path)
        recent_mod.remove_recent(self._base_root, dirname)
        return True

    def get_counters(self) -> Dict[str, int]:
        """获取当前计数器快照。"""
        return self._counter.snapshot_by_name()


__all__ = ["DataManagerExt"]
