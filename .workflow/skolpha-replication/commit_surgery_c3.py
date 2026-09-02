# -*- coding: utf-8 -*-
"""提交拆分手术脚本：C3 (W56) 前向重建。一次性使用。"""
from pathlib import Path


def rep(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == count, f"{path}: old 出现 {s.count(old)} 次（预期 {count}）"
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("OK", path)


# 1. base.py → 7 形态
rep("labeling/base.py", '''class AnnotationMode(Enum):
    """支持的标注模式（2026-09-01 极柱工作流裁剪后保留集）。"""

    POLYGON = "polygon"          # Q — 多边形标注
    RECTANGLE = "rectangle"      # R — 矩形标注
    INTERACTIVE = "interactive"  # I — SAM 点标（点提示分割）
    REGION_SAM = "region_sam"    # J — SAM 矩形标（框选定区分割，W43：拖拽定区+点击分割）
    EDIT = "edit"                # E — 顶点编辑（W55：选中多边形→拖/加点/删点）

    @classmethod
    def manual_modes(cls):
        """返回手动标注模式（非 AI 辅助）。"""
        return (cls.POLYGON, cls.RECTANGLE)''', '''class AnnotationMode(Enum):
    """支持的标注模式（2026-09-01 极柱工作流裁剪；W56 增工业两形态）。"""

    POLYGON = "polygon"          # Q — 多边形标注
    RECTANGLE = "rectangle"      # R — 矩形标注
    CUT_LINE = "cut_line"        # C — 切割线（W56：对标 SKolpha cut_line_label）
    OPERATION = "operation"      # O — 操作标注（W56：对标 SKolpha operation_label）
    INTERACTIVE = "interactive"  # I — SAM 点标（点提示分割）
    REGION_SAM = "region_sam"    # J — SAM 矩形标（框选定区分割，W43：拖拽定区+点击分割）
    EDIT = "edit"                # E — 顶点编辑（W55：选中多边形→拖/加点/删点）

    @classmethod
    def manual_modes(cls):
        """返回手动标注模式（非 AI 辅助）。"""
        return (
            cls.POLYGON, cls.RECTANGLE, cls.CUT_LINE, cls.OPERATION,
        )''')

# 2. modes/__init__.py
rep("labeling/modes/__init__.py", '''已删模式：画笔/关键点/SAM 笔刷/SAM 全图（历史见 RELEASES.md）。

INTERACTIVE''', '''已删模式：画笔/关键点/SAM 笔刷/SAM 全图（历史见 RELEASES.md）。
W56 增工业两形态：CUT_LINE 切割线 / OPERATION 操作标注
（对标 SKolpha，docs/prd-skolpha-replication.md FR-001/002）。

INTERACTIVE''')
rep("labeling/modes/__init__.py", '''        POLYGON = "polygon"
        RECTANGLE = "rectangle"
        INTERACTIVE = "interactive"''', '''        POLYGON = "polygon"
        RECTANGLE = "rectangle"
        CUT_LINE = "cut_line"
        OPERATION = "operation"
        INTERACTIVE = "interactive"''')
rep("labeling/modes/__init__.py", '''for _name, _module_path in [
    ("InteractiveLabeler", "labeling.modes.interactive"),''', '''for _name, _module_path in [
    ("CutLineLabeler", "labeling.modes.cut_line"),
    ("InteractiveLabeler", "labeling.modes.interactive"),''')
rep("labeling/modes/__init__.py", '''    ("PolygonLabeler", "labeling.modes.polygon"),
    ("RectangleLabeler", "labeling.modes.rectangle"),''', '''    ("OperationLabeler", "labeling.modes.operation"),
    ("PolygonLabeler", "labeling.modes.polygon"),
    ("RectangleLabeler", "labeling.modes.rectangle"),''')
rep("labeling/modes/__init__.py", '''    AnnotationMode.RECTANGLE: "RectangleLabeler",
    AnnotationMode.INTERACTIVE: "InteractiveLabeler",''', '''    AnnotationMode.RECTANGLE: "RectangleLabeler",
    AnnotationMode.CUT_LINE: "CutLineLabeler",
    AnnotationMode.OPERATION: "OperationLabeler",
    AnnotationMode.INTERACTIVE: "InteractiveLabeler",''')
rep("labeling/modes/__init__.py", '''    AnnotationMode.REGION_SAM: "RegionSamLabeler",
}

for _mode, _cls_name in _MODE_LABELLER_MAP.items():
    _cls = _LABELERS.get(_cls_name)
    if _cls is not None:
        _ALL_FACTORIES[_mode] = _cls
        if _mode in (AnnotationMode.POLYGON, AnnotationMode.RECTANGLE):
            _MANUAL_FACTORIES[_mode] = _cls''', '''    AnnotationMode.REGION_SAM: "RegionSamLabeler",
}

# 手动模式集合（与 AnnotationMode.manual_modes 对齐：非 AI 辅助）
_MANUAL_MODES = (
    AnnotationMode.POLYGON, AnnotationMode.RECTANGLE,
    AnnotationMode.CUT_LINE, AnnotationMode.OPERATION,
)

for _mode, _cls_name in _MODE_LABELLER_MAP.items():
    _cls = _LABELERS.get(_cls_name)
    if _cls is not None:
        _ALL_FACTORIES[_mode] = _cls
        if _mode in _MANUAL_MODES:
            _MANUAL_FACTORIES[_mode] = _cls''')

# 3. canvas.py → W56（imports + 渲染分支）
rep("labeling/canvas.py", '''from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
    QPixmap,
    QPolygonF,
)''', '''from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
    QPixmap,
    QPainterPath,
    QPolygonF,
)''')
rep("labeling/canvas.py", '''        if shape.mode is AnnotationMode.RECTANGLE and len(points) >= 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            self.addRect(min(x1, x2), min(y1, y2),
                        abs(x2 - x1), abs(y2 - y1), pen, brush)
        else:
            # 多边形 → QPolygonF（W14 P2-10：QPointF 静态导入，行为等价）
            poly = QPolygonF([QPointF(p[0], p[1]) for p in points])
            self.addPolygon(poly, pen, brush)''', '''        if (shape.mode in (AnnotationMode.RECTANGLE, AnnotationMode.OPERATION)
                and len(points) >= 2):
            # W56：OPERATION（操作区域）与 RECTANGLE 同为两点对角矩形
            x1, y1 = points[0]
            x2, y2 = points[1]
            self.addRect(min(x1, x2), min(y1, y2),
                        abs(x2 - x1), abs(y2 - y1), pen, brush)
        elif shape.mode is AnnotationMode.CUT_LINE and len(points) >= 2:
            # W56 切割线：开放折线——QPolygonF 会自动闭合首尾，须走
            # QPainterPath；虚线样式与区域类形态（填充面）视觉区分
            path = QPainterPath(QPointF(points[0][0], points[0][1]))
            for p in points[1:]:
                path.lineTo(QPointF(p[0], p[1]))
            pen.setStyle(Qt.DashLine)
            self.addPath(path, pen)
        else:
            # 多边形 → QPolygonF（W14 P2-10：QPointF 静态导入，行为等价）
            poly = QPolygonF([QPointF(p[0], p[1]) for p in points])
            self.addPolygon(poly, pen, brush)''')

# 4. io_labelme.py → W56
rep("labeling/io_labelme.py", '''- POLYGON/BRUSH → shape_type "polygon"；RECTANGLE → "rectangle"；KEYPOINT → "point"。
- 为保留画笔（brush）身份以支持精确往返，在每个 shape 字典附 ``"mode"`` 自定义键；''', '''- POLYGON → shape_type "polygon"；RECTANGLE/OPERATION → "rectangle"；
  CUT_LINE → "linestrip"（labelme 原生折线形态，跨工具互操作——外部
  工具写的 linestrip 读回 CUT_LINE；W56 对标 SKolpha cut_line_label/
  operation_label）。
- 为保留原始模式身份以支持精确往返，在每个 shape 字典附 ``"mode"`` 自定义键；''')
rep("labeling/io_labelme.py", '''_MODE_TO_SHAPE_TYPE: dict[AnnotationMode, str] = {
    AnnotationMode.POLYGON: "polygon",
    AnnotationMode.RECTANGLE: "rectangle",
}''', '''_MODE_TO_SHAPE_TYPE: dict[AnnotationMode, str] = {
    AnnotationMode.POLYGON: "polygon",
    AnnotationMode.RECTANGLE: "rectangle",
    AnnotationMode.CUT_LINE: "linestrip",       # W56：切割线（labelme 原生形态）
    AnnotationMode.OPERATION: "rectangle",      # W56：操作区域（矩形形态）
}''')
rep("labeling/io_labelme.py", '''_SHAPE_TYPE_TO_MODE: dict[str, AnnotationMode] = {
    "polygon": AnnotationMode.POLYGON,
    "rectangle": AnnotationMode.RECTANGLE,
}''', '''_SHAPE_TYPE_TO_MODE: dict[str, AnnotationMode] = {
    "polygon": AnnotationMode.POLYGON,
    "rectangle": AnnotationMode.RECTANGLE,
    "linestrip": AnnotationMode.CUT_LINE,       # W56：外部 linestrip 读为切割线
}''')
rep("labeling/io_labelme.py", '''    # 矩形只需两个对角点；多边形/画笔/关键点按原样
    pts = tuple(shape.points[:2]) if shape.mode is AnnotationMode.RECTANGLE else shape.points''', '''    # 矩形/操作标注只需两个对角点；多边形/切割线按原样
    _TWO_POINT_MODES = (AnnotationMode.RECTANGLE, AnnotationMode.OPERATION)
    pts = tuple(shape.points[:2]) if shape.mode in _TWO_POINT_MODES else shape.points''')

# 5. label/page.py → W56
rep("gui/pages/label/page.py", '''# 模式定义：(mode, 按钮文本键, 快捷键)
# 2026-09-01 极柱工作流裁剪：删 画笔P/关键点K/SAM笔刷B/SAM全图G（docs/prd-labeling-mode-prune.md）
_MODES = [
    (AnnotationMode.POLYGON, "多边形", "Q"),
    (AnnotationMode.RECTANGLE, "矩形", "R"),
    (AnnotationMode.INTERACTIVE, "交互式", "I"),''', '''# 模式定义：(mode, 按钮文本键, 快捷键)
# 2026-09-01 极柱工作流裁剪：删 画笔P/关键点K/SAM笔刷B/SAM全图G（docs/prd-labeling-mode-prune.md）
# W56 增工业两形态：切割线 C / 操作标注 O（docs/prd-skolpha-replication.md FR-001/002）
_MODES = [
    (AnnotationMode.POLYGON, "多边形", "Q"),
    (AnnotationMode.RECTANGLE, "矩形", "R"),
    (AnnotationMode.CUT_LINE, "切割线", "C"),
    (AnnotationMode.OPERATION, "操作标注", "O"),
    (AnnotationMode.INTERACTIVE, "交互式", "I"),''')
rep("gui/pages/label/page.py", '''_DRAW_MODES = _SAM_MODES | {
    AnnotationMode.POLYGON, AnnotationMode.RECTANGLE,
    AnnotationMode.EDIT,
}''', '''_DRAW_MODES = _SAM_MODES | {
    AnnotationMode.POLYGON, AnnotationMode.RECTANGLE,
    AnnotationMode.CUT_LINE, AnnotationMode.OPERATION,
    AnnotationMode.EDIT,
}''')
rep("gui/pages/label/page.py", '''    # ------------------------------ 标注模式 ------------------------------ #
    def _apply_mode(self, mode: AnnotationMode) -> None:''', '''    # ------------------------------ 标注模式 ------------------------------ #
    def set_default_shape_mode(self, mode: AnnotationMode) -> None:
        """工程 transferType 联动入口（W58-A 接线：Rect→矩形 / Polygon→多边形）。

        W56 预留：函数先行，项目信号接线在工程绑定批（Task 8）。
        """
        self._apply_mode(mode)

    def _apply_mode(self, mode: AnnotationMode) -> None:''')

print("C3 labeling chain done")
