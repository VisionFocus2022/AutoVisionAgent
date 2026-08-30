"""W19（v3 第三波 FR-4 / AC-4.1~4.2）：数据集版本管理核心库测试。

三组行为（先 RED 后 GREEN，对应 project/versioning.py）：
1. 全生命周期：建树 → build_manifest → create_snapshot → 增/删/改 →
   diff_manifests 精确三类 → restore_snapshot 哈希还原 + 新增文件保留；
2. verify_snapshot 检出污染：快照后就地改写源文件（硬链共享块）→ corrupted；
3. restore_snapshot 拒绝 corrupted 快照（raise，错误信息含问题文件）。

关键测试语义：快照文件是 NTFS 硬链（os.link）——"就地改写"（r+b 写穿
同一 inode）会污染快照共享块（第 2 组守这个语义）；而"原子替换"
（temp + os.replace，模拟规范编辑器）断开硬链、保持快照不可变
（第 1 组生命周期改动用这个方式写）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil

import pytest

from project import versioning


def _sha(path) -> str:
    """测试侧独立哈希（不经过被测模块，避免同源同错）。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path, data: bytes) -> None:
    """原子替换写入：新 inode，断开与快照的硬链（规范编辑器行为）。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_inplace(path, data: bytes) -> None:
    """就地改写：r+b 写穿既有 inode（污染硬链共享块，非规范行为）。"""
    with open(path, "r+b") as f:
        f.write(data)


@pytest.fixture
def proj(tmp_path):
    """标准项目树：images/ 2 图 + annotations/ 1 JSON（对齐 ProjectLayout 子目录）。"""
    img = tmp_path / "proj" / "images"
    ann = tmp_path / "proj" / "annotations"
    img.mkdir(parents=True)
    ann.mkdir()
    (img / "a.png").write_bytes(b"A" * 100)
    (img / "b.png").write_bytes(b"B" * 200)
    (ann / "a.json").write_text("{}", encoding="utf-8")
    return tmp_path / "proj"


# ============================== 第 1 组：全生命周期（AC-4.1） ============================== #
@pytest.mark.unit
def test_full_lifecycle_snapshot_diff_restore(proj):
    """建树 → 快照 → 增/删/改 → diff 三类精确 → 恢复 → 哈希还原 + 新增保留。"""
    m1 = versioning.build_manifest(str(proj))
    assert set(m1) == {"images/a.png", "images/b.png", "annotations/a.json"}
    assert m1["images/a.png"]["size"] == 100
    assert m1["images/a.png"]["sha256"] == _sha(proj / "images" / "a.png")

    snap = versioning.create_snapshot(str(proj), "基准")
    assert os.path.isfile(os.path.join(snap, "manifest.json"))
    assert os.path.isfile(os.path.join(snap, "images", "a.png"))

    # 快照后：增 1 / 删 1 / 改 1（改走原子替换——断开硬链，保持快照不可变；
    # 就地改写污染快照的场景由第 2 组专门守）
    (proj / "images" / "c.png").write_bytes(b"C" * 50)  # 增
    os.remove(proj / "images" / "b.png")  # 删
    _write_atomic(proj / "annotations" / "a.json", b'{"x": 1}')  # 改

    m2 = versioning.build_manifest(str(proj))
    diff = versioning.diff_manifests(m1, m2)
    assert diff == {
        "added": ["images/c.png"],
        "removed": ["images/b.png"],
        "changed": ["annotations/a.json"],
    }

    result = versioning.restore_snapshot(str(proj), snap)
    # 改 1 + 删 1 → 还原 2 处；增 1 → 保留 1 处（非破坏性）
    assert result == {"restored": 2, "kept_new": 1}

    m3 = versioning.build_manifest(str(proj))
    assert m3["images/a.png"]["sha256"] == m1["images/a.png"]["sha256"]
    assert m3["annotations/a.json"]["sha256"] == (
        m1["annotations/a.json"]["sha256"]
    )
    assert (proj / "images" / "b.png").exists()
    assert (proj / "images" / "c.png").exists()  # 新增文件保留
    assert json.loads((proj / "annotations" / "a.json").read_text("utf-8")) == {}
    # 恢复后快照本体完好（copy2 回拷未写穿共享 inode）
    assert versioning.verify_snapshot(snap) == []


@pytest.mark.unit
def test_build_manifest_skips_snapshots_dir(proj):
    """.snapshots/ 自身不入清单（否则快照套快照、diff/恢复被污染）。"""
    versioning.create_snapshot(str(proj), "v1")
    manifest = versioning.build_manifest(str(proj))
    assert len(manifest) == 3
    assert not any(p.startswith(".snapshots") for p in manifest)


@pytest.mark.unit
def test_diff_manifests_pure_three_classes():
    """diff_manifests 是纯函数：仅按路径集合与 sha256 分三类。"""
    old = {"a": {"sha256": "1", "size": 1}, "b": {"sha256": "2", "size": 2}}
    new = {"b": {"sha256": "9", "size": 2}, "c": {"sha256": "3", "size": 3}}
    assert versioning.diff_manifests(old, new) == {
        "added": ["c"],
        "removed": ["a"],
        "changed": ["b"],
    }


@pytest.mark.unit
def test_create_snapshot_uses_hardlinks(proj):
    """快照文件与源文件共享 inode（NTFS 硬链，O(1) 不复制数据块）。"""
    snap = versioning.create_snapshot(str(proj), "v1")
    assert os.stat(proj / "images" / "a.png").st_nlink >= 2
    assert os.stat(os.path.join(snap, "images", "a.png")).st_nlink >= 2
    # manifest.json 结构：label 元数据 + files 清单（原子写，无 .tmp 残留）
    with open(os.path.join(snap, "manifest.json"), encoding="utf-8") as f:
        payload = json.loads(f.read())
    assert payload["label"] == "v1"
    assert len(payload["files"]) == 3
    assert not any(
        n.startswith("manifest.json.tmp") for n in os.listdir(snap)
    )


@pytest.mark.unit
def test_create_snapshot_sanitizes_label(proj):
    """非法文件名字符（Windows 保留集）净化为下划线，目录可建。"""
    snap = versioning.create_snapshot(str(proj), 'a/b:c*d?e<f>"g|h')
    name = os.path.basename(snap)
    assert os.path.isdir(snap)
    for ch in '<>:"/\\|?*':
        assert ch not in name


@pytest.mark.unit
def test_list_snapshots_sorted_with_counts(proj):
    """无快照 → []；有则按时间排序 [(dir, label, manifest 条目数)]。"""
    assert versioning.list_snapshots(str(proj)) == []
    s1 = versioning.create_snapshot(str(proj), "alpha")
    s2 = versioning.create_snapshot(str(proj), "beta")
    snaps = versioning.list_snapshots(str(proj))
    assert [(label, count) for _, label, count in snaps] == [
        ("alpha", 3),
        ("beta", 3),
    ]
    assert snaps[0][0] == s1 and snaps[1][0] == s2  # 时间序（时间戳前缀）


# ============================== 第 2 组：verify 检出污染（AC-4.2） ============================== #
@pytest.mark.unit
def test_verify_clean_snapshot_has_no_problems(proj):
    snap = versioning.create_snapshot(str(proj), "v1")
    assert versioning.verify_snapshot(snap) == []


@pytest.mark.unit
def test_verify_detects_inplace_rewrite_via_shared_blocks(proj):
    """快照后就地改写源文件 → 硬链共享块被写穿 → verify 报告 corrupted。"""
    snap = versioning.create_snapshot(str(proj), "v1")
    assert (proj / "images" / "a.png").stat().st_nlink >= 2  # 确认共享 inode
    _write_inplace(proj / "images" / "a.png", b"Z" * 100)
    problems = versioning.verify_snapshot(snap)
    assert len(problems) == 1
    assert "images/a.png" in problems[0]


@pytest.mark.unit
def test_verify_reports_missing_snapshot_file(proj):
    """快照目录内文件缺失（哈希无从对照）→ 问题条目。"""
    snap = versioning.create_snapshot(str(proj), "v1")
    os.remove(os.path.join(snap, "images", "b.png"))
    problems = versioning.verify_snapshot(snap)
    assert len(problems) == 1
    assert "images/b.png" in problems[0]


@pytest.mark.unit
def test_verify_without_manifest_raises(proj, tmp_path):
    """无 manifest.json 的目录不是合法快照 → ValueError（诚实失败）。"""
    fake = tmp_path / "not_a_snapshot"
    fake.mkdir()
    with pytest.raises(ValueError):
        versioning.verify_snapshot(str(fake))


# ============================== 第 3 组：restore 拒绝 corrupted（AC-4.2） ============================== #
@pytest.mark.unit
def test_restore_rejects_corrupted_snapshot(proj):
    """快照被就地改写污染 → restore 先 verify 并 raise，错误含问题文件。"""
    snap = versioning.create_snapshot(str(proj), "v1")
    _write_inplace(proj / "images" / "a.png", b"Z" * 100)  # 污染共享块
    with pytest.raises(ValueError) as excinfo:
        versioning.restore_snapshot(str(proj), snap)
    assert "images/a.png" in str(excinfo.value)
    # 拒绝恢复：项目现状不被覆盖（仍是被污染后的 Z 内容）
    assert (proj / "images" / "a.png").read_bytes() == b"Z" * 100


@pytest.mark.unit
def test_restore_recreates_removed_subdir(proj):
    """快照后整目录被删 → restore 重建目录并回拷文件。"""
    snap = versioning.create_snapshot(str(proj), "v1")
    shutil.rmtree(proj / "annotations")
    result = versioning.restore_snapshot(str(proj), snap)
    assert result == {"restored": 1, "kept_new": 0}
    assert (proj / "annotations" / "a.json").exists()
    assert json.loads((proj / "annotations" / "a.json").read_text("utf-8")) == {}
