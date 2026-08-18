"""W19（v3 第三波 FR-2 方向 B）：FetchRegion 流式拉取 PoC 测试。

背景：跨机/无法做共享内存映射的消费端目前没有大区域取回通道。
方向 B 在协议上补一条服务端流式 RPC：客户端把 SharedMemoryHandle
原样发回，服务端按 1 MiB ArrayChunk 流式回传区域字节。锁定：

- 写入已知字节序列（位置相关伪随机，含跨块边界非整块尾块）的区域，
  经 FetchRegion 收齐全部分块后拼回数据与原文逐字节相等；
- 分块元数据自洽：offset 单调递增、非尾块恰为 1 MiB、尾块 last=True；
- 区域不存在/已被回收 → context.abort(NOT_FOUND)（直调用假 context 捕获）。

生产路径不变（serialization 默认不产生 FetchRegion 调用；
PRD FR-2 / ADR-0002）。
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
grpc = pytest.importorskip("grpc")

from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.server import AutoVisionAgentServicer  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402

# 与 serving.server 的分块大小保持一致（1 MiB）
_CHUNK = 1024 * 1024


class _FakeDispatcher:
    """最小假分发器：FetchRegion 不触碰推理路径。"""

    loaded_tasks: list[str] = []


class _Aborted(Exception):
    """假 context.abort 抛出的终止信号（模拟真实 gRPC 的 abort 行为）。"""


class _AbortCaptureContext:
    """直调 servicer 时替代 grpc.ServicerContext：只实现 abort。"""

    def __init__(self):
        self.code = None
        self.details = None

    def abort(self, code, details=""):
        self.code = code
        self.details = details
        raise _Aborted()


@pytest.fixture
def shm(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.fixture
def servicer(shm):
    return AutoVisionAgentServicer(_FakeDispatcher(), shm=shm)


def _ctx():
    return None  # 快乐路径直调不触碰 context


def _known_bytes(n: int) -> bytes:
    """位置相关的已知字节序列（固定种子伪随机，避免全零数据的假阳性）。"""
    rng = np.random.default_rng(20260818)
    return rng.integers(0, 256, size=n, dtype=np.uint8).tobytes()


# ------------------------------ 流式收齐逐字节相等 ------------------------------ #


@pytest.mark.unit
def test_fetch_region_roundtrips_known_bytes(servicer, shm):
    """2 MiB + 非整块尾巴 → 3 个分块，拼回后与原文逐字节相等。"""
    data = _known_bytes(2 * _CHUNK + 12345)
    handle = shm.write_bytes(data, dtype="uint8", shape=(len(data),))

    chunks = list(servicer.FetchRegion(handle.to_proto(), _ctx()))

    assert chunks, "必须至少返回一个分块"
    assembled = b"".join(c.data for c in chunks)
    assert assembled == data, "流式收齐后必须与原数据逐字节相等"
    # 分块元数据自洽
    assert chunks[-1].last is True
    assert all(not c.last for c in chunks[:-1]), "只有末块可打 last 标记"
    offsets = [c.offset for c in chunks]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
    # W19 验证修正：首块起始位移为 0（相对句柄 offset），消费端按
    # handle.offset + chunk.offset 定位写入缓冲
    assert offsets[0] == 0
    assert all(len(c.data) == _CHUNK for c in chunks[:-1]), "非尾块必须满 1 MiB"


@pytest.mark.unit
def test_fetch_region_exact_single_chunk(servicer, shm):
    """恰 1 MiB 的区域 → 单分块且 last=True（边界：无第二块）。"""
    data = _known_bytes(_CHUNK)
    handle = shm.write_bytes(data, dtype="uint8", shape=(len(data),))

    chunks = list(servicer.FetchRegion(handle.to_proto(), _ctx()))

    assert len(chunks) == 1
    assert chunks[0].data == data
    assert chunks[0].last is True
    # W19 验证修正：offset=本块起始位移（首块为 0，与 proto 注释一致）
    assert chunks[0].offset == 0


# ------------------------------ 区域缺失 → abort ------------------------------ #


@pytest.mark.unit
def test_fetch_region_missing_aborts_not_found(servicer):
    """区域不存在/已被回收 → context.abort(NOT_FOUND)（不产出任何分块）。"""
    ctx = _AbortCaptureContext()
    req = pb.SharedMemoryHandle(
        file_path=r"C:\nonexistent\ava_w19_missing.bin",
        offset=0,
        length=16,
        dtype="uint8",
    )

    with pytest.raises(_Aborted):
        list(servicer.FetchRegion(req, ctx))

    assert ctx.code == grpc.StatusCode.NOT_FOUND
    assert ctx.details, "abort 必须携带可排障的 details"
