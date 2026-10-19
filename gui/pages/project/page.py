"""项目管理页：新建/列表/打开项目 + 计数器展示（FR-D7 / FR-E1 / FR-E2）。

对接 project/{models, store, counter, recent}，在文件系统层
管理规范项目目录结构。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.interfaces_supervised import TaskType
from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error
from gui.widgets.file_dialog import pick_directory
from project.counter import TaskCounter
from project.models import ProjectId, ProjectLayout, parse_project_dirname
from project.paths import resolve_base_root
from project.store import FileSystemProjectStore

# 可用任务类型
_TASKS = [
    (TaskType.DET, "检测 (det)"),
    (TaskType.SEG, "分割 (seg)"),
    (TaskType.PSEG, "实例分割 (pseg)"),
    (TaskType.CLS, "分类 (cls)"),
    (TaskType.POSE, "关键点 (pose)"),
    (TaskType.SSEG, "语义分割 (sseg)"),
    (TaskType.ABDET, "异常检测 (abdet)"),
]


def _build_pack_row(page, parent_lay) -> None:
    """W3-2：项目包导出/导入按钮行（W24 规模拆分自 _build_ui）。"""
    pack_lay = QHBoxLayout()
    page.btn_pack_export = QPushButton(tr("导出项目包"), page)
    pack_lay.addWidget(page.btn_pack_export)
    page.btn_pack_import = QPushButton(tr("导入项目包"), page)
    pack_lay.addWidget(page.btn_pack_import)
    parent_lay.addLayout(pack_lay)


class ProjectPage(QWidget):
    """项目管理页。"""

    status_changed = Signal(str, str)
    project_opened = Signal(str)  # 项目路径 → 外部切换页面

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._base_root: str = resolve_base_root()  # W28：单源（workspace 可配）
        self._counter = TaskCounter()
        self._store: FileSystemProjectStore | None = None
        self._build_ui()
        self._wire()
        self._init_store()

    # ============================== UI ============================== #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 顶部：新建项目 ----
        create_frame = QFrame(self)
        create_frame.setStyleSheet(
            "QFrame { background-color: #1b1e26; border-radius: 8px; }"
        )
        cf = QVBoxLayout(create_frame)
        cf.setContentsMargins(12, 12, 12, 12)
        cf.setSpacing(8)

        lbl = QLabel(tr("新建项目"), create_frame)
        lbl.setStyleSheet("color: #7c3aed; font-size: 14px; font-weight: bold;")
        cf.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel(tr("名称")))
        self.txt_name = QLineEdit("my_project", create_frame)
        row.addWidget(self.txt_name)

        row.addWidget(QLabel(tr("任务")))
        self.cmb_task = QComboBox(create_frame)
        for task, label in _TASKS:
            self.cmb_task.addItem(label, task)
        row.addWidget(self.cmb_task)

        self.btn_create = QPushButton(tr("创建"), create_frame)
        self.btn_create.setProperty("role", "accent")
        row.addWidget(self.btn_create)
        cf.addLayout(row)

        # 存储根目录
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("存储目录")))
        self.txt_root = QLineEdit(self._base_root, create_frame)
        row2.addWidget(self.txt_root, 1)
        self.btn_browse = QPushButton(tr("浏览"), create_frame)
        row2.addWidget(self.btn_browse)
        self.btn_reload = QPushButton(tr("刷新列表"), create_frame)
        row2.addWidget(self.btn_reload)
        cf.addLayout(row2)

        root.addWidget(create_frame)

        # ---- 正文：项目列表 + 计数器 ----
        body = QHBoxLayout()
        body.setSpacing(10)

        # 左：项目列表
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self._caption(tr("项目列表")))
        self.project_list = QListWidget(self)
        self.project_list.setStyleSheet(
            "QListWidget { background-color: #13151c; border-radius: 8px; }"
        )
        left.addWidget(self.project_list, 1)

        btn_lay = QHBoxLayout()
        self.btn_open = QPushButton(tr("打开项目"), self)
        self.btn_open.setProperty("role", "accent")
        btn_lay.addWidget(self.btn_open)
        self.btn_delete = QPushButton(tr("删除"), self)
        btn_lay.addWidget(self.btn_delete)
        left.addLayout(btn_lay)

        # W3-2：项目包导出/导入（资产迁移）——构建抽 _build_pack_row
        _build_pack_row(self, left)
        body.addLayout(left, 1)

        # 右：计数器面板
        right_frame = QFrame(self)
        right_frame.setFixedWidth(260)
        right_frame.setStyleSheet(
            "QFrame { background-color: #1b1e26; border-radius: 8px; }"
        )
        rf = QVBoxLayout(right_frame)
        rf.setContentsMargins(10, 10, 10, 10)
        rf.setSpacing(6)
        rf.addWidget(self._caption(tr("任务计数器")))
        self._counter_labels: dict = {}
        for task, label in _TASKS:
            row_w = QHBoxLayout()
            row_w.addWidget(QLabel(f"{label}:", right_frame))
            lbl_c = QLabel("0", right_frame)
            lbl_c.setStyleSheet("color: #7c3aed; font-size: 14px; font-weight: bold;")
            lbl_c.setAlignment(Qt.AlignRight)
            row_w.addWidget(lbl_c)
            rf.addLayout(row_w)
            self._counter_labels[task] = lbl_c

        rf.addStretch()
        body.addWidget(right_frame)
        root.addLayout(body, 1)

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
        self.btn_create.clicked.connect(self._create_project)
        self.btn_browse.clicked.connect(self._browse_root)
        # W3-2：刷新=重读根目录输入框并重建 store（此前只 _refresh 列表
        # ——手改根路径后刷新无效的死角，UIA 切根实证）
        self.btn_reload.clicked.connect(self._init_store)
        self.btn_open.clicked.connect(self._open_project)
        self.btn_delete.clicked.connect(self._delete_project)
        self.btn_pack_export.clicked.connect(self._export_pack)
        self.btn_pack_import.clicked.connect(self._import_pack)
        self.project_list.itemDoubleClicked.connect(
            lambda _: self._open_project()
        )

    def _init_store(self) -> None:
        """根据 txt_root 初始化 store。"""
        root = self.txt_root.text().strip()
        if root:
            self._base_root = root
        os.makedirs(self._base_root, exist_ok=True)
        self._store = FileSystemProjectStore(self._base_root)
        self._refresh()

    # ============================== 行为 ============================== #
    def _browse_root(self) -> None:
        d = pick_directory(
            self, "选择存储目录"
        )
        if d:
            self.txt_root.setText(d)
            self._init_store()

    def _create_project(self) -> None:
        """创建项目。"""
        name = self.txt_name.text().strip()
        if not name:
            self.status_changed.emit(tr("请输入项目名"), "!")
            return
        task = self.cmb_task.currentData()
        try:
            assert self._store is not None
            project_id, layout = self._store.create_project(name, task)
            # 添加到最近列表
            from project import recent
            recent.add_recent(self._base_root, project_id.to_dirname())
            self._refresh()
            self.status_changed.emit(
                tr("项目已创建"), project_id.to_dirname()
            )
        except Exception as exc:
            self.status_changed.emit(tr("创建失败"), str(exc)[:40])

    def _refresh(self) -> None:
        """刷新列表和计数器（不调 _init_store，避免递归）。"""
        self.project_list.clear()

        assert self._store is not None
        projects = self._store.list_projects()
        from project import recent
        recent_dirs = recent.recent_list(self._base_root)

        # 先显示 recent，再补充其余
        shown = set()
        for dirname in recent_dirs:
            pid = parse_project_dirname(dirname)
            if pid and self._store.exists(pid):
                self._add_project_item(pid, "(★)")
                shown.add(dirname)

        for pid in projects:
            if pid.to_dirname() not in shown:
                self._add_project_item(pid)

        # 更新计数器（snapshot 键是任务值字符串如 "det"，非枚举——W9 修复
        # 此前用枚举查询恒得 0，面板从未显示过真实计数）
        if self._store._counter:
            snapshot = self._store._counter.snapshot()
            for task, lbl in self._counter_labels.items():
                lbl.setText(str(snapshot.get(task.value, 0)))

        self.status_changed.emit(tr("就绪"), f"{len(projects)} {tr('个项目')}")

    def _add_project_item(
        self, pid: ProjectId, suffix: str = ""
    ) -> None:
        """添加项目到列表。"""
        text = f"{pid.to_dirname()}  [{pid.task.value}]  {suffix}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, pid)
        self.project_list.addItem(item)

    def _open_project(self) -> None:
        """打开选中项目。"""
        item = self.project_list.currentItem()
        if not item:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        pid: ProjectId = item.data(Qt.UserRole)
        if not pid:
            return
        layout = ProjectLayout.for_id(pid, self._base_root)
        from project import recent
        recent.add_recent(self._base_root, pid.to_dirname())
        self.project_opened.emit(layout.root)
        self.status_changed.emit(tr("已打开"), pid.to_dirname())

    def _delete_project(self) -> None:
        """删除选中项目。"""
        item = self.project_list.currentItem()
        if not item:
            return
        pid: ProjectId = item.data(Qt.UserRole)
        if not pid:
            return
        from PySide6.QtWidgets import QMessageBox
        path = pid.to_path(self._base_root)

        # R5-1: 路径遍历防护 — 删除前校验路径在 _base_root 子树内
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(self._base_root)
        if real_path == real_root or not real_path.startswith(
            real_root + os.sep
        ):
            self.status_changed.emit(tr("路径不安全，拒绝删除"), "ERROR")
            return

        reply = QMessageBox.question(
            self, tr("确认删除"),
            tr("确定要删除项目目录吗？此操作不可恢复！\n\n") + pid.to_dirname(),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        import shutil
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            from project import recent
            recent.remove_recent(self._base_root, pid.to_dirname())
            self._refresh()
            self.status_changed.emit(tr("已删除"), pid.to_dirname())
        except (OSError, PermissionError) as exc:
            self.status_changed.emit(tr("删除失败"), str(exc)[:40])

    # ============================== 项目包（W3-2） ============================== #
    def _export_pack(self) -> None:
        """导出选中项目为 zip（worker，大包秒级）。"""
        item = self.project_list.currentItem()
        if not item:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        pid: ProjectId = item.data(Qt.UserRole)
        from gui.widgets.file_dialog import pick_save_file

        zip_path = pick_save_file(
            self, "保存项目包", "AVPack (*.zip);;All (*)"
        )
        if not zip_path:
            return
        project_root = ProjectLayout.for_id(pid, self._base_root).root
        self.btn_pack_export.setEnabled(False)
        self.status_changed.emit(tr("项目包导出中..."), "info")

        def _work():
            try:
                from project.pack import export_pack

                m = export_pack(project_root, zip_path)
                invoke_main(self, "_pack_done_slot", str(m["file_count"]))
            except (OSError, ValueError) as exc:
                invoke_main(self, "_pack_failed_slot", str(exc))

        run_job(_work, name="project.pack_export",
                on_error=ui_on_error(self, "_pack_failed_slot"))

    def _import_pack(self) -> None:
        """导入项目包 zip 到当前存储根（worker）。"""
        from gui.widgets.file_dialog import pick_open_file

        zip_path = pick_open_file(
            self, "选择项目包", "AVPack (*.zip)"
        )
        if not zip_path:
            self.status_changed.emit(tr("已取消"), tr("未选择项目包"))
            return
        base_root = self._base_root
        self.btn_pack_import.setEnabled(False)
        self.status_changed.emit(tr("项目包导入中..."), "info")

        def _work():
            try:
                from project.pack import import_pack

                r = import_pack(zip_path, base_root)
                invoke_main(self, "_pack_done_slot", str(r["file_count"]))
            except (OSError, ValueError) as exc:
                invoke_main(self, "_pack_failed_slot", str(exc))

        run_job(_work, name="project.pack_import",
                on_error=ui_on_error(self, "_pack_failed_slot"))

    @Slot(str)
    def _pack_done_slot(self, count: str) -> None:
        """W3-2：包操作完成（导出/导入共用计数回显）。"""
        self.btn_pack_export.setEnabled(True)
        self.btn_pack_import.setEnabled(True)
        self._refresh()
        self.status_changed.emit(tr("项目包完成"), f"{count} {tr('个文件')}")

    @Slot(str)
    def _pack_failed_slot(self, msg: str) -> None:
        """W3-2：包操作失败（PackError 等）显式复位。"""
        self.btn_pack_export.setEnabled(True)
        self.btn_pack_import.setEnabled(True)
        self.status_changed.emit(tr("项目包失败"), msg[:80])

    def retranslate(self) -> None:
        self.btn_create.setText(tr("创建"))
        self.btn_open.setText(tr("打开项目"))
        self.btn_delete.setText(tr("删除"))
        self.btn_browse.setText(tr("浏览"))
        self.btn_reload.setText(tr("刷新列表"))


__all__ = ["ProjectPage"]
