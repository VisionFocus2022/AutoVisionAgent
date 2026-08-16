"""检测历史记录（对标 SKolpha detection_history）。

持久化存储推理历史记录，支持按任务/时间/图像路径查询和导出。
数据以 JSONL 格式存储，线程安全。

用法::

    from core.detection_history import get_history

    history = get_history()
    history.add_record(
        task="det",
        image_path="/data/test.jpg",
        result_count=5,
        score_avg=0.87,
        user="admin",
    )
    records = history.query(task="det", limit=50)
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from core.constants import CONFIG_DIR

_logger = logging.getLogger(__name__)

# 默认历史记录存储目录
_DEFAULT_HISTORY_DIR = CONFIG_DIR.parent / "logs" / "history"
_DEFAULT_MAX_RECORDS = 10000  # 内存中最多保留的记录数


@dataclass
class DetectionRecord:
    """单次检测记录。"""

    timestamp: str = ""
    task: str = ""               # 任务类型（det/cls/seg/...）
    image_path: str = ""         # 推理图像路径
    result_count: int = 0        # 检测结果数量
    score_avg: float = 0.0       # 平均置信度
    inference_time: float = 0.0  # 推理耗时（秒）
    user: str = "system"         # 操作用户
    device: str = ""             # 推理设备
    extra: Dict[str, Any] = field(default_factory=dict)


class DetectionHistory:
    """检测历史记录管理器（单例模式）。

    - 内存中保留最近 ``max_records`` 条记录（环形缓冲）。
    - 每条记录同时追加写入 JSONL 文件持久化。
    - 支持按任务类型/时间范围查询。
    """

    _instance: Optional["DetectionHistory"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "DetectionHistory":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        history_dir: Optional[Path] = None,
        max_records: int = _DEFAULT_MAX_RECORDS,
    ) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._history_dir = Path(history_dir) if history_dir else _DEFAULT_HISTORY_DIR
        self._max_records = max_records
        self._lock = threading.Lock()
        self._records: Deque[DetectionRecord] = deque(maxlen=max_records)

    def add_record(
        self,
        task: str = "",
        image_path: str = "",
        result_count: int = 0,
        score_avg: float = 0.0,
        inference_time: float = 0.0,
        user: str = "system",
        device: str = "",
        **extra: Any,
    ) -> DetectionRecord:
        """添加一条检测历史记录。

        Returns:
            创建的 DetectionRecord。
        """
        record = DetectionRecord(
            timestamp=datetime.now().isoformat(),
            task=task,
            image_path=image_path,
            result_count=result_count,
            score_avg=round(score_avg, 4),
            inference_time=round(inference_time, 4),
            user=user,
            device=device,
            extra=extra,
        )

        with self._lock:
            self._records.append(record)
            self._persist_locked(record)

        _logger.debug(
            "检测历史记录: task=%s image=%s count=%d",
            task, image_path, result_count,
        )
        return record

    def _persist_locked(self, record: DetectionRecord) -> None:
        """将记录追加写入 JSONL 文件（需在锁内调用）。"""
        self._history_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._history_dir / f"history_{datetime.now().strftime('%Y%m%d')}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False, default=str) + "\n")
        except OSError:
            _logger.exception("写入检测历史失败: %s", log_file)

    def query(
        self,
        task: Optional[str] = None,
        user: Optional[str] = None,
        limit: int = 100,
    ) -> List[DetectionRecord]:
        """查询内存中的检测历史记录。

        Args:
            task: 按任务类型过滤（None 表示全部）。
            user: 按用户过滤。
            limit: 最多返回条数。

        Returns:
            匹配的记录列表（倒序，最新的在前）。
        """
        with self._lock:
            records = list(self._records)

        results = []
        for r in reversed(records):
            if task and r.task != task:
                continue
            if user and r.user != user:
                continue
            results.append(r)
            if len(results) >= limit:
                break
        return results

    def query_from_file(
        self,
        date_str: Optional[str] = None,
        task: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """从持久化文件查询历史记录。

        Args:
            date_str: 日期（YYYYMMDD 格式，None 表示今天）。
            task: 按任务类型过滤。
            limit: 最多返回条数。

        Returns:
            匹配的记录字典列表。
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        log_file = self._history_dir / f"history_{date_str}.jsonl"
        if not log_file.exists():
            return []

        results: List[Dict[str, Any]] = []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if task and entry.get("task") != task:
                        continue
                    results.append(entry)
        except OSError:
            _logger.exception("读取检测历史失败: %s", log_file)

        return results[-limit:]

    def stats(self) -> Dict[str, Any]:
        """返回内存中记录的统计摘要。"""
        with self._lock:
            records = list(self._records)

        if not records:
            return {"total": 0, "by_task": {}, "avg_score": 0.0}

        by_task: Dict[str, int] = {}
        total_score = 0.0
        total_count = 0
        for r in records:
            by_task[r.task] = by_task.get(r.task, 0) + 1
            total_score += r.score_avg
            total_count += r.result_count

        return {
            "total": len(records),
            "by_task": by_task,
            "avg_score": round(total_score / len(records), 4),
            "total_detections": total_count,
        }

    def clear(self) -> None:
        """清空内存中的记录（不影响已持久化的文件）。"""
        with self._lock:
            self._records.clear()


def get_history(
    history_dir: Optional[Path] = None,
    max_records: int = _DEFAULT_MAX_RECORDS,
) -> DetectionHistory:
    """获取全局检测历史单例。"""
    return DetectionHistory(history_dir, max_records)


__all__ = [
    "DetectionRecord",
    "DetectionHistory",
    "get_history",
]
