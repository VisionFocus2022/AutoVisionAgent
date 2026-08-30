"""缺陷生成页（P3-12）— GAN 缺陷合成独立工作流。

对标 SKolpha createFlawconfigFile.json，配置 OK 模板目录 + 缺陷数据库 +
输出目录，经注册表调用 SGAN 引擎（W2: SganBlendEngine）批量生成合成缺陷图像。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
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
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_directory

logger = logging.getLogger(__name__)


class FlawGenPage(QWidget):
    """缺陷生成页：配置 OK 模板 + 缺陷特征 → 合成图像。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
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

        # （W28：删过期建设横幅——SGAN 引擎 W2 已真化，该话术不再成立）

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

        # （W28：删生成模式死下拉——"随机混合/指定缺陷类型"选择从未传给
        #  引擎 infer，纯装饰；引擎支持模式参数时再随接线建回）

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
        # P2-19：关键操作留痕（生成开始）
        logger.info(
            "缺陷生成开始：ok=%s，flaw=%s，out=%s，count=%d",
            ok_dir, flaw_dir, out_dir, count,
        )

        def _work():
            try:
                os.makedirs(out_dir, exist_ok=True)

                # W2: 经注册表取真化后的 SGAN 引擎（SganBlendEngine，seamlessClone 融合）。
                # 修复 P1-2：不再直接 SganMmeditEngine(TaskType.SGAN)（构造 TypeError 必崩），
                # 也不再复制占位图冒充生成结果——缺缺陷库由引擎诚实 raise。
                from core.exceptions import SupervisedEngineError
                from core.image_io import imwrite_unicode
                from core.interfaces_supervised import TaskType

                # registry 直连为 GUI 正式形态（v3 P2-7）
                from models.supervised.engines import register_all_engines
                from models.supervised.registry import get_engine

                register_all_engines()
                engine = get_engine(TaskType.SGAN)

                # 缺陷库 = 真实缺陷图目录；目录无效 → SupervisedEngineError → 失败提示
                # W28：device 走 resolve_device 契约（W19/W21 同款——cuda 可用
                # 透传/回退 cpu，lite 的 CPU torch 自动回退；原硬编码 "cpu"）
                from models.supervised.device import resolve_device
                engine.load(flaw_database=flaw_dir, device=resolve_device("cuda"))

                ok_imgs = [
                    os.path.join(r, f)
                    for r, _, fs in os.walk(ok_dir)
                    for f in fs if f.lower().endswith((".jpg", ".png", ".bmp"))
                ]
                if not ok_imgs:
                    invoke_main(self, "_failed_slot", tr("OK 模板目录为空"))
                    return

                generated = 0
                for i in range(min(count, len(ok_imgs))):
                    result = engine.infer(ok_imgs[i % len(ok_imgs)])
                    syn = (result.extra or {}).get("synthesized_image")
                    if syn is not None:
                        out_path = os.path.join(out_dir, f"synthetic_{i:04d}.png")
                        if imwrite_unicode(out_path, syn):  # 中文路径安全写图
                            generated += 1
                    # 更新进度
                    pct = int((i + 1) / count * 100)
                    invoke_main(self, "_progress_slot", pct)

                # P2-19：关键操作留痕（生成完成，一次一条；逐图仅进度无日志）
                logger.info("缺陷生成完成：%d 张 → %s", generated, out_dir)
                self._on_done(generated)

            except SupervisedEngineError as exc:
                # 诚实失败：引擎/缺陷库问题 → 明确报错（W2 删除"复制占位图"假回退）
                logger.warning("缺陷生成失败: %s", exc)
                invoke_main(self, "_failed_slot", str(exc))
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                invoke_main(self, "_failed_slot", str(exc))

        # W15-J2（P2-1 批次 A）：经 gui.core.jobs 统一调度——注册表登记 +
        # 协作取消 + 异常路由（_work 内两段 except 路由/文案不变）；
        # W17（v3 P2-1）：on_error 兜底——元组外异常也复位生成按钮
        run_job(
            _work, name="flaw_gen.generate",
            on_error=ui_on_error(self, "_failed_slot"),
        )

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


__all__ = ["FlawGenPage"]
