"""项目 ID / 目录模型。

对标 SKolpha config_manager.py 的项目管理机制：
- 每个项目目录名格式：{task}_{seq}_{name}
- 每个项目有规范化子目录：images/ annotations/ models/ configs/ results/
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from core.interfaces_supervised import TaskType


# 项目子目录名称
SUBDIRS = ("images", "annotations", "models", "configs", "results")


@dataclass(frozen=True)
class ProjectId:
    """项目唯一标识。

    Attributes:
        task: 任务类型。
        seq: 序列号（每种任务类型独立递增）。
        name: 项目名（字母数字下划线连字符）。
    """

    task: TaskType
    seq: int
    name: str

    def to_dirname(self) -> str:
        """转为目录名：{task}_{seq}_{name}。"""
        return f"{self.task.value}_{self.seq:04d}_{self.name}"

    def to_path(self, base_root: str) -> str:
        """转为文件系统路径。"""
        return os.path.join(base_root, self.to_dirname())

    def __str__(self) -> str:
        return self.to_dirname()


class ProjectLayout:
    """项目目录布局计算。

    根据项目 ID 和存储根目录，计算各子目录路径。
    """

    def __init__(self, pid: ProjectId, base_root: str) -> None:
        self._pid = pid
        self._base_root = base_root

    @property
    def root(self) -> str:
        """项目根目录。"""
        return self._pid.to_path(self._base_root)

    @property
    def images_dir(self) -> str:
        return os.path.join(self.root, "images")

    @property
    def annotations_dir(self) -> str:
        return os.path.join(self.root, "annotations")

    @property
    def models_dir(self) -> str:
        return os.path.join(self.root, "models")

    @property
    def configs_dir(self) -> str:
        return os.path.join(self.root, "configs")

    @property
    def results_dir(self) -> str:
        return os.path.join(self.root, "results")

    def all_dirs(self) -> list:
        """返回所有子目录路径列表。"""
        return [
            self.images_dir,
            self.annotations_dir,
            self.models_dir,
            self.configs_dir,
            self.results_dir,
        ]

    @staticmethod
    def for_id(pid: ProjectId, base_root: str) -> "ProjectLayout":
        """工厂方法。"""
        return ProjectLayout(pid, base_root)


def parse_project_dirname(dirname: str) -> Optional[ProjectId]:
    """解析项目目录名为 ProjectId。

    目录名格式：{task}_{seq}_{name}

    Args:
        dirname: 目录名。

    Returns:
        ProjectId 或 None（格式不匹配）。
    """
    # 匹配格式 {task}_{4位数字}_{name}
    match = re.match(
        r"^([a-z]+)_(\d{3,4})_(.+)$", dirname
    )
    if not match:
        return None
    task_str, seq_str, name = match.groups()
    try:
        task = TaskType(task_str)
    except ValueError:
        return None
    return ProjectId(task=task, seq=int(seq_str), name=name)


__all__ = [
    "SUBDIRS",
    "ProjectId",
    "ProjectLayout",
    "parse_project_dirname",
]
