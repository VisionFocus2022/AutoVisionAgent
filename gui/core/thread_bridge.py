"""线程桥接公共辅助（R4-14；W3-T3 修复 PySide6 类型映射）。

统一封装 QMetaObject.invokeMethod 调用，
消除 13+ 处重复的 import + Q_ARG + invokeMethod 模式。

W3-T3 修复：旧版用 ``eval(类型名字符串)`` 解析 Qt 元类型——str 载荷映射到
"QString"（PySide6 已移除）→ NameError，回退导入 QVariant 亦不存在 →
ImportError，即带 str 的跨线程调用在 PySide6 下必崩（T3 测试实测复现）。
现改为显式映射表直传 Python 原生类型；dict/list 走 QVariantMap/QVariantList
（实验实测经 @Slot(dict)/@Slot(list) 槽可靠回传）。

W14-C2 修复（架构审查 P2-16）：
- _to_qarg 补 None/tuple/numpy 标量三路载荷（此前一律 TypeError，而多数
  worker except 元组不含 TypeError → 线程裸死、按钮永久禁用）：
  * None → "QVariant" 通道原样送达，接收槽须声明 ``@Slot("QVariant")``
    （PySide6 6.11 offscreen 实测：Q_ARG(type(None))/Q_ARG(object) 抛
    RuntimeError，Q_ARG(str, None) 送达乱码——仅 QVariant 通道可靠往返）；
  * tuple → "QVariantList" 通道，送达后为 list（Qt 无 tuple 元类型，不保真）；
  * numpy 标量（np.int64/np.float32/...）→ ``.item()`` 归一为 Python 标量
    后走既有 str/int/float 通道。
- invokeMethod 返回 False（槽缺失/无 @Slot/签名不匹配）时 logger.warning
  （含目标类名与槽名），不再静默丢弃调用。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Q_ARG, QMetaObject, QObject
from PySide6.QtCore import Qt as _Qt

logger = logging.getLogger(__name__)


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
    if qtype is not None:
        return Q_ARG(qtype, value)

    # W14-C2（P2-16）：以下载荷此前一律 TypeError（详见模块 docstring 语义）
    if value is None:
        return Q_ARG("QVariant", None)
    if isinstance(value, tuple):
        return Q_ARG("QVariantList", list(value))
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes, dict, list)):
        # numpy 标量等（np.int64/np.float32/...）→ Python 标量后走常规映射
        try:
            return _to_qarg(value.item())
        except TypeError:
            pass  # .item() 归一后仍不支持 → 落到下方统一拒绝

    raise TypeError(
        f"invoke_main 不支持 {type(value).__name__} 载荷；"
        "重对象请改用页面暂存属性 + 原语唤起模式"
    )


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
        ok = QMetaObject.invokeMethod(widget, slot_name, _Qt.QueuedConnection)
    else:
        qargs = [_to_qarg(a) for a in args]
        ok = QMetaObject.invokeMethod(
            widget, slot_name, _Qt.QueuedConnection, *qargs
        )
    if not ok:
        # W14-C2（P2-16）：False = 槽缺失/漏 @Slot/签名不匹配，调用被 Qt 静默丢弃
        logger.warning(
            "invoke_main 调度失败（invokeMethod 返回 False，调用已丢弃）："
            "目标 %s 上不存在可用槽 %s（检查 @Slot 装饰器与载荷类型匹配）",
            type(widget).__name__,
            slot_name,
        )


def ui_on_error(
    widget: QObject, slot_name: str, *prefix_args: Any
) -> Callable[[Exception], None]:
    """构造 run_job 的 on_error 回调：worker 异常经 invoke_main 转发到页面失败槽。

    W17（v3 P2-1）：worker 抛出页面 except 元组外的异常类型（AppError 家族/
    IndexError/KeyError 等）时，run_job 仅落日志、恢复槽永不执行 → 按钮永久
    禁用。页面把本回调传给 ``run_job(..., on_error=...)`` 即获得"任何异常必达
    UI"的兜底（页面既有 except 元组保留优先，负责针对性文案）。

    Args:
        widget: 目标 QObject（通常是页面实例）。
        slot_name: 失败槽方法名（需 @Slot 装饰；末参数收 str(exc)）。
        *prefix_args: 槽的前缀参数——供需要操作上下文的失败槽，如
            ``ui_on_error(self, "_op_failed", op)`` → ``_op_failed(op, err)``。

    Returns:
        run_job 的 on_error 回调（在工作线程执行，经 invoke_main 跳主线程）。
    """
    def _handle(exc: Exception) -> None:
        invoke_main(widget, slot_name, *prefix_args, str(exc))

    return _handle


__all__ = ["invoke_main", "ui_on_error"]
