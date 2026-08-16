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
    masks = np.zeros((2, 256, 256), dtype=bool)  # 128 KiB > 64 KiB 阈值
    masks[0, 0, 0] = True
    result = DetectionResult(task=TaskType.PSEG, masks=masks)

    proto = detection_result_to_proto(result, shm)
    assert proto.masks_shm.length == masks.nbytes
    assert proto.masks_shm.dtype == "bool"
    assert list(proto.masks_shm.shape) == [2, 256, 256]

    back = shm.read_array(proto.masks_shm)
    np.testing.assert_array_equal(back, masks)


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
