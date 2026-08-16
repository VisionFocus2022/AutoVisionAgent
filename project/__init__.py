"""project — 项目管理模块。

提供项目 ID/目录模型、文件系统项目仓库、任务计数器、最近项目列表。
"""
from __future__ import annotations

from project.models import ProjectId, ProjectLayout, parse_project_dirname
from project.counter import TaskCounter
from project.store import FileSystemProjectStore
from project import recent

__all__ = [
    "ProjectId",
    "ProjectLayout",
    "parse_project_dirname",
    "TaskCounter",
    "FileSystemProjectStore",
    "recent",
]
