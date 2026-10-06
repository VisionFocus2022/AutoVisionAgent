"""审计日志（对标 SKolpha audit_logger）。

记录用户关键操作（登录、模型加载、推理、训练、导出等），
持久化到 JSONL 文件，支持查询与导出。

线程安全：内部使用 threading.Lock 保护写入操作。

防篡改（M6 哈希链，2026-10-06）：每条落盘记录携带 seq/prev_hash/self_hash
——self_hash = sha256(prev_hash + 记录规范化 JSON)。离线编辑任意历史行
会使其 self_hash 与重算值不符、且后续链全部断裂，verify_chain() 可机械
检出。纯明文时代（无哈希字段）的旧文件行按 legacy 跳过（链自首个带哈希
行重新起算）。哈希计算 best-effort：任何异常不得阻断日志写入本身。
"""
from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core.constants import CONFIG_DIR

_logger = logging.getLogger(__name__)

_GENESIS_HASH = ""


def _entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    """M6：单条记录链哈希——sha256(prev_hash + 规范化 JSON)。

    规范化：排除 self_hash 字段本身，键排序，ensure_ascii=False（与
    落盘序列化同参数，保证重算一致）。
    """
    payload = {k: v for k, v in entry.items() if k != "self_hash"}
    canonical = json.dumps(
        payload, ensure_ascii=False, default=str, sort_keys=True
    )
    return hashlib.sha256(
        (prev_hash + "|" + canonical).encode("utf-8")
    ).hexdigest()


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

    _instance: AuditLogger | None = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> AuditLogger:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, log_dir: Path | None = None) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._log_dir = Path(log_dir) if log_dir else _resolve_audit_dir()
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._buffer_max = 100  # 缓冲区满后刷盘
        self._buffer_hard_max = 1000  # W39·v6 P3-3：目录不可写时的内存硬上限（丢最旧）
        # M6 哈希链状态：最近一条落盘记录的 self_hash（链头衔接用）。
        # 惰性初始化——首次刷盘时从当日文件尾行恢复（跨进程延续链）。
        self._chain_prev_hash: str | None = None
        self._chain_seq: int = 0
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
        entry: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "user": user,
            "details": details,
        }

        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) > self._buffer_hard_max:
                # W39·v6 P3-3：目录不可写时防无界增长——丢最旧并告警
                dropped = len(self._buffer) - self._buffer_hard_max
                del self._buffer[:dropped]
                _logger.warning(
                    "审计缓冲达硬上限 %d 条（审计目录不可写？），丢弃最旧 %d 条",
                    self._buffer_hard_max, dropped,
                )
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
        """在已持锁状态下写入磁盘。

        W39·v6 P3-3：mkdir/写盘失败不再上抛（原 mkdir 在 try 外——
        目录不可写时每条 log 都从 log() 抛出）；失败仅告警，缓冲由
        _buffer_hard_max 兜底有界，等待目录恢复后下次刷盘。

        M6（2026-10-06）：落盘前逐条附加 seq/prev_hash/self_hash 链。
        链状态惰性恢复（当日文件尾行），跨进程延续；哈希计算失败仅
        告警降级为无哈希行（不阻断日志写入本身）。
        """
        if not self._buffer:
            return

        log_file = self._log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_chain_state_locked(log_file)
            lines: list[str] = []
            for entry in self._buffer:
                try:
                    entry["seq"] = self._chain_seq + 1
                    entry["prev_hash"] = self._chain_prev_hash
                    entry["self_hash"] = _entry_hash(
                        self._chain_prev_hash, entry
                    )
                    self._chain_seq += 1
                    self._chain_prev_hash = entry["self_hash"]
                except Exception:
                    _logger.warning("审计哈希链计算失败（降级无哈希行）",
                                    exc_info=True)
                lines.append(
                    json.dumps(entry, ensure_ascii=False, default=str) + "\n"
                )
            with open(log_file, "a", encoding="utf-8") as f:
                f.writelines(lines)
            self._buffer.clear()
        except OSError:
            _logger.exception("写入审计日志失败: %s", log_file)

    def _ensure_chain_state_locked(self, log_file: Path) -> None:
        """M6：从当日文件尾行恢复链状态（首次刷盘时执行一次）。"""
        if self._chain_prev_hash is not None:
            return
        self._chain_prev_hash = _GENESIS_HASH
        self._chain_seq = 0
        try:
            if not log_file.exists():
                return
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if "self_hash" in entry:
                        # 尾部最新链点（legacy 行无哈希，跳过不回退状态）
                        self._chain_prev_hash = entry["self_hash"]
                        self._chain_seq = max(
                            self._chain_seq, int(entry.get("seq", 0))
                        )
        except OSError:
            _logger.warning("审计链状态恢复失败（从创世重起）", exc_info=True)

    def verify_chain(self, date_str: str | None = None) -> list[int]:
        """M6：校验当日（或指定日）审计文件的哈希链完整性。

        Returns:
            断链行号列表（1-based，文件级行号）。空列表=链完整。
            legacy 无哈希行不计断链（链自首个带哈希行起算）。
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        log_file = self._log_dir / f"audit_{date_str}.jsonl"
        if not log_file.exists():
            return []

        broken: list[int] = []
        prev_hash: str | None = None  # None=尚未进入链区（legacy 段）
        try:
            with open(log_file, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        broken.append(lineno)  # 损坏行（含被改烂的行）
                        continue
                    if "self_hash" not in entry:
                        continue  # legacy 行
                    expected_prev = prev_hash if prev_hash is not None \
                        else entry.get("prev_hash")  # 链首自证
                    if (entry.get("prev_hash") != expected_prev
                            or _entry_hash(entry.get("prev_hash", ""), entry)
                            != entry["self_hash"]):
                        broken.append(lineno)
                        prev_hash = entry.get("self_hash")  # 继续找后续断点
                        continue
                    prev_hash = entry["self_hash"]
        except OSError:
            _logger.exception("读取审计文件校验链失败: %s", log_file)
        return broken

    def query(
        self,
        action: str | None = None,
        user: str | None = None,
        date_str: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
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

        results: list[dict[str, Any]] = []
        try:
            with open(log_file, encoding="utf-8") as f:
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


def get_audit_logger(log_dir: Path | None = None) -> AuditLogger:
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


def log_serving_rpc(
    user: str = "grpc-client",
    rpc: str = "",
    task: str = "",
    success: bool = True,
    **extra: Any,
) -> None:
    """记录 serving 层 RPC 事件（M6，2026-10-05 一轮审查）。

    一轮审查发现"gRPC 推理/LoadModel 路径零审计接入——对外暴露面恰是
    审计盲区"（gui 路径有 log_detection_complete，gRPC 路径没有）。
    由 serving.server 的 LoadModel/UnloadModel/Detect 成功失败路径调用，
    补齐对外接口的审计留痕。user 固定为标识性占位（回环无鉴权架构下
    无真实用户概念，ADR-0001）。
    """
    get_audit_logger().log(
        "serving_rpc",
        user=user,
        rpc=rpc,
        task=task,
        success=success,
        **extra,
    )


def verify_audit_chain(date_str: str | None = None) -> list[int]:
    """M6 便捷函数：校验审计链完整性（默认单例、当日）。"""
    return get_audit_logger().verify_chain(date_str)


__all__ = [
    "AuditLogger",
    "get_audit_logger",
    "log_access_denied",
    "log_detection_complete",
    "log_login",
    "log_model_export",
    "log_serving_rpc",
    "log_train_complete",
    "verify_audit_chain",
]
