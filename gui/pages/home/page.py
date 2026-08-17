"""主页/仪表盘（FR-D3）— 对标 SKolpha 主页：项目概览 + 快捷入口 + 系统状态。"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr

logger = logging.getLogger(__name__)


class _StatCard(QFrame):
    """统计卡片。"""

    def __init__(self, title: str, value: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("color: #888; font-size: 12px;")
        self._value_label = QLabel(value)
        self._value_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #00D4AA;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addWidget(self._title_label)
        lay.addWidget(self._value_label)

    def set_value(self, v: str) -> None:
        self._value_label.setText(v)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)


class HomePage(QWidget):
    """主页仪表盘。"""

    navigate = Signal(str)  # 请求导航到某页面 ID
    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(20)

        # 标题
        self._title = QLabel(tr("仪表盘"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        # 统计卡片
        cards_layout = QGridLayout()
        cards_layout.setSpacing(16)
        self._card_projects = _StatCard(tr("项目数"), "0")
        self._card_images = _StatCard(tr("图像总数"), "0")
        self._card_models = _StatCard(tr("已训练模型"), "0")
        self._card_gpus = _StatCard(tr("GPU 状态"), "—")
        cards_layout.addWidget(self._card_projects, 0, 0)
        cards_layout.addWidget(self._card_images, 0, 1)
        cards_layout.addWidget(self._card_models, 0, 2)
        cards_layout.addWidget(self._card_gpus, 0, 3)
        root.addLayout(cards_layout)

        # 快捷入口
        self._shortcuts_title = QLabel(tr("快捷操作"))
        self._shortcuts_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #CCC;")
        root.addWidget(self._shortcuts_title)

        sc_layout = QHBoxLayout()
        sc_layout.setSpacing(12)
        for label, page_id in [
            (tr("新建项目"), "project"),
            (tr("导入数据"), "data_manage"),
            (tr("开始训练"), "train"),
            (tr("模型推理"), "predict"),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda checked, pid=page_id: self.navigate.emit(pid))
            sc_layout.addWidget(btn)
        sc_layout.addStretch()
        root.addLayout(sc_layout)

        # 最近项目列表（R3-14）
        self._recent_title = QLabel(tr("最近项目"))
        self._recent_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #CCC;"
        )
        root.addWidget(self._recent_title)

        self._recent_list = QListWidget()
        self._recent_list.setMaximumHeight(180)
        self._recent_list.setStyleSheet(
            "QListWidget { background-color: #13151c; border-radius: 8px;"
            " padding: 4px; }"
            "QListWidget::item { padding: 8px 12px; border-radius: 4px; }"
            "QListWidget::item:hover { background-color: #1b1e26; }"
        )
        self._recent_list.itemDoubleClicked.connect(self._on_recent_clicked)
        root.addWidget(self._recent_list)

        # R4-6: 检测历史统计
        self._history_title = QLabel(tr("检测历史"))
        self._history_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #CCC;"
        )
        root.addWidget(self._history_title)

        self._history_label = QLabel(tr("暂无检测记录"))
        self._history_label.setStyleSheet("color: #888; font-size: 13px; padding: 4px;")
        root.addWidget(self._history_label)

        root.addStretch()

    def update_stats(
        self,
        projects: int = 0,
        images: int = 0,
        models: int = 0,
        gpu: str = "—",
    ) -> None:
        self._card_projects.set_value(str(projects))
        self._card_images.set_value(str(images))
        self._card_models.set_value(str(models))
        self._card_gpus.set_value(gpu)

    def refresh_recent(self, base_root: str) -> None:
        """刷新最近项目列表（R3-14）。"""
        from project.recent import recent_list
        self._recent_list.clear()
        dirs = recent_list(base_root)
        for dirname in dirs[:20]:
            item = QListWidgetItem(dirname)
            self._recent_list.addItem(item)
        if not dirs:
            empty = QListWidgetItem(tr("暂无最近项目"))
            empty.setFlags(empty.flags() & ~empty.flags())
            self._recent_list.addItem(empty)

    def refresh_history(self) -> None:
        """R4-6: 刷新检测历史统计。"""
        try:
            from core.detection_history import get_history
            stats = get_history().stats()
            total = stats.get("total", 0)
            if total == 0:
                self._history_label.setText(tr("暂无检测记录"))
            else:
                avg = stats.get("avg_score", 0.0)
                by_task = stats.get("by_task", {})
                task_str = " / ".join(f"{k}:{v}" for k, v in by_task.items())
                self._history_label.setText(
                    f"{tr('推理总数')}: {total}  |  "
                    f"{tr('平均置信度')}: {avg:.3f}  |  {task_str}"
                )
        except Exception:
            # W14-C3（P2-13）：UI 文案保持"暂无检测记录"，但真实原因
            # （损坏 JSON / 权限问题等）必须进日志，否则真实历史被掩盖
            logger.warning("检测历史加载失败，回退显示'暂无检测记录'", exc_info=True)
            self._history_label.setText(tr("暂无检测记录"))

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        """双击最近项目 → 导航到项目页。"""
        self.navigate.emit("project")

    def retranslate(self) -> None:
        self._title.setText(tr("仪表盘"))
        self._shortcuts_title.setText(tr("快捷操作"))
        self._card_projects.set_title(tr("项目数"))
        self._card_images.set_title(tr("图像总数"))
        self._card_models.set_title(tr("已训练模型"))
        self._card_gpus.set_title(tr("GPU 状态"))
        self._recent_title.setText(tr("最近项目"))
        self._history_title.setText(tr("检测历史"))
