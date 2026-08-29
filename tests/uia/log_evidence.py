"""应用日志铁证通道（W49 · SDW §5.1「应用日志锚点」机械实现）。

通道选择：AUDIT/ERROR 行经 Python logging **即时**写入 autovision.log
（audit_{date}.jsonl 有缓冲，atexit/满量才落盘——锚点一律打 autovision.log）。

双模式落点（与 tests/uia/conftest.py 启动分支对齐）：
- python 源码模式（AVA_UIA_SOURCE=python）：AVA_LOG_DIR 会话临时目录；
- exe 模式（默认）：dist/AutoVisionAgent/logs（conftest 剥 AVA_LOG_DIR，
  exe 写 cwd 相对路径）。

纪律（§5.1）：记录偏移量的打点必须发生在触发动作**之前**。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXE_LOG_DIR = _REPO_ROOT / "dist" / "AutoVisionAgent" / "logs"

# autovision.log 行格式：2026-08-29 14:25:08,555 - core.audit_logger - INFO - AUDIT [ts] user=u action=a
_AUDIT_RE = re.compile(
    r"AUDIT \[(?P<ts>[^\]]+)\] user=(?P<user>\S+) action=(?P<action>\S+)"
)


def resolve_app_log_dir() -> Path:
    """当前 UIA 模式的应用日志目录（python=AVA_LOG_DIR；exe=dist logs）。"""
    if os.environ.get("AVA_UIA_SOURCE", "exe").lower() == "python":
        env_dir = os.environ.get("AVA_LOG_DIR")
        if env_dir:
            return Path(env_dir)
    return _EXE_LOG_DIR


class LogAnchor:
    """动作前打点：持有 autovision.log 偏移量，尾部增量读取。

    用法（§5.1 偏移量先行）::

        anchor = LogAnchor()          # 打点
        click_button(win, "导出")      # 触发动作
        assert anchor.wait_line(r"模型导出开始: model=")
        assert not anchor.error_lines()
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.dir = Path(log_dir) if log_dir else resolve_app_log_dir()
        self.path = self.dir / "autovision.log"
        self.offset = self._current_size()

    def _current_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def tail(self) -> str:
        """偏移量之后的增量文本（文件尚不存在/不可读返回空）。"""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def wait_line(self, pattern: str, timeout: float = 15.0):
        """轮询尾部直到正则命中（返回 match 或 None）。"""
        rx = re.compile(pattern)
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = rx.search(self.tail())
            if m is not None:
                return m
            time.sleep(0.4)
        return None

    def error_lines(self) -> list:
        """尾部增量中的 ERROR 级日志行（诚实失败类操作的副作用断言用）。"""
        return [l for l in self.tail().splitlines() if " - ERROR - " in l]


def wait_audit_line(
    anchor: LogAnchor,
    action: str,
    user: Optional[str] = None,
    timeout: float = 15.0,
):
    """轮询锚点尾部增量中的 AUDIT 行（返回 match 或 None）。

    Args:
        anchor: 动作前打点（审计行必须落在打点之后才作数）。
        action: 操作类型（login/export/train/...）。
        user: 操作用户（None=不过滤）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for m in _AUDIT_RE.finditer(anchor.tail()):
            if m.group("action") == action and (
                user is None or m.group("user") == user
            ):
                return m
        time.sleep(0.4)
    return None
