"""标注页：画布 + 工具栏 + 标签列表 + 图像文件列表 + 撤销/重做 + LabelMe 存盘（FR-C/D）。

对标 SKolpha：支持选择文件夹批量加载图像，左侧文件列表浏览切换。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QSize, QThreadPool, QTimer, Slot
from PySide6.QtGui import QKeySequence, QShortcut, QPixmap, QIcon, QImage
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from labeling import AnnotationMode, Shape, save_labelme
from core.exceptions import AnnotationIOError
from labeling.canvas import AnnotationCanvas
from labeling.controller import AnnotationController
from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_open_file, pick_save_file, pick_directory
from gui.widgets.thumbnail_loader import ThumbnailTask

from core.constants import IMG_EXTS as _IMG_EXTS

logger = logging.getLogger(__name__)

# 模式定义：(mode, 按钮文本键, 快捷键)
_MODES = [
    (AnnotationMode.POLYGON, "多边形", "Q"),
    (AnnotationMode.RECTANGLE, "矩形", "R"),
    (AnnotationMode.BRUSH, "画笔", "P"),
    (AnnotationMode.KEYPOINT, "关键点", "K"),
    (AnnotationMode.INTERACTIVE, "交互式", "I"),
]


def det_engine_available() -> bool:
    """检查已注册的 DET 引擎是否可用（registry 直连为 GUI 正式形态，v3 P2-7）。"""
    try:
        from models.supervised.registry import get_default_registry
        from core.interfaces_supervised import TaskType
        return bool(get_default_registry().has(TaskType.DET))
    except (ImportError, RuntimeError, OSError, ValueError):
        return False


def run_ai_prelabel(image_path: str) -> List:
    """AI 预标注纯工作函数（W3-T3 自 _ai_prelabel 抽出，无 Qt 依赖）。

    registry 直连为 GUI 正式形态（v3 P2-7）：仅用已注册的 DET 引擎推理。
    W18 诚实化：零样本 dispatcher 回退桥已删（零样本未实装，回退必失败）；
    引擎不可用由页面 det_engine_available 预检在状态栏明示，此处仅兜底
    返回空列表并记 WARNING，不留静默路径。
    返回 Shape 列表（可能为空）。
    """
    try:
        # registry 直连为 GUI 正式形态（v3 P2-7）
        from models.supervised.registry import get_default_registry
        from core.interfaces_supervised import TaskType
        reg = get_default_registry()
        if not reg.has(TaskType.DET):
            logger.warning("AI 预标注跳过：无已注册 DET 引擎（零样本未实装）")
            return []
        engine = reg.get(TaskType.DET)
        from core.image_io import imread_unicode
        img = imread_unicode(image_path)
        if img is None:
            logger.warning("AI 预标注跳过：图像读取失败 %s", image_path)
            return []
        result = engine.infer(img)
        # 真引擎 boxes 是 numpy 数组——不得做真值判断（歧义异常，W9 修复）
        if result.boxes is None or len(result.boxes) == 0:
            return []
        label = result.labels[0] if result.labels else "defect"
        return [
            Shape(
                AnnotationMode.RECTANGLE,
                ((float(box[0]), float(box[1])),
                 (float(box[2]), float(box[3]))),
                label=label,
            )
            for box in result.boxes
        ]
    except (ImportError, RuntimeError, OSError, ValueError):
        logger.exception("AI 预标注失败")
        return []


class _ZoomableView(QGraphicsView):
    """可缩放/平移的标注画布视图（对标 SKolpha 画布缩放）。

    通过子类化重写鼠标事件并委托给 controller，避免 monkey-patch 在
    PySide6 中无法可靠拦截 C++ vtable 事件分发的问题。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 默认手型平移（中键/无标注模式时使用）
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self._zoom_factor = 1.15
        self._controller: Optional[AnnotationController] = None

    def set_controller(self, controller: AnnotationController) -> None:
        """注入标注控制器，接管鼠标事件分发。"""
        self._controller = controller

    def set_draw_mode(self, active: bool) -> None:
        """根据是否处于"绘制标注"模式切换 dragMode。

        绘制模式下用 NoDrag，避免左键拖拽被基类解释为画布平移，
        导致 controller 收不到完整的鼠标按下/拖拽/释放事件流。
        非绘制模式下恢复 ScrollHandDrag，保留手型平移体验。
        """
        self.setDragMode(QGraphicsView.NoDrag if active else QGraphicsView.ScrollHandDrag)

    def wheelEvent(self, event) -> None:
        """Ctrl+滚轮缩放，普通滚轮由父类处理（滚动条）。"""
        if event.modifiers() & Qt.ControlModifier:
            factor = (
                self._zoom_factor
                if event.angleDelta().y() > 0
                else 1 / self._zoom_factor
            )
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._controller is not None:
            self._controller.on_mouse_press(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._controller is not None:
            self._controller.on_mouse_move(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._controller is not None:
            self._controller.on_mouse_release(event)
        else:
            super().mouseReleaseEvent(event)


class LabelPage(QWidget):
    """标注画布页（实装页）— 支持文件夹批量加载。"""

    status_changed = Signal(str, str)  # (text, accent) -> 主壳状态栏

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        # 数据层
        self.canvas = AnnotationCanvas()
        self.canvas.set_blank(800, 600)
        self.controller = AnnotationController(
            self.canvas, mode=AnnotationMode.POLYGON, label="defect"
        )
        self._image_path: Optional[str] = None
        self._mode_btns: Dict[AnnotationMode, QPushButton] = {}

        # 图像文件列表
        self._image_files: List[str] = []
        self._current_index: int = -1

        # 标注剪贴板（copy/paste）
        self._clipboard: List = []

        # R5-5: 异步缩略图加载
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(4)
        self._thumb_items: Dict[str, "QListWidgetItem"] = {}

        # W4-T3 (P2-6): SAM 交互式标注接线状态
        self._sam_adapter = None
        self._sam_busy = False
        self._pending_sam_image = None

        self._build_ui()
        self._wire()
        self._apply_mode(AnnotationMode.POLYGON)

    # ------------------------------ UI ------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 顶部工具栏
        root.addWidget(self._build_toolbar())

        # 正文：左侧文件列表 + 画布 + 右侧面板
        root.addWidget(self._build_body_splitter(), 1)

    def _build_toolbar(self) -> QFrame:
        """顶部工具栏：打开/翻页/模式组 + 编辑/AI 预标注/保存组。"""
        bar = QFrame(self)
        bar.setObjectName("toolbar")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self._build_toolbar_nav_group(bar, h)
        self._build_toolbar_action_group(bar, h)
        return bar

    def _build_toolbar_nav_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏导航组：打开文件/文件夹 + 翻页 + 标注模式按钮。"""
        self.btn_open_folder = QPushButton(tr("打开文件夹"), bar)
        self.btn_open_folder.setProperty("role", "accent")
        h.addWidget(self.btn_open_folder)

        self.btn_open_file = QPushButton(tr("打开图像"), bar)
        h.addWidget(self.btn_open_file)

        self.btn_prev = QPushButton(tr("上一张"), bar)
        self.btn_prev.setProperty("tool", True)
        h.addWidget(self.btn_prev)

        self.btn_next = QPushButton(tr("下一张"), bar)
        self.btn_next.setProperty("tool", True)
        h.addWidget(self.btn_next)

        self.lbl_pos = QLabel("0 / 0", bar)
        self.lbl_pos.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.lbl_pos.setFixedWidth(80)
        self.lbl_pos.setAlignment(Qt.AlignCenter)
        h.addWidget(self.lbl_pos)

        sep1 = self._sep(bar)
        h.addWidget(sep1)

        for mode, label_key, key in _MODES:
            btn = QPushButton(f"{tr(label_key)}  {key}", bar)
            btn.setProperty("tool", True)
            btn.setProperty("active", False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=mode: self._apply_mode(m))
            self._mode_btns[mode] = btn
            h.addWidget(btn)

    def _build_toolbar_action_group(self, bar: QWidget, h: QHBoxLayout) -> None:
        """工具栏编辑组：撤销/重做/删除/清空 + AI 预标注/显隐 + 保存。"""
        sep2 = self._sep(bar)
        h.addWidget(sep2)

        self.btn_undo = self._tbtn(bar, tr("撤销"))
        self.btn_redo = self._tbtn(bar, tr("重做"))
        self.btn_delete = self._tbtn(bar, tr("删除"))
        self.btn_clear = self._tbtn(bar, tr("清空"))
        for b in (self.btn_undo, self.btn_redo, self.btn_delete, self.btn_clear):
            h.addWidget(b)

        sep3 = self._sep(bar)
        h.addWidget(sep3)

        self.btn_ai_prelabel = self._tbtn(bar, tr("AI预标注") + "  W")
        self.btn_ai_prelabel.setProperty("role", "accent")
        h.addWidget(self.btn_ai_prelabel)

        self.btn_toggle_shapes = self._tbtn(bar, tr("显隐标注"))
        h.addWidget(self.btn_toggle_shapes)

        h.addStretch()

        self.btn_save = QPushButton(tr("保存标注"), bar)
        self.btn_save.setProperty("role", "accent")
        h.addWidget(self.btn_save)

    def _build_body_splitter(self) -> QSplitter:
        """正文三栏：图像文件列表 + 画布 + 右侧标签面板。"""
        body_splitter = QSplitter(Qt.Horizontal, self)

        # 左侧图像文件列表
        left_panel = QFrame()
        left_panel.setFixedWidth(200)
        lp = QVBoxLayout(left_panel)
        lp.setContentsMargins(4, 4, 4, 4)
        lp.setSpacing(4)
        lp.addWidget(self._caption(tr("图像列表")))
        self.file_list = QListWidget()
        self.file_list.setIconSize(QSize(60, 60))
        self.file_list.setSpacing(2)
        lp.addWidget(self.file_list, 1)
        body_splitter.addWidget(left_panel)

        # 画布（可缩放/平移）
        self.view = _ZoomableView()
        self.view.setScene(self.canvas)
        body_splitter.addWidget(self.view)

        body_splitter.setStretchFactor(0, 0)
        body_splitter.setStretchFactor(1, 1)

        # 右侧面板
        panel = QFrame()
        panel.setFixedWidth(220)
        p = QVBoxLayout(panel)
        p.setContentsMargins(8, 8, 8, 8)
        p.setSpacing(6)
        p.addWidget(self._caption(tr("当前标签")))
        self.label_input = QLineEdit("defect", panel)
        p.addWidget(self.label_input)
        self.btn_apply_label = QPushButton(tr("添加标签"), panel)
        self.btn_apply_label.clicked.connect(self._apply_label)
        p.addWidget(self.btn_apply_label)

        p.addWidget(self._caption(tr("标签列表")))
        self.shape_list = QListWidget(panel)
        p.addWidget(self.shape_list, 1)

        body_splitter.addWidget(panel)
        body_splitter.setStretchFactor(2, 0)
        return body_splitter

    @staticmethod
    def _sep(parent: QWidget) -> QFrame:
        f = QFrame(parent)
        f.setFixedWidth(1)
        f.setStyleSheet("background-color: #3f4452;")
        return f

    @staticmethod
    def _caption(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("color: #94a3b8; font-size: 12px;")
        return lab

    @staticmethod
    def _tbtn(parent: QWidget, text: str) -> QPushButton:
        b = QPushButton(text, parent)
        b.setProperty("tool", True)
        b.setCursor(Qt.PointingHandCursor)
        return b

    # ------------------------------ 接线 ------------------------------ #
    def _wire(self) -> None:
        # 通过子类化重写而非 monkey-patch 注入 controller（PySide6 可靠拦截）
        # controller.install 设置 controller._view 引用（供坐标转换用），
        # view.set_controller 让 view 的鼠标事件重写方法委托给 controller
        self.controller.install(self.view)
        self.view.set_controller(self.controller)
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_open_file.clicked.connect(self.open_image)
        self.btn_save.clicked.connect(self.save)
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_next.clicked.connect(self.next_image)
        self.btn_undo.clicked.connect(self.canvas.undo)
        self.btn_redo.clicked.connect(self.canvas.redo)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_clear.clicked.connect(self.canvas.clear_shapes)
        self.btn_ai_prelabel.clicked.connect(self._ai_prelabel)
        self.btn_toggle_shapes.clicked.connect(self._toggle_shapes_visible)

        self.file_list.currentRowChanged.connect(self._on_file_selected)

        self.canvas.shapes_changed.connect(self._on_shapes_changed)
        self.canvas.undo_redo_changed.connect(self._on_undo_redo_changed)

        # 快捷键（页面作用域）
        for mode, _label, key in _MODES:
            QShortcut(QKeySequence(key), self).activated.connect(
                lambda m=mode: self._apply_mode(m)
            )
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.canvas.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self.canvas.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self.canvas.redo)
        QShortcut(QKeySequence("Return"), self).activated.connect(
            self.controller.handle_commit
        )
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.controller.cancel)
        QShortcut(QKeySequence("Delete"), self).activated.connect(self._delete_selected)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.open_image)
        QShortcut(QKeySequence("A"), self).activated.connect(self.prev_image)
        QShortcut(QKeySequence("D"), self).activated.connect(self.next_image)
        QShortcut(QKeySequence("W"), self).activated.connect(self._ai_prelabel)
        QShortcut(QKeySequence("Space"), self).activated.connect(self._toggle_shapes_visible)
        # copy/paste 标注
        QShortcut(QKeySequence("Ctrl+C"), self).activated.connect(self._copy_shapes)
        QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(lambda: self._paste_shapes(20))

        self._on_shapes_changed(self.canvas.shapes)
        self._on_undo_redo_changed(self.canvas.can_undo(), self.canvas.can_redo())

    # ------------------------------ 文件夹加载 ------------------------------ #
    def open_folder(self) -> None:
        """对标 SKolpha：选择文件夹 -> 递归扫描图像 -> 填充文件列表。"""
        folder = pick_directory(
            self, "打开文件夹"
        )
        if not folder:
            return

        # 递归扫描所有图像文件
        images: List[str] = []
        for root_dir, _dirs, files in os.walk(folder):
            for f in sorted(files):
                if f.lower().endswith(_IMG_EXTS):
                    images.append(os.path.join(root_dir, f))

        if not images:
            self.status_changed.emit(tr("无图像"), folder)
            return

        self._image_files = images
        self._current_index = -1

        # R5-5: 异步填充文件列表（上限 500 张 + 分页提示）
        self._thumb_items.clear()
        self._thumb_pool.clear()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        max_display = 500
        for img_path in images[:max_display]:
            item = QListWidgetItem(os.path.basename(img_path))
            self.file_list.addItem(item)
            self._thumb_items[img_path] = item
            task = ThumbnailTask(img_path, size=64)
            task.signals.loaded.connect(self._on_thumbnail_loaded)
            self._thumb_pool.start(task)
        if len(images) > max_display:
            more = QListWidgetItem(
                f"... {len(images) - max_display} {tr('张更多（仅加载前500张缩略图）')}"
            )
            more.setFlags(Qt.NoItemFlags)
            self.file_list.addItem(more)
        self.file_list.blockSignals(False)

        # 自动加载第一张
        if images:
            self.file_list.setCurrentRow(0)

        self.status_changed.emit(
            tr("已加载"), f"{len(images)} {tr('张')}"
        )

    def _on_thumbnail_loaded(self, path: str, image: QImage) -> None:
        """R5-5: 缩略图异步加载回调（W9: QImage 主线程转 QIcon）。"""
        item = self._thumb_items.get(path)
        if item is not None:
            item.setIcon(QIcon(QPixmap.fromImage(image)))

    def open_image(self) -> None:
        """打开单张图像（原有功能保留）。"""
        path = pick_open_file(
            self, "打开图像",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
        )
        if not path:
            return
        self._image_files = [path]
        self._current_index = -1

        self.file_list.blockSignals(True)
        self.file_list.clear()
        item = QListWidgetItem(os.path.basename(path))
        pm = QPixmap(path)
        if not pm.isNull():
            item.setIcon(QIcon(pm))
        self.file_list.addItem(item)
        self.file_list.blockSignals(False)

        self.file_list.setCurrentRow(0)

    def _load_by_index(self, index: int) -> None:
        """按索引加载图像到画布。"""
        if index < 0 or index >= len(self._image_files):
            return

        path = self._image_files[index]
        pm = QPixmap(path)
        if pm.isNull():
            self.status_changed.emit(tr("打开图像") + "失败", path)
            return

        self.canvas.set_image_pixmap(pm)
        self._image_path = path
        self._current_index = index
        self.view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)

        self.lbl_pos.setText(f"{index + 1} / {len(self._image_files)}")
        self._update_nav_buttons()

        filename = os.path.basename(path)
        self.status_changed.emit(filename, f"{pm.width()}x{pm.height()}")

        # W4-T3: 交互式模式下换图 → 重新预热 SAM embedding（缓存按图哈希）
        if (self.controller.mode is AnnotationMode.INTERACTIVE
                and getattr(self._sam_adapter, "loaded", False)):
            self._warm_sam()

    def _on_file_selected(self, row: int) -> None:
        """文件列表点击 -> 加载图像。"""
        if 0 <= row < len(self._image_files):
            self._load_by_index(row)

    def prev_image(self) -> None:
        """上一张（快捷键 A）。"""
        if self._image_files and self._current_index > 0:
            self.file_list.setCurrentRow(self._current_index - 1)

    def next_image(self) -> None:
        """下一张（快捷键 D）。"""
        if self._image_files and self._current_index < len(self._image_files) - 1:
            self.file_list.setCurrentRow(self._current_index + 1)

    def _update_nav_buttons(self) -> None:
        total = len(self._image_files)
        self.btn_prev.setEnabled(self._current_index > 0)
        self.btn_next.setEnabled(self._current_index < total - 1)

    # ------------------------------ AI 预标注 ------------------------------ #
    def _ai_prelabel(self) -> None:
        """AI 自动预标注（快捷键 W）。

        对标 SKolpha：加载预训练模型推理 -> 自动生成标注 -> 人工修正。
        W3-T3: 推理移出 UI 线程，完成后经 invoke_main 回主线程落形状。
        W18（v3 P2-7）：零样本桥已删——DET 引擎不可用时状态栏诚实提示
        （零样本未实装），不再派发必失败的静默路径。
        """
        if not self._image_path:
            self.status_changed.emit(tr("请先打开图像"), "!")
            return
        if not det_engine_available():
            self.status_changed.emit(
                tr("AI预标注不可用"),
                tr("零样本未实装，请先训练/注册 DET 引擎"),
            )
            return
        logger.info("AI 预标注开始: %s", self._image_path)
        self.btn_ai_prelabel.setEnabled(False)
        self._pending_prelabel = []

        def _work():
            try:
                shapes = run_ai_prelabel(self._image_path)
            except (ImportError, RuntimeError, OSError, ValueError):
                logger.exception("AI 预标注失败")
                shapes = []
            self._pending_prelabel = shapes
            invoke_main(self, "_prelabel_done", len(shapes))

        # W17（v3 P2-1）：on_error 兜底——元组外异常也复位按钮（prelabel 槽）
        run_job(_work, name="label_ai_prelabel", on_error=ui_on_error(self, "_prelabel_failed"))

    @Slot(int)
    def _prelabel_done(self, count: int) -> None:
        """槽：预标注完成（主线程）——落形状并恢复按钮。"""
        self.btn_ai_prelabel.setEnabled(True)
        for s in self._pending_prelabel or []:
            self.canvas.add_shape(mode=s.mode, label=s.label, points=list(s.points))
        self._pending_prelabel = []
        if count > 0:
            self.status_changed.emit(tr("AI预标注完成"), f"{count} {tr('标注数')}")

    @Slot(str)
    def _prelabel_failed(self, err: str) -> None:
        """槽：预标注异常兜底（W17 on_error）——恢复按钮并报错。"""
        self.btn_ai_prelabel.setEnabled(True)
        self._pending_prelabel = []
        self.status_changed.emit(tr("操作失败"), err[:60])

    def _toggle_shapes_visible(self) -> None:
        """显隐标注层（快捷键 Space）。"""
        current = self.canvas.itemsVisible()
        self.canvas.setItemsVisible(not current)
        self.status_changed.emit(
            tr("显隐标注"),
            tr("已显示") if not current else tr("已隐藏")
        )

    # ------------------------------ 标注模式 ------------------------------ #
    def _apply_mode(self, mode: AnnotationMode) -> None:
        self.controller.set_mode(mode)
        self._apply_label()  # 同步当前标签
        for m, btn in self._mode_btns.items():
            btn.setProperty("active", m is mode)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.status_changed.emit(tr("工具") + f": {mode.value}", "AutoVisionAgent")

        # 切换 dragMode：绘制类模式（矩形/画笔/关键点/交互式）禁用基类平移，
        # 避免左键拖拽被解释为画布平移而吞掉鼠标事件流；
        # 多边形模式左键仅打点不拖拽，保留平移体验
        is_draw_mode = mode in (
            AnnotationMode.RECTANGLE,
            AnnotationMode.BRUSH,
            AnnotationMode.KEYPOINT,
            AnnotationMode.INTERACTIVE,
        )
        self.view.set_draw_mode(is_draw_mode)

        # W4-T3 (P2-6): 交互式模式接线 SAM（依赖检测/权重选择/注入）
        if mode is AnnotationMode.INTERACTIVE:
            self._ensure_sam()

        # 切模式后刷新可用性
        self._on_undo_redo_changed(self.canvas.can_undo(), self.canvas.can_redo())

    # ------------------------------ SAM 接线（W4-T3 / P2-6） ------------------------------ #
    def _ensure_sam(self) -> None:
        """进入交互式模式：依赖检测 + 权重选择/加载 + 注入（状态栏全程明示）。"""
        if getattr(self._sam_adapter, "loaded", False):
            self._warm_sam()
            return

        try:
            import segment_anything  # noqa: F401  仅探测可选依赖
        except ImportError:
            self.status_changed.emit(tr("SAM 未安装"), tr("交互式标注不可用"))
            return

        ckpt = pick_open_file(self, tr("选择 SAM 权重"), "SAM Checkpoint (*.pth)")
        if not ckpt:
            self.status_changed.emit(tr("SAM 未加载权重"), tr("交互式标注不可用"))
            return

        from labeling.sam_adapter import SamAdapter

        adapter = SamAdapter()
        self._sam_busy = True

        def _work():
            err = ""
            try:
                adapter.load(ckpt, device="cpu")
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                err = str(exc)
            self._sam_adapter = adapter
            self._sam_busy = False
            if err:
                invoke_main(self, "_sam_failed", err)
                return
            invoke_main(self, "_sam_warmed")

        # W17（v3 P2-1）：on_error 兜底（意外异常时 _sam_busy 复位见 _sam_failed）
        run_job(_work, name="label_sam_load", on_error=ui_on_error(self, "_sam_failed"))

    @Slot()
    def _sam_warmed(self) -> None:
        """槽：权重加载完成（主线程）——继续预热当前帧。"""
        self._warm_sam()

    def _warm_sam(self) -> None:
        """worker 预计算当前帧 embedding（点击时命中缓存，UI 不冻结）。"""
        if not self._image_path or self._sam_busy:
            return
        adapter = self._sam_adapter
        image_path = self._image_path
        self._sam_busy = True

        def _work():
            from core.image_io import imread_unicode

            err = ""
            img = imread_unicode(image_path)
            if img is not None:
                try:
                    adapter.set_image(img)
                except (RuntimeError, OSError, ValueError) as exc:
                    err = str(exc)
            self._sam_busy = False
            if img is None or err:
                invoke_main(self, "_sam_failed", err or tr("图像读取失败"))
                return
            self._pending_sam_image = img
            invoke_main(self, "_sam_attach")

        run_job(_work, name="label_sam_warm", on_error=ui_on_error(self, "_sam_failed"))

    @Slot()
    def _sam_attach(self) -> None:
        """槽：预热完成（主线程）——注入 InteractiveLabeler。"""
        if self.controller.attach_interactive(
            self._sam_adapter, self._pending_sam_image
        ):
            self.status_changed.emit(tr("SAM 已加载"), tr("交互式标注就绪"))

    @Slot(str)
    def _sam_failed(self, err: str) -> None:
        """槽：SAM 加载/预热失败（主线程）——诚实报错。

        W17：顺带复位 _sam_busy——意外异常路径（on_error 兜底）下 worker
        来不及清标志，不复位会永久阻塞后续预热。
        """
        self._sam_busy = False
        self.status_changed.emit(tr("SAM 加载失败"), err[:60])

    def _apply_label(self) -> None:
        text = self.label_input.text().strip() or "defect"
        self.controller.set_label(text)

    def save(self) -> None:
        shapes = self.canvas.shapes
        if not shapes:
            self.status_changed.emit(tr("就绪"), tr("标注数") + "=0")
            return
        default_name = "annotation.json"
        if self._image_path:
            base = self._image_path.rsplit(".", 1)[0]
            default_name = base + ".json"
        path = pick_save_file(
            self, "保存标注", "LabelMe (*.json)"
        )
        if not path:
            return
        w, h = self.canvas.image_size
        try:
            save_labelme(path, shapes, self._image_path or "", h, w)
        except (OSError, ValueError, TypeError, AnnotationIOError) as exc:
            # AnnotationIOError 必收：save_labelme 把 IO/解析错误包成
            # AppError 子类（非 OSError）——漏收则裸穿 Qt 槽（W9 实测）
            self.status_changed.emit(str(exc), "ERROR")
            return
        logger.info("保存标注: %s（%d 个形状）", path, len(shapes))
        self.status_changed.emit(tr("已保存"), f"{len(shapes)} {tr('标注数')}")
        # 保存后自动切换下一张（R3-14），提升批量标注效率。
        # 延迟 600ms 切换：让"已保存"状态在状态栏停留片刻，便于 UIA 自动化
        # 测试捕获（避免立即被下一张图的 filename 状态覆盖）。
        if self._image_files and self._current_index < len(self._image_files) - 1:
            QTimer.singleShot(600, self.next_image)

    def _delete_selected(self) -> None:
        row = self.shape_list.currentRow()
        if row >= 0:
            self.canvas.remove_shape_at(row)

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

    # ------------------------------ 回刷 ------------------------------ #
    def _on_shapes_changed(self, shapes) -> None:
        self.shape_list.blockSignals(True)
        self.shape_list.clear()
        for i, s in enumerate(shapes):
            item = QListWidgetItem(f"#{i + 1}  [{s.mode.value}]  {s.label}")
            self.shape_list.addItem(item)
        self.shape_list.blockSignals(False)
        self.status_changed.emit(tr("就绪"), f"{len(shapes)} {tr('标注数')}")

    def _on_undo_redo_changed(self, can_undo: bool, can_redo: bool) -> None:
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def retranslate(self) -> None:
        self.btn_open_folder.setText(tr("打开文件夹"))
        self.btn_open_file.setText(tr("打开图像"))
        self.btn_prev.setText(tr("上一张"))
        self.btn_next.setText(tr("下一张"))
        self.btn_save.setText(tr("保存标注"))
        self.btn_undo.setText(tr("撤销"))
        self.btn_redo.setText(tr("重做"))
        self.btn_delete.setText(tr("删除"))
        self.btn_clear.setText(tr("清空"))
        self.btn_apply_label.setText(tr("添加标签"))
        for mode, label_key, key in _MODES:
            if mode in self._mode_btns:
                self._mode_btns[mode].setText(f"{tr(label_key)}  {key}")


__all__ = ["LabelPage"]
