"""线程桥接公共辅助（R4-14；W3-T3 修复 PySide6 类型映射）。

统一封装 QMetaObject.invokeMethod 调用，
消除 13+ 处重复的 import + Q_ARG + invokeMethod 模式。

W3-T3 修复：旧版用 ``eval(类型名字符串)`` 解析 Qt 元类型——str 载荷映射到
"QString"（PySide6 已移除）→ NameError，回退导入 QVariant 亦不存在 →
ImportError，即带 str 的跨线程调用在 PySide6 下必崩（T3 测试实测复现）。
现改为显式映射表直传 Python 原生类型；dict/list 走 QVariantMap/QVariantList
（实验实测经 @Slot(dict)/@Slot(list) 槽可靠回传）。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMetaObject, Qt as _Qt, Q_ARG, QObject


# Python 类型 → Q_ARG 类型（原生类型直传；容器走 Qt 元类型名）
_TYPE_MAP = {
    int: int,
    float: float,
    str: str,
    bool: bool,
    dict: "QVariantMap",
    list: "QVariantList",
}


def _to_qarg(value: Any) -> Any:
    """将 Python 值转换为 Q_ARG 参数。"""
    qtype = _TYPE_MAP.get(type(value))
    if qtype is None:
        raise TypeError(
            f"invoke_main 不支持 {type(value).__name__} 载荷；"
            "重对象请改用页面暂存属性 + 原语唤起模式"
        )
    return Q_ARG(qtype, value)


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
