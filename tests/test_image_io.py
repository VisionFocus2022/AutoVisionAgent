"""中文路径读图统一测试（W1-T3，P2-5）。

本项目根目录即中文路径（E:\学习项目\视觉大模型），Windows 下裸 cv2.imread
对非系统码页路径返回 None。core.image_io.imread_unicode 用 np.fromfile +
cv2.imdecode 绕开，语义与 cv2.imread 对齐（BGR、失败返回 None）。
"""
from __future__ import annotations

import json

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _write_png(path, h=24, w=32) -> None:
    """用 imencode+tofile 写 PNG（该写法本身中文路径安全）。"""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0] = 255  # BGR: 蓝通道
    ok, buf = cv2.imencode(".png", arr)
    assert ok
    buf.tofile(str(path))


@pytest.fixture
def cn_dir(tmp_path):
    """含中文子目录的临时目录（父路径为 ASCII，隔离验证中文段）。"""
    d = tmp_path / "中文目录"
    d.mkdir()
    return d


@pytest.mark.unit
def test_cv2_imread_fails_on_chinese_path_control(cn_dir):
    """对照实验：裸 cv2.imread 在本机中文路径下返回 None（缺陷前提，zh-CN Windows 实测）。"""
    p = cn_dir / "图像文件.png"
    _write_png(p)
    assert p.exists() and p.stat().st_size > 0
    assert cv2.imread(str(p)) is None, "若本断言失败说明该环境 imread 已支持中文路径，P2-5 前提需复核"


@pytest.mark.unit
def test_imread_unicode_reads_chinese_path(cn_dir):
    from core.image_io import imread_unicode

    p = cn_dir / "图像文件.png"
    _write_png(p)
    img = imread_unicode(str(p))
    assert img is not None
    assert img.shape == (24, 32, 3)
    assert img.dtype == np.uint8
    assert img[0, 0, 0] == 255  # BGR 语义保持


@pytest.mark.unit
def test_imread_unicode_ascii_path(cn_dir):
    from core.image_io import imread_unicode

    p = cn_dir / "ascii.png"
    _write_png(p)
    img = imread_unicode(str(p))
    assert img is not None and img.shape == (24, 32, 3)


@pytest.mark.unit
def test_imread_unicode_returns_none_on_missing_file(cn_dir):
    """与 cv2.imread 契约对齐：文件不存在返回 None 而非抛异常。"""
    from core.image_io import imread_unicode

    assert imread_unicode(str(cn_dir / "不存在.png")) is None


@pytest.mark.unit
def test_vision_dataset_chinese_path_returns_image(cn_dir):
    """VisionDataset 在中文路径下不得静默返回 None 图像（W1 前为 None 流入训练数据）。"""
    from dataset.vision_dataset import VisionDataset

    p = cn_dir / "图像文件.png"
    _write_png(p)
    ann = {
        "version": "5.4.3",
        "shapes": [
            {"label": "defect", "shape_type": "rectangle",
             "points": [[4.0, 4.0], [12.0, 12.0]]},
        ],
        "imageHeight": 24, "imageWidth": 32,
    }
    (cn_dir / "图像文件.json").write_text(json.dumps(ann), encoding="utf-8")

    ds = VisionDataset(image_dir=str(cn_dir), annotation_dir=str(cn_dir))
    assert len(ds) == 1
    item = ds[0]
    assert item["image"] is not None, "中文路径下图像被静默读成 None"
    assert item["image"].ndim == 3


@pytest.mark.unit
def test_vision_dataset_unreadable_image_raises(cn_dir, monkeypatch):
    """读失败的图像应显式报错，而不是把 None 塞进训练批次。"""
    from dataset import vision_dataset as vd

    p = cn_dir / "坏图.png"
    p.write_bytes(b"not an image")
    (cn_dir / "坏图.json").write_text(
        json.dumps({"version": "5.4.3", "shapes": [],
                    "imageHeight": 24, "imageWidth": 32}),
        encoding="utf-8",
    )
    ds = vd.VisionDataset(image_dir=str(cn_dir), annotation_dir=str(cn_dir))
    with pytest.raises(ValueError, match="图像读取失败"):
        _ = ds[0]
