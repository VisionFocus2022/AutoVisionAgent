"""serving/mask_codec 单元测试（W6-T2，CompactMask RLE 对标 shm 大掩码传输）。

线格式 bool_rle：int32 小端交替游程（False 起始），C 序展平；shape 由句柄携带。
契约：编解码逐位往返、稀疏工业掩码压缩比 <10%、shm 写读往返、
AVA_SHM_MASK_RLE 开关两态（默认关=W5 行为不变）。
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from serving.mask_codec import decode_mask_rle, encode_mask_rle  # noqa: E402
from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.serialization import detection_result_to_proto  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402
from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402


def _sparse(h=1080, w=1920, n_defects=3, seed=7):
    m = np.zeros((n_defects, h, w), dtype=bool)
    rng = np.random.RandomState(seed)
    for i in range(n_defects):
        y, x = rng.randint(0, h - 40), rng.randint(0, w - 60)
        m[i, y : y + rng.randint(8, 24), x : x + rng.randint(30, 120)] = True
    return m


# ----------------------------- 编解码往返 ----------------------------- #
@pytest.mark.unit
def test_roundtrip_sparse():
    m = _sparse()
    out = decode_mask_rle(encode_mask_rle(m), m.shape)
    np.testing.assert_array_equal(out, m)
    assert out.dtype == np.bool_ and out.shape == m.shape


def _make_single_pixel():
    m = np.zeros((1, 10, 6), dtype=bool)
    m[0, 4, 2] = True
    return m


@pytest.mark.unit
@pytest.mark.parametrize(
    "mask",
    [
        np.zeros((1, 8, 8), dtype=bool),                 # 全假
        np.ones((1, 8, 8), dtype=bool),                  # 全真
        _make_single_pixel(),
        np.zeros((3, 16, 12), dtype=bool),               # 多实例全假
    ],
    ids=["all-false", "all-true", "single-pixel", "n3-all-false"],
)
def test_roundtrip_edge_masks(mask):
    out = decode_mask_rle(encode_mask_rle(mask), mask.shape)
    np.testing.assert_array_equal(out, mask)


@pytest.mark.unit
def test_rle_format_contract():
    """格式锚：[False游程, True游程, ...] int32 小端。"""
    m = np.array([[0, 0, 1, 1, 1, 0]], dtype=bool).reshape(1, 1, 6)
    raw = encode_mask_rle(m)
    runs = np.frombuffer(raw, dtype="<i4")
    assert runs.tolist() == [2, 3, 1]  # 2 假 + 3 真 + 1 假
    assert len(raw) == 12  # 3 × int32


# ----------------------------- 压缩比 ----------------------------- #
@pytest.mark.unit
def test_compression_ratio_sparse_industrial():
    """1080p×3 稀疏缺陷掩码：RLE 字节 < 原始 10%（对标 CompactMask 同量级）。"""
    m = _sparse()
    encoded = encode_mask_rle(m)
    assert len(encoded) < m.nbytes * 0.10, (
        f"RLE {len(encoded)}B 未达 <10%（raw {m.nbytes}B）"
    )

    # 对标基准：sv CompactMask（公开 offsets 字节数同量级）
    sv = pytest.importorskip("supervision")
    from supervision.detection.compact_mask import CompactMask

    ys, xs = np.where(m[0])
    bb = np.array(
        [[xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]], np.float32
    )
    cm = CompactMask.from_dense(m[:1], bb, image_shape=m.shape[1:])
    assert np.asarray(cm.offsets).nbytes < m.nbytes * 0.10


# ----------------------------- shm 传输往返 ----------------------------- #
@pytest.fixture
def shm(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.mark.unit
def test_shm_write_compact_roundtrip(shm):
    m = _sparse(h=240, w=320, n_defects=2)
    handle = shm.write_mask_compact(m)

    assert handle.dtype == "bool_rle"
    assert tuple(handle.shape) == m.shape
    assert handle.length < m.nbytes  # 落盘的就是压缩字节

    back = shm.read_array(handle)
    np.testing.assert_array_equal(back, m)
    assert back.dtype == np.bool_


@pytest.mark.unit
def test_shm_roundtrip_via_proto_handle(shm):
    """经 proto 句柄（gRPC 链路形态）读回：dtype 标记须在线上存活。"""
    m = _make_single_pixel()
    handle = shm.write_mask_compact(m)
    proto: pb.SharedMemoryHandle = handle.to_proto()

    assert proto.dtype == "bool_rle"
    back = shm.read_array(proto)
    np.testing.assert_array_equal(back, m)


# ----------------------------- 序列化开关（默认关） ----------------------------- #
def _pseg_result():
    return DetectionResult(
        task=TaskType.PSEG,
        boxes=[[10, 10, 300, 200]],
        labels=("crack",),
        masks=_sparse(h=240, w=320, n_defects=1),
    )


@pytest.mark.unit
def test_serialization_default_compact(shm, monkeypatch):
    """W7：默认走压缩（.NET 已支持 bool_rle 解码）；W17：小掩码内联进 proto。"""
    monkeypatch.delenv("AVA_SHM_MASK_RLE", raising=False)
    result = _pseg_result()
    proto = detection_result_to_proto(result, shm)

    # 稀疏小掩码（RLE 后 << 64KiB）→ 内联通道；dtype/shape 挂句柄元数据
    assert proto.masks_shm.dtype == "bool_rle"
    assert proto.masks_inline != b""
    assert proto.masks_shm.length == 0
    assert not proto.masks_shm.file_path
    from serving.mask_codec import decode_mask_rle

    np.testing.assert_array_equal(
        decode_mask_rle(bytes(proto.masks_inline), proto.masks_shm.shape),
        result.masks,
    )


@pytest.mark.unit
def test_serialization_opt_out_raw(shm, monkeypatch):
    """AVA_SHM_MASK_RLE=0 显式退回 raw（互操作逃生门）。"""
    monkeypatch.setenv("AVA_SHM_MASK_RLE", "0")
    result = _pseg_result()
    proto = detection_result_to_proto(result, shm)

    assert proto.masks_shm.dtype == "bool"
    np.testing.assert_array_equal(
        shm.read_array(proto.masks_shm), result.masks
    )
