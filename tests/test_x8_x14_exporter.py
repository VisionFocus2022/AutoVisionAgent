"""X8 校准注入 + X14 原子写测试（2026-10-06 三轮审查批次 2）。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

torch = pytest.importorskip("torch")
onnxrt = pytest.importorskip("onnxruntime")
np = pytest.importorskip("numpy")


def _tiny_model():
    import torch.nn as nn

    return nn.Sequential(nn.Conv2d(3, 2, 3, padding=1), nn.ReLU())


def _calib_pngs(tmp_path, n=2, size=(16, 16)):
    from PIL import Image

    paths = []
    for i in range(n):
        p = tmp_path / f"calib_{i}.png"
        Image.new("RGB", size, color=(i * 100, 50, 200)).save(p)
        paths.append(str(p))
    return paths


# ============================== X8：校准注入 ============================== #


@pytest.mark.unit
def test_int8_with_calib_images_uses_real_data(tmp_path, monkeypatch, caplog):
    """X8 核心：calib_images 传入 → 静态量化收到真图 reader（非随机）。"""
    from exporter.supervised_exporter import SupervisedExporter, _FileCalibReader

    model = _tiny_model()
    out = tmp_path / "m.onnx"
    calib = _calib_pngs(tmp_path, n=2)

    captured = {}

    import onnxruntime.quantization as q

    def fake_static(src, dst, reader, **kw):
        captured["reader"] = reader
        # 复制源文件模拟量化产物（内容不校验）
        import shutil

        shutil.copy(src, dst)

    monkeypatch.setattr(q, "quantize_static", fake_static)

    exp = SupervisedExporter()
    with caplog.at_level("INFO"):
        result = exp.export_onnx(
            model, "det", str(out), input_shape=(1, 3, 16, 16),
            precision="int8", calib_images=calib,
        )

    assert str(result).endswith(".int8.onnx")
    reader = captured["reader"]
    assert isinstance(reader, _FileCalibReader), "必须用真实样本 reader"
    # reader 产出与图数一致且形状正确
    batches = []
    while True:
        d = reader.get_next()
        if d is None:
            break
        batches.append(d)
    assert len(batches) == 2
    # NCHW 含 batch 维——与 _DummyCalibReader/quantize_static 喂数秩一致
    assert batches[0]["input"].shape == (1, 3, 16, 16)
    assert any("真实样本" in r.message for r in caplog.records)


@pytest.mark.unit
def test_int8_no_calib_warns_random(tmp_path, monkeypatch, caplog):
    """X8：不传 calib → WARNING 明示随机校准精度风险。"""
    from exporter.supervised_exporter import SupervisedExporter, _DummyCalibReader

    model = _tiny_model()
    out = tmp_path / "m.onnx"

    captured = {}

    import onnxruntime.quantization as q

    def fake_static(src, dst, reader, **kw):
        captured["reader"] = reader
        import shutil

        shutil.copy(src, dst)

    monkeypatch.setattr(q, "quantize_static", fake_static)

    exp = SupervisedExporter()
    with caplog.at_level("WARNING"):
        exp.export_onnx(
            model, "det", str(out), input_shape=(1, 3, 16, 16), precision="int8",
        )

    assert isinstance(captured["reader"], _DummyCalibReader), "默认仍随机校准"
    assert any("随机数据校准" in r.message for r in caplog.records), \
        "随机校准必须 WARNING 显式风险"


@pytest.mark.unit
def test_file_calib_reader_skips_corrupt(tmp_path):
    """X8：1 好 1 坏图 → 仅 yield 1 个样本。"""
    from exporter.supervised_exporter import _FileCalibReader

    good = _calib_pngs(tmp_path, n=1)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")

    reader = _FileCalibReader([good[0], str(bad)], (1, 3, 16, 16))
    n = 0
    while reader.get_next() is not None:
        n += 1
    assert n == 1


@pytest.mark.unit
def test_file_calib_reader_all_corrupt_raises(tmp_path):
    """X8：全坏 → RuntimeError（复用既有动态回退路径）。"""
    from exporter.supervised_exporter import _FileCalibReader

    bad1 = tmp_path / "b1.png"
    bad1.write_bytes(b"junk")
    bad2 = tmp_path / "b2.png"
    bad2.write_bytes(b"junk")

    with pytest.raises(RuntimeError, match="校准图"):
        _FileCalibReader([str(bad1), str(bad2)], (1, 3, 16, 16))


# ============================== X14：原子写 ============================== #


@pytest.mark.unit
def test_export_failure_leaves_no_partial_file(tmp_path):
    """X14 核心：导出中途失败 → 目标与 .tmp 均不存在（零残留）。"""
    import torch.nn as nn

    from core.exceptions import ModelExportError
    from exporter.supervised_exporter import SupervisedExporter

    class _BoomNet(nn.Module):
        def forward(self, x):
            raise RuntimeError("forward boom")

    out = tmp_path / "m.onnx"
    exp = SupervisedExporter(simplify=False)

    with pytest.raises(ModelExportError):
        exp._export_base_onnx(_BoomNet(), "det", out, (1, 3, 16, 16))

    assert not out.exists(), "失败不得残留目标文件"
    assert not (tmp_path / "m.onnx.tmp").exists(), "失败必须清理 .tmp"


@pytest.mark.unit
def test_export_success_no_tmp_leftover(tmp_path):
    """X14：成功导出后 .tmp 已被 rename 消费（目录无 tmp 残留）。"""
    from exporter.supervised_exporter import SupervisedExporter

    model = _tiny_model()
    out = tmp_path / "m.onnx"
    exp = SupervisedExporter(simplify=False)

    result, shape = exp._export_base_onnx(model, "det", out, (1, 3, 16, 16))

    assert result == out and out.exists()
    assert shape == (1, 3, 16, 16), "R4-F3：显式 shape 原样回传"
    assert not list(tmp_path.glob("*.tmp")), "成功后不得残留 .tmp"
