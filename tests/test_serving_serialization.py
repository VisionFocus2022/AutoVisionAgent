"""serving/serialization 单元测试（W3-T4，P2-4：serving 0% → 补测）。

覆盖：TaskType 字符串映射、DetectionResult→proto（boxes 内联 / masks 大数组
走共享内存 / extra 字符串化）、DetectRequest 三种图像源解码与错误路径。
"""
from __future__ import annotations

import io

import pytest

np = pytest.importorskip("numpy")

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.serialization import (  # noqa: E402
    decode_request_image,
    detection_result_to_proto,
    str_to_task_type,
    task_type_to_str,
)
from serving.shared_memory import SharedMemoryManager  # noqa: E402


@pytest.fixture
def shm(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


# ----------------------------- TaskType 映射 ----------------------------- #
@pytest.mark.unit
def test_task_type_str_roundtrip():
    assert task_type_to_str(TaskType.PSEG) == "pseg"
    assert str_to_task_type("pseg") is TaskType.PSEG


@pytest.mark.unit
def test_str_to_task_type_unknown_falls_back():
    assert str_to_task_type("nonsense") is TaskType.DET
    assert str_to_task_type("sgan", default=TaskType.SGAN) is TaskType.SGAN


# ----------------------------- result → proto ----------------------------- #
@pytest.mark.unit
def test_result_to_proto_boxes_inlined(shm):
    result = DetectionResult(
        task=TaskType.DET,
        score=0.87,
        scores=(0.9, 0.5),
        labels=("crack", "scratch"),
        boxes=np.array([[10, 20, 30, 40], [1, 2, 3, 4]], dtype=float),
    )
    proto = detection_result_to_proto(result, shm)

    assert proto.task == "det"
    assert proto.score == pytest.approx(0.87)
    assert list(proto.scores) == [0.9, 0.5]
    assert list(proto.labels) == ["crack", "scratch"]
    assert proto.box_count == 2
    assert len(proto.boxes_flat) == 8
    assert proto.masks_shm.length == 0  # 无掩码 → 空句柄


@pytest.mark.unit
def test_result_to_proto_masks_via_shm(shm):
    """大掩码（RLE 后仍 > 64 KiB，用不可压缩随机掩码构造）走共享内存。"""
    rng = np.random.default_rng(7)
    masks = rng.random((2, 256, 256)) > 0.5  # 随机交替 → RLE ≈ 256 KiB
    result = DetectionResult(task=TaskType.PSEG, masks=masks)

    proto = detection_result_to_proto(result, shm)
    # W7：bool 掩码走 bool_rle 编码；随机掩码不可压缩（RLE 后 ~256 KiB）
    assert proto.masks_shm.dtype == "bool_rle"
    assert proto.masks_shm.length > 64 * 1024  # 超内联阈值 → 走 shm
    assert list(proto.masks_shm.shape) == [2, 256, 256]
    # W17：大数组不内联
    assert proto.masks_inline == b""

    back = shm.read_array(proto.masks_shm)
    np.testing.assert_array_equal(back, masks)


# ------------------- W17（v3 P1-1）：小数组内联 ------------------- #


@pytest.mark.unit
def test_result_to_proto_small_mask_inlined(shm):
    """小掩码（RLE 后 < 64 KiB）内联进 proto：不建 shm 区域（v3 P1-1 止血——
    随附 C# 客户端无法回收结果区域，小掩码内联后不再消耗区域配额）。"""
    masks = np.zeros((2, 256, 256), dtype=bool)  # 原始 128 KiB，RLE 后仅数十字节
    masks[0, 0, 0] = True
    result = DetectionResult(task=TaskType.PSEG, masks=masks)

    proto = detection_result_to_proto(result, shm)

    # 内联非空；句柄仅作 dtype/shape 元数据载体（file_path 空、length 0）
    assert proto.masks_inline != b""
    assert proto.masks_shm.file_path == ""
    assert proto.masks_shm.length == 0
    assert proto.masks_shm.dtype == "bool_rle"
    assert list(proto.masks_shm.shape) == [2, 256, 256]
    # 未创建任何 shm 区域
    assert len(list(shm._base_dir.glob("ava_*.bin"))) == 0

    # 消费端解码路径：dtype/shape 取自句柄元数据，载荷取自内联字节
    from serving.mask_codec import decode_mask_rle

    back = decode_mask_rle(bytes(proto.masks_inline), proto.masks_shm.shape)
    np.testing.assert_array_equal(back, masks)


@pytest.mark.unit
def test_result_to_proto_keypoints_inline_small_and_shm_large(shm):
    """keypoints 同契约：小数组（80 B）内联 raw float32；大数组（1.6 MB）走 shm。"""
    small = np.arange(2 * 5 * 2, dtype=np.float32).reshape(2, 5, 2)
    proto = detection_result_to_proto(
        DetectionResult(task=TaskType.POSE, keypoints=small), shm
    )
    assert proto.keypoints_inline != b""
    assert proto.keypoints_shm.file_path == ""
    assert proto.keypoints_shm.length == 0
    assert proto.keypoints_shm.dtype == "float32"
    assert list(proto.keypoints_shm.shape) == [2, 5, 2]
    back = np.frombuffer(bytes(proto.keypoints_inline), dtype="<f4").reshape(2, 5, 2)
    np.testing.assert_array_equal(back, small)
    assert len(list(shm._base_dir.glob("ava_*.bin"))) == 0

    large = np.zeros((2000, 64, 2), dtype=np.float32)  # 1.6 MB > 64 KiB
    proto2 = detection_result_to_proto(
        DetectionResult(task=TaskType.POSE, keypoints=large), shm
    )
    assert proto2.keypoints_inline == b""
    assert proto2.keypoints_shm.length == large.nbytes
    back2 = shm.read_array(proto2.keypoints_shm)
    np.testing.assert_array_equal(back2, large)


@pytest.mark.unit
def test_result_to_proto_extra_stringified(shm):
    result = DetectionResult(
        task=TaskType.ABDET, score=0.5, extra={"anomaly_map": "ndarray<...>"}
    )
    proto = detection_result_to_proto(result, shm)
    assert dict(proto.extra) == {"anomaly_map": "ndarray<...>"}


# ----------------------------- request → numpy ----------------------------- #
def _png_bytes(w=8, h=6):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.unit
def test_decode_from_image_path(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes())

    req = pb.DetectRequest(image_path=str(p))
    arr = decode_request_image(req, SharedMemoryManager(base_dir=str(tmp_path)))
    assert arr.shape == (6, 8, 3)
    assert arr[0, 0, 0] == 255  # RGB 顺序


@pytest.mark.unit
def test_decode_from_image_bytes():
    req = pb.DetectRequest(image_bytes=_png_bytes())
    arr = decode_request_image(req, SharedMemoryManager(base_dir="unused"))
    assert arr.shape == (6, 8, 3)


@pytest.mark.unit
def test_decode_from_shm_priority(shm, tmp_path):
    """image_shm 优先于 image_path。"""
    arr = np.full((4, 5, 3), 7, dtype=np.uint8)
    handle = shm.write_array(arr)

    p = tmp_path / "decoy.png"
    p.write_bytes(_png_bytes())
    req = pb.DetectRequest(image_path=str(p))
    req.image_shm.CopyFrom(handle.to_proto())

    out = decode_request_image(req, shm)
    np.testing.assert_array_equal(out, arr)


@pytest.mark.unit
def test_decode_gray_shm_expands_to_rgb(shm):
    gray = np.arange(20, dtype=np.uint8).reshape(4, 5)
    handle = shm.write_array(gray)
    req = pb.DetectRequest()
    req.image_shm.CopyFrom(handle.to_proto())

    out = decode_request_image(req, shm)
    assert out.shape == (4, 5, 3)
    np.testing.assert_array_equal(out[..., 0], gray)
    np.testing.assert_array_equal(out[..., 2], gray)


@pytest.mark.unit
def test_decode_errors(tmp_path):
    shm = SharedMemoryManager(base_dir=str(tmp_path / "shm"))

    # 无任何图像源
    with pytest.raises(ValueError, match="未提供任何图像源"):
        decode_request_image(pb.DetectRequest(), shm)

    # 路径不存在
    with pytest.raises(FileNotFoundError):
        decode_request_image(
            pb.DetectRequest(image_path=str(tmp_path / "nope.png")), shm
        )

    # 字节不可解码
    with pytest.raises(ValueError, match="无法解码"):
        decode_request_image(pb.DetectRequest(image_bytes=b"garbage!"), shm)


# ================ W14-C3 追加：静默 except 补日志（P2-13） ================ #
class _EvilStr:
    """__str__ 抛异常的载荷（模拟 extra 不可字符串化）。"""

    def __str__(self):
        raise RuntimeError("no string for you")


@pytest.mark.unit
def test_extra_stringify_failure_logs_warning(shm, caplog):
    """RED（P2-13）：extra 字符串化失败此前 continue 静默吞掉。"""
    import logging

    result = DetectionResult(
        task=TaskType.DET, score=0.5,
        extra={"bad": _EvilStr(), "ok": 1},
    )
    with caplog.at_level(logging.WARNING, logger="serving.serialization"):
        proto = detection_result_to_proto(result, shm)
    assert dict(proto.extra).get("ok") == "1"   # 好键保留
    assert "bad" not in dict(proto.extra)       # 坏键跳过
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "extra" in r.getMessage()]
    assert warns, "extra 字符串化失败应落 WARNING"


@pytest.mark.unit
def test_decode_image_bytes_failure_logs_warning(tmp_path, caplog):
    """RED（P2-13）：image_bytes 解码失败此前静默 return None（上抛
    ValueError 前零痕迹）。"""
    import logging

    shm = SharedMemoryManager(base_dir=str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="serving.serialization"):
        with pytest.raises(ValueError, match="无法解码"):
            decode_request_image(pb.DetectRequest(image_bytes=b"garbage!"), shm)
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "解码" in r.getMessage()]
    assert warns, "image_bytes 解码失败应落 WARNING"


# ============ W17 簇C 追加：P3⑤ 部分失败回滚 ============ #


@pytest.mark.unit
def test_result_to_proto_partial_failure_rolls_back_created_regions(tmp_path):
    """RED（P3⑤）：masks 先成功写满区域配额（max_regions=1），keypoints 再
    写触发上限 RuntimeError——异常上抛前必须回滚已创建的 masks 区域：
    客户端不会收到任何句柄，区域不得无主泄漏（登记占位 + 磁盘残留）。"""
    mgr = SharedMemoryManager(base_dir=str(tmp_path / "shm"), max_regions=1)

    rng = np.random.default_rng(11)
    masks = rng.random((2, 256, 256)) > 0.5  # RLE 后 ~256 KiB → 走 shm，占满唯一配额
    keypoints = np.zeros((2000, 64, 2), dtype=np.float32)  # ~1 MB → 第二次写触发上限

    result = DetectionResult(task=TaskType.POSE, masks=masks, keypoints=keypoints)
    with pytest.raises(RuntimeError, match="上限"):
        detection_result_to_proto(result, mgr)

    assert len(mgr._regions) == 0, "部分失败后 masks 区域应被回滚释放（登记表清空）"
    assert list(mgr._base_dir.glob("ava_*.bin")) == [], "回滚后磁盘不得残留区域文件"
