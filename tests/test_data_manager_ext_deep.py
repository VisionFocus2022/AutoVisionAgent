"""industrial_vision_platform/data_manager_ext 深度补测（W10-T4：38% 洼地填平）。

覆盖：create_project 元数据合并（读成功 / 缺文件 / 损坏 JSON 三路）与
TaskType 直传、recent 列表、import_to_project 递归复制/已存在去重/失败
统计、get_project_stats（分类子目录 + 散图 + 标注 + 划分）、
split_project_dataset（比例校验 / 空库 / 真移动 / 同名目标去重）、
delete_project（合法 / 非法 / 幽灵目录）、get_counters、显式计数器注入、
project 模块不可用时的降级导入分支。全部离线（tmp_path）驱动。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

import industrial_vision_platform.data_manager_ext as dme
from core.interfaces_supervised import TaskType
from project.counter import TaskCounter
from project.models import ProjectId, ProjectLayout


@pytest.fixture
def base(tmp_path):
    return str(tmp_path / "projects")


@pytest.fixture
def ext(base):
    return dme.DataManagerExt(None, base)


def _write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "w" if isinstance(content, str) else "wb"
    with open(path, mode) as f:
        f.write(content)


# ============================== create_project ============================== #
@pytest.mark.unit
def test_create_project_with_label_tag_merges_meta(ext, base):
    """store 先写基础 meta，ext 再读回合并 label/tag（读成功路径）。"""
    dirname, layout = ext.create_project("demo", "det", label="钢印", tag="v2")
    assert dirname == "det_0001_demo"
    assert layout.root == os.path.join(base, dirname)
    assert os.path.isdir(layout.images_dir)
    assert os.path.isdir(layout.annotations_dir)

    with open(os.path.join(layout.root, "project_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["task"] == "det"
    assert meta["seq"] == 1
    assert meta["name"] == "demo"
    assert meta["label"] == "钢印"
    assert meta["tag"] == "v2"


@pytest.mark.unit
def test_create_project_meta_missing_starts_fresh(ext, base, monkeypatch):
    """meta 文件缺失（OSError 分支）→ 从空 dict 重建。"""
    pid = ProjectId(TaskType.SEG, 7, "stub")
    layout = ProjectLayout(pid, base)
    os.makedirs(layout.root, exist_ok=True)
    monkeypatch.setattr(
        ext._store, "create_project", lambda name, task: (pid, layout)
    )
    dirname, lay = ext.create_project("n", "seg", label="L")
    assert dirname == "seg_0007_stub"
    with open(os.path.join(lay.root, "project_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta == {"label": "L"}  # 原有基础字段全部丢失，仅保留新写入项


@pytest.mark.unit
def test_create_project_meta_corrupt_json_resets(ext, base, monkeypatch):
    """meta 文件损坏（JSONDecodeError 分支）→ 同样从空 dict 重建。"""
    pid = ProjectId(TaskType.CLS, 3, "corrupt")
    layout = ProjectLayout(pid, base)
    os.makedirs(layout.root, exist_ok=True)
    _write(os.path.join(layout.root, "project_meta.json"), "{oops not json")
    monkeypatch.setattr(
        ext._store, "create_project", lambda name, task: (pid, layout)
    )
    _, lay = ext.create_project("n", "cls", label="X", tag="T")
    with open(os.path.join(lay.root, "project_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta == {"label": "X", "tag": "T"}


@pytest.mark.unit
def test_create_project_accepts_tasktype_enum(ext):
    """task 参数直传 TaskType 枚举（非字符串）也成立。"""
    dirname, layout = ext.create_project("enum", TaskType.CLS)
    assert dirname.startswith("cls_")
    assert os.path.isdir(layout.root)


@pytest.mark.unit
def test_create_project_meta_write_failure_swallowed(ext, base, monkeypatch):
    """meta 写盘失败（OSError 分支，lines 113-114）→ 静默吞掉，不影响创建返回。"""
    pid = ProjectId(TaskType.DET, 5, "wfail")
    layout = ProjectLayout(pid, base)
    os.makedirs(layout.root, exist_ok=True)
    monkeypatch.setattr(
        ext._store, "create_project", lambda name, task: (pid, layout)
    )

    def _disk_full(obj, f, **kw):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("json.dump", _disk_full)
    dirname, lay = ext.create_project("n", "det", label="L")  # 不应抛出
    assert dirname == "det_0005_wfail"
    assert lay.root == layout.root


# ============================== recent ============================== #
@pytest.mark.unit
def test_recent_projects_newest_first(ext):
    d1, _ = ext.create_project("first", "det")
    d2, _ = ext.create_project("second", "det")
    assert ext.recent_projects() == [d2, d1]  # 最新置顶


# ============================== import_to_project ============================== #
@pytest.mark.unit
def test_import_to_project_recursive_and_dedupe(ext, base):
    src = os.path.join(base, "..", "src_img")  # base 同级的源目录
    src = os.path.normpath(src)
    _write(os.path.join(src, "a.png"))
    _write(os.path.join(src, "sub", "b.JPG"))  # 大写扩展名 + 子目录递归
    _write(os.path.join(src, "c.txt"))  # 非图像忽略
    _write(os.path.join(src, "d.bmp"))

    _, layout = ext.create_project("imp", "det")
    r1 = ext.import_to_project(layout.root, src)
    assert r1 == {"imported": 3, "failed": 0}
    ok_dir = os.path.join(layout.root, "images", "OK")
    assert sorted(os.listdir(ok_dir)) == ["a.png", "b.JPG", "d.bmp"]

    # 再次导入同类：目标已存在 → 视为成功不重拷（line 175）
    r2 = ext.import_to_project(layout.root, src)
    assert r2 == {"imported": 3, "failed": 0}
    assert sorted(os.listdir(ok_dir)) == ["a.png", "b.JPG", "d.bmp"]


@pytest.mark.unit
def test_import_to_project_copy_failure_counted(ext, base, monkeypatch):
    src = os.path.normpath(os.path.join(base, "..", "bad_src"))
    _write(os.path.join(src, "e.png"))
    _write(os.path.join(src, "f.jpg"))
    _write(os.path.join(src, "g.txt"))  # 非图像，不进统计

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("shutil.copy2", _boom)
    _, layout = ext.create_project("badimp", "det")
    r = ext.import_to_project(layout.root, src)
    assert r == {"imported": 0, "failed": 2}


# ============================== get_project_stats ============================== #
@pytest.mark.unit
def test_get_project_stats_full(ext, base):
    root = os.path.join(base, "stat_proj")
    _write(os.path.join(root, "images", "OK", "a.png"))
    _write(os.path.join(root, "images", "OK", "b.jpg"))
    _write(os.path.join(root, "images", "OK", "junk.txt"))  # 不计数
    _write(os.path.join(root, "images", "NG", "c.png"))
    _write(os.path.join(root, "images", "loose.png"))  # 散图
    _write(os.path.join(root, "images", "readme.txt"))  # 散置非图忽略
    _write(os.path.join(root, "annotations", "x.json"))
    _write(os.path.join(root, "annotations", "y.json"))
    _write(os.path.join(root, "annotations", "z.txt"))  # 非 json 忽略
    _write(os.path.join(root, "train", "t1.png"))
    _write(os.path.join(root, "train", "t2.png"))
    _write(os.path.join(root, "val", "v1.png"))
    # 无 test/ 目录 → splits 不含 test 键

    stats = ext.get_project_stats(root)
    assert stats["total_images"] == 4  # OK 2 + NG 1 + 散图 1
    assert stats["classes"] == {"OK": 2, "NG": 1}
    assert stats["annotated"] == 2
    assert stats["splits"] == {"train": 2, "val": 1}


@pytest.mark.unit
def test_get_project_stats_empty_project(ext, base):
    stats = ext.get_project_stats(os.path.join(base, "ghost"))
    assert stats == {
        "total_images": 0,
        "annotated": 0,
        "classes": {},
        "splits": {},
    }


# ============================== split_project_dataset ============================== #
@pytest.mark.unit
def test_split_ratio_must_sum_to_one(ext, base):
    with pytest.raises(ValueError, match="ratios must sum to 1.0"):
        ext.split_project_dataset(os.path.join(base, "p"), 0.5, 0.1, 0.1)


@pytest.mark.unit
def test_split_empty_returns_zeros(ext, base):
    root = os.path.join(base, "p")
    os.makedirs(os.path.join(root, "images"), exist_ok=True)
    counts = ext.split_project_dataset(root)
    assert counts == {"train": 0, "val": 0, "test": 0}
    assert not os.path.exists(os.path.join(root, "train"))  # 不创建空目录


@pytest.mark.unit
def test_split_moves_all_images(ext, base):
    root = os.path.join(base, "p")
    for i in range(10):
        _write(os.path.join(root, "images", "OK", f"{i}.png"))

    counts = ext.split_project_dataset(root, 0.8, 0.1, 0.1)
    assert counts == {"train": 8, "val": 1, "test": 1}
    assert os.listdir(os.path.join(root, "images", "OK")) == []  # 全部移走
    assert len(os.listdir(os.path.join(root, "train"))) == 8
    assert len(os.listdir(os.path.join(root, "val"))) == 1
    assert len(os.listdir(os.path.join(root, "test"))) == 1


@pytest.mark.unit
def test_split_skips_existing_destination(ext, base):
    """目标同名文件已存在 → 不覆盖、不移动（lines 277-278）。"""
    root = os.path.join(base, "p")
    ok_dir = os.path.join(root, "images", "OK")
    _write(os.path.join(ok_dir, "a.png"), b"ONE")

    counts = ext.split_project_dataset(root, 1.0, 0.0, 0.0)
    assert counts == {"train": 1, "val": 0, "test": 0}

    _write(os.path.join(ok_dir, "a.png"), b"TWO")  # 源目录重新出现同名文件
    counts2 = ext.split_project_dataset(root, 1.0, 0.0, 0.0)
    assert counts2 == {"train": 1, "val": 0, "test": 0}
    train_file = os.path.join(root, "train", "a.png")
    with open(train_file, "rb") as f:
        assert f.read() == b"ONE"  # 旧文件保留，未被覆盖
    with open(os.path.join(ok_dir, "a.png"), "rb") as f:
        assert f.read() == b"TWO"  # 新文件留在原地


# ============================== delete_project ============================== #
@pytest.mark.unit
def test_delete_project_removes_dir_and_recent(ext, base):
    dirname, layout = ext.create_project("del", "seg")
    assert os.path.isdir(layout.root)
    assert ext.recent_projects() == [dirname]

    assert ext.delete_project(dirname) is True
    assert not os.path.isdir(layout.root)
    assert ext.recent_projects() == []


@pytest.mark.unit
def test_delete_project_invalid_dirname_returns_false(ext):
    assert ext.delete_project("not-a-project") is False


@pytest.mark.unit
def test_delete_project_missing_dir_still_succeeds(ext, base):
    """目录名合法但磁盘不存在 → 不 rmtree，仍清理 recent 并返回 True。"""
    assert ext.delete_project("det_0999_ghost") is True
    assert not os.path.isdir(os.path.join(base, "det_0999_ghost"))


# ============================== 计数器 ============================== #
@pytest.mark.unit
def test_get_counters_reflects_creations(ext):
    ext.create_project("a", "det")
    ext.create_project("b", "det")
    assert ext.get_counters() == {"det": 2}


@pytest.mark.unit
def test_constructor_explicit_counter_wins(base, tmp_path):
    """显式传入 counter → get_counters 用它而非 store 内部计数器。"""
    other_root = str(tmp_path / "other_counter")
    tc = TaskCounter(other_root)
    ext = dme.DataManagerExt(None, base, counter=tc)
    ext.create_project("x", "det")  # seq 走 store 自己的计数器
    assert ext.get_counters() == {}  # 显式计数器未被触碰
    assert tc.snapshot() == {}


# ============================== project 模块缺失降级分支 ============================== #
@pytest.mark.unit
def test_import_fallback_when_project_unavailable(monkeypatch, caplog):
    """sys.modules 注入 None 使 project.models 导入失败 → 执行降级分支
    （lines 31-47），桩符号可用且不抛错。"""
    monkeypatch.setitem(sys.modules, "project.models", None)
    spec = importlib.util.spec_from_file_location(
        "dme_fallback_probe", dme.__file__
    )
    mod = importlib.util.module_from_spec(spec)
    with caplog.at_level("WARNING"):
        spec.loader.exec_module(mod)

    assert "不可用" in caplog.text
    assert mod.ProjectId is str
    assert mod.ProjectLayout is dict
    assert mod.parse_project_dirname is None
    assert mod.TaskCounter().next_id() == 0
    assert mod.recent_mod.load_recent() == []
    assert mod.recent_mod.add_recent("x") is None
    assert mod.recent_mod.save_recent([]) is None
    assert hasattr(mod, "DataManagerExt")
