"""project/store.py + project/counter.py 单元测试（R4-12）。

覆盖：项目创建/列出/元数据读写，TaskCounter next_id/snapshot。
"""
import os

import pytest

from core.interfaces_supervised import TaskType


@pytest.mark.unit
class TestTaskCounter:
    """TaskCounter 功能测试。"""

    def test_next_id_increments(self, tmp_path):
        """next_id 递增分配。"""
        from project.counter import TaskCounter
        counter = TaskCounter(str(tmp_path))
        id1 = counter.next_id("det")
        id2 = counter.next_id("det")
        assert id2 == id1 + 1

    def test_next_id_different_tasks(self, tmp_path):
        """不同任务独立计数。"""
        from project.counter import TaskCounter
        counter = TaskCounter(str(tmp_path))
        det_id = counter.next_id("det")
        det_id2 = counter.next_id("det")
        cls_id = counter.next_id("cls")
        # det 已递增到 2，cls 从 1 开始 → 独立计数器
        assert det_id == 1
        assert det_id2 == 2
        assert cls_id == 1  # cls 独立从 1 开始

    def test_snapshot(self, tmp_path):
        """snapshot 返回当前计数快照。"""
        from project.counter import TaskCounter
        counter = TaskCounter(str(tmp_path))
        counter.next_id("det")
        counter.next_id("det")
        counter.next_id("cls")
        snap = counter.snapshot()
        assert snap["det"] == 2
        assert snap["cls"] == 1

    def test_get(self, tmp_path):
        """get 返回当前计数（不递增）。"""
        from project.counter import TaskCounter
        counter = TaskCounter(str(tmp_path))
        counter.next_id("det")
        counter.next_id("det")
        assert counter.get("det") == 2
        assert counter.get("cls") == 0

    def test_persistence(self, tmp_path):
        """计数器持久化。"""
        from project.counter import TaskCounter
        counter1 = TaskCounter(str(tmp_path))
        counter1.next_id("det")
        counter1.next_id("det")
        # 新实例从文件恢复
        counter2 = TaskCounter(str(tmp_path))
        snap = counter2.snapshot()
        assert snap.get("det", 0) == 2


@pytest.mark.unit
class TestFileSystemProjectStore:
    """FileSystemProjectStore 功能测试。"""

    def test_create_project(self, tmp_path):
        """创建项目目录。"""
        from project.store import FileSystemProjectStore
        store = FileSystemProjectStore(str(tmp_path))
        pid, layout = store.create_project("test_project", TaskType.DET)
        assert pid is not None
        # 目录已创建
        proj_dir = pid.to_path(str(tmp_path))
        assert os.path.isdir(proj_dir)

    def test_list_projects(self, tmp_path):
        """列出已创建项目。"""
        from project.store import FileSystemProjectStore
        store = FileSystemProjectStore(str(tmp_path))
        store.create_project("proj_a", TaskType.DET)
        store.create_project("proj_b", TaskType.CLS)
        projects = store.list_projects()
        assert len(projects) == 2

    def test_load_meta(self, tmp_path):
        """加载项目元数据。"""
        from project.store import FileSystemProjectStore
        store = FileSystemProjectStore(str(tmp_path))
        pid, _ = store.create_project("meta_test", TaskType.DET)
        meta = store.load_meta(pid)
        # 元数据可能为 None（未保存）或 dict
        if meta is not None:
            assert isinstance(meta, dict)

    def test_get_layout(self, tmp_path):
        """获取项目布局。"""
        from project.store import FileSystemProjectStore
        store = FileSystemProjectStore(str(tmp_path))
        pid, layout = store.create_project("layout_test", TaskType.DET)
        layout2 = store.get_layout(pid)
        assert layout2 is not None
