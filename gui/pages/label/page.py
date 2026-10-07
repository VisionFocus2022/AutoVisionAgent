"""标注页：画布 + 工具栏 + 标签列表 + 图像文件列表 + 撤销/重做 + LabelMe 存盘（FR-C/D）。

对标 SKolpha：支持选择文件夹批量加载图像，左侧文件列表浏览切换。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
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

from core.constants import IMG_EXTS as _IMG_EXTS
from core.exceptions import AnnotationIOError, InvalidShapeError
from gui.core.i18n import tr
from gui.pages.label.sam_session import SamSessionMixin
from gui.widgets.file_dialog import pick_directory, pick_open_file, pick_save_file
from gui.widgets.thumbnail_loader import ThumbnailTask
from labeling import AnnotationMode, save_labelme
from labeling.canvas import AnnotationCanvas
from labeling.controller import AnnotationController

logger = logging.getLogger(__name__)

# 模式定义：(mode, 按钮文本键, 快捷键)
_MODES = [
    (AnnotationMode.POLYGON, "多边形", "Q"),
    (AnnotationMode.RECTANGLE, "矩形", "R"),
    (AnnotationMode.BRUSH, "画笔", "P"),
    (AnnotationMode.KEYPOINT, "关键点", "K"),
    (AnnotationMode.INTERACTIVE, "交互式", "I"),
    (AnnotationMode.REGION_SAM, "SAM 区域", "J"),
    # W46·B：补 W44 AUTO/AMG 通道缺失的 UI 入口（此前 _sam_attach 的
    # AUTO 分支无按钮可达=死路）——SAM3 后端下 label 输入框即概念提示词
    (AnnotationMode.AUTO, "SAM 全图", "G"),
]

# W44：SAM 系模式集合——触发 _ensure_sam 注入（含 AUTO 走 AMG detector）；
# 绘制模式集合=SAM 系+手动系（规模守卫触发抽取，v6 P3 棘轮语义）
_SAM_MODES = frozenset({
    AnnotationMode.INTERACTIVE, AnnotationMode.REGION_SAM,
    AnnotationMode.AUTO,
})
_DRAW_MODES = _SAM_MODES | {
    AnnotationMode.POLYGON, AnnotationMode.RECTANGLE,
    AnnotationMode.BRUSH, AnnotationMode.KEYPOINT,
}


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
        self._controller: AnnotationController | None = None

    def set_controller(self, controller: AnnotationController) -> None:
        """注入标注控制器，接管鼠标事件分发。"""
        self._controller = controller

    def set_draw_mode(self, active: bool) -> None:
        """根据是否处于"绘制标注"模式切换 dragMode 与视口光标。

        绘制模式下用 NoDrag，避免左键拖拽被基类解释为画布平移，
        导致 controller 收不到完整的鼠标按下/拖拽/释放事件流；
        并将视口光标固定为标准箭头——ScrollHandDrag 会强制显示手型
        光标，妨碍多边形打点的精确定位。
        非绘制模式下恢复 ScrollHandDrag，保留手型平移体验。
        """
        self.setDragMode(QGraphicsView.NoDrag if active else QGraphicsView.ScrollHandDrag)
        if active:
            self.viewport().setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event) -> None:
        """Ctrl+滚轮缩放（以鼠标指向处为锚点），普通滚轮由父类处理（滚动条）。"""
        if event.modifiers() & Qt.ControlModifier:
            factor = (
                self._zoom_factor
                if event.angleDelta().y() > 0
                else 1 / self._zoom_factor
            )
            self._zoom_at(event.position().toPoint(), factor)
        else:
            super().wheelEvent(event)

    def _zoom_at(self, view_pos, factor: float) -> None:
        """以 view_pos（视口坐标）为锚点缩放 factor 倍。

        记录缩放前光标下的场景点，缩放后按「滚动条值 = 场景点 × 新缩放
        − 光标视口坐标」直接定位滚动条——滚动条值单位是视图像素而非
        场景单位（scale 后需乘新缩放），使放大缩小始终围绕鼠标指向处展开。
        """
        anchor = self.mapToScene(view_pos)
        self.scale(factor, factor)
        t = self.transform()
        self.horizontalScrollBar().setValue(
            round(anchor.x() * t.m11() - view_pos.x())
        )
        self.verticalScrollBar().setValue(
            round(anchor.y() * t.m22() - view_pos.y())
        )

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


class LabelPage(SamSessionMixin, QWidget):
    """标注画布页（实装页）— 支持文件夹批量加载。

    SAM 交互式会话（加载/预热/注入）混入自 SamSessionMixin（W27 抽取，
    槽名与行为不变）。
    """

    status_changed = Signal(str, str)  # (text, accent) -> 主壳状态栏
    request_page = Signal(str)  # W59c：「下一步」向导导航（shell 泛化挂接）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        # 数据层
        self.canvas = AnnotationCanvas()
        self.canvas.set_blank(800, 600)
        self.controller = AnnotationController(
            self.canvas, mode=AnnotationMode.POLYGON, label="defect"
        )
        # W55·v7 P2-4：标注器反馈 → 状态栏（推理失败/未就绪/零产出）
        self.controller.set_feedback_callback(self._on_labeler_feedback)
        self._image_path: str | None = None
        self._mode_btns: dict[AnnotationMode, QPushButton] = {}

        # 图像文件列表
        self._image_files: list[str] = []
        self._current_index: int = -1
        self._folder: str = ""  # W62：当前打开的文件夹（向导上下文交接用）

        # 标注剪贴板（copy/paste）
        self._clipboard: list = []

        # R5-5: 异步缩略图加载
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(4)
        self._thumb_items: dict[str, QListWidgetItem] = {}

        # W4-T3 (P2-6): SAM 交互式标注接线状态
        self._sam_adapter = None
        # W56·v7 P2-5：SAM 状态机，_sam_busy 为 mixin 只读兼容属性
        self._sam_state = "idle"
        self._pending_sam_image = None
        # O7·契约 C2 模式②（2026-10-05）：SAM 加载 worker → 主线程槽的
        # adapter 传递 pending 属性（worker 不直接写 _sam_adapter）
        self._pending_sam_adapter = None

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
        """顶部工具栏：打开/翻页/模式组 + 编辑/保存组。"""
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
        """工具栏编辑组：撤销/重做/删除/清空/卸载 SAM + 保存。"""
        sep2 = self._sep(bar)
        h.addWidget(sep2)

        self.btn_undo = self._tbtn(bar, tr("撤销"))
        self.btn_redo = self._tbtn(bar, tr("重做"))
        self.btn_delete = self._tbtn(bar, tr("删除"))
        self.btn_clear = self._tbtn(bar, tr("清空"))
        self.btn_sam_unload = self._tbtn(bar, tr("卸载 SAM"))  # W56·v7 P2-1
        self.btn_sam_unload.clicked.connect(self.unload_sam)
        for b in (self.btn_undo, self.btn_redo, self.btn_delete, self.btn_clear,
                  self.btn_sam_unload):
            h.addWidget(b)

        h.addStretch()

        self.btn_save = QPushButton(tr("保存标注"), bar)
        self.btn_save.setProperty("role", "accent")
        h.addWidget(self.btn_save)

        # W59c：向导下一步——标注完成→数据管理（导出训练集）
        self.btn_goto_data = QPushButton(tr("下一步：数据管理"), bar)
        self.btn_goto_data.clicked.connect(
            lambda: self.request_page.emit("data_manage")
        )
        h.addWidget(self.btn_goto_data)

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

        self.file_list.currentRowChanged.connect(self._on_file_selected)

        self.canvas.shapes_changed.connect(self._on_shapes_changed)
        self.canvas.undo_redo_changed.connect(self._on_undo_redo_changed)

        # 快捷键（页面作用域）
        for mode, _label, key in _MODES:
            QShortcut(QKeySequence(key), self).activated.connect(
                lambda m=mode: self._apply_mode(m)
            )
        # 静态快捷键表驱动注册（W24 ≤800 行守卫：逐条注册已收敛为表）
        for seq, handler in [
            ("Ctrl+Z", self.canvas.undo), ("Ctrl+Y", self.canvas.redo),
            ("Ctrl+Shift+Z", self.canvas.redo),
            ("Return", self.controller.handle_commit),
            ("Esc", self.controller.cancel), ("Delete", self._delete_selected),
            ("Ctrl+S", self.save), ("Ctrl+O", self.open_image),
            ("A", self.prev_image), ("D", self.next_image),
            ("Ctrl+C", self._copy_shapes),
            ("Ctrl+V", lambda: self._paste_shapes(20)),
        ]:
            QShortcut(QKeySequence(seq), self).activated.connect(handler)

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
        self.load_folder(folder)

    def load_folder(self, folder: str) -> None:
        """无对话框载入目录（W2-4：缺陷生成"去标注"缝；open_folder 复用）。"""
        self._folder = folder  # W62：向导交接上下文

        # 递归扫描所有图像文件
        images: list[str] = []
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
        self._mark_annotated_items()  # W59b：● 标记有同名 JSON 的图

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
        self._folder = os.path.dirname(path)  # W62：单图回落所在目录
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
        # W55·v7 P1-1：换图硬清空上一图形状（含撤销栈）；有意携带走 Ctrl+C/V
        self.canvas.reset_session()
        self._image_path = path
        self._current_index = index
        self.view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)

        self.lbl_pos.setText(f"{index + 1} / {len(self._image_files)}")
        self._update_nav_buttons()

        filename = os.path.basename(path)
        self.status_changed.emit(filename, f"{pm.width()}x{pm.height()}")

        # W55·v7 P1-2：换图 SAM 会话同步（全模式，防丢拍见 _sam_attach）
        if getattr(self._sam_adapter, "loaded", False):
            self._sync_sam_session()
        # W59b：画布为空时自动载入同名 LabelMe JSON（PRD FR-1）
        self._try_load_existing_json()

    # ====================== 同目录 LabelMe 识别（W59b · PRD FR-1） ====================== #

    @property
    def current_folder(self) -> str:
        """当前打开的文件夹（W62：向导目录交接用；未打开为空串）。"""
        return self._folder

    def _sibling_json(self, image_path: str) -> str | None:
        """同名 LabelMe JSON 路径（存在才返回）。"""
        jp = os.path.splitext(image_path)[0] + ".json"
        return jp if os.path.isfile(jp) else None

    def _mark_annotated_items(self) -> None:
        """文件列表为有同名 JSON 的图加 ● 前缀（打开文件夹后一次扫描）。

        只查存在性不解析（1288 次 stat 量级可忽略）；非图像说明行按
        「项文本以文件名结尾」判据跳过（错位保护）。
        """
        for row in range(min(self.file_list.count(), len(self._image_files))):
            item = self.file_list.item(row)
            base = os.path.basename(self._image_files[row])
            if not item.text().endswith(base):
                continue
            if self._sibling_json(self._image_files[row]) and \
                    not item.text().startswith("● "):
                item.setText(f"● {base}")

    def _try_load_existing_json(self) -> None:
        """画布为空时自动载入当前图同名 LabelMe JSON（PRD FR-1②）。

        画布非空（手绘在途）不合并不覆盖；损坏 JSON 容错提示不炸
        （json.JSONDecodeError 属 ValueError 子类，已覆盖）。
        """
        if self.canvas.shapes or not self._image_path:
            return
        jp = self._sibling_json(self._image_path)
        if not jp:
            return
        try:
            from labeling.io_labelme import load_labelme_shapes

            shapes = load_labelme_shapes(jp)
        except (OSError, ValueError, KeyError, AnnotationIOError) as exc:
            logger.warning("载入既有标注失败: %s (%s)", jp, exc)
            self.status_changed.emit(tr("载入标注失败"), str(exc)[:60])
            return
        if shapes:
            self.canvas.replace_all(shapes)
            self.status_changed.emit(
                tr("已载入"), f"{len(shapes)} {tr('标注数')}"
            )

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

    # ------------------------------ 标注模式 ------------------------------ #
    def _apply_mode(self, mode: AnnotationMode) -> None:
        self.controller.set_mode(mode)
        self._apply_label()  # 同步当前标签
        for m, btn in self._mode_btns.items():
            btn.setProperty("active", m is mode)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.status_changed.emit(tr("工具") + f": {mode.value}", "AutoVisionAgent")

        # 切换 dragMode：全部标注模式统一 NoDrag + 箭头光标——controller
        # 接管鼠标事件流后基类平移从不触发，多边形保留 ScrollHandDrag 时
        # 只剩强制手型光标的副作用（打点定位需要标准箭头）
        self.view.set_draw_mode(mode in _DRAW_MODES)

        # W4-T3 (P2-6): 交互式模式接线 SAM（依赖检测/权重选择/注入）
        if mode in _SAM_MODES:
            self._ensure_sam()

        # 切模式后刷新可用性
        self._on_undo_redo_changed(self.canvas.can_undo(), self.canvas.can_redo())

    # ------------------------------ SAM 接线（W27 抽出至 SamSessionMixin） ------------------------------ #
    # _ensure_sam/_sam_warmed/_warm_sam/_sam_attach/_sam_failed 见
    # gui/pages/label/sam_session.py（行为保持抽取，invoke_main 槽名
    # 派发经 MRO 命中 Mixin 方法）

    def _apply_label(self) -> None:
        text = self.label_input.text().strip() or "defect"
        self.controller.set_label(text)

    def save(self) -> None:
        shapes = self.canvas.shapes
        if not shapes:
            self.status_changed.emit(tr("就绪"), tr("标注数") + "=0")
            return
        path = pick_save_file(
            self, "保存标注", "LabelMe (*.json)"
        )
        if not path:
            return
        w, h = self.canvas.image_size
        try:
            save_labelme(path, shapes, self._image_path or "", h, w)
        except (OSError, ValueError, TypeError, AnnotationIOError,
                InvalidShapeError) as exc:
            # AnnotationIOError/InvalidShapeError 必收（AppError 子类非
            # OSError）——漏收则裸穿 Qt 槽（W9 实测；W46·B 补 Invalid）
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
