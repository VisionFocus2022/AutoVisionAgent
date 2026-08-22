"""任务下拉框统一构建（W1-T4：与引擎注册表实况对齐）。

架构审查 P1-1：train/predict/eval 下拉恰好只暴露缺失的 det/seg/abdet，
已实现的 6 个引擎反而不可从 GUI 到达。本模块按 TaskType 枚举构建下拉，
并按注册表实况标注（训练页：缺引擎标"模拟"）或过滤（推理页：只列可用）。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt

from core.interfaces_supervised import TaskType
from gui.core.i18n import tr

# 任务中文名（i18n 键）；标签形如 "检测 (det)"
TASK_LABELS = {
    TaskType.DET: "检测",
    TaskType.SEG: "分割",
    TaskType.PSEG: "实例分割",
    TaskType.CLS: "分类",
    TaskType.POSE: "关键点",
    TaskType.SSEG: "语义分割",
    TaskType.ABDET: "异常检测",
    TaskType.SGAN: "缺陷生成",
    TaskType.SUPER: "超分辨率",
    TaskType.OCR: "文字识别",
}


def registered_tasks() -> set:
    """返回已注册引擎的任务集合（顺带触发惰性注册）。"""
    try:
        # registry 直连为 GUI 正式形态（v3 P2-7）
        from models.supervised.engines import register_all_engines
        from models.supervised.registry import get_default_registry
        register_all_engines()
        return set(get_default_registry().list())
    except Exception:  # noqa: BLE001 —— 注册表不可用时按"全部不可用"处理
        return set()


def populate_task_combo(
    combo,
    *,
    only_available: bool = False,
    unavailable_suffix: str = "（未装引擎）",
    unavailable_tooltip: str = "该任务引擎未安装",
    exclude: tuple = (),
) -> List[Tuple[TaskType, bool]]:
    """按 TaskType 全量填充任务下拉框。

    Args:
        only_available: True 只列已注册引擎的任务（推理/评估页语义）；
            False 列全部 9 项并对缺引擎项加后缀（训练页语义，可走模拟训练）。
            极端情况下注册表整体不可用时退化为全量展示，避免空下拉。
        unavailable_suffix: 缺引擎项的标签后缀。
        unavailable_tooltip: 缺引擎项的悬浮提示。

    exclude: 不列入的任务（训练页排除推理-only 任务如 OCR）。

    Returns:
        [(TaskType, available), ...] 与下拉项一一对应（枚举序，DET 首项）。
    """
    available = registered_tasks()
    if only_available and not available:
        only_available = False

    items: List[Tuple[TaskType, bool]] = []
    combo.clear()
    for task in TaskType:
        if task in exclude:  # W32：推理-only 任务（如 OCR）训练页不列
            continue
        ok = task in available
        if only_available and not ok:
            continue
        label = f"{tr(TASK_LABELS.get(task, task.value))} ({task.value})"
        if not ok:
            label += tr(unavailable_suffix)
        combo.addItem(label, task)
        if not ok:
            combo.setItemData(combo.count() - 1, tr(unavailable_tooltip), Qt.ToolTipRole)
        items.append((task, ok))
    return items


__all__ = ["TASK_LABELS", "registered_tasks", "populate_task_combo"]
