"""serving/shared_memory 单元测试（W3-T4，P2-4：serving 0% → 补测）。

覆盖：write/read 往返（本进程映射与跨管理器文件路径两条读径）、
dtype 契约、句柄 proto 往返、release/cleanup 生命周期。
"""
from __future__ import annotations

import os

import pytest

np = pytest.importorskip("numpy")

from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.shared_memory import (  # noqa: E402
    SharedMemoryHandle,
    SharedMemoryManager,
)


@pytest.fixture
def mgr(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.mark.unit
def test_write_read_roundtrip_same_manager(mgr):
    arr = np.arange(48, dtype=np.uint8).reshape(2, 4, 6)
    handle = mgr.write_array(arr)

    assert handle.dtype == "uint8"
    assert handle.shape == (2, 4, 6)
    assert handle.length == arr.nbytes == 48
    assert os.path.exists(handle.file_path)

    back = mgr.read_array(handle)
    np.testing.assert_array_equal(back, arr)
    assert back.shape == arr.shape


@pytest.mark.unit
def test_read_via_second_manager_file_path(mgr, tmp_path):
    """对端进程路径：另一管理器无本进程映射，须按 file_path 直读。"""
    arr = np.linspace(0, 1, 20, dtype=np.float32)
    handle = mgr.write_array(arr)

    other = SharedMemoryManager(base_dir=str(tmp_path / "shm"))
    back = other.read_array(handle)
    np.testing.assert_array_equal(back, arr)


@pytest.mark.unit
def test_write_bytes_with_shape(mgr):
    raw = bytes(range(12))
    handle = mgr.write_bytes(raw, dtype="uint8", shape=(3, 4))

    back = mgr.read_array(handle)
    assert back.shape == (3, 4)
    assert bytes(back.reshape(-1).tolist()) == raw


@pytest.mark.unit
def test_unsupported_dtype_rejected(mgr):
    # float16 不在契约内：_np_dtype_name 映射失败即拒（消息与 write_bytes 的
    # 显式拒绝不同源，但都是 ValueError + 提及 dtype）
    with pytest.raises(ValueError, match="dtype"):
        mgr.write_array(np.zeros(4, dtype=np.float16))
    with pytest.raises(ValueError, match="不支持的 dtype"):
        mgr.write_bytes(b"x", dtype="int32")


@pytest.mark.unit
def test_handle_proto_roundtrip_and_coerce(mgr):
    arr = np.ones((5, 5), dtype=bool)
    handle = mgr.write_array(arr)

    msg: pb.SharedMemoryHandle = handle.to_proto()
    assert msg.dtype == "bool"
    assert list(msg.shape) == [5, 5]

    back_handle = SharedMemoryHandle.from_proto(msg)
    assert back_handle == handle

    # proto 句柄直接喂 read_array（_coerce_handle 分支）
    np.testing.assert_array_equal(mgr.read_array(msg), arr)


@pytest.mark.unit
def test_release_deletes_file_and_is_idempotent(mgr):
    handle = mgr.write_array(np.zeros(8, dtype=np.uint8))
    path = handle.file_path

    assert mgr.release(path) is True
    assert not os.path.exists(path)
    # 二次 release：未命中本进程区域
    assert mgr.release(path) is False


@pytest.mark.unit
def test_cleanup_releases_all_regions(mgr):
    handles = [
        mgr.write_array(np.full(6, i, dtype=np.uint8)) for i in range(3)
    ]
    mgr.cleanup()
    for h in handles:
        assert not os.path.exists(h.file_path)


@pytest.mark.unit
def test_coerce_handle_rejects_unknown_type(mgr):
    with pytest.raises(TypeError, match="无法识别的句柄类型"):
        mgr.read_array(object())
