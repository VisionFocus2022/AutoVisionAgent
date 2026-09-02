"""批量模式动作 Mixin（W56 FR-003——页面 ≤800 行守卫，动作外置）。

对标 SKolpha：batchPredictThread（整批后台线程）↔ "batch" 模式；
batchPredictOnlyOne（逐张即时）↔ "incremental" 模式。并发微调仅作用于
batch 模式的后处理层（引擎前向恒串行——见 batch_runner 模块注释）。
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QSpinBox

from gui.core.i18n import tr

_BATCH_MODE_ITEMS = (
    ("batch", "整批完成"),
    ("incremental", "逐张即时"),
)


class BatchModeActionsMixin:
    """批量模式/并发选项控件组（构建 + 取值；无状态）。"""

    def _add_batch_options(self, h, bar) -> None:
        """向工具栏布局 h 追加模式/并发控件（页面 _build_ui 一行挂接）。"""
        h.addWidget(QLabel(tr("批量模式"), bar))
        self.cmb_batch_mode = QComboBox(bar)
        for value, text in _BATCH_MODE_ITEMS:
            self.cmb_batch_mode.addItem(tr(text), value)
        h.addWidget(self.cmb_batch_mode)

        h.addWidget(QLabel(tr("并发数"), bar))
        self.spin_batch_concurrency = QSpinBox(bar)
        self.spin_batch_concurrency.setRange(1, 4)
        self.spin_batch_concurrency.setValue(1)
        self.spin_batch_concurrency.setToolTip(
            tr("仅整批模式生效：并行渲染/产物写（需引擎支持批量推理）")
        )
        h.addWidget(self.spin_batch_concurrency)

        # W58-A（工程绑定）接线位：predictionParams{modelFile, threshold} 带入
        self.btn_from_project = QPushButton(tr("从项目带入"), bar)
        self.btn_from_project.setProperty("tool", True)
        self.btn_from_project.setEnabled(False)
        self.btn_from_project.setToolTip(tr("工程绑定后启用（预测参数带入）"))
        h.addWidget(self.btn_from_project)

    def batch_mode_value(self) -> str:
        """当前批量模式（"batch" | "incremental"）。"""
        return self.cmb_batch_mode.currentData() or "batch"

    def batch_concurrency_value(self) -> int:
        """后处理并发度（1-4）。"""
        return int(self.spin_batch_concurrency.value())


__all__ = ["BatchModeActionsMixin"]
