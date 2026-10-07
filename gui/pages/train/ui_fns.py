"""训练页模块级 UI 助手（W2-3 批拆自 page.py——规模守卫 800）。

纯函数/对话框构造，无页面状态依赖；行为与拆出前零变更。
"""
from __future__ import annotations

from gui.core.i18n import tr


def _format_eta(eta) -> str:
    """ETA 秒 → " · 剩余 m:ss" 文案（W1-1）。"""
    if isinstance(eta, (int, float)) and eta > 0:
        mm, ss = divmod(int(eta), 60)
        return f" · 剩余 {mm}:{ss:02d}"
    return ""


def _confirm_simulated_dialog(parent) -> bool:
    """模拟训练显式确认框（W1-3 拆自页面方法）。自定义中文按钮不依赖 Qt 翻译。"""
    from PySide6.QtWidgets import QMessageBox

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(tr("模拟训练确认"))
    msg.setText(tr("即将执行模拟训练：该任务未实装真训练或未选择数据集，训练过程为假 loss 模拟，不会产生可用的真实模型。"))
    btn_go = msg.addButton(tr("继续模拟训练"), QMessageBox.YesRole)
    msg.addButton(tr("取消"), QMessageBox.NoRole)
    msg.setDefaultButton(btn_go)
    msg.exec()
    return msg.clickedButton() is btn_go


def _format_final_metrics(metrics: dict | None) -> str:
    """末轮 val 指标 → 完成状态文案（W1-6）。

    三键齐全才格式化（部分指标显示半截比不显示更误导）；任何形态
    异常返回空串——显示层不挡训练完成路径。
    """
    try:
        return (
            f"P={metrics['precision']:.2f} R={metrics['recall']:.2f}"
            f" mAP50={metrics['map50']:.2f}"
        )
    except (KeyError, TypeError, ValueError):
        return ""


__all__ = ["_confirm_simulated_dialog", "_format_eta", "_format_final_metrics"]
