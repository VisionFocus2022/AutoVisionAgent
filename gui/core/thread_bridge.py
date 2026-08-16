"""线程桥接公共辅助（R4-14）。

统一封装 QMetaObject.invokeMethod 调用，
消除 13+ 处重复的 import + Q_ARG + invokeMethod 模式。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMetaObject, Qt as _Qt, Q_ARG, QObject


# Python 类型 → Qt 元类型名称映射
_TYPE_MAP = {
    int: "int",
    float: "double",
    str: "QString",
    bool: "bool",
    dict: "QVariantMap",
    list: "QVariantList",
}


def _to_qarg(value: Any) -> Any:
    """将 Python 值转换为 Q_ARG 参数。"""
    type_name = _TYPE_MAP.get(type(value), "QVariant")
    try:
        return Q_ARG(type_name if isinstance(type_name, type) else eval(type_name), value)  # type: ignore[arg-type]
    except Exception:
        # 回退：使用 QVariant
        from PySide6.QtCore import QVariant
        return Q_ARG(QVariant, QVariant(value))


def invoke_main(widget: QObject, slot_name: str, *args: Any) -> None:
    """从工作线程安全调用主线程槽方法。

    封装 QMetaObject.invokeMethod + QueuedConnection，
    消除重复的 import 和 Q_ARG 构造。

    Args:
        widget: 目标 QObject（通常是页面/对话框实例）。
        slot_name: 槽方法名（字符串，需有 @Slot 装饰器）。
        *args: 传递给槽方法的参数。

    用法::

        # 旧代码（重复 13+ 处）:
        from PySide6.QtCore import QMetaObject, Qt as _Qt, Q_ARG
        QMetaObject.invokeMethod(self, "set_progress",
                                 _Qt.QueuedConnection,
                                 Q_ARG(int, pct))

        # 新代码:
        from gui.core.thread_bridge import invoke_main
        invoke_main(self, "set_progress", pct)
    """
    if not args:
        QMetaObject.invokeMethod(widget, slot_name, _Qt.QueuedConnection)
        return

    qargs = [_to_qarg(a) for a in args]
    QMetaObject.invokeMethod(widget, slot_name, _Qt.QueuedConnection, *qargs)


__all__ = ["invoke_main"]
