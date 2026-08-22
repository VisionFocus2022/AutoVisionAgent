"""审计日志（对标 SKolpha audit_logger）。

记录用户关键操作（登录、模型加载、推理、训练、导出等），
持久化到 JSONL 文件，支持查询与导出。

线程安全：内部使用 threading.Lock 保护写入操作。
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.constants import CONFIG_DIR

_logger = logging.getLogger(__name__)

# 默认审计日志目录
def _resolve_audit_dir() -> Path:
    """W23（v4 P2-1c）：默认审计目录——AVA_LOG_DIR 指定时取其下 audit/，
    否则仓库 logs/audit（测试态隔离约定，与 gui/main.setup_logging 一致）。"""
    env_dir = os.environ.get("AVA_LOG_DIR")
    if env_dir:
        return Path(env_dir) / "audit"
    return CONFIG_DIR.parent / "logs" / "audit"


class AuditLogger:
    """审计日志记录器（单例模式）。

    将审计事件以 JSONL 格式追加写入文件，每行一个 JSON 对象。

    用法::

        from core.audit_logger import get_audit_logger

        audit = get_audit_logger()
        audit.log("inference", user="admin", task="det",
                  image="test.jpg", result_count=5)
    """

    _instance: Optional["AuditLogger"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "AuditLogger":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._log_dir = Path(log_dir) if log_dir else _resolve_audit_dir()
        self._lock = threading.Lock()
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_max = 100  # 缓冲区满后刷盘
        # W11-P1: 首次创建单例时注册退出钩子，退出/崩溃兜底刷盘，
        # 否则缓冲尾记录（最多 _buffer_max-1 条）随进程一起丢失。
        atexit.register(self.flush)

    def log(
        self,
        action: str,
        user: str = "system",
        **details: Any,
    ) -> None:
        """记录一条审计日志。

        Args:
            action: 操作类型（login/logout/inference/train/export/...）。
            user: 操作用户。
            **details: 其他任意键值对细节。
        """
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "user": user,
            "details": details,
        }

        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self._buffer_max:
                self._flush_locked()

        # 也输出到 Python logging（便于控制台查看）
        _logger.info(
            "AUDIT [%s] user=%s action=%s",
            entry["timestamp"], user, action,
        )

    def flush(self) -> None:
        """强制将缓冲区写入磁盘。"""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """在已持锁状态下写入磁盘。"""
        if not self._buffer:
            return

        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._buffer.clear()
        except OSError:
            _logger.exception("写入审计日志失败: %s", log_file)

    def query(
        self,
        action: Optional[str] = None,
        user: Optional[str] = None,
        date_str: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询审计日志。

        Args:
            action: 按操作类型过滤（None 表示全部）。
            user: 按用户过滤。
            date_str: 按日期过滤（YYYYMMDD 格式，None 表示今天）。
            limit: 最多返回条数。

        Returns:
            匹配的审计日志条目列表（倒序）。
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")

        log_file = self._log_dir / f"audit_{date_str}.jsonl"
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
                    if action and entry.get("action") != action:
                        continue
                    if user and entry.get("user") != user:
                        continue
                    results.append(entry)
        except OSError:
            _logger.exception("读取审计日志失败: %s", log_file)

        return results[-limit:]


def get_audit_logger(log_dir: Optional[Path] = None) -> AuditLogger:
    """获取全局审计日志单例。"""
    return AuditLogger(log_dir)


# 便捷快捷函数
def log_detection_complete(
    user: str = "system",
    task: str = "",
    image: str = "",
    result_count: int = 0,
    **extra: Any,
) -> None:
    """记录推理完成事件（对标 SKolpha audit_logger.log_detection_complete）。"""
    get_audit_logger().log(
        "detection_complete",
        user=user,
        task=task,
        image=image,
        result_count=result_count,
        **extra,
    )


def log_model_export(
    user: str = "system",
    task: str = "",
    format: str = "",
    path: str = "",
    **extra: Any,
) -> None:
    """记录模型导出事件。"""
    get_audit_logger().log(
        "model_export",
        user=user,
        task=task,
        format=format,
        path=path,
        **extra,
    )


def log_train_complete(
    user: str = "system",
    task: str = "",
    epochs: int = 0,
    best_metric: float = 0.0,
    **extra: Any,
) -> None:
    """记录训练完成事件。"""
    get_audit_logger().log(
        "train_complete",
        user=user,
        task=task,
        epochs=epochs,
        best_metric=best_metric,
        **extra,
    )


def log_login(
    user: str = "system",
    role: str = "",
    mode: str = "local",
    **extra: Any,
) -> None:
    """记录登录事件（mode="offline" 表示离线模式进入）。

    W13-C3：模块 docstring 宣称记录登录，此前 login 页零调用；
    由登录页在登录成功与离线模式确认处调用。
    """
    get_audit_logger().log(
        "login",
        user=user,
        role=role,
        mode=mode,
        **extra,
    )


def log_access_denied(
    user: str = "system",
    role: str = "",
    page: str = "",
    **extra: Any,
) -> None:
    """记录页面访问被拒事件（W29 角色门控：操作护栏非安全边界）。

    MainWindow.select 守卫拒绝时调用——被拒访问留审计痕。
    """
    get_audit_logger().log(
        "access_denied",
        user=user,
        role=role,
        page=page,
        **extra,
    )


__all__ = [
    "AuditLogger",
    "get_audit_logger",
    "log_access_denied",
    "log_detection_complete",
    "log_login",
    "log_model_export",
    "log_train_complete",
]
