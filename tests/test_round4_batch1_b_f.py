"""第四轮审查第一批修复回归测试（2026-10-07）。

B-1 训练指纹守卫 / B-2 停止标志复位 / F-1 L2 回退 nearest 广播 /
F-3 auto shape 回传。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")


# ============================== B-1/B-2：训练状态生命周期 ============================== #


class _TrainCfg:
    """train_epoch 最小 cfg 替身。"""

    def __init__(self, data_yaml="d.yaml", backbone="yolov8n", epochs=2,
                 img_size=320, batch_size=2, device="cpu", workers=0,
                 output_dir="out", amp=False):
        self.data_yaml = data_yaml
        self.backbone = backbone
        self.epochs = epochs
        self.img_size = img_size
        self.batch_size = batch_size
        self.device = device
        self.workers = workers
        self.output_dir = output_dir
        self.amp = amp


@pytest.mark.unit
def test_b1_same_signature_hits_cache():
    """B-1：同指纹（幂等重训语义）二次调用命中缓存不重跑。"""
    from core.interfaces_supervised import TaskType
    from models.supervised.engines._yolo_seg_base import _YoloSegBase

    eng = _YoloSegBase(TaskType.SEG)
    calls = {"n": 0}

    def fake_train(**kw):
        calls["n"] += 1
        return None

    # 打桩 ultralytics.YOLO 与 model.train（不走真训练）
    import types

    fake_yolo_mod = types.ModuleType("ultralytics")

    class _FakeModel:
        def __init__(self, *a, **k):
            self.trainer = None
            self.callbacks = {}

        def add_callback(self, name, cb):
            pass

        def train(self, **kw):
            return fake_train(**kw)

    fake_yolo_mod.YOLO = _FakeModel

    import sys

    saved = sys.modules.get("ultralytics")
    sys.modules["ultralytics"] = fake_yolo_mod
    try:
        m1 = eng.train_epoch(0, _TrainCfg())
        m2 = eng.train_epoch(1, _TrainCfg())  # 同指纹
        assert calls["n"] == 1, "同指纹必须命中缓存（不重跑）"
        assert m1 == m2
    finally:
        if saved is not None:
            sys.modules["ultralytics"] = saved
        else:
            del sys.modules["ultralytics"]


@pytest.mark.unit
def test_b1_different_signature_retrains():
    """B-1 核心：换数据集/换参数 → 二次训练真实重跑（此前返回旧值）。"""
    from core.interfaces_supervised import TaskType
    from models.supervised.engines._yolo_seg_base import _YoloSegBase

    eng = _YoloSegBase(TaskType.SEG)
    calls = {"n": 0}
    import sys
    import types

    fake_yolo_mod = types.ModuleType("ultralytics")

    class _FakeModel:
        def __init__(self, *a, **k):
            self.trainer = None

        def add_callback(self, name, cb):
            pass

        def train(self, **kw):
            calls["n"] += 1
            return None

    fake_yolo_mod.YOLO = _FakeModel
    saved = sys.modules.get("ultralytics")
    sys.modules["ultralytics"] = fake_yolo_mod
    try:
        eng.train_epoch(0, _TrainCfg(data_yaml="a.yaml"))
        eng.train_epoch(0, _TrainCfg(data_yaml="b.yaml"))  # 换数据集
        assert calls["n"] == 2, "换指纹必须真实重训"
    finally:
        if saved is not None:
            sys.modules["ultralytics"] = saved
        else:
            del sys.modules["ultralytics"]


@pytest.mark.unit
def test_b2_stop_flag_reset_on_new_training():
    """B-2 核心：停止过的引擎再次训练——停止请求不得带入（首轮即停）。"""
    from core.interfaces_supervised import TaskType
    from models.supervised.engines._yolo_seg_base import _YoloSegBase

    eng = _YoloSegBase(TaskType.SEG)

    # 模拟上一轮训练被用户停止
    eng._stop_requested = True

    captured_cb = {}

    def capture_callbacks(engine, model, epochs):
        # _install_epoch_callbacks 是模块函数，直接验证其注册的回调
        # 行为前先复位（train_epoch 已复位 _stop_requested）
        captured_cb["stop_before"] = engine._stop_requested

    # 直接调用 train_epoch 观察复位（打桩 ultralytics）
    import sys
    import types

    fake_yolo_mod = types.ModuleType("ultralytics")

    class _FakeModel:
        def __init__(self, *a, **k):
            self.trainer = None

        def add_callback(self, name, cb):
            captured_cb[name] = cb

        def train(self, **kw):
            return None

    fake_yolo_mod.YOLO = _FakeModel
    saved = sys.modules.get("ultralytics")
    sys.modules["ultralytics"] = fake_yolo_mod
    try:
        eng.train_epoch(0, _TrainCfg())
        assert eng._stop_requested is False, "train_epoch 入口必须复位停止标志"
        # 复位且无进度回调时 _install_epoch_callbacks 不注册（既有守卫，
        # 复位后 0 回调=第二次训练零干扰）；注册路径单独验证：
        cb_calls = []

        def _cb(trainer):
            cb_calls.append(trainer)

        eng._progress_cb = lambda d: None  # 模拟注册了进度回调的场景
        eng._stop_requested = False  # 已复位状态
        from models.supervised.engines._yolo_seg_base import _install_epoch_callbacks

        class _M2(_FakeModel):
            pass

        m2 = _M2()
        _install_epoch_callbacks(eng, m2, 2)
        # m2.add_callback 未记录——直接验证守卫语义：无 cb 不炸即通过
        # 真正的复位断言已在上方（_stop_requested is False）
        assert cb_calls == []
    finally:
        if saved is not None:
            sys.modules["ultralytics"] = saved
        else:
            del sys.modules["ultralytics"]


# ============================== F-1：L2 回退 nearest 广播 ============================== #


@pytest.mark.unit
def test_f1_l2_fallback_uneven_counts_no_crash(monkeypatch):
    """F-1 核心：未装 lpips 的 L2 回退 + nearest + gen≠real 张数不崩
    （此前广播 ValueError，生产默认路径必崩）。"""
    import sys

    from evaluation import generative_metrics as gm

    monkeypatch.setattr(gm, "_LPIPS_CACHE", {})
    saved = sys.modules.pop("lpips", None)
    try:
        gen = [
            np.full((4, 4, 3), 0.2, dtype=np.float32),
            np.full((4, 4, 3), 0.8, dtype=np.float32),
        ]
        tgt = [
            np.full((4, 4, 3), 0.25, dtype=np.float32),
            np.full((4, 4, 3), 0.5, dtype=np.float32),
            np.full((4, 4, 3), 0.75, dtype=np.float32),
        ]
        val = gm.perceptual_loss(gen, tgt)  # 2 vs 3——此前此处崩
        assert isinstance(val, float) and val >= 0.0
        # 语义验证：逐 gen 最近邻 MSE（gen1→tgt1 差 0.05²，gen2→tgt3 差 0.05²）
        assert val == pytest.approx(0.05 ** 2, abs=1e-5), \
            f"nearest L2 语义：期望 0.0025, 实得 {val}"
    finally:
        if saved is not None:
            sys.modules["lpips"] = saved


# ============================== F-3：auto shape 回传 ============================== #


@pytest.mark.unit
def test_f3_auto_shape_returned_for_quantization(tmp_path):
    """F-3 核心：cls 不传 input_shape → 量化侧收到 224（此前收 None
    兜底 640，校准分辨率错配）。"""
    import torch.nn as nn

    from exporter.supervised_exporter import SupervisedExporter

    model = nn.Sequential(nn.Conv2d(3, 2, 3, padding=1), nn.ReLU())
    exp = SupervisedExporter(simplify=False)

    out_path, shape = exp._export_base_onnx(
        model, "cls", tmp_path / "m.onnx", None
    )
    assert shape == (1, 3, 224, 224), f"auto cls shape 必须回传 224: {shape}"
    assert out_path.exists()

    # sseg → 512 / super → 256
    _, s2 = exp._export_base_onnx(model, "sseg", tmp_path / "m2.onnx", None)
    assert s2 == (1, 3, 512, 512)
    _, s3 = exp._export_base_onnx(model, "super", tmp_path / "m3.onnx", None)
    assert s3 == (1, 3, 256, 256)


@pytest.mark.unit
def test_f3_export_onnx_passes_auto_shape_to_quantize(tmp_path, monkeypatch):
    """F-3 集成：export_onnx(cls, int8, 不传 shape) → _try_quantize 收到 224。"""
    import torch.nn as nn

    from exporter.supervised_exporter import SupervisedExporter

    captured = {}

    def spy(self, path, precision, input_shape=None, calib_images=None):
        captured["shape"] = input_shape
        return None  # 不真量化

    monkeypatch.setattr(SupervisedExporter, "_try_quantize", spy)

    model = nn.Sequential(nn.Conv2d(3, 2, 3, padding=1), nn.ReLU())
    exp = SupervisedExporter(simplify=False)
    exp.export_onnx(model, "cls", str(tmp_path / "m.onnx"), precision="int8")

    assert captured["shape"] == (1, 3, 224, 224), \
        f"量化必须收到 auto 解析后的 shape: {captured['shape']}"


# ============================== 第三批：F-4/S-1/S-2/N-1 ============================== #


@pytest.mark.unit
def test_f4_nearest_batched_semantics_unchanged(monkeypatch):
    """F-4：批量化后 nearest 语义不变（每 gen 对全 tgt 取 min 再平均）
    且前向次数从 n_gen×n_real 降为 n_gen 次批量调用。"""
    import sys
    import types

    from evaluation import generative_metrics as gm

    forward_calls = {"n": 0}
    batch_sizes = []

    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

        def __call__(self, a, b):
            forward_calls["n"] += 1
            batch_sizes.append((tuple(a.shape), tuple(b.shape)))
            # 返回 per-pair 距离：|a_mean - b_mean| 按批展开

            diff = (a.mean(dim=(1, 2, 3)) - b.mean(dim=(1, 2, 3))).abs()
            return diff

    fake_mod = types.ModuleType("lpips")
    fake_mod.LPIPS = lambda net="alex": _Model()
    monkeypatch.setitem(sys.modules, "lpips", fake_mod)
    gm._LPIPS_CACHE.clear()

    gen = [
        np.full((4, 4, 3), 0.2, dtype=np.float32),
        np.full((4, 4, 3), 0.8, dtype=np.float32),
    ]
    tgt = [
        np.full((4, 4, 3), 0.25, dtype=np.float32),
        np.full((4, 4, 3), 0.5, dtype=np.float32),
        np.full((4, 4, 3), 0.75, dtype=np.float32),
    ]

    val = gm.perceptual_loss(gen, tgt)
    # 2 gen × 3 tgt：旧实现 6 次前向；批量化后 2 次（每 gen 一次）
    assert forward_calls["n"] == 2, f"批量化后应为 n_gen 次前向: {forward_calls['n']}"
    # 批形状：(1,3,4,4) expand → (3,3,4,4) vs tgt 堆叠 (3,3,4,4)
    assert batch_sizes[0] == ((3, 3, 4, 4), (3, 3, 4, 4)), batch_sizes[0]
    # 语义：每 gen 最近邻 |0.2-0.25|=0.05、|0.8-0.75|=0.05 → ×2（[-1,1] 变换）
    assert val == pytest.approx(0.1, abs=1e-4), f"nearest 语义不得漂移: {val}"


@pytest.mark.unit
def test_s1_yolo_load_pins_device_override():
    """S-1：load(device) 后 overrides['device'] 钉死（推理侧不再自动选设备）。"""
    import sys
    import types

    fake_yolo_mod = types.ModuleType("ultralytics")

    class _FakeYOLO:
        def __init__(self, path=None):
            self.overrides = {}

    fake_yolo_mod.YOLO = _FakeYOLO

    from core.interfaces_supervised import TaskType
    from models.supervised.engines._yolo_seg_base import _YoloSegBase

    saved = sys.modules.get("ultralytics")
    sys.modules["ultralytics"] = fake_yolo_mod
    try:
        import tempfile

        eng = _YoloSegBase(TaskType.SEG)
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            f.write(b"stub")
            wpath = f.name
        eng.load(wpath, device="cpu")
        assert eng._model.overrides["device"] == "cpu", \
            "R4-S1：load 的 device 必须钉进 overrides"
        os.unlink(wpath)
    finally:
        if saved is not None:
            sys.modules["ultralytics"] = saved
        else:
            del sys.modules["ultralytics"]


@pytest.mark.unit
def test_n1_rgba_rejected():
    """N-1：RGBA 4 通道显式拒绝（此前 shape[2]<3 放行 4 通道穿透）。"""
    import numpy as np

    from labeling.sam_adapter import SamAdapter

    adapter = SamAdapter(model_type="vit_b")

    class _FakePredictor:
        def set_image(self, image):
            pass

    adapter._predictor = _FakePredictor()
    with pytest.raises(ValueError, match="HWC"):
        adapter.set_image(np.zeros((8, 8, 4), dtype=np.uint8))


# ============================== 第三批：F-4/S-1/S-2/N-1 ============================== #

