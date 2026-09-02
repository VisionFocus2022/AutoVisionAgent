"""操作标注模式（快捷键 O）。

矩形拖拽框定操作区域；标签输入框内容即操作名。

对标 SKolpha operation_label（W56 复刻；区域+操作名语义为推断级——
实机核对后按 PRD AC-010 回填修订，若原品为多边形区域再扩展）。
"""
from __future__ import annotations

from labeling.base import AnnotationMode
from labeling.modes.rectangle import RectangleLabeler


class OperationLabeler(RectangleLabeler):
    """操作区域标注器（矩形拖拽交互复用矩形模式；mode=OPERATION）。"""

    mode = AnnotationMode.OPERATION


__all__ = ["OperationLabeler"]
