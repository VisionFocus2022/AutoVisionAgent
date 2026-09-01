"""标注剪贴板 Mixin（W55 自 page.py 抽取，保 page.py ≤800 行守卫）。

行为保持抽取（W27 SamSessionMixin 先例）：复制选中形状（未选中=复制
全部）到页内剪贴板、Ctrl+V 偏移粘贴。宿主依赖：canvas/controller/
status_changed/_clipboard。
"""
from __future__ import annotations

from gui.core.i18n import tr


class LabelClipboardMixin:
    """LabelPage 剪贴板能力（Ctrl+C / Ctrl+V）。"""

    def _copy_shapes(self) -> None:
        """复制选中标注到剪贴板（Ctrl+C）。"""
        row = self.shape_list.currentRow()
        if row >= 0 and row < len(self.canvas.shapes):
            shape = self.canvas.shapes[row]
            # 深拷贝形状数据（points/mode/label）
            self._clipboard = [{
                "mode": shape.mode,
                "label": shape.label,
                "points": list(getattr(shape, "points", [])),
            }]
            self.status_changed.emit(tr("已复制"), f"1 {tr('标注')}")
        else:
            # 复制全部
            self._clipboard = [{
                "mode": s.mode,
                "label": s.label,
                "points": list(getattr(s, "points", [])),
            } for s in self.canvas.shapes]
            self.status_changed.emit(tr("已复制"), f"{len(self._clipboard)} {tr('标注')}")

    def _paste_shapes(self, offset: int = 20) -> None:
        """粘贴剪贴板标注（Ctrl+V），偏移避免完全重叠。"""
        if not self._clipboard:
            self.status_changed.emit(tr("剪贴板为空"), "!")
            return
        for item in self._clipboard:
            try:
                # 创建偏移后的点列表
                offset_points = [
                    (p[0] + offset, p[1] + offset) if isinstance(p, (tuple, list)) else p
                    for p in item.get("points", [])
                ]
                # 通过 controller 添加形状
                self.controller.set_mode(item["mode"])
                self.controller.set_label(item["label"])
                if hasattr(self.canvas, "add_shape_from_points"):
                    self.canvas.add_shape_from_points(
                        offset_points, item["mode"], item["label"]
                    )
                elif hasattr(self.canvas, "add_shape"):
                    self.canvas.add_shape(
                        offset_points, item["mode"], item["label"]
                    )
            except (ImportError, RuntimeError, OSError, ValueError):
                import logging
                logging.getLogger(__name__).exception("粘贴标注失败")
        self.status_changed.emit(tr("已粘贴"), f"{len(self._clipboard)} {tr('标注')}")


__all__ = ["LabelClipboardMixin"]
