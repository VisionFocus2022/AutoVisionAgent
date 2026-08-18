"""serving/shared_memory 生命周期守护测试（W11 v2 P1-1，簇 F1：RED 先行）。

背景（架构审查 v2 确证）：``SharedMemoryManager.__init__`` 原先只 mkdir 不清扫，
%TEMP%/autovisionagent_shm 下进程崩溃残留的 ava_*.bin 永久堆积；区域登记
无上限，调用方忘 release 时静默无限泄漏。

本文件锁定三件事：
1. 启动清扫——新建管理器时删除陈旧（mtime 年龄超阈值）的 ava_*.bin；
   新鲜文件与非 ava_ 前缀文件一律不动。
2. 区域上限——上限可经构造参数 / 环境变量 AVA_SHM_MAX_REGIONS 注入（默认 64），
   写满后继续写入必须 RuntimeError（消息含当前区域数与上限）且不留泄漏文件。
3. 区域 TTL（W17，v3 P1-1）——区域登记时长超过 TTL（构造参数 /
   AVA_SHM_REGION_TTL_SECONDS，默认 300s，<=0 关闭）时，在下次写入前被
   惰性回收（文件删除、登记摘除、腾出上限槽位）；未超期区域不受影响。
"""
from __future__ import annotations

import os
import time

import pytest

np = pytest.importorskip("numpy")

from serving.shared_memory import SharedMemoryManager  # noqa: E402


def _put_file(base, name: str, content: bytes = b"x", mtime_age_seconds: float = 0.0):
    """在 base 下放置一个文件，可把 mtime 回拨到指定年龄前。"""
    path = base / name
    path.write_bytes(content)
    if mtime_age_seconds:
        old = time.time() - mtime_age_seconds
        os.utime(path, (old, old))
    return path


@pytest.fixture
def shm_dir(tmp_path):
    d = tmp_path / "shm"
    d.mkdir()
    return d


# ------------------------------ 启动清扫 ------------------------------ #


@pytest.mark.unit
def test_startup_sweep_deletes_stale_ava_files(shm_dir):
    stale = _put_file(shm_dir, "ava_deadbeef.bin", mtime_age_seconds=2 * 3600)

    SharedMemoryManager(base_dir=str(shm_dir))

    assert not stale.exists()


@pytest.mark.unit
def test_startup_sweep_keeps_fresh_and_foreign_files(shm_dir):
    fresh = _put_file(shm_dir, "ava_fresh.bin")
    foreign_stale = _put_file(shm_dir, "other_leftover.bin", mtime_age_seconds=3 * 3600)

    SharedMemoryManager(base_dir=str(shm_dir))

    assert fresh.exists()
    assert foreign_stale.exists()


# ------------------------------ 区域上限 ------------------------------ #


@pytest.mark.unit
def test_region_limit_raises_when_full_and_leaks_nothing(shm_dir):
    mgr = SharedMemoryManager(base_dir=str(shm_dir), max_regions=2)
    mgr.write_array(np.zeros(4, dtype=np.uint8))
    mgr.write_array(np.zeros(4, dtype=np.uint8))

    with pytest.raises(RuntimeError, match=r"当前 2 个 / 上限 2 个"):
        mgr.write_array(np.zeros(4, dtype=np.uint8))

    # 被拒绝的写入不得留下泄漏文件：目录内 ava_*.bin 数仍为 2
    assert len(list(shm_dir.glob("ava_*.bin"))) == 2


# ------------------------------ 区域 TTL（W17）------------------------------ #


@pytest.mark.unit
def test_region_ttl_lazy_reap_on_write(shm_dir):
    """超 TTL 区域在下次写入前被惰性回收：文件删除、登记摘除；新区域可读。"""
    mgr = SharedMemoryManager(
        base_dir=str(shm_dir), region_ttl_seconds=0.05
    )
    h1 = mgr.write_array(np.arange(4, dtype=np.uint8))
    h2 = mgr.write_array(np.arange(4, dtype=np.uint8))
    assert os.path.exists(h1.file_path) and os.path.exists(h2.file_path)

    time.sleep(0.08)  # 越过 TTL
    h3 = mgr.write_array(np.arange(4, dtype=np.uint8))

    assert not os.path.exists(h1.file_path)
    assert not os.path.exists(h2.file_path)
    # 未超期的新区域不受影响，仍可按句柄读回
    assert os.path.exists(h3.file_path)
    back = mgr.read_array(h3)
    np.testing.assert_array_equal(back, np.arange(4, dtype=np.uint8))


@pytest.mark.unit
def test_region_ttl_frees_cap_slots(shm_dir):
    """TTL 回收腾出上限槽位：上限 2 + 短 TTL 下第 3 次写入不再 RuntimeError。"""
    mgr = SharedMemoryManager(
        base_dir=str(shm_dir), max_regions=2, region_ttl_seconds=0.05
    )
    mgr.write_array(np.zeros(4, dtype=np.uint8))
    mgr.write_array(np.zeros(4, dtype=np.uint8))

    time.sleep(0.08)
    # 无 TTL 时此处必 RuntimeError（当前 2 / 上限 2）；TTL 回收后应成功
    h3 = mgr.write_array(np.zeros(4, dtype=np.uint8))

    # 紧接着（未超期）写入应重新受上限约束：此时在册 1 个，写第 2 个 OK、第 3 个拒绝
    mgr.write_array(np.zeros(4, dtype=np.uint8))
    with pytest.raises(RuntimeError, match=r"上限 2"):
        mgr.write_array(np.zeros(4, dtype=np.uint8))
    assert os.path.exists(h3.file_path)


@pytest.mark.unit
def test_region_ttl_disabled_keeps_regions(shm_dir):
    """TTL<=0 关闭惰性回收：超时区域仍在册，上限行为与 W11 语义一致。"""
    mgr = SharedMemoryManager(
        base_dir=str(shm_dir), max_regions=2, region_ttl_seconds=0
    )
    h1 = mgr.write_array(np.zeros(4, dtype=np.uint8))
    mgr.write_array(np.zeros(4, dtype=np.uint8))

    time.sleep(0.05)
    with pytest.raises(RuntimeError, match=r"当前 2 个 / 上限 2 个"):
        mgr.write_array(np.zeros(4, dtype=np.uint8))
    assert os.path.exists(h1.file_path)  # 未被 TTL 回收


@pytest.mark.unit
def test_region_ttl_env_override(shm_dir, monkeypatch):
    """AVA_SHM_REGION_TTL_SECONDS 环境变量注入 TTL（构造参数缺省时生效）。"""
    monkeypatch.setenv("AVA_SHM_REGION_TTL_SECONDS", "0.05")
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    h1 = mgr.write_array(np.zeros(4, dtype=np.uint8))

    time.sleep(0.08)
    mgr.write_array(np.zeros(4, dtype=np.uint8))

    assert not os.path.exists(h1.file_path)


@pytest.mark.unit
def test_release_frees_slot_under_limit(shm_dir):
    mgr = SharedMemoryManager(base_dir=str(shm_dir), max_regions=1)
    handle = mgr.write_array(np.zeros(4, dtype=np.uint8))
    with pytest.raises(RuntimeError):
        mgr.write_array(np.zeros(4, dtype=np.uint8))

    mgr.release(handle.file_path)
    mgr.write_array(np.zeros(4, dtype=np.uint8))  # 释放后应可再次写入


@pytest.mark.unit
def test_max_regions_injectable_via_env_var(shm_dir, monkeypatch):
    monkeypatch.setenv("AVA_SHM_MAX_REGIONS", "1")
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    mgr.write_array(np.zeros(4, dtype=np.uint8))

    with pytest.raises(RuntimeError, match=r"当前 1 个 / 上限 1 个"):
        mgr.write_array(np.zeros(4, dtype=np.uint8))


@pytest.mark.unit
def test_max_regions_default_is_64(shm_dir, monkeypatch):
    monkeypatch.delenv("AVA_SHM_MAX_REGIONS", raising=False)
    mgr = SharedMemoryManager(base_dir=str(shm_dir))
    assert mgr._max_regions == 64
