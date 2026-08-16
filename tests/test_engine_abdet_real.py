"""AbdetAnomalibEngine 真测试 — 覆盖 abdet_anomalib.py 未覆盖行（FR-A7）。

被测引擎: models/supervised/engines/abdet_anomalib.py

覆盖目标行:
- 38-39  : load_from_checkpoint 抛异常 → SupervisedEngineError（用 tmp_path 写垃圾 .ckpt 触发 UnpicklingError）
- 61-74  : infer body（torch.no_grad + anomaly_map/score 解析 + with_extra）— 通过 I/O 边界
           monkeypatch engine._model 为返回 anomalib 风格 dict 的可调用 fake 覆盖解析逻辑
- 83-84  : _to_tensor 的 str→PIL.Image 路径（用 tmp_path 真图直测）

离线可行性说明:
- 不下载权重。_to_tensor 是 staticmethod，可直接单测（ndarray / Tensor / str-PIL 三路）。
- load() 的错误路径用 tmp_path 写垃圾 .ckpt 触发 Patchcore.load_from_checkpoint 抛 UnpicklingError → 引擎包装为 SupervisedEngineError。
- infer body 需要"已拟合的 PatchCore 模型"才能产生真实 anomaly_map/pred_score（需正常样本特征记忆库 + 联网 backbone 权重），
  真实拟合→推理属训练流水线（M1-B），此处按 I/O 边界 mock 合法化：把 engine._model 替换为返回与 anomalib
  PatchCore 同形状输出的可调用 fake（dict 含 anomaly_map / pred_score 张量），仅用于覆盖引擎侧的
  torch.no_grad / 解析 / with_extra 逻辑，**不**绕过被测引擎任何分支。
- 真实拟合→推理端到端测试随训练流水线进行；若需真权重则需联网下载 backbone，按现有 pose_yolo 约定标 @pytest.mark.gpu
  并在无权重时 skip。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("anomalib")
pytest.importorskip("torch")
pytest.importorskip("PIL")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised.engines.abdet_anomalib import AbdetAnomalibEngine


# ----------------------------- 单元：_to_tensor 三路（含 83-84 str→PIL）----------------------------- #
@pytest.mark.unit
def test_to_tensor_ndarray_path():
    """_to_tensor 接受 ndarray（HxWx3 uint8）→ [B,3,H,W] float32 归一化 [0,1]。"""
    img = np.random.RandomState(42).randint(0, 256, (64, 64, 3), dtype=np.uint8)
    t = AbdetAnomalibEngine._to_tensor(img)
    import torch

    assert isinstance(t, torch.Tensor)
    assert tuple(t.shape) == (1, 3, 64, 64)
    assert t.dtype == torch.float32
    # 归一化到 [0,1]：原图最大值 255 → 1.0；最小值 0 → 0.0
    assert t.min() >= 0.0 and t.max() <= 1.0


@pytest.mark.unit
def test_to_tensor_tensor_path_3d():
    """_to_tensor 接受 3D Tensor（C,H,W）→ unsqueeze 为 [B,C,H,W]。"""
    import torch

    t_in = torch.randint(0, 256, (3, 32, 32), dtype=torch.uint8)
    t = AbdetAnomalibEngine._to_tensor(t_in, device="cpu")
    assert tuple(t.shape) == (1, 3, 32, 32)
    assert t.dtype == torch.float32


@pytest.mark.unit
def test_to_tensor_tensor_path_already_normalized():
    """_to_tensor 接受 [0,1] 范围 Tensor → 不再除 255（t.max()<=1 分支）。"""
    import torch

    t_in = torch.rand(3, 16, 16)  # max <= 1
    t = AbdetAnomalibEngine._to_tensor(t_in)
    assert tuple(t.shape) == (1, 3, 16, 16)


@pytest.mark.unit
def test_to_tensor_str_pil_path(tmp_path):
    """_to_tensor 的 str→PIL.Image 路径（行 83-84）：从磁盘读真实图像文件。"""
    from PIL import Image

    arr = np.random.RandomState(7).randint(0, 256, (48, 48, 3), dtype=np.uint8)
    img_path = tmp_path / "abdet_input.png"
    Image.fromarray(arr).save(str(img_path))

    t = AbdetAnomalibEngine._to_tensor(str(img_path))
    import torch

    assert isinstance(t, torch.Tensor)
    assert tuple(t.shape) == (1, 3, 48, 48)
    assert t.dtype == torch.float32


# ----------------------------- 错误路径：load（行 38-39）----------------------------- #
@pytest.mark.integration
def test_load_garbage_ckpt_raises_supervised_error(tmp_path):
    """行 38-39：垃圾 .ckpt → Patchcore.load_from_checkpoint 抛异常 → 包装为 SupervisedEngineError。"""
    eng = AbdetAnomalibEngine()
    bad = tmp_path / "broken.ckpt"
    bad.write_bytes(b"not-a-real-checkpoint-payload")

    with pytest.raises(SupervisedEngineError):
        eng.load(str(bad), device="cpu")
    # 失败后 _model 不应被设置成有效模型
    assert eng._model is None


@pytest.mark.integration
def test_load_missing_weights_raises(tmp_path):
    """load 缺文件 → SupervisedEngineError（行 29-32 错误路径，前置守卫）。"""
    eng = AbdetAnomalibEngine()
    with pytest.raises(SupervisedEngineError):
        eng.load(str(tmp_path / "nope.ckpt"))


# ----------------------------- 错误路径：infer 未加载 ----------------------------- #
@pytest.mark.integration
def test_infer_not_loaded_raises():
    """行 59-60：_model is None → SupervisedEngineError。"""
    eng = AbdetAnomalibEngine()
    with pytest.raises(SupervisedEngineError):
        eng.infer(np.zeros((32, 32, 3), dtype=np.uint8))


# ----------------------------- infer body（行 61-74）—— I/O 边界 mock ----------------------------- #
class _FakePatchcore:
    """模拟已拟合的 anomalib Patchcore 推理输出（I/O 边界 mock，合法）。

    返回与真实 Patchcore 同结构的 dict（anomaly_map: [B,1,H,W], pred_score: [B]）。
    引擎侧解析逻辑（torch.no_grad / dict 取键 / detach.cpu.mean / with_extra）被真覆盖。
    """

    def __init__(self, score_value: float, map_hw: tuple = (64, 64)) -> None:
        import torch

        self._score = torch.tensor([score_value], dtype=torch.float32)
        self._map = torch.full((1, 1, map_hw[0], map_hw[1]), score_value, dtype=torch.float32)
        self.called = 0

    def __call__(self, tensor):
        import torch

        self.called += 1
        # 引擎用 torch.no_grad() 上下文调用；此处不依赖 grad
        with torch.no_grad():
            return {"anomaly_map": self._map, "pred_score": self._score}

    def eval(self):  # 引擎 load 成功后会调 .eval()，这里 infer body 测试不经过 load，但保留兼容
        return self


@pytest.mark.integration
def test_infer_body_parses_dict_output_defective():
    """行 61-74：infer 解析 dict 输出，score>=threshold → is_defective=True。

    mock engine._model（I/O 边界）为返回 anomalib 风格 dict 的 fake，
    覆盖 torch.no_grad / anomaly_map 解析 / pred_score.detach.cpu.mean / with_extra。
    """
    import torch

    eng = AbdetAnomalibEngine()
    eng._model = _FakePatchcore(score_value=0.9, map_hw=(64, 64))
    eng._device = "cpu"

    img = np.random.RandomState(11).randint(0, 256, (64, 64, 3), dtype=np.uint8)
    result = eng.infer(img, threshold=0.5)

    assert isinstance(result, DetectionResult)
    assert result.task == TaskType.ABDET
    # W2 适配本树契约：anomaly_map 存 extra（本树 DetectionResult 无该字段）
    anomaly_map = dict(result.extra)["anomaly_map"]
    assert anomaly_map is not None
    assert tuple(anomaly_map.shape) == (1, 1, 64, 64)
    # score 经 detach.cpu.mean
    assert result.score == pytest.approx(0.9)
    # with_extra 记录 is_defective
    extra_dict = dict(result.extra)
    assert "is_defective" in extra_dict
    assert extra_dict["is_defective"] is True
    assert eng._model.called == 1


@pytest.mark.integration
def test_infer_body_parses_dict_output_not_defective():
    """行 61-74：score < threshold → is_defective=False。"""
    eng = AbdetAnomalibEngine()
    eng._model = _FakePatchcore(score_value=0.1, map_hw=(32, 32))
    eng._device = "cpu"

    img = np.zeros((32, 32, 3), dtype=np.uint8)
    result = eng.infer(img, threshold=0.5)

    assert result.score == pytest.approx(0.1)
    assert dict(result.extra)["is_defective"] is False


@pytest.mark.integration
def test_infer_body_with_str_image(tmp_path):
    """行 61-74 + 83-84：infer 接受 str 图像路径（走 _to_tensor 的 PIL 分支）+ 解析逻辑。"""
    from PIL import Image

    arr = np.random.RandomState(3).randint(0, 256, (48, 48, 3), dtype=np.uint8)
    img_path = tmp_path / "ab.png"
    Image.fromarray(arr).save(str(img_path))

    eng = AbdetAnomalibEngine()
    eng._model = _FakePatchcore(score_value=0.7, map_hw=(48, 48))
    eng._device = "cpu"

    result = eng.infer(str(img_path), threshold=0.5)
    assert result.score == pytest.approx(0.7)
    assert dict(result.extra)["is_defective"] is True


@pytest.mark.integration
def test_infer_body_object_with_attrs():
    """行 66-67 getattr 分支：_model 返回非 dict 对象（含 .anomaly_map / .pred_score 属性）。"""
    import torch

    class ObjOut:
        def __init__(self):
            self.anomaly_map = torch.zeros(1, 1, 16, 16)
            self.pred_score = torch.tensor([0.3])

    eng = AbdetAnomalibEngine()
    eng._model = lambda tensor: ObjOut()  # 返回对象而非 dict → 命中 getattr 分支
    eng._device = "cpu"

    result = eng.infer(np.zeros((16, 16, 3), dtype=np.uint8), threshold=0.5)
    assert result.score == pytest.approx(0.3)
    assert dict(result.extra)["is_defective"] is False


@pytest.mark.integration
def test_infer_body_none_score():
    """行 67-68 score=None 分支：pred_score=None → score_f=None，is_defective=False。"""
    eng = AbdetAnomalibEngine()
    eng._model = lambda tensor: {"anomaly_map": None, "pred_score": None}
    eng._device = "cpu"

    result = eng.infer(np.zeros((24, 24, 3), dtype=np.uint8), threshold=0.5)
    # W2 适配本树契约：score: float 字段不容 None → 落 0.0；
    # anomaly_map 为 None 时不写入 extra
    assert result.score == 0.0
    assert "anomaly_map" not in dict(result.extra)
    assert dict(result.extra)["is_defective"] is False


# ----------------------------- load 成功路径：mock anomalib.Patchcore 构造器 ----------------------------- #
@pytest.mark.unit
def test_load_success_sets_attributes(tmp_path, monkeypatch):
    """load() 成功行（行 42-44 _model.eval / _weights_path / _device）。

    monkeypatch anomalib.models.Patchcore.load_from_checkpoint 为返回 sentinel fake，
    覆盖引擎 load 在成功分支的属性设置逻辑（验 _model/_weights_path/_device/_model.eval() 被调）。
    这是 I/O 边界 mock（替 Patchcore 构造），不替被测引擎本身。
    """

    class _Sentinel:
        def __init__(self):
            self.eval_called = 0

        def eval(self):
            self.eval_called += 1
            return self

    sentinel = _Sentinel()

    import anomalib.models as am

    def fake_load_from_checkpoint(path, map_location=None):
        assert os.path.exists(path)
        return sentinel

    monkeypatch.setattr(am.Patchcore, "load_from_checkpoint", staticmethod(fake_load_from_checkpoint))

    ckpt = tmp_path / "ok.ckpt"
    ckpt.write_bytes(b"x")

    eng = AbdetAnomalibEngine()
    eng.load(str(ckpt), device="cpu")

    assert eng._model is sentinel
    assert eng._weights_path == str(ckpt)
    assert eng._device == "cpu"
    assert sentinel.eval_called == 1  # 行 42 .eval() 被调用


# ----------------------------- 真实拟合→推理端到端（需联网拟合，skip）----------------------------- #
@pytest.mark.gpu
def test_real_fitted_infer_end_to_end():
    """真实拟合 PatchCore → 推理（需正常样本拟合 + 联网 backbone 权重）。

    此处不进行；真实拟合→推理随训练流水线（M1-B）。无可用拟合权重时显式 skip。
    """
    pytest.skip("PatchCore 真实拟合→推理随训练流水线（M1-B）；本引擎层验证构造/错误路径/解析逻辑已覆盖。")
