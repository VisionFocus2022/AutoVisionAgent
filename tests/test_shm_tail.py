"""serving/shared_memory.py 尾巴补测（W14-C4：86% → 目标 ≥93%）。

覆盖权威 missing 行清单（定向 coverage 实测）：
123（TEMP 缺省目录）、155-156（清扫 stat OSError 跳过）、162-164（清扫
unlink 失败告警）、189（write_array 显式坏 dtype）、209-217（bool 掩码 RLE
压缩写出）、234-240（_write_raw 映射失败回滚清理）、272-275（bool_rle 读回
解码）、278（read_array 坏 dtype）、299-305（read_bytes 本地映射/远端文件
双路径）、314-323（_discard_mapping 三段尽力回收异常全吞）、351-352
（cleanup 单区失败告警续清）、361（max_regions 显式非法）、367-368（环境
变量非整数回退默认）、401（_read_range_from_file 带 offset seek）。
"""
from __future__ import annotations

import logging
import mmap
import os
from pathlib import Path

import numpy as np
import pytest

from serving.shared_memory import (
    SharedMemoryHandle,
    SharedMemoryManager,
    _read_range_from_file,
)


@pytest.fixture
def shm_dir(tmp_path):
    d = tmp_path / "shm"
    d.mkdir()
    return d


def _stale(path: Path) -> None:
    """把文件 mtime 拨回 3 小时前（超过 _STALE_FILE_MAX_AGE_SECONDS=2h）。"""
    old = os.stat(path).st_mtime - 3 * 60 * 60
    os.utime(path, (old, old))


# ============================== 构造/缺省目录 ============================== #
@pytest.mark.unit
def test_default_base_dir_uses_temp_env(shm_dir, monkeypatch):
    """base_dir=None → TEMP 环境变量下 autovisionagent_shm 子目录（:123）。"""
    monkeypatch.setenv("TEMP", str(shm_dir))
    monkeypatch.setenv("TMP", str(shm_dir))
    mgr = SharedMemoryManager()
    assert str(mgr._base_dir) == str(shm_dir / "autovisionagent_shm")
    h = mgr.write_array(np.arange(6, dtype=np.uint8).reshape(2, 3))
    assert mgr.read_array(h).tolist() == [[0, 1, 2], [3, 4, 5]]
    mgr.cleanup()


# ============================== 启动清扫异常分支 ============================== #
@pytest.mark.unit
def test_sweep_skips_entry_when_stat_fails(shm_dir, monkeypatch):
    """陈旧文件 stat 抛 OSError → continue 跳过，文件不删也不炸（:155-156）。"""
    stale_f = shm_dir / "ava_dead.bin"
    stale_f.write_bytes(b"x")
    _stale(stale_f)

    orig_stat = Path.stat

    def _stat_raises_for_ava(self, *a, **kw):
        if self.name.startswith("ava_"):
            raise OSError("stat boom")
        return orig_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", _stat_raises_for_ava)
    SharedMemoryManager(base_dir=str(shm_dir))  # 不得抛
    # 用 os.path.exists 断言（Path.exists 内部走被 patch 的 Path.stat）
    assert os.path.exists(stale_f)  # stat 失败 → continue → 未删除


@pytest.mark.unit
def test_sweep_unlink_failure_warns_and_continues(
    shm_dir, monkeypatch, caplog
):
    """陈旧文件 unlink 抛 OSError → 告警并留给下次启动，构造不炸（:162-164）。"""
    stale_f = shm_dir / "ava_locked.bin"
    stale_f.write_bytes(b"x")
    _stale(stale_f)

    orig_unlink = Path.unlink
    monkeypatch.setattr(
        Path, "unlink",
        lambda self, *a, **kw: (_ for _ in ()).throw(OSError("locked"))
        if self.name.startswith("ava_") else orig_unlink(self, *a, **kw),
    )
    with caplog.at_level(logging.WARNING, logger="serving.shared_memory"):
        SharedMemoryManager(base_dir=str(shm_dir))
    assert any("启动清扫陈旧共享内存文件失败" in r.getMessage()
               for r in caplog.records)
    assert stale_f.exists()  # Windows 被占用场景：文件留待下次


# ============================== 写出边界 ============================== #
@pytest.mark.unit
def test_write_array_explicit_dtype_unsupported(shm_dir):
    """显式 dtype 覆盖为契约外类型 → ValueError（:189）。"""
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    with pytest.raises(ValueError, match="不支持的 dtype"):
        mgr.write_array(np.zeros(4, dtype=np.float32), dtype="float16")


@pytest.mark.unit
def test_write_mask_compact_rle_roundtrip(shm_dir):
    """bool 掩码走 RLE 压缩写出（dtype=bool_rle）+ read_array 自动解码
    还原（:209-217、:272-275）。"""
    rng = np.random.default_rng(7)
    masks = rng.random((2, 5, 7)) > 0.5
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    h = mgr.write_mask_compact(masks)
    assert h.dtype == "bool_rle"
    assert h.shape == (2, 5, 7)
    back = mgr.read_array(h)
    assert back.dtype == np.bool_
    assert back.shape == (2, 5, 7)
    np.testing.assert_array_equal(back, masks)
    mgr.cleanup()


@pytest.mark.unit
def test_write_mask_compact_non_bool_input_coerced(shm_dir):
    """非 bool 掩码（uint8 0/1）→ astype(bool) 强转后走 RLE（:213）。"""
    masks = (np.arange(12) % 3 == 0).astype(np.uint8).reshape(3, 4)
    assert masks.dtype != np.bool_
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    back = mgr.read_array(mgr.write_mask_compact(masks))
    assert back.dtype == np.bool_
    np.testing.assert_array_equal(back, masks.astype(np.bool_))
    mgr.cleanup()


@pytest.mark.unit
def test_write_raw_cleanup_tolerates_unlink_failure(shm_dir, monkeypatch):
    """映射失败回滚时连 unlink 也失败 → 仍上抛原始异常、登记表不污染
    （:238-239）。"""
    mgr = SharedMemoryManager(base_dir=str(shm_dir))

    def _mmap_boom(*a, **kw):
        raise OSError("mmap boom")

    monkeypatch.setattr(mmap, "mmap", _mmap_boom)
    monkeypatch.setattr(os, "unlink",
                        lambda p: (_ for _ in ()).throw(OSError("unlink boom")))
    with pytest.raises(OSError, match="mmap boom"):  # 原始异常优先上抛
        mgr.write_bytes(b"payload")
    assert mgr._regions == {}


@pytest.mark.unit
def test_write_raw_mapping_failure_cleans_up(shm_dir, monkeypatch):
    """mmap 映射失败 → 关 fd、删文件、异常上抛（:234-240）。"""
    mgr = SharedMemoryManager(base_dir=str(shm_dir))

    def _boom(*a, **kw):
        raise OSError("mmap boom")

    monkeypatch.setattr(mmap, "mmap", _boom)
    with pytest.raises(OSError, match="mmap boom"):
        mgr.write_bytes(b"payload")
    assert mgr._regions == {}  # 登记表未污染
    assert not list(shm_dir.glob("ava_*.bin"))  # 半成品文件已删


# ============================== 读入边界 ============================== #
@pytest.mark.unit
def test_read_array_unsupported_dtype(shm_dir):
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    h = mgr.write_bytes(b"\x00" * 8)
    bad = SharedMemoryHandle(file_path=h.file_path, offset=0, length=8,
                             dtype="float16", shape=(2, 4))
    with pytest.raises(ValueError, match="不支持的 dtype"):
        mgr.read_array(bad)


@pytest.mark.unit
def test_read_bytes_local_mapping_and_remote_file(shm_dir):
    """read_bytes 双路径：本地已映射区域走 mmap 切片；陌生管理器按
    文件路径读（:299-305）。"""
    payload = bytes(range(32))
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    h = mgr.write_bytes(payload)
    assert mgr.read_bytes(h) == payload  # 本地映射分支（:304）

    other = SharedMemoryManager(base_dir=str(shm_dir))  # 无登记 → 文件分支
    assert other.read_bytes(h) == payload
    mgr.cleanup()


@pytest.mark.unit
def test_read_range_from_file_with_offset(tmp_path):
    """offset≠0 → seek 后读取指定区间（:401）。"""
    f = tmp_path / "plain.bin"
    f.write_bytes(b"0123456789")
    assert _read_range_from_file(str(f), 2, 3) == b"234"
    assert _read_range_from_file(str(f), 0, 4) == b"0123"


# ============================== 回收尽力而为 ============================== #
@pytest.mark.unit
def test_discard_mapping_swallows_all_failures(monkeypatch):
    """mm.close 抛 BufferError、os.close/os.unlink 抛 OSError 均须吞
    （:314-315、:318-319、:322-323）——尽力回收不得二次抛错。"""
    monkeypatch.setattr(os, "close",
                        lambda fd: (_ for _ in ()).throw(OSError("close boom")))
    monkeypatch.setattr(os, "unlink",
                        lambda p: (_ for _ in ()).throw(OSError("unlink boom")))

    class _BadMm:
        def close(self):
            raise BufferError("exported buffers exist")

    SharedMemoryManager._discard_mapping(-999, _BadMm(), "no/such/file")


@pytest.mark.unit
def test_cleanup_release_failure_warns_and_continues(
    shm_dir, monkeypatch, caplog
):
    """某区域 release 抛错 → 告警但继续清其余区域，不炸不中断（:351-352）。"""
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    mgr.write_bytes(b"one")
    mgr.write_bytes(b"two")

    def _bad_release(_p):
        raise RuntimeError("release boom")

    monkeypatch.setattr(mgr, "release", _bad_release)
    with caplog.at_level(logging.WARNING, logger="serving.shared_memory"):
        mgr.cleanup()  # 每个区域都告警但循环走完
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("清理共享内存" in m for m in msgs) == 2


# ============================== max_regions 解析边界 ============================== #
@pytest.mark.unit
def test_max_regions_explicit_below_one_rejected(shm_dir):
    """显式 max_regions < 1 → ValueError（:361）。"""
    with pytest.raises(ValueError, match="max_regions 必须 >= 1"):
        SharedMemoryManager(base_dir=str(shm_dir), max_regions=0)


@pytest.mark.unit
def test_max_regions_env_non_integer_warns_and_defaults(
    shm_dir, monkeypatch, caplog
):
    """AVA_SHM_MAX_REGIONS 非整数 → 告警 + 回退默认 64（:367-368）。"""
    monkeypatch.setenv("AVA_SHM_MAX_REGIONS", "not-a-number")
    with caplog.at_level(logging.WARNING, logger="serving.shared_memory"):
        mgr = SharedMemoryManager(base_dir=str(shm_dir))
    assert mgr._max_regions == 64
    assert any("不是整数" in r.getMessage() for r in caplog.records)
