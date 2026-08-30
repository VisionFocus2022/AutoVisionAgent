"""文件系统项目仓库 — 管理项目的创建/列出/删除。

对标 SKolpha 的项目目录管理：create/list/load_meta/get_layout。
"""
from __future__ import annotations

import logging
import os

from core.interfaces_supervised import TaskType
from project.counter import TaskCounter
from project.models import (
    ProjectId,
    ProjectLayout,
    parse_project_dirname,
)

_logger = logging.getLogger(__name__)


class FileSystemProjectStore:
    """文件系统项目仓库。

    Args:
        base_root: 项目存储根目录。
    """

    def __init__(self, base_root: str) -> None:
        self._base_root = base_root
        os.makedirs(base_root, exist_ok=True)
        self._counter = TaskCounter(base_root)

    # ============================== 创建 ============================== #
    def create_project(
        self, name: str, task: TaskType
    ) -> tuple[ProjectId, ProjectLayout]:
        """创建新项目目录。

        Args:
            name: 项目名。
            task: 任务类型。

        Returns:
            (ProjectId, ProjectLayout) 元组。
        """
        seq = self._counter.next_id(task.value)
        pid = ProjectId(task=task, seq=seq, name=name)
        layout = ProjectLayout(pid, self._base_root)

        # 创建所有子目录
        for subdir in layout.all_dirs():
            os.makedirs(subdir, exist_ok=True)

        # 写入项目元数据
        meta_path = os.path.join(layout.root, "project_meta.json")
        try:
            import json
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "task": task.value,
                        "seq": seq,
                        "name": name,
                        "dirname": pid.to_dirname(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError:
            _logger.warning("项目元数据写入失败: %s", meta_path)

        return pid, layout

    # ============================== 列出 ============================== #
    def list_projects(self) -> list[ProjectId]:
        """列出所有项目（扫描根目录下的合法项目目录）。"""
        result: list[ProjectId] = []
        try:
            entries = os.listdir(self._base_root)
        except OSError:
            return result
        for entry in entries:
            full_path = os.path.join(self._base_root, entry)
            if not os.path.isdir(full_path):
                continue
            pid = parse_project_dirname(entry)
            if pid is not None:
                result.append(pid)
        # 按 task + seq 排序
        result.sort(key=lambda p: (p.task.value, p.seq))
        return result

    # ============================== 查询 ============================== #
    def exists(self, pid: ProjectId) -> bool:
        """检查项目目录是否存在。"""
        return os.path.isdir(pid.to_path(self._base_root))

    def get_layout(self, pid: ProjectId) -> ProjectLayout:
        """获取项目的目录布局。"""
        return ProjectLayout(pid, self._base_root)

    def load_meta(self, pid: ProjectId) -> dict | None:
        """加载项目元数据 JSON。"""
        meta_path = os.path.join(
            pid.to_path(self._base_root), "project_meta.json"
        )
        if not os.path.exists(meta_path):
            return None
        try:
            import json
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


__all__ = ["FileSystemProjectStore"]
