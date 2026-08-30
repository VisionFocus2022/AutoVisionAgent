"""任务计数器 — 每种任务类型独立递增的 ID 分配器。

对标 SKolpha config_manager.py 的 get_task_counts()/update_task_count()。
持久化到 JSON 文件：{base_root}/task_counter.json。
"""
from __future__ import annotations

import json
import os

from project.paths import resolve_base_root

_COUNTER_FILENAME = "task_counter.json"


class TaskCounter:
    """任务 ID 计数器。

    持久化到 {base_root}/task_counter.json，格式：
    {"det": 3, "cls": 1, "pseg": 24, ...}

    Args:
        base_root: 存储根目录。
    """

    def __init__(self, base_root: str = "") -> None:
        # W28：默认根走 resolve_base_root 单源（workspace 可配；原为内联
        # expanduser 硬编码——设置页 workspace 键曾持久化但零消费）
        self._base_root = base_root or resolve_base_root()
        self._counts: dict[str, int] = {}
        self._load()

    # ============================== 持久化 ============================== #
    @property
    def _counter_path(self) -> str:
        return os.path.join(self._base_root, _COUNTER_FILENAME)

    def _load(self) -> None:
        """从磁盘加载计数器。"""
        path = self._counter_path
        if not os.path.exists(path):
            self._counts = {}
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._counts = {
                        str(k): int(v) for k, v in data.items()
                        if isinstance(v, (int, float))
                    }
        except (json.JSONDecodeError, OSError):
            self._counts = {}

    def _save(self) -> None:
        """保存计数器到磁盘。"""
        os.makedirs(self._base_root, exist_ok=True)
        path = self._counter_path
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._counts, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ============================== API ============================== #
    def next_id(self, task: str = "") -> int:
        """分配下一个 ID（递增并持久化）。

        Args:
            task: 任务类型值字符串（如 "det"）。

        Returns:
            新分配的 ID（从 1 开始）。
        """
        current = self._counts.get(task, 0)
        new_id = current + 1
        self._counts[task] = new_id
        self._save()
        return new_id

    def snapshot(self) -> dict[str, int]:
        """返回当前所有计数器的快照（不修改）。"""
        return dict(self._counts)

    def snapshot_by_name(self) -> dict[str, int]:
        """别名：snapshot()。"""
        return self.snapshot()

    def get(self, task: str) -> int:
        """获取指定任务的当前计数（不递增）。"""
        return self._counts.get(task, 0)

    def set(self, task: str, value: int) -> None:
        """手动设置计数器值。"""
        self._counts[task] = max(0, int(value))
        self._save()

    def reset(self, task: str | None = None) -> None:
        """重置计数器。

        Args:
            task: 指定任务则只重置该任务；None 则重置全部。
        """
        if task is None:
            self._counts.clear()
        else:
            self._counts.pop(task, None)
        self._save()


__all__ = ["TaskCounter"]
