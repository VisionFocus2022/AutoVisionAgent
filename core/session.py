"""登录会话持有者（W13-C3，v2 架构审查 P1-4）。

模块级单例存当前用户，默认 "system"。独立于 audit_logger 存在
（core 不反向依赖 gui）：gui 登录页写入，audit 调用方读取，
使审计记录归属到登录用户而非恒 "system"。
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_current_user = "system"


def set_current_user(user: str) -> None:
    """设置当前用户（登录成功/离线模式确认时调用；空值回退 "system"）。"""
    global _current_user
    with _lock:
        _current_user = user if user else "system"


def get_current_user() -> str:
    """读取当前用户（未登录/未设置时恒为 "system"）。"""
    with _lock:
        return _current_user


def reset_current_user() -> None:
    """重置为默认（测试隔离/登出用）。"""
    set_current_user("system")


__all__ = ["get_current_user", "reset_current_user", "set_current_user"]
