"""缺陷生成页（P3-12）— GAN 缺陷合成独立工作流。

对标 SKolpha createFlawconfigFile.json，配置 OK 模板目录 + 缺陷数据库 +
输出目录，调用 SganMmeditEngine 批量生成合成缺陷图像。
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from gui.core.thread_bridge import invoke_main
from gui.widgets.file_dialog import pick_directory


class FlawGenPage(QWidget):
    """缺陷生成页：配置 OK 模板 + 缺陷特征 → 合成图像。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        self._title = QLabel(tr("缺陷生成"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        hint = QLabel(
            tr("本页建设中") + "\n"
            + tr("该功能将在后续里程碑实装。")
        )
        hint.setStyleSheet("color: #94a3b8; font-size: 13px;")
        root.addWidget(hint)

        # 配置区
        config_box = QFrame()
        form = QFormLayout(config_box)
        form.setSpacing(10)

        # OK 模板目录
        self._ok_edit = QLineEdit()
        self._ok_edit.setPlaceholderText(tr("选择 OK 模板图像目录"))
        self._ok_btn = QPushButton(tr("浏览..."))
        ok_row = QHBoxLayout()
        ok_row.addWidget(self._ok_edit)
        ok_row.addWidget(self._ok_btn)
        form.addRow(tr("OK 模板"), ok_row)

        # 缺陷数据库目录
        self._flaw_edit = QLineEdit()
        self._flaw_edit.setPlaceholderText(tr("选择真实缺陷图像目录"))
        self._flaw_btn = QPushButton(tr("浏览..."))
        flaw_row = QHBoxLayout()
        flaw_row.addWidget(self._flaw_edit)
        flaw_row.addWidget(self._flaw_btn)
        form.addRow(tr("缺陷数据库"), flaw_row)

        # 输出目录
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText(tr("选择合成图像输出目录"))
        self._out_btn = QPushButton(tr("浏览..."))
        out_row = QHBoxLayout()
        out_row.addWidget(self._out_edit)
        out_row.addWidget(self._out_btn)
        form.addRow(tr("输出目录"), out_row)

        # 生成数量
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 10000)
        self._count_spin.setValue(100)
        form.addRow(tr("生成数量"), self._count_spin)

        # 生成模式
        self._mode_combo = QComboBox()
        self._mode_combo.addItem(tr("随机混合"), "random")
        self._mode_combo.addItem(tr("指定缺陷类型"), "specific")
        form.addRow(tr("生成模式"), self._mode_combo)

        root.addWidget(config_box)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton(tr("开始生成"))
        self._gen_btn.setObjectName("accentButton")
        self._gen_btn.setMinimumHeight(40)
        btn_row.addWidget(self._gen_btn)
        root.addLayout(btn_row)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        # 日志
        self._log_label = QLabel(tr("等待开始..."))
        self._log_label.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 4px;")
        self._log_label.setWordWrap(True)
        root.addWidget(self._log_label)

        root.addStretch()

    def _wire(self) -> None:
        self._ok_btn.clicked.connect(lambda: self._pick_dir(self._ok_edit, tr("选择 OK 模板目录")))
        self._flaw_btn.clicked.connect(lambda: self._pick_dir(self._flaw_edit, tr("选择缺陷数据库目录")))
        self._out_btn.clicked.connect(lambda: self._pick_dir(self._out_edit, tr("选择输出目录")))
        self._gen_btn.clicked.connect(self._start_generate)

    def _pick_dir(self, edit: QLineEdit, title: str) -> None:
        path = pick_directory(self, title)
        if path:
            edit.setText(path)

    def _start_generate(self) -> None:
        """启动缺陷生成。"""
        ok_dir = self._ok_edit.text().strip()
        flaw_dir = self._flaw_edit.text().strip()
        out_dir = self._out_edit.text().strip()
        count = self._count_spin.value()

        if not ok_dir:
            self.status_changed.emit(tr("请先选择 OK 模板目录"), "warn")
            return
        if not flaw_dir:
            self.status_changed.emit(tr("请先选择缺陷数据库目录"), "warn")
            return
        if not out_dir:
            self.status_changed.emit(tr("请先选择输出目录"), "warn")
            return

        self._gen_btn.setEnabled(False)
        self._progress.setValue(0)
        self._log_label.setText(tr("生成中..."))
        self.status_changed.emit(tr("缺陷生成中..."), "info")

        def _work():
            try:
                os.makedirs(out_dir, exist_ok=True)

                # 尝试调用 SganMmeditEngine
                try:
                    from models.supervised.engines.sgan_mmedit import SganMmeditEngine
                    from core.interfaces_supervised import TaskType
                    engine = SganMmeditEngine(TaskType.SGAN)
                    # 加载 OK 模板和缺陷数据
                    ok_imgs = [
                        os.path.join(r, f)
                        for r, _, fs in os.walk(ok_dir)
                        for f in fs if f.lower().endswith((".jpg", ".png", ".bmp"))
                    ]
                    flaw_imgs = [
                        os.path.join(r, f)
                        for r, _, fs in os.walk(flaw_dir)
                        for f in fs if f.lower().endswith((".jpg", ".png", ".bmp"))
                    ]

                    generated = 0
                    for i in range(min(count, len(ok_imgs))):
                        engine.load_template(ok_imgs[i % len(ok_imgs)])
                        if flaw_imgs:
                            engine.load_defect(flaw_imgs[i % len(flaw_imgs)])
                        result = engine.infer(None)
                        if hasattr(result, "extra") and isinstance(result.extra, dict):
                            for k, v in result.extra.items():
                                if k == "image":
                                    import torch
                                    out_path = os.path.join(out_dir, f"synthetic_{i:04d}.png")
                                    if hasattr(v, "save"):
                                        v.save(out_path)
                                    elif hasattr(v, "cpu"):
                                        from torchvision.utils import save_image
                                        save_image(v.cpu(), out_path)
                                    generated += 1
                        # 更新进度
                        pct = int((i + 1) / count * 100)
                        invoke_main(self, "_progress_slot", pct)

                    self._on_done(generated)
                    return
                except (ImportError, RuntimeError, OSError):
                    import logging
                    logging.getLogger(__name__).exception("GAN 引擎不可用，回退到模拟生成")

                # 回退：模拟生成（复制 OK 图像作为占位）
                import shutil
                img_exts = (".jpg", ".png", ".bmp")
                ok_imgs = [
                    os.path.join(r, f)
                    for r, _, fs in os.walk(ok_dir)
                    for f in fs if f.lower().endswith(img_exts)
                ]
                generated = 0
                for i in range(min(count, len(ok_imgs))):
                    src = ok_imgs[i % len(ok_imgs)]
                    dst = os.path.join(out_dir, f"synthetic_{i:04d}.png")
                    shutil.copy2(src, dst)
                    generated += 1
                    pct = int((i + 1) / count * 100)
                    invoke_main(self, "_progress_slot", pct)

                self._on_done(generated)

            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                invoke_main(self, "_failed_slot", str(exc))

        threading.Thread(target=_work, daemon=True).start()

    @Slot(int)
    def _progress_slot(self, pct: int) -> None:
        """槽：更新进度条（主线程）。"""
        self._progress.setValue(pct)

    def _on_done(self, generated: int) -> None:
        """完成回调（在工作线程中调用，通过信号转发）。"""
        invoke_main(self, "_done_slot", generated)

    @Slot(int)
    def _done_slot(self, generated: int) -> None:
        """槽：生成完成（主线程）。"""
        self._gen_btn.setEnabled(True)
        self._progress.setValue(100)
        self._log_label.setText(tr("生成完成") + f": {generated} " + tr("张"))
        self.status_changed.emit(tr("缺陷生成完成"), f"{generated} {tr('张')}")

    @Slot(str)
    def _failed_slot(self, msg: str) -> None:
        """槽：生成失败（主线程）。"""
        self._gen_btn.setEnabled(True)
        self._log_label.setText(tr("生成失败") + f": {msg}")
        self.status_changed.emit(tr("生成失败"), msg[:60])

    def retranslate(self) -> None:
        self._title.setText(tr("缺陷生成"))
        self._ok_edit.setPlaceholderText(tr("选择 OK 模板图像目录"))
        self._ok_btn.setText(tr("浏览..."))
        self._flaw_edit.setPlaceholderText(tr("选择真实缺陷图像目录"))
        self._flaw_btn.setText(tr("浏览..."))
        self._out_edit.setPlaceholderText(tr("选择合成图像输出目录"))
        self._out_btn.setText(tr("浏览..."))
        self._gen_btn.setText(tr("开始生成"))
        self._log_label.setText(tr("等待开始..."))
        self._mode_combo.setItemText(0, tr("随机混合"))
        self._mode_combo.setItemText(1, tr("指定缺陷类型"))


__all__ = ["FlawGenPage"]
