"""第四轮审查第二批修复回归测试（2026-10-07）。

S-4 project 三处原子写 / S-5 项目名净化 / S-6 快照单遍自洽 / S-7
anomaly_map detach。
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ============================== S-4：原子写 ============================== #


@pytest.mark.unit
def test_s4_counter_atomic_no_tmp_leftover(tmp_path):
    """S-4：计数器保存后无 .tmp 残留（原子写生效）。"""
    from project.counter import TaskCounter

    c = TaskCounter(str(tmp_path))
    for _ in range(5):
        c.next_id("det")

    data = json.loads((tmp_path / "task_counter.json").read_text(encoding="utf-8"))
    assert data == {"det": 5}
    assert not list(tmp_path.glob("*.tmp")), "原子写不得残留 tmp"


@pytest.mark.unit
def test_s4_recent_atomic_roundtrip(tmp_path):
    from project.recent import add_recent, recent_list

    add_recent(str(tmp_path), "det_0001_demo")
    add_recent(str(tmp_path), "det_0002_new")
    lst = recent_list(str(tmp_path))
    assert lst[0] == "det_0002_new"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.unit
def test_s4_corrupt_counter_recovers_with_count_reset(tmp_path):
    """S-4 语义：损坏文件 → 从空重启（有 warning 不崩）。"""
    from project.counter import TaskCounter

    (tmp_path / "task_counter.json").write_text("{corrupt", encoding="utf-8")
    c = TaskCounter(str(tmp_path))  # 不崩
    assert c.get("det") == 0
    n = c.next_id("det")
    assert n == 1


# ============================== S-5：项目名净化 ============================== #


@pytest.mark.unit
def test_s5_project_name_traversal_rejected(tmp_path):
    """S-5 核心：路径穿越名被显式拒绝（此前逃逸 base_root 建目录）。"""
    from core.exceptions import UnsupportedTaskError  # noqa: F401
    from core.interfaces_supervised import TaskType
    from project.store import FileSystemProjectStore

    store = FileSystemProjectStore(str(tmp_path))
    for evil in ("../../evil", "..\\..\\evil", "a/b", "a:b", "na*me", ""):
        with pytest.raises(ValueError, match="项目名"):
            store.create_project(evil, TaskType.DET)
    # base_root 之外无目录产生
    assert not (tmp_path.parent / "evil").exists()


@pytest.mark.unit
def test_s5_valid_names_accepted(tmp_path):
    from core.interfaces_supervised import TaskType
    from project.store import FileSystemProjectStore

    store = FileSystemProjectStore(str(tmp_path))
    for ok in ("demo", "my-project_2", "中文项目"):
        pid, _layout = store.create_project(ok, TaskType.DET)
        assert pid.name == ok


# ============================== S-6：快照单遍自洽 ============================== #


@pytest.mark.unit
def test_s6_snapshot_manifest_matches_content(tmp_path):
    """S-6 核心：manifest 哈希与快照侧文件内容自洽（verify 必过）。"""
    from project.versioning import create_snapshot, verify_snapshot

    proj = tmp_path / "proj"
    (proj / "data").mkdir(parents=True)
    (proj / "data" / "a.txt").write_text("hello", encoding="utf-8")
    (proj / "b.txt").write_text("world", encoding="utf-8")

    snap = create_snapshot(str(proj), "v1")
    problems = verify_snapshot(snap)
    assert problems == [], f"快照必须自洽: {problems}"


@pytest.mark.unit
def test_s6_snapshot_after_concurrent_edit_still_consistent(tmp_path):
    """S-6：快照期间源文件被改（模拟一致性窗口）——manifest 哈希的是
    快照侧内容，verify 依然通过（旧实现此处必假阳性）。"""
    from project.versioning import create_snapshot, verify_snapshot

    proj = tmp_path / "proj"
    proj.mkdir()
    target = proj / "x.txt"
    target.write_text("before", encoding="utf-8")

    # 猴补 _link_or_copy：硬链后立即改源文件（就地改写穿硬链共享块）
    import project.versioning as ver

    orig_link = ver._link_or_copy

    def link_then_mutate(src, dst):
        orig_link(src, dst)
        if os.path.basename(src) == "x.txt":
            with open(src, "w", encoding="utf-8") as f:
                f.write("after-mutation")

    ver._link_or_copy = link_then_mutate
    try:
        snap = create_snapshot(str(proj), "race")
    finally:
        ver._link_or_copy = orig_link

    # 单遍哈希的是快照侧（dst）——即使源被改，快照内容与 manifest 一致
    problems = verify_snapshot(snap)
    assert problems == [], f"单遍自洽必须成立: {problems}"


# ============================== S-7：anomaly_map detach ============================== #


@pytest.mark.unit
def test_s7_anomaly_map_detached_cpu():
    """S-7：infer 输出处理段——anomaly_map detach+cpu 语义（不依赖引擎
    实例化，直接验证处理逻辑与生产代码同构）。"""
    torch = pytest.importorskip("torch")
    from core.interfaces_supervised import DetectionResult, TaskType

    # 复刻 abdet_anomalib.infer 尾段（R4-S7 修复后的处理逻辑）
    anomaly_map = torch.tensor([[1.0, 2.0]], requires_grad=True)
    score = torch.tensor([0.8])
    score_f = float(score.detach().cpu().mean())

    result = DetectionResult(task=TaskType.ABDET, score=score_f)
    if anomaly_map is not None:
        # 与生产代码一字不差的 S-7 处理
        result = result.with_extra("anomaly_map", anomaly_map.detach().cpu())

    am = result.extra["anomaly_map"]
    assert not am.requires_grad, "必须 detach（防计算图滞留）"
    assert am.device.type == "cpu", "必须 cpu（防 GPU 显存累积）"

    # 源码静态断言：生产 infer 含 detach().cpu()（防未来回归）
    import inspect

    import models.supervised.engines.abdet_anomalib as mod

    src = inspect.getsource(mod)
    assert 'anomaly_map.detach().cpu()' in src, \
        "abdet infer 必须保持 anomaly_map detach().cpu()（R4-S7）"
