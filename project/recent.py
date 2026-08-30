"""最近项目列表管理（扩展 FR-E1/E2）。

持久化最近打开的项目列表到 JSON 文件，对标 SKolpha 的 programFile.json recent 字段。
"""
from __future__ import annotations

import json
import os

_RECENT_FILENAME = "recent_projects.json"
_MAX_RECENT = 20


def _recent_path(base_root: str) -> str:
    return os.path.join(base_root, _RECENT_FILENAME)


def recent_list(base_root: str) -> list[str]:
    """读取最近项目目录名列表。"""
    path = _recent_path(base_root)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("recent", [])
    except (json.JSONDecodeError, OSError):
        return []


def add_recent(base_root: str, dirname: str) -> list[str]:
    """添加项目目录名到最近列表（去重，置顶，截断）。"""
    lst = recent_list(base_root)
    # 去重
    lst = [d for d in lst if d != dirname]
    lst.insert(0, dirname)
    # 截断
    lst = lst[:_MAX_RECENT]
    # 持久化
    path = _recent_path(base_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"recent": lst}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return lst


def remove_recent(base_root: str, dirname: str) -> list[str]:
    """从最近列表移除。"""
    lst = [d for d in recent_list(base_root) if d != dirname]
    path = _recent_path(base_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"recent": lst}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return lst


__all__ = ["recent_list", "add_recent", "remove_recent"]
