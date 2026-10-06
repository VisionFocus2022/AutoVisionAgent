"""安全修复回归测试（S1 + S2，2026-10-05 全面工程审查阻塞项）。

S1：FetchRegion/read_* 链任意文件读取——白名单（base_dir + ava_*.bin）
    拒绝 shm 目录外的路径；本进程在册区域与跨管理器合法读取不受影响。
S2：恶意 RLE 载荷 OOM——元素总数上限、4 字节对齐、负游程拒绝、
    int64 求和（防回绕）；encode 侧 int32 溢出显式拒绝。

契约锚定：
- 恶意声明的巨大 shape（如 (2^31,)）在 np.repeat 前即被拒；
- runs=[0x7FFFFFFF, 0x7FFFFFFF, 2] 与 shape 总积 2^31 的回绕绕过构造
  在 int64 求和下原形毕露；
- 白名单拒绝统一呈现 NOT_FOUND（fail-closed，防路径探测信号区分）。
"""
from __future__ import annotations

import struct

import pytest

np = pytest.importorskip("numpy")
grpc = pytest.importorskip("grpc")

from core.mask_codec import decode_mask_rle, encode_mask_rle  # noqa: E402
from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.server import AutoVisionAgentServicer  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402

# ============================== S2：RLE 防护 ============================== #


@pytest.mark.unit
def test_decode_rejects_oversized_shape():
    """恶意 shape 声明几十亿像素 → 元素总数上限直接拒绝（防 OOM）。"""
    with pytest.raises(ValueError, match="超过上限"):
        decode_mask_rle(b"\x00" * 4, (1 << 40,))  # 1 万亿元素


@pytest.mark.unit
def test_decode_rejects_negative_runs():
    """负游程（伪造/损坏载荷）必须拒绝。"""
    bad = struct.pack("<3i", -2, 4, 1)  # runs=[-2, 4, 1], sum=3
    with pytest.raises(ValueError, match="负值"):
        decode_mask_rle(bad, (3,))


@pytest.mark.unit
def test_decode_rejects_misaligned_payload():
    """载荷长度非 4 字节倍数（int32 游程损坏）必须拒绝。"""
    with pytest.raises(ValueError, match="4 的倍数"):
        decode_mask_rle(b"\x01\x02\x03", (3,))


@pytest.mark.unit
def test_decode_rejects_runs_sum_mismatch():
    """游程之和 != 形状元素数（锁 Tessa 盲区 #5 契约）。"""
    good = encode_mask_rle(np.array([[0, 1, 0]], dtype=bool).reshape(1, 1, 3))
    assert decode_mask_rle(good, (3,)) is not None  # sanity：正常载荷可通过

    bad = struct.pack("<2i", 2, 4)  # sum=6 ≠ shape 总积 3
    with pytest.raises(ValueError, match="游程之和"):
        decode_mask_rle(bad, (3,))


@pytest.mark.unit
def test_decode_int32_wraparound_bypass_defeated():
    """int32 回绕绕过构造：runs 和在 int32 回绕后恰好等于 total 的伪造
    载荷，int64 求和下必现原形（S2 核心闸门）。"""
    # 构造：0x7FFFFFFF + 0x7FFFFFFF + 2 = 2^32 + 0（int32 回绕后看似 0）
    # 但 total 也须为非负小值才可能绕过——int64 求和下真实和为 2^32，
    # 与任何合法 total 都不可能相等 → 必须被拒。
    runs = struct.pack("<3i", 0x7FFFFFFF, 0x7FFFFFFF, 2)
    with pytest.raises(ValueError):
        decode_mask_rle(runs, (16,))


@pytest.mark.unit
def test_decode_empty_payload_contract():
    """空载荷边界：空 shape → 全 False 掩码；非空 shape → 拒绝。

    注：shape=() 时返回 0-d 标量数组（np.zeros(()) 语义，size==1），
    与修复前行为保持一致。
    """
    empty = decode_mask_rle(b"", ())
    assert empty.shape == () and not bool(empty)

    zeros = decode_mask_rle(b"", (0, 8))
    assert zeros.shape == (0, 8) and zeros.size == 0

    with pytest.raises(ValueError, match="空 RLE 载荷"):
        decode_mask_rle(b"", (4, 4))


@pytest.mark.unit
def test_encode_rejects_oversized_mask():
    """encode 侧：元素数超 int32 表示范围 → 显式拒绝（防静默回绕）。

    用 broadcast_to 构造 stride-0 大视图（shape 声明 2^31 但零内存分配），
    真实触发上限校验路径。
    """
    huge = np.broadcast_to(np.bool_(False), (1 << 31,))
    assert huge.size == 1 << 31  # sanity：视图 size 真实超限
    with pytest.raises(ValueError, match="拒绝编码"):
        encode_mask_rle(huge)


# ============================== S1：路径白名单 ============================== #


class _FakeDispatcher:
    loaded_tasks: list[str] = []


class _Aborted(Exception):
    pass


class _AbortCaptureContext:
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


def _handle(file_path: str, length: int = 16) -> pb.SharedMemoryHandle:
    return pb.SharedMemoryHandle(
        file_path=file_path, offset=0, length=length, dtype="uint8"
    )


@pytest.mark.unit
def test_fetch_region_rejects_path_outside_base_dir(servicer, shm, tmp_path):
    """S1 核心：指向 shm 目录外任意文件的句柄必须被拒（统一 NOT_FOUND）。"""
    # 在 shm 目录外放一个真实存在的文件（模拟 users.json 等敏感文件）
    secret = tmp_path / "users.json"
    secret.write_text('{"user": "secret"}')
    ctx = _AbortCaptureContext()

    with pytest.raises(_Aborted):
        list(servicer.FetchRegion(_handle(str(secret)), ctx))

    assert ctx.code == grpc.StatusCode.NOT_FOUND  # fail-closed 统一呈现


@pytest.mark.unit
def test_fetch_region_rejects_wrong_extension_inside_base_dir(servicer, shm, tmp_path):
    """白名单双条件：目录内但文件名不匹配 ava_*.bin（如 users.json 放进
    shm 目录）同样拒绝——防"先放文件再读"的绕过姿势。"""
    evil = shm._base_dir / "users.json"
    evil.write_text("{}")
    ctx = _AbortCaptureContext()

    with pytest.raises(_Aborted):
        list(servicer.FetchRegion(_handle(str(evil)), ctx))

    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.unit
def test_fetch_region_rejects_ava_name_outside_base_dir(servicer, shm, tmp_path):
    """白名单双条件另一面：文件名匹配 ava_*.bin 但在 shm 目录外同样拒绝。"""
    evil = tmp_path / "ava_evil.bin"
    evil.write_bytes(b"E" * 64)
    ctx = _AbortCaptureContext()

    with pytest.raises(_Aborted):
        list(servicer.FetchRegion(_handle(str(evil), length=64), ctx))

    assert ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.unit
def test_fetch_region_allows_legitimate_region(servicer, shm):
    """白名单不误伤：shm 目录内合法 ava_*.bin 区域正常流式回传。"""
    data = b"L" * 100
    handle = shm.write_bytes(data, dtype="uint8", shape=(100,))

    chunks = list(servicer.FetchRegion(handle.to_proto(), None))

    assert b"".join(c.data for c in chunks) == data
    assert chunks[-1].last is True


@pytest.mark.unit
def test_read_array_cross_manager_still_works(shm, tmp_path):
    """跨管理器合法读取（C# 客户端 → 服务端链路）不被白名单误伤：
    同目录另一管理器（模拟对端进程）按文件路径读，正常返回。"""
    arr = np.arange(24, dtype=np.float32)
    handle = shm.write_array(arr)

    other = SharedMemoryManager(base_dir=str(tmp_path / "shm"))
    back = other.read_array(handle)
    np.testing.assert_array_equal(back, arr)


@pytest.mark.unit
def test_read_bytes_rejects_outside_path(shm, tmp_path):
    """read_bytes 路径同样受白名单约束（防从 FetchRegion 之外的入口绕过）。"""
    secret = tmp_path / "initial_credentials.txt"
    secret.write_text("password=123")
    h = pb.SharedMemoryHandle(
        file_path=str(secret), offset=0, length=4, dtype="uint8"
    )
    with pytest.raises(ValueError, match="不在允许目录内"):
        shm.read_bytes(h)


@pytest.mark.unit
def test_allow_any_file_escape_hatch(shm, tmp_path, monkeypatch):
    """AVA_SHM_ALLOW_ANY_FILE=1 显式放宽（测试/特殊部署逃生门）。
    默认关闭；开启后白名单外路径恢复旧行为（可读）。"""
    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"0123456789")
    h = pb.SharedMemoryHandle(
        file_path=str(plain), offset=0, length=4, dtype="uint8"
    )
    monkeypatch.setenv("AVA_SHM_ALLOW_ANY_FILE", "1")
    assert shm.read_bytes(h) == b"0123"
