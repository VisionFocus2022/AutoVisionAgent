"""W19（v3 第三波 FR-2 方向 A）：共享内存区域租约（lease）语义 PoC 测试。

背景：W17 给区域加了 TTL 惰性清扫（``_reap_expired``）后，客户端正在
消费中的区域理论上可能被服务端在 TTL 到期后回收；且随附 C# 客户端
结构性无法回收结果区域。方向 A 探索「显式租约」语义：客户端对结果
区域持有一个 lease_id（有限时长），服务端在租约未到期期间不得回收该
区域；释放时携带 lease_id 校验归属。三态锁定：

(a) 正确 lease_id 的 ReleaseSharedMemory 成功释放对应区域；
(b) 错误 lease_id 的释放被拒（success=False + 非空 error，区域仍在）；
(c) lease 未到期时 TTL reaper 不回收该区域（短 TTL + 活跃租约，
    触发惰性清扫后区域仍可读）——租约到期时钟与区域 TTL 时钟独立，
    租约到期后 TTL 回收恢复（补充态）。

生产路径（serialization 默认不填 lease_id）行为不变——本文件只锁定
PoC 语义本身（PRD FR-2 / ADR-0002）。
"""
from __future__ import annotations

import os
import time

import pytest

np = pytest.importorskip("numpy")
grpc = pytest.importorskip("grpc")

from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.server import AutoVisionAgentServicer  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402


class _FakeDispatcher:
    """最小假分发器：本文件不触碰推理路径，仅需可注入。"""

    loaded_tasks: list[str] = []


@pytest.fixture
def shm(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.fixture
def shm_dir(tmp_path):
    d = tmp_path / "shm"
    d.mkdir()
    return d


@pytest.fixture
def servicer(shm):
    return AutoVisionAgentServicer(_FakeDispatcher(), shm=shm)


def _ctx():
    return None  # 直调方法不触碰 context


def _release(servicer, file_path: str, lease_id: int = 0):
    return servicer.ReleaseSharedMemory(
        pb.ReleaseSharedMemoryRequest(file_path=file_path, lease_id=lease_id),
        _ctx(),
    )


# ------------------------------ 态 (a)：正确租约释放 ------------------------------ #


@pytest.mark.unit
def test_correct_lease_releases_region(shm, servicer):
    """(a) 正确 lease_id → ReleaseSharedMemory 成功，文件删除。"""
    handle = shm.write_array(np.arange(8, dtype=np.uint8))
    lease_id = shm.acquire_lease(handle.file_path, ttl_ms=60_000)

    resp = _release(servicer, handle.file_path, lease_id=lease_id)

    assert resp.success is True
    assert not os.path.exists(handle.file_path)


# ------------------------------ 态 (b)：错误租约被拒 ------------------------------ #


@pytest.mark.unit
def test_wrong_lease_rejected_keeps_region(shm, servicer):
    """(b) 错误 lease_id → success=False + 非空 error，区域未被释放。"""
    handle = shm.write_array(np.arange(8, dtype=np.uint8))
    lease_id = shm.acquire_lease(handle.file_path, ttl_ms=60_000)

    resp = _release(servicer, handle.file_path, lease_id=lease_id + 999)

    assert resp.success is False
    assert resp.error, "拒绝时必须给出非空错误说明"
    assert os.path.exists(handle.file_path), "错误租约不得释放区域"


# ------------------- 态 (c)：活跃租约豁免 TTL 回收（两时钟独立） ------------------- #


@pytest.mark.unit
def test_active_lease_blocks_ttl_reaper(shm_dir):
    """(c) 区域 TTL 已过但租约未到期：触发惰性清扫后区域仍在且可读。"""
    mgr = SharedMemoryManager(
        base_dir=str(shm_dir), region_ttl_seconds=0.05
    )
    h = mgr.write_array(np.arange(8, dtype=np.uint8))
    # 租约时长 60s——远超区域 TTL（50ms），模拟客户端"还在读"
    mgr.acquire_lease(h.file_path, ttl_ms=60_000)

    time.sleep(0.08)  # 区域 TTL 已过，租约远未到期
    mgr.write_array(np.arange(8, dtype=np.uint8))  # 写路径触发 _reap_expired

    assert os.path.exists(h.file_path), "活跃租约区域不得被 TTL 回收"
    back = mgr.read_array(h)
    np.testing.assert_array_equal(back, np.arange(8, dtype=np.uint8))


@pytest.mark.unit
def test_expired_lease_no_longer_blocks_reaper(shm_dir):
    """补充态：租约到期后 TTL 回收恢复——租约只是临时豁免，非永久保护。"""
    mgr = SharedMemoryManager(
        base_dir=str(shm_dir), region_ttl_seconds=0.05
    )
    h = mgr.write_array(np.arange(8, dtype=np.uint8))
    mgr.acquire_lease(h.file_path, ttl_ms=50)  # 50ms 租约，与区域 TTL 同量级

    time.sleep(0.15)  # 区域 TTL（50ms）与租约（50ms）均已过期
    mgr.write_array(np.arange(8, dtype=np.uint8))  # 触发惰性清扫

    assert not os.path.exists(h.file_path), "租约到期后区域应恢复 TTL 回收"
