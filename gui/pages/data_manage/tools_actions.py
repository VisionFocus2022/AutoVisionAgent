"""标注工具动作 Mixin（W60——data_manage 页 800 行守卫，动作外置）。

自页面抽取的存量三件（统计/替换/删除，含 _get_ann_dir/_stats_done）
+ W60 新增次批三件（裁剪数据集/照片尾缀修改/数据清洗）。页面经
class bases 挂接；按钮点击接线留在页面 _wire（MRO 解析到本 Mixin），
新按钮在 _add_extra_tool_buttons 内自接。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QPushButton

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.permissions import check_action
from gui.core.thread_bridge import invoke_main, ui_on_error


class LabelToolsMixin:
    """标注批量工具组（统计/替换/删除 存量 + 裁剪/尾缀/清洗 W60）。"""

    def _get_ann_dir(self) -> str | None:
        """获取标注目录（优先 annotations/，否则用图像目录）。"""
        d = self._annotations_dir or self._image_dir
        if not d or not os.path.isdir(d):
            self.status_changed.emit(tr("请先选择目录"), "!")
            return None
        return d

    def _tool_statistics(self) -> None:
        """标注数据统计：各类别数量分布（W3-T3: worker 线程扫描）。"""
        d = self._get_ann_dir()
        if not d:
            return
        from gui.pages.data_manage import workers
        self.btn_stat.setEnabled(False)

        def _work():
            try:
                stats = workers.label_statistics(d)
            except (OSError, ValueError, RuntimeError) as exc:
                invoke_main(self, "_op_failed", "stats", str(exc))
                return
            invoke_main(self, "_stats_done", stats if stats else {})

        # W15-J2（P2-1 批次 A）：同上，经 jobs 统一调度；W17 on_error 兜底
        run_job(
            _work, name="data_manage.stats",
            on_error=ui_on_error(self, "_op_failed", "stats"),
        )

    @Slot(dict)
    def _stats_done(self, stats: dict) -> None:
        """槽：统计完成（主线程）。"""
        self.btn_stat.setEnabled(True)
        if not stats:
            self.status_changed.emit(tr("无标注数据"), "!")
            return
        text = "\n".join(f"{k}: {v['count']} ·均{v['avg_area']:.0f}px²" for k, v in stats.items())
        self.lbl_classes.setText(text)
        self.status_changed.emit(tr("标注统计"), f"{len(stats)} {tr('个类别')}")

    def _tool_replace_label(self) -> None:
        """批量替换标签名（W3-T3: worker 线程执行）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._get_ann_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog
        old_label, ok = QInputDialog.getText(self, tr("替换标签"), tr("旧标签名:"))
        if not ok or not old_label:
            return
        new_label, ok = QInputDialog.getText(self, tr("替换标签"), tr("新标签名:"))
        if not ok or not new_label:
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "replace",
            lambda: workers.replace_labels(d, old_label, new_label),
            lambda n: f"{n} {tr('个文件')}",
        )

    def _tool_delete_labels(self) -> None:
        """批量删除指定标签名的标注（W3-T3: worker 线程执行）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._get_ann_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, tr("删除标签"), tr("要删除的标签名（逗号分隔）:")
        )
        if not ok or not text:
            return
        labels = [s.strip() for s in text.split(",") if s.strip()]
        from gui.pages.data_manage import workers

        self._run_worker(
            "delete",
            lambda: workers.delete_labels(d, labels),
            lambda n: f"{n} {tr('个文件')}",
        )

    # ============================== W60 次批三件 ============================== #

    def _add_extra_tool_buttons(self, bar, h) -> None:
        """工具栏次批按钮组（W60：裁剪数据集/修改尾缀/数据清洗）。"""
        self.btn_crop_ds = QPushButton(tr("裁剪数据集"), bar)
        self.btn_crop_ds.setProperty("tool", True)
        self.btn_crop_ds.clicked.connect(self._tool_crop_dataset)
        h.addWidget(self.btn_crop_ds)

        self.btn_suffix = QPushButton(tr("修改尾缀"), bar)
        self.btn_suffix.setProperty("tool", True)
        self.btn_suffix.clicked.connect(self._tool_rename_suffix)
        h.addWidget(self.btn_suffix)

        self.btn_clean = QPushButton(tr("数据清洗"), bar)
        self.btn_clean.setProperty("tool", True)
        self.btn_clean.clicked.connect(self._tool_clean_dataset)
        h.addWidget(self.btn_clean)

    def _require_image_dir(self) -> str | None:
        """图像目录前置校验（次批三件共用）。"""
        d = self._image_dir
        if not d or not os.path.isdir(d):
            self.status_changed.emit(tr("请先选择目录"), "!")
            return None
        return d

    def _tool_crop_dataset(self) -> None:
        """裁剪数据集：图像+标注配对瓦片（对话框取瓦片尺寸）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._require_image_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog

        tile_w, ok1 = QInputDialog.getInt(
            self, tr("裁剪数据集"), tr("瓦片宽:"), 640, 32, 8192
        )
        if not ok1:
            return
        tile_h, ok2 = QInputDialog.getInt(
            self, tr("裁剪数据集"), tr("瓦片高:"), 640, 32, 8192
        )
        if not ok2:
            return
        from gui.pages.data_manage import workers

        ann_dir = self._annotations_dir
        self.btn_crop_ds.setEnabled(False)

        def _work():
            try:
                imgs, jsons = workers.crop_dataset(
                    d, tile_w, tile_h, ann_dir=ann_dir
                )
            except (OSError, ValueError, RuntimeError) as exc:
                invoke_main(self, "_op_failed", "crop_ds", str(exc))
                return
            invoke_main(
                self, "_extra_tool_done", "crop_ds",
                f"{imgs} {tr('图瓦片')} / {jsons} {tr('标注瓦片')} → tiles/",
            )

        run_job(
            _work, name="data_manage.crop_dataset",
            on_error=ui_on_error(self, "_op_failed", "crop_ds"),
        )

    def _tool_rename_suffix(self) -> None:
        """照片尾缀修改：批量改扩展名（同名标注不动）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._require_image_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog

        old_ext, ok1 = QInputDialog.getText(
            self, tr("修改尾缀"), tr("旧后缀（如 .JPG）:")
        )
        if not ok1 or not old_ext.strip():
            return
        new_ext, ok2 = QInputDialog.getText(
            self, tr("修改尾缀"), tr("新后缀（如 .jpg）:")
        )
        if not ok2 or not new_ext.strip():
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "suffix",
            lambda: workers.rename_image_suffix(d, old_ext, new_ext),
            lambda n: f"{n} {tr('个文件')}",
        )

    def _tool_clean_dataset(self) -> None:
        """数据清洗：坏图/孤立标注扫描，确认后隔离移入 _trash（可逆）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._require_image_dir()
        if not d:
            return
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, tr("数据清洗"),
            tr("清洗将把损坏图像与孤立标注移入 _trash 子目录（可恢复），确认执行？"),
        )
        if answer != QMessageBox.Yes:
            return
        from gui.pages.data_manage import workers

        ann_dir = self._annotations_dir
        self.btn_clean.setEnabled(False)

        def _work():
            try:
                report = workers.clean_dataset(
                    d, ann_dir=ann_dir, quarantine="_trash"
                )
            except (OSError, ValueError, RuntimeError) as exc:
                invoke_main(self, "_op_failed", "clean", str(exc))
                return
            invoke_main(
                self, "_extra_tool_done", "clean",
                f"{tr('损坏')} {report['corrupt']} / "
                f"{tr('孤立标注')} {report['orphan_json']} / "
                f"{tr('已隔离')} {report['moved']}",
            )

        run_job(
            _work, name="data_manage.clean_dataset",
            on_error=ui_on_error(self, "_op_failed", "clean"),
        )

    @Slot(str, str)
    def _extra_tool_done(self, op: str, message: str) -> None:
        """槽：次批工具完成（主线程）——恢复按钮并汇报。"""
        btn = getattr(self, {
            "crop_ds": "btn_crop_ds", "clean": "btn_clean",
        }.get(op, ""), None)
        if btn is not None:
            btn.setEnabled(True)
        self.status_changed.emit(tr("完成"), message)


__all__ = ["LabelToolsMixin"]
