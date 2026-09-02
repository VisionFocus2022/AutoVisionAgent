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
            tr("整批模式生效：并行渲染/产物写（需引擎支持批量推理）")
        )
        h.addWidget(self.spin_batch_concurrency)

        # W58-A（工程绑定 FR-005）：带入 predictionParams{modelFile, threshold}
        # 按钮常启——无项目时点击走「请先选择项目」诚实报错（不玩 MRO 遮蔽）
        self.btn_from_project = QPushButton(tr("从项目带入"), bar)
        self.btn_from_project.setProperty("tool", True)
        self.btn_from_project.clicked.connect(self._bring_from_project)
        h.addWidget(self.btn_from_project)

        self.btn_save_binding = QPushButton(tr("保存绑定"), bar)
        self.btn_save_binding.setProperty("tool", True)
        self.btn_save_binding.clicked.connect(self._save_binding)
        h.addWidget(self.btn_save_binding)

    def _bring_from_project(self) -> None:
        """从项目绑定带入模型与阈值（predictionParams 对标）。"""
        import os as _os

        from project.binding import read_binding

        if not self._project_dir:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        binding = read_binding(self._project_dir)
        if not binding.model_file or not _os.path.exists(binding.model_file):
            self.status_changed.emit(
                tr("工程未绑定模型"),
                tr("请先在项目中训练模型或手动保存绑定"),
            )
            return
        # 复核 LOW 修正：加载失败时状态栏已发失败原因——此处直接返回，
        # 不再覆盖成功文案（旧实现无条件报「已从项目带入」）
        if not self._load_model_from(binding.model_file):
            return
        if binding.threshold is not None:
            self.spin_threshold.setValue(binding.threshold)
        self.status_changed.emit(
            tr("已从项目带入"), _os.path.basename(binding.model_file)
        )

    def _save_binding(self) -> None:
        """把当前模型+阈值存入项目绑定（读改写保留 transferType/dataPath）。"""
        from project.binding import update_binding

        if not self._project_dir:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        try:
            update_binding(
                self._project_dir,
                model_file=self._model_path or "",
                threshold=self._threshold(),
            )
        except OSError as exc:
            self.status_changed.emit(tr("保存绑定失败"), str(exc)[:40])
            return
        self.status_changed.emit(tr("已保存绑定"), self._project_dir[-40:])

    def batch_mode_value(self) -> str:
        """当前批量模式（"batch" | "incremental"）。"""
        return self.cmb_batch_mode.currentData() or "batch"

    def batch_concurrency_value(self) -> int:
        """后处理并发度（1-4）。"""
        return int(self.spin_batch_concurrency.value())


__all__ = ["BatchModeActionsMixin"]
