"""数据管理页：图像导入、浏览、划分、统计（FR-D4 / FR-E4）。

数据操作经 gui.pages.data_manage.workers 纯函数（导入/划分/标注批量
工具）与 dataset.format_export（YOLO/COCO 训练集导出）完成，重活统一在
gui.core.jobs 后台任务执行；项目目录绑定经 set_project_dir() 探测
images/annotations 布局（P2-22：撤销原文失实宣称，按实际依赖重写）。
"""
from __future__ import annotations

import logging
import os
import re

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# 支持的图像扩展名
from core.constants import IMG_EXTS as _IMG_EXTS
from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.permissions import check_action  # W39：动作门控（v6 P2-6 漏网收口）
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.pages.data_manage.version_compare import version_diff_text  # W39·v6 P3：规模守卫抽取
from gui.widgets.file_dialog import pick_directory
from gui.widgets.thumbnail_loader import ThumbnailTask

logger = logging.getLogger(__name__)

# 操作标识 → 完成消息标题（emit 时经 tr() 翻译，语言切换后仍正确）
_OP_TITLES = {
    "import": "导入完成",
    "split": "划分完成",
    "replace": "替换完成",
    "delete": "删除完成",
    "flip": "翻转完成",
    "cut": "切割完成",
    "export": "导出完成",
    # W19（v3 第三波 FR-4.2）：版本管理入口
    "snapshot": "快照完成",
}

# W20：自然排序——把路径切成 文本/数字 交替块。W22：文件名仅首个数字块按
# 数值（主序号 1<2<10），其后数字块按文本——位相关字段（时间戳）按文本即
# 按时间先后；全数值比较在数字块长短不一时跨长度错排（20 位 20240611… >
# 全部 17 位 20240613…），同序号组内日期倒跳＝"导入后顺序混乱"复发根因。
_NATURAL_CHUNK_RE = re.compile(r"(\d+)")


def _natural_key(path: str) -> tuple:
    """两级排序键：目录块全数值自然序 + 文件名首数字块数值、其后文本。

    re.split 恒产出 文本/数字 交替块（数字块固定落奇数位），文件名首数字
    块即其块元组下标 1——同位类型跨路径一致，元组比较不会 int/str 越型。
    """
    dir_part, _, name = path.replace("\\", "/").lower().rpartition("/")
    dir_key = tuple(
        int(c) if c.isdigit() else c for c in _NATURAL_CHUNK_RE.split(dir_part)
    )
    name_key = tuple(
        int(c) if i == 1 else c
        for i, c in enumerate(_NATURAL_CHUNK_RE.split(name))
    )
    return (dir_key, name_key)


class DataManagePage(QWidget):
    """数据管理页：导入图像 → 浏览缩略图 → 划分数据集 → 查看统计。"""

    status_changed = Signal(str, str)  # (text, accent) → 主壳状态栏

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")

        # 数据
        self._project_dir: str | None = None
        self._image_dir: str | None = None
        self._images: list[str] = []
        self._annotations_dir: str | None = None
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(4)
        self._thumb_items: dict[str, QListWidgetItem] = {}  # R5-5: path → item
        # W19（v3 第三波 FR-4.2）：最近一次版本对比对话框（非模态，供测试直读）
        self._diff_dialog = None

        self._build_ui()
        self._wire()

        # W3-T3: 重活操作 → 触发按钮（worker 执行期间禁用）
        # W17：补注册 stats——此前统计失败路径查不到按钮，btn_stat 不复位
        self._op_buttons: dict[str, QPushButton] = {
            "import": self.btn_import,
            "split": self.btn_split,
            "stats": self.btn_stat,
            "replace": self.btn_replace,
            "delete": self.btn_delete_lbl,
            "flip": self.btn_flip,
            "cut": self.btn_cut,
            "export": self.btn_export,
            # W19（v3 第三波 FR-4.2）：快照后台执行期间禁用按钮
            "snapshot": self.btn_snapshot,
        }

    # ============================== UI ============================== #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 顶部工具栏 ----
        root.addWidget(self._build_toolbar())

        # ---- 正文：缩略图 + 右侧统计 ----
        root.addLayout(self._build_body(), 1)

    def _build_toolbar(self) -> QFrame:
        """顶部工具栏：数据组（目录/导入/划分/刷新）+ 标注工具/导出组。"""
        bar = QFrame(self)
        bar.setObjectName("toolbar")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self._build_toolbar_data_group(bar, h)
        self._build_toolbar_label_group(bar, h)
        self._build_toolbar_version_group(bar, h)
        return bar

    def _build_toolbar_data_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏数据组：选择目录/导入 + 划分比例/模式 + 划分/刷新。"""
        self.btn_open_dir = QPushButton(tr("选择目录"), bar)
        self.btn_open_dir.setProperty("role", "accent")
        h.addWidget(self.btn_open_dir)

        self.btn_import = QPushButton(tr("导入图像"), bar)
        h.addWidget(self.btn_import)
        sep = QFrame(bar)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep)

        # 划分比例
        h.addWidget(QLabel(tr("训练"), bar))
        self.spin_train = QDoubleSpinBox(bar)
        self.spin_train.setRange(0.0, 1.0)
        self.spin_train.setSingleStep(0.05)
        self.spin_train.setValue(0.8)
        h.addWidget(self.spin_train)
        h.addWidget(QLabel(tr("验证"), bar))
        self.spin_val = QDoubleSpinBox(bar)
        self.spin_val.setRange(0.0, 1.0)
        self.spin_val.setSingleStep(0.05)
        self.spin_val.setValue(0.1)
        h.addWidget(self.spin_val)
        h.addWidget(QLabel(tr("测试"), bar))
        self.spin_test = QDoubleSpinBox(bar)
        self.spin_test.setRange(0.0, 1.0)
        self.spin_test.setSingleStep(0.05)
        self.spin_test.setValue(0.1)
        h.addWidget(self.spin_test)

        # R5-11: 划分模式选择
        h.addWidget(QLabel(tr("模式"), bar))
        self.cmb_split_mode = QComboBox(bar)
        self.cmb_split_mode.addItem(tr("复制"), "copy")
        self.cmb_split_mode.addItem(tr("移动"), "move")
        self.cmb_split_mode.addItem(tr("符号链接"), "symlink")
        self.cmb_split_mode.addItem(tr("文件列表"), "list")
        h.addWidget(self.cmb_split_mode)

        self.btn_split = QPushButton(tr("划分数据集"), bar)
        h.addWidget(self.btn_split)

        h.addStretch()

        self.btn_refresh = QPushButton(tr("刷新"), bar)
        h.addWidget(self.btn_refresh)

    def _build_toolbar_label_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏标注组：统计/替换/删除/翻转/切割 + 训练集导出。"""
        sep2 = QFrame(bar)
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep2)

        # 标注工具组（对标 SKolpha frontend.tools）
        self.btn_stat = QPushButton(tr("标注统计"), bar)
        h.addWidget(self.btn_stat)
        self.btn_replace = QPushButton(tr("替换标签"), bar)
        h.addWidget(self.btn_replace)
        self.btn_delete_lbl = QPushButton(tr("删除标签"), bar)
        h.addWidget(self.btn_delete_lbl)
        self.btn_flip = QPushButton(tr("翻转标注"), bar)
        h.addWidget(self.btn_flip)
        self.btn_cut = QPushButton(tr("切割标注"), bar)
        h.addWidget(self.btn_cut)

        # W5-T2: 训练集导出（LabelMe→YOLO/COCO，补齐标注→训练断链）
        self.cmb_export_fmt = QComboBox(bar)
        self.cmb_export_fmt.addItem(tr("YOLO 格式"), "yolo")
        self.cmb_export_fmt.addItem(tr("COCO 格式"), "coco")
        h.addWidget(self.cmb_export_fmt)
        self.btn_export = QPushButton(tr("导出训练集"), bar)
        h.addWidget(self.btn_export)

    def _build_toolbar_version_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏版本组：创建快照 + 版本对比（W19 v3 第三波 FR-4.2）。"""
        sep3 = QFrame(bar)
        sep3.setFixedWidth(1)
        sep3.setStyleSheet("background-color: #3f4452;")
        h.addWidget(sep3)

        self.btn_snapshot = QPushButton(tr("创建快照"), bar)
        h.addWidget(self.btn_snapshot)
        self.btn_diff = QPushButton(tr("版本对比"), bar)
        h.addWidget(self.btn_diff)

    def _build_body(self) -> QHBoxLayout:
        """正文：缩略图列表 + 右侧统计面板。"""
        body = QHBoxLayout()
        body.setSpacing(10)

        # 缩略图列表
        self.thumb_list = QListWidget(self)
        self.thumb_list.setViewMode(QListWidget.IconMode)
        self.thumb_list.setIconSize(QSize(120, 120))
        self.thumb_list.setResizeMode(QListWidget.Adjust)
        self.thumb_list.setSpacing(6)
        # W41：均一网格（icon 120 + 水平余量 12 / 垂直 icon+两行文字+余量）
        # ——无 gridSize/wrapping 时条目尺寸随内容浮动，行首左缘错位
        # （用户报障）；IconMode 下 wrapping=True 是 gridSize 生效前提
        self.thumb_list.setWrapping(True)
        self.thumb_list.setGridSize(QSize(132, 168))
        body.addWidget(self.thumb_list, 1)

        # 右侧统计面板
        panel = QFrame(self)
        panel.setFixedWidth(240)
        p = QVBoxLayout(panel)
        p.setContentsMargins(8, 8, 8, 8)
        p.setSpacing(8)

        p.addWidget(self._caption(tr("统计信息")))
        self.lbl_total = QLabel(tr("图像总数") + ": 0", panel)
        self.lbl_annotated = QLabel(tr("已标注") + ": 0", panel)
        self.lbl_unannotated = QLabel(tr("未标注") + ": 0", panel)
        for lbl in (self.lbl_total, self.lbl_annotated, self.lbl_unannotated):
            lbl.setStyleSheet("color: #cbd5e1; font-size: 13px;")
            p.addWidget(lbl)

        p.addWidget(self._caption(tr("类别计数")))
        self.lbl_classes = QLabel(tr("无数据"), panel)
        self.lbl_classes.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.lbl_classes.setWordWrap(True)
        p.addWidget(self.lbl_classes)

        p.addWidget(self._caption(tr("当前目录")))
        self.lbl_dir = QLabel(tr("未选择"), panel)
        self.lbl_dir.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_dir.setWordWrap(True)
        p.addWidget(self.lbl_dir)

        p.addStretch()
        body.addWidget(panel)
        return body

    @staticmethod
    def _caption(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            "color: #7c3aed; font-size: 13px; font-weight: bold;"
            " border-bottom: 1px solid #3f4452; padding-bottom: 4px;"
        )
        return lab

    # ============================== 接线 ============================== #
    def _wire(self) -> None:
        self.btn_open_dir.clicked.connect(self._select_dir)
        self.btn_import.clicked.connect(self._import_images)
        self.btn_split.clicked.connect(self._split_dataset)
        self.btn_refresh.clicked.connect(self._refresh)

        # 标注工具
        self.btn_stat.clicked.connect(self._tool_statistics)
        self.btn_replace.clicked.connect(self._tool_replace_label)
        self.btn_delete_lbl.clicked.connect(self._tool_delete_labels)
        self.btn_flip.clicked.connect(self._tool_flip_annotation)
        self.btn_cut.clicked.connect(self._tool_cut_json)
        self.btn_export.clicked.connect(self._tool_export_dataset)

        # W19（v3 第三波 FR-4.2）：版本管理入口
        self.btn_snapshot.clicked.connect(self._tool_snapshot)
        self.btn_diff.clicked.connect(self._tool_version_diff)

        # 比例联动：三者之和 = 1.0
        self.spin_train.valueChanged.connect(self._on_ratio_changed)
        self.spin_val.valueChanged.connect(self._on_ratio_changed)
        self.spin_test.valueChanged.connect(self._on_ratio_changed)

    def _on_ratio_changed(self) -> None:
        """保持三者之和 = 1.0（调整最后一个自动补偿）。"""
        total = self.spin_train.value() + self.spin_val.value() + self.spin_test.value()
        if abs(total - 1.0) > 0.001 and total > 0:
            # 归一化但不覆盖用户正在编辑的控件
            pass  # 仅在划分时校验

    # ============================== 行为 ============================== #
    def set_project_dir(self, path: str) -> None:
        """设置项目根目录，自动定位 images/ 子目录。"""
        self._project_dir = path
        img_dir = os.path.join(path, "images")
        ann_dir = os.path.join(path, "annotations")
        if os.path.isdir(img_dir):
            self._image_dir = img_dir
        else:
            self._image_dir = path
        if os.path.isdir(ann_dir):
            self._annotations_dir = ann_dir
        else:
            self._annotations_dir = None
        self._refresh()

    def _select_dir(self) -> None:
        """选择数据目录。"""
        path = pick_directory(
            self, "选择数据目录"
        )
        if not path:
            return
        self._image_dir = path
        ann = os.path.join(os.path.dirname(path), "annotations")
        if os.path.isdir(ann):
            self._annotations_dir = ann
        self._refresh()
        self.status_changed.emit(
            tr("已选择目录"), path.replace("\\", "/").split("/")[-1]
        )

    def _import_images(self) -> None:
        """从外部目录导入图像到当前数据目录（W3-T3: worker 线程执行复制）。"""
        if not self._image_dir:
            self.status_changed.emit(tr("请先选择目录"), "!")
            return
        src = pick_directory(
            self, "选择导入源目录"
        )
        if not src:
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "import",
            lambda: workers.import_images(src, self._image_dir),
            lambda n: f"{n} {tr('张')}",
        )

    def _split_dataset(self) -> None:
        """在数据目录下创建 train/val/test 子目录结构（W3-T3: worker 线程执行）。"""
        if not self._image_dir:
            self.status_changed.emit(tr("请先选择目录"), "!")
            return
        r_train = self.spin_train.value()
        r_val = self.spin_val.value()
        r_test = self.spin_test.value()
        total = r_train + r_val + r_test
        if abs(total - 1.0) > 0.001:
            self.status_changed.emit(
                tr("比例之和必须为1.0"), f"{total:.2f}"
            )
            return

        base = self._image_dir
        images = [
            f for f in os.listdir(base)
            if f.lower().endswith(_IMG_EXTS)
        ]
        if not images:
            self.status_changed.emit(tr("无图像可划分"), "!")
            return

        mode = self.cmb_split_mode.currentData() or "copy"
        from PySide6.QtWidgets import QMessageBox
        _mode_desc = {
            "copy": tr("复制"),
            "move": tr("移动"),
            "symlink": tr("符号链接"),
            "list": tr("文件列表"),
        }.get(mode, tr("复制"))
        reply = QMessageBox.question(
            self, tr("确认划分"),
            tr(f"将({_mode_desc})图像划分到 train/val/test 子目录。确认？"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "split",
            lambda: workers.split_dataset(base, r_train, r_val, r_test, mode),
            lambda t: f"T{t[0]}/V{t[1]}/T{t[2]}",
        )

    # ============================== worker 基础设施（W3-T3） ============================== #
    def _run_worker(self, op: str, work, fmt) -> None:
        """在 worker 线程执行 work()，完成后经 invoke_main 回主线程。

        Args:
            op: 操作标识（用于恢复对应按钮与完成标题）。
            work: 无参重活函数（worker 线程执行）。
            fmt: 结果 → 状态栏消息的格式化函数。
        """
        btn = self._op_buttons.get(op)
        if btn is not None:
            btn.setEnabled(False)

        def _wrapper():
            try:
                result = work()
            except (OSError, ValueError, RuntimeError) as exc:
                invoke_main(self, "_op_failed", op, str(exc))
                return
            if op in ("import", "split"):
                # P2-19：关键数据操作留痕（一次一条，无逐图刷屏）
                logger.info("%s：%s", _OP_TITLES.get(op, op), result)
            invoke_main(self, "_op_done", op, fmt(result))

        # W15-J2（P2-1 批次 A）：经 gui.core.jobs 统一调度——注册表登记 +
        # 协作取消 + 异常路由（wrapper 内 expected 异常元组/时序/文案不变）；
        # W17（v3 P2-1）：on_error 兜底——元组外异常经 _op_failed(op, err) 复位按钮
        run_job(
            _wrapper, name=f"data_manage.{op}",
            on_error=ui_on_error(self, "_op_failed", op),
        )

    @Slot(str, str)
    def _op_done(self, op: str, msg: str) -> None:
        """槽：worker 完成（主线程）——恢复按钮并刷新。"""
        btn = self._op_buttons.get(op)
        if btn is not None:
            btn.setEnabled(True)
        self._refresh()
        self.status_changed.emit(tr(_OP_TITLES.get(op, op)), msg)

    @Slot(str, str)
    def _op_failed(self, op: str, err: str) -> None:
        """槽：worker 失败（主线程）——恢复按钮并报错。"""
        btn = self._op_buttons.get(op)
        if btn is not None:
            btn.setEnabled(True)
        self.status_changed.emit(tr("操作失败"), err[:60])

    def _refresh(self) -> None:
        """重新扫描目录，刷新缩略图与统计。"""
        self.thumb_list.clear()
        if not self._image_dir or not os.path.isdir(self._image_dir):
            self.lbl_dir.setText(tr("未选择"))
            self._update_stats(0, 0, {})
            return

        self.lbl_dir.setText(self._image_dir)
        # W20-2：顶层=活动数据集；划分副本不与根目录同屏重复（语义见
        # workers.collect_display_images）
        from gui.pages.data_manage import workers as _dm_workers

        images, display_names, hidden = _dm_workers.collect_display_images(
            self._image_dir
        )
        # W20：确定性自然排序（否则展示序跟随文件系统枚举序，见 _natural_key 注释）
        images.sort(key=_natural_key)
        self._images = images

        # R5-5: 异步加载缩略图（限制前 200 张避免卡顿）
        self._thumb_items.clear()
        self._thumb_pool.clear()  # 取消上一批未完成的任务
        for img_path in images[:200]:
            item = QListWidgetItem(
                display_names.get(img_path, os.path.basename(img_path))
            )
            self.thumb_list.addItem(item)
            self._thumb_items[img_path] = item
            task = ThumbnailTask(img_path, size=120)
            task.signals.loaded.connect(self._on_thumbnail_loaded)
            self._thumb_pool.start(task)

        if hidden:
            note = QListWidgetItem(
                f"{tr('已隐藏子目录图像')} {hidden} {tr('张')}"
            )
            note.setFlags(Qt.NoItemFlags)
            self.thumb_list.addItem(note)

        if len(images) > 200:
            more = QListWidgetItem(f"... {len(images) - 200} {tr('张更多')}")
            more.setFlags(Qt.NoItemFlags)
            self.thumb_list.addItem(more)

        # 统计已标注数
        ann_count = 0
        if self._annotations_dir and os.path.isdir(self._annotations_dir):
            ann_count = len([
                f for f in os.listdir(self._annotations_dir)
                if f.endswith(".json")
            ])

        self._update_stats(len(images), ann_count, {})
        self.status_changed.emit(tr("就绪"), f"{len(images)} {tr('张')}")

    def _on_thumbnail_loaded(self, path: str, image: QImage) -> None:
        """R5-5: 缩略图异步加载回调（W9: QImage 主线程转 QIcon）。"""
        item = self._thumb_items.get(path)
        if item is not None:
            item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _update_stats(
        self, total: int, annotated: int, classes: dict[str, int]
    ) -> None:
        """更新统计面板。"""
        self.lbl_total.setText(f"{tr('图像总数')}: {total}")
        self.lbl_annotated.setText(f"{tr('已标注')}: {annotated}")
        self.lbl_unannotated.setText(f"{tr('未标注')}: {total - annotated}")
        if classes:
            text = "\n".join(f"{k}: {v}" for k, v in classes.items())
            self.lbl_classes.setText(text)
        else:
            self.lbl_classes.setText(tr("无数据"))

    # ============================== 标注批量工具 ============================== #
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
        text = "\n".join(f"{k}: {v}" for k, v in stats.items())
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

    def _tool_flip_annotation(self) -> None:
        """翻转标注坐标（配合图像翻转）（W3-T3: worker 线程执行）。"""
        denied = check_action("data_manage.batch_label_edit")
        if denied:
            self.status_changed.emit(denied, "!")
            return
        d = self._get_ann_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog
        items = ["horizontal", "vertical"]
        mode, ok = QInputDialog.getItem(
            self, tr("翻转标注"), tr("翻转模式:"), items, 0, False
        )
        if not ok:
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "flip",
            lambda: workers.flip_annotations(d, mode),
            lambda n: f"{n} {tr('个文件')}",
        )

    def _tool_cut_json(self) -> None:
        """切割标注 JSON（大图切小图时同步切割标注）（W3-T3: worker 线程执行）。"""
        d = self._get_ann_dir()
        if not d:
            return
        from PySide6.QtWidgets import QInputDialog
        tile_str, ok = QInputDialog.getText(
            self, tr("切割标注"), tr("瓦片大小 (宽x高，如 640x640):")
        )
        if not ok or not tile_str:
            return
        try:
            parts = tile_str.lower().split("x")
            tile_w, tile_h = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            self.status_changed.emit(tr("格式错误"), "!")
            return
        from gui.pages.data_manage import workers

        self._run_worker(
            "cut",
            lambda: workers.cut_annotations(d, tile_w, tile_h),
            lambda n: f"{n} {tr('个瓦片')}",
        )

    def _tool_export_dataset(self) -> None:
        """导出训练集：LabelMe → YOLO/COCO（W5-T2，worker 线程执行）。"""
        d = self._get_ann_dir()
        if not d:
            return
        img_dir = self._image_dir or d
        out_root = pick_directory(self, "选择导出输出目录")
        if not out_root:
            return
        fmt = self.cmb_export_fmt.currentData() or "yolo"
        from dataset.format_export import labelme_dir_to_coco, labelme_dir_to_yolo

        if fmt == "coco":
            def work():
                return labelme_dir_to_coco(
                    img_dir, d,
                    os.path.join(out_root, "coco", "annotations.json"),
                )
        else:
            def work():
                return labelme_dir_to_yolo(
                    img_dir, d, os.path.join(out_root, "yolo")
                )

        self._run_worker(
            "export",
            work,
            lambda s: (
                f"{s.images} {tr('张')} / {s.labels} {tr('标注数')}"
                f" / {tr('跳过')} {s.skipped}"
            ),
        )

    # ============================== 版本管理（W19 v3 第三波 FR-4.2） ============================== #
    def _tool_snapshot(self) -> None:
        """创建项目快照（run_job 后台执行，on_error 兜底复位）。"""
        if not self._project_dir or not os.path.isdir(self._project_dir):
            self.status_changed.emit(tr("请先设置项目目录"), "!")
            return
        from project import versioning

        root = self._project_dir
        self._run_worker(
            "snapshot",
            lambda: versioning.create_snapshot(root, "manual"),
            lambda snap_dir: os.path.basename(snap_dir),
        )

    def _tool_version_diff(self) -> None:
        """版本对比：最近两个快照的 diff 摘要（非模态 QDialog 展示）。"""
        if not self._project_dir or not os.path.isdir(self._project_dir):
            self.status_changed.emit(tr("请先设置项目目录"), "!")
            return
        from project import versioning

        snaps = versioning.list_snapshots(self._project_dir)
        if len(snaps) < 2:
            self.status_changed.emit(
                tr("快照不足两个，无法对比"), f"{len(snaps)}"
            )
            return
        (old_dir, old_label, _), (new_dir, new_label, _) = snaps[-2], snaps[-1]
        try:
            diff = versioning.diff_manifests(
                versioning.load_manifest(old_dir),
                versioning.load_manifest(new_dir),
            )
        except ValueError as exc:
            self.status_changed.emit(tr("快照清单读取失败"), str(exc)[:60])
            return

        from PySide6.QtWidgets import QDialog, QTextEdit

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("版本对比"))
        lay = QVBoxLayout(dlg)
        view = QTextEdit(dlg)
        view.setObjectName("diffText")
        view.setReadOnly(True)
        view.setPlainText(
            f"{tr('旧')} {old_label} → {tr('新')} {new_label}\n\n"
            + self._version_diff_text(diff)
        )
        lay.addWidget(view)
        self._diff_dialog = dlg
        # 非模态：不阻塞主线程（offscreen 测试可直接读文本）
        dlg.show()
        total = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
        self.status_changed.emit(
            tr("版本对比完成"), f"{total} {tr('处差异')}"
        )

    def _version_diff_text(self, diff: dict) -> str:
        """diff 摘要文本（W39 抽出至 version_compare 模块，薄委托保测试缝）。"""
        return version_diff_text(diff)

    def retranslate(self) -> None:
        """切换语言时刷新文案。"""
        self.btn_open_dir.setText(tr("选择目录"))
        self.btn_import.setText(tr("导入图像"))
        self.btn_split.setText(tr("划分数据集"))
        self.btn_refresh.setText(tr("刷新"))
        self.btn_stat.setText(tr("标注统计"))
        self.btn_replace.setText(tr("替换标签"))
        self.btn_delete_lbl.setText(tr("删除标签"))
        self.btn_flip.setText(tr("翻转标注"))
        self.btn_cut.setText(tr("切割标注"))
        self.btn_export.setText(tr("导出训练集"))
        self.btn_snapshot.setText(tr("创建快照"))
        self.btn_diff.setText(tr("版本对比"))
        self.cmb_export_fmt.setItemText(0, tr("YOLO 格式"))
        self.cmb_export_fmt.setItemText(1, tr("COCO 格式"))
        self._refresh()


__all__ = ["DataManagePage"]
