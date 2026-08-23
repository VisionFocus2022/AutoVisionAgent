"""登录会话持有者（W13-C3，v2 架构审查 P1-4）。

模块级单例存当前用户，默认 "system"。独立于 audit_logger 存在
（core 不反向依赖 gui）：gui 登录页写入，audit 调用方读取，
使审计记录归属到登录用户而非恒 "system"。
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_current_user = "system"
_current_role: str | None = None  # W35：动作门控数据源（未登录=None 宽容态）


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


def set_current_role(role: str | None) -> None:
    """设置当前会话角色（W35：登录成功处与 win.set_role 同点单点设置；
    None=未登录宽容态）。"""
    global _current_role
    with _lock:
        _current_role = role or None


def get_current_role() -> str | None:
    """读取当前会话角色（未登录为 None）。"""
    with _lock:
        return _current_role


def reset_current_role() -> None:
    """重置角色（测试隔离/登出用）。"""
    set_current_role(None)


__all__ = [
    "get_current_user",
    "get_current_role",
    "reset_current_user",
    "reset_current_role",
    "set_current_user",
    "set_current_role",
]
