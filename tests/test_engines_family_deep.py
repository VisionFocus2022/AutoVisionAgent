"""引擎家族五文件深测（W10-T3）— super_cv2 / cls_torchvision / _yolo_seg_base / pose_yolo / pseg_yolo。

现有覆盖（tests/test_engine_m2_contracts.py）只打错误路径（未加载 raise / 路径不存在 raise /
info / release）。本文件补：load 成功路径、infer 解析路径、后处理分支、装载失败（损坏权重）。

离线策略（沿用 tests/test_engine_det_real.py 的 I/O 边界替身注入惯例）：
- super_cv2：monkeypatch cv2.dnn_superres.DnnSuperResImpl_create 为记录型替身，
  覆盖文件名推断 model_name/scale、ascii_path_copy 中文路径、setModel 大小写回退、
  readModel 失败包装、GRAY→BGR 转换与 upsample 契约。cv2 缺失分支用
  sys.modules["cv2"]=None 触发 ImportError（monkeypatch 自动还原）。
- cls_torchvision：monkeypatch _safe_torch_load（I/O 边界）返回 bias 固定的微型真网络
  （恒预测 class 3，softmax 确定性 ≈0.6439），直驱真 transform 流水线 + 前向/批量契约；
  损坏权重 → _safe_torch_load 诚实 RuntimeError 直测。
- _yolo_seg_base / pose_yolo / pseg_yolo：替身注入（FakeYoloCtor / _FakeYolo 结果替身）
  覆盖 load 成功与 infer 各分支；另用 YOLO("yolov8n-seg.yaml") /
  YOLO("yolov8n-pose.yaml")（架构 yaml 随机权重，不联网）做真模型 integration 验证。

真权重推理分支（.pt 权重）不伪造——notes 说明；integration 用 yaml 构建替代。
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("cv2")
pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("ultralytics")

import cv2  # noqa: E402
import torch  # noqa: E402

from core.exceptions import SupervisedEngineError  # noqa: E402
from core.interfaces_supervised import TaskType  # noqa: E402
from models.supervised.engines._yolo_seg_base import _YoloSegBase  # noqa: E402
from models.supervised.engines.cls_torchvision import ClsTorchvisionEngine  # noqa: E402
from models.supervised.engines.pose_yolo import PoseYoloEngine  # noqa: E402
from models.supervised.engines.pseg_yolo import PsegYoloEngine  # noqa: E402
from models.supervised.engines.seg_yolo import SegYoloEngine  # noqa: E402
from models.supervised.engines.super_cv2 import SuperCv2Engine  # noqa: E402


# ============================== 共享替身 ============================== #
class _FakeBoxes:
    """ultralytics Boxes 替身：xyxy/conf/cls 张量 + __len__。"""

    def __init__(self, xyxy, conf, cls):
        self.xyxy = torch.tensor(xyxy, dtype=torch.float32)
        self.conf = torch.tensor(conf, dtype=torch.float32)
        self.cls = torch.tensor(cls, dtype=torch.float32)

    def __len__(self) -> int:
        return int(self.xyxy.shape[0])


class _FakeMasks:
    """ultralytics Masks 替身：.data [N,H,W] 张量 + __len__。"""

    def __init__(self, n: int, h: int = 8, w: int = 8):
        self.data = torch.zeros(n, h, w)

    def __len__(self) -> int:
        return int(self.data.shape[0])


class _FakeKeypoints:
    """ultralytics Keypoints 替身：.data [N,K,3] 张量 + __len__。"""

    def __init__(self, n: int, k: int = 3):
        self.data = torch.arange(n * k * 3, dtype=torch.float32).reshape(n, k, 3)

    def __len__(self) -> int:
        return int(self.data.shape[0])


class _FakeYoloModel:
    """已加载模型的 __call__ 替身：返回预置 results 列表并记录调用参数。"""

    def __init__(self, result):
        self._result = result
        self.calls: list = []

    def __call__(self, image, conf=None, verbose=None):
        self.calls.append((image, conf, verbose))
        return [self._result]


class _FakeYoloCtor:
    """ultralytics.YOLO 构造器替身（load 成功路径用）。"""

    last_instance = None

    def __init__(self, weights_path):
        self.weights_path = weights_path
        _FakeYoloCtor.last_instance = self


def _fake_result(boxes, masks=None, keypoints=None) -> SimpleNamespace:
    return SimpleNamespace(boxes=boxes, masks=masks, keypoints=keypoints)


_ZEROS_IMG = np.zeros((16, 16, 3), dtype=np.uint8)


# ============================== super_cv2 ============================== #
class _FakeDnnSr:
    """cv2.dnn_superres.DnnSuperResImpl 替身（记录调用，可控失败）。"""

    def __init__(self, fail_read: bool = False, setmodel_raises_on_lowercase: bool = False):
        self.fail_read = fail_read
        self.setmodel_raises_on_lowercase = setmodel_raises_on_lowercase
        self.read_paths: list = []
        self.read_contents: list = []
        self.set_calls: list = []
        self.upsample_inputs: list = []

    def readModel(self, path):
        if self.fail_read:
            raise RuntimeError("ReadProtoFromBinaryFile failed (fake)")
        self.read_paths.append(str(path))
        with open(path, "rb") as f:
            self.read_contents.append(f.read())

    def setModel(self, name, scale):
        self.set_calls.append((name, scale))  # 先记录（含失败尝试）再按需抛错
        if self.setmodel_raises_on_lowercase and name == name.lower():
            raise cv2.error("setModel: model name not recognized (fake)")

    def upsample(self, arr):
        self.upsample_inputs.append(arr)
        h, w = arr.shape[:2]
        scale = self.set_calls[-1][1] if self.set_calls else 4
        return np.zeros((h * scale, w * scale, arr.shape[2]), dtype=np.uint8)


def _install_fake_sr(monkeypatch, fake_sr: _FakeDnnSr) -> _FakeDnnSr:
    monkeypatch.setattr(cv2.dnn_superres, "DnnSuperResImpl_create", lambda: fake_sr)
    return fake_sr


def _write_weights(tmp_path, fname: str, payload: bytes = b"fake-pb-bytes"):
    w = tmp_path / fname
    w.write_bytes(payload)
    return w


class TestSuperCv2Load:
    """load() 成功路径：文件名推断 / ASCII 拷贝 / setModel 回退 / 失败包装（行 51-99）。"""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fname,explicit_name,explicit_scale,exp_name,exp_scale",
        [
            ("EDSR_x4.pb", "", 0, "edsr", 4),
            ("model_ESPCN_x3.pb", "", 0, "espcn", 3),
            ("FSRCNN.pb", "", 0, "fsrcnn", 4),      # 无数字 → scale 保持默认 4
            ("lapsrn_big_x8.pb", "", 0, "lapsrn", 8),
            ("plain_weights.pb", "", 0, "edsr", 4),  # 无任何指纹 → 双默认
            ("plain_weights.pb", "LapSRN", 3, "lapsrn", 3),  # 显式覆盖（含小写化）
        ],
    )
    def test_load_infers_model_name_and_scale_from_filename(
        self, monkeypatch, tmp_path, fname, explicit_name, explicit_scale,
        exp_name, exp_scale,
    ):
        fake = _install_fake_sr(monkeypatch, _FakeDnnSr())
        w = _write_weights(tmp_path, fname)

        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu", model_name=explicit_name, scale=explicit_scale)

        assert fake.set_calls == [(exp_name, exp_scale)]
        assert eng.model_name == exp_name
        assert eng.scale == exp_scale
        assert eng._model is fake
        assert eng._weights_path == str(w)
        assert eng._device == "cpu"
        # tmp_path 为纯 ASCII → ascii_path_copy 快路径直通原路径
        assert fake.read_paths == [str(w)]

    @pytest.mark.unit
    def test_load_chinese_path_reads_via_ascii_copy(self, monkeypatch, tmp_path):
        """中文路径权重 → readModel 收到 ASCII 临时拷贝（内容一致），引擎记原路径。"""
        fake = _install_fake_sr(monkeypatch, _FakeDnnSr())
        payload = b"fake-pb-bytes"
        w = _write_weights(tmp_path, "超分权重_EDSR_x2.pb", payload)

        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu")

        assert len(fake.read_paths) == 1
        ascii_path = fake.read_paths[0]
        assert ascii_path != str(w)
        ascii_path.encode("ascii")  # 含非 ASCII 会抛 UnicodeEncodeError 使测试失败
        assert fake.read_contents == [payload]
        assert fake.set_calls == [("edsr", 2)]
        assert eng._weights_path == str(w)  # 引擎记录的仍是用户原路径

    @pytest.mark.unit
    def test_load_setmodel_lowercase_error_falls_back_to_capitalize(
        self, monkeypatch, tmp_path
    ):
        """setModel 小写名抛 cv2.error → 用 capitalize 名重试（行 89-91）。"""
        fake = _install_fake_sr(
            monkeypatch, _FakeDnnSr(setmodel_raises_on_lowercase=True)
        )
        w = _write_weights(tmp_path, "EDSR_x4.pb")

        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu")

        assert fake.set_calls == [("edsr", 4), ("Edsr", 4)]
        assert eng._model is fake

    @pytest.mark.unit
    def test_load_readmodel_failure_wrapped(self, monkeypatch, tmp_path):
        """readModel 抛错 → 包装为 SupervisedEngineError（行 93-96）。"""
        _install_fake_sr(monkeypatch, _FakeDnnSr(fail_read=True))
        w = _write_weights(tmp_path, "EDSR_x4.pb")

        eng = SuperCv2Engine()
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.load(str(w))
        assert "加载超分模型失败" in str(exc_info.value)
        assert exc_info.value.details.get("task") == TaskType.SUPER.value

    @pytest.mark.unit
    def test_load_cv2_missing_wrapped(self, monkeypatch, tmp_path):
        """cv2 不可导入 → SupervisedEngineError（行 51-56，诚实回退）。"""
        w = _write_weights(tmp_path, "EDSR_x4.pb")
        monkeypatch.setitem(sys.modules, "cv2", None)  # import cv2 → ImportError

        eng = SuperCv2Engine()
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.load(str(w))
        assert "opencv 未安装" in str(exc_info.value)


class TestSuperCv2Infer:
    """infer() 成功路径：BGR 直通 / GRAY→BGR / 路径读图（行 101-124）。"""

    @pytest.mark.unit
    def test_infer_bgr_input_upsampled(self, monkeypatch, tmp_path):
        fake = _install_fake_sr(monkeypatch, _FakeDnnSr())
        w = _write_weights(tmp_path, "EDSR_x4.pb")
        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu")

        img = np.full((8, 8, 3), 7, dtype=np.uint8)
        res = eng.infer(img)

        assert res.task == TaskType.SUPER
        assert res.score == 1.0
        assert res.labels == ("super_resolved",)
        hr = res.extra["hr_image"]
        assert hr.shape == (32, 32, 3)
        assert fake.upsample_inputs[0] is img  # 3D 输入直通，不走 GRAY2BGR

    @pytest.mark.unit
    def test_infer_gray_input_converted_to_bgr(self, monkeypatch, tmp_path):
        """2D 灰度输入 → COLOR_GRAY2BGR 转 3 通道再 upsample（行 114-115）。"""
        fake = _install_fake_sr(monkeypatch, _FakeDnnSr())
        w = _write_weights(tmp_path, "EDSR_x4.pb")
        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu")

        res = eng.infer(np.full((8, 8), 9, dtype=np.uint8))

        assert fake.upsample_inputs[0].ndim == 3
        assert fake.upsample_inputs[0].shape == (8, 8, 3)
        assert res.extra["hr_image"].shape == (32, 32, 3)

    @pytest.mark.unit
    def test_infer_from_unicode_image_path(self, monkeypatch, tmp_path):
        """str 路径输入 → imread_unicode 读 BGR（覆盖 _to_numpy str 分支经 infer）。"""
        from core.image_io import imwrite_unicode

        _install_fake_sr(monkeypatch, _FakeDnnSr())
        w = _write_weights(tmp_path, "EDSR_x4.pb")
        eng = SuperCv2Engine()
        eng.load(str(w), device="cpu")

        img_path = tmp_path / "测试图.png"
        assert imwrite_unicode(img_path, np.full((6, 6, 3), 5, dtype=np.uint8))

        res = eng.infer(str(img_path))
        assert eng._model.upsample_inputs[0].shape == (6, 6, 3)
        assert res.extra["hr_image"].shape == (24, 24, 3)


class TestSuperCv2Helpers:
    """scale/model_name 属性与 _to_numpy 静态方法（行 126-143）。"""

    @pytest.mark.unit
    def test_defaults_before_load(self):
        eng = SuperCv2Engine()
        assert eng.scale == 4
        assert eng.model_name == "edsr"

    @pytest.mark.unit
    def test_to_numpy_ndarray_passthrough_and_list(self):
        arr = np.zeros((4, 4, 3), dtype=np.uint8)
        assert SuperCv2Engine._to_numpy(arr) is arr  # ndarray 原样（asarray 快路径）
        out = SuperCv2Engine._to_numpy([[1, 2], [3, 4]])
        assert isinstance(out, np.ndarray)
        assert out.shape == (2, 2)

    @pytest.mark.unit
    def test_to_numpy_str_path(self, tmp_path):
        from core.image_io import imwrite_unicode

        p = tmp_path / "gray_src.png"
        assert imwrite_unicode(p, np.full((5, 7), 200, dtype=np.uint8))
        out = SuperCv2Engine._to_numpy(str(p))
        assert isinstance(out, np.ndarray)
        assert out.shape == (5, 7, 3)  # imread_unicode 默认 IMREAD_COLOR → 3 通道
        # 不存在的文件：imread_unicode 契约返回 None
        assert SuperCv2Engine._to_numpy(str(tmp_path / "nope.png")) is None


# ============================== cls_torchvision ============================== #
def _tiny_cls_net() -> torch.nn.Module:
    """微型真网络：池化→展平→零权重 Linear，bias=[0,1,2,3]。

    logits 恒为 [0,1,2,3]（与输入无关）→ 恒预测 class 3，
    softmax conf = e^3/(1+e+e^2+e^3) ≈ 0.6439（确定性）。
    """
    net = torch.nn.Sequential(
        torch.nn.AdaptiveAvgPool2d(1),
        torch.nn.Flatten(),
        torch.nn.Linear(3, 4),
    )
    with torch.no_grad():
        net[2].weight.zero_()
        net[2].bias.copy_(torch.tensor([0.0, 1.0, 2.0, 3.0]))
    return net


class TestClsTorchvision:
    """load/infer/infer_batch 成功路径 + 损坏权重失败路径（行 30-37, 55-65, 78-97）。"""

    @pytest.mark.unit
    def test_load_builds_transform_pipeline(self, monkeypatch, tmp_path):
        """load 成功：_safe_torch_load 收 cpu map_location，eval/to/device 生效，
        真 torchvision transform 流水线一次性构建（行 30-45）。"""
        w = _write_weights(tmp_path, "cls_weights.pth")
        net = _tiny_cls_net()
        seen = {}

        def fake_load(path, map_location="cpu"):
            seen["path"] = path
            seen["map_location"] = map_location
            return net

        monkeypatch.setattr(
            ClsTorchvisionEngine, "_safe_torch_load", staticmethod(fake_load)
        )

        eng = ClsTorchvisionEngine()
        eng.load(str(w), device="cpu")

        assert seen == {"path": str(w), "map_location": "cpu"}
        assert eng._model is net
        assert not net.training  # eval() 已调用
        assert eng._weights_path == str(w)
        assert eng._device == "cpu"
        assert eng._transform is not None
        # transform 是真流水线：uint8 HWC → CHW 归一化张量
        t = eng._transform(np.zeros((64, 64, 3), dtype=np.uint8))
        assert isinstance(t, torch.Tensor)
        assert tuple(t.shape) == (3, 224, 224)

    @pytest.fixture()
    def loaded_engine(self, monkeypatch, tmp_path) -> ClsTorchvisionEngine:
        w = _write_weights(tmp_path, "cls_weights.pth")
        monkeypatch.setattr(
            ClsTorchvisionEngine,
            "_safe_torch_load",
            staticmethod(lambda p, map_location="cpu": _tiny_cls_net()),
        )
        eng = ClsTorchvisionEngine()
        eng.load(str(w), device="cpu")
        return eng

    @pytest.mark.unit
    def test_infer_single_image_default_label(self, loaded_engine):
        """单图推理：softmax→argmax→class_3 标签 + 确定性置信度（行 55-69）。"""
        res = loaded_engine.infer(np.full((64, 64, 3), 128, dtype=np.uint8))
        assert res.task == TaskType.CLS
        assert res.labels == ("class_3",)
        assert 0.5 < res.score <= 1.0
        assert res.score == pytest.approx(0.6439, abs=1e-3)

    @pytest.mark.unit
    def test_infer_labels_mapped(self, loaded_engine):
        res = loaded_engine.infer(
            np.zeros((32, 32, 3), dtype=np.uint8), labels=["a", "b", "c", "d"]
        )
        assert res.labels == ("d",)

    @pytest.mark.unit
    def test_infer_labels_shorter_than_classes_falls_back(self, loaded_engine):
        """标签表短于类别数（预测 class 3 但 labels 仅 3 项）→ 应回退 class_N，
        不应 IndexError（W10-T3 修复；det/seg/pseg 同族均有越界守卫）。"""
        res = loaded_engine.infer(
            np.zeros((32, 32, 3), dtype=np.uint8), labels=["a", "b", "c"]
        )
        assert res.labels == ("class_3",)

    @pytest.mark.unit
    def test_infer_batch_default_label(self, loaded_engine):
        imgs = [np.full((32, 32, 3), i * 40 + 10, dtype=np.uint8) for i in range(3)]
        results = loaded_engine.infer_batch(imgs)
        assert len(results) == 3
        for r in results:
            assert r.task == TaskType.CLS
            assert r.labels == ("class_3",)
        # bias-only 网络 → 每张图置信度一致
        assert results[0].score == pytest.approx(results[1].score)
        assert results[1].score == pytest.approx(results[2].score)

    @pytest.mark.unit
    def test_infer_batch_labels_mapped(self, loaded_engine):
        imgs = [np.zeros((32, 32, 3), dtype=np.uint8)] * 2
        results = loaded_engine.infer_batch(imgs, labels=["a", "b", "c", "d"])
        assert [r.labels for r in results] == [("d",), ("d",)]

    @pytest.mark.unit
    def test_infer_batch_labels_shorter_falls_back(self, loaded_engine):
        """批量同理：labels 越界回退 class_N（W10-T3 修复）。"""
        imgs = [np.zeros((32, 32, 3), dtype=np.uint8)] * 2
        results = loaded_engine.infer_batch(imgs, labels=["solo"])
        assert all(r.labels == ("class_3",) for r in results)

    @pytest.mark.unit
    def test_infer_batch_not_loaded_raises(self):
        with pytest.raises(SupervisedEngineError) as exc_info:
            ClsTorchvisionEngine().infer_batch([np.zeros((8, 8, 3), dtype=np.uint8)])
        assert exc_info.value.details.get("task") == TaskType.CLS.value

    @pytest.mark.unit
    def test_load_corrupt_weights_raises_runtime_error(self, tmp_path):
        """损坏权重 → _safe_torch_load 诚实 RuntimeError（显式异常路径，
        特征化：cls 引擎与 det_yolo 一样不额外包装为 SupervisedEngineError）。"""
        w = _write_weights(tmp_path, "corrupt.pth", b"definitely not a torch file")
        eng = ClsTorchvisionEngine()
        with pytest.raises(RuntimeError, match="无法安全加载权重"):
            eng.load(str(w))


# ============================== _yolo_seg_base（经 SegYoloEngine） ============================== #
class TestYoloSegBaseFake:
    """_YoloSegBase 的 load 成功 + infer 全分支（行 29-37, 46-78）。SEG 不在 m2 契约集内，
    错误路径（load 缺路径 / infer 未加载）一并补上。"""

    @pytest.mark.unit
    def test_base_direct_instantiation(self):
        base = _YoloSegBase(TaskType.PSEG)
        assert base.task == TaskType.PSEG
        assert base._model is None

    @pytest.mark.unit
    def test_load_success_via_fake_yolo(self, monkeypatch, tmp_path):
        import ultralytics

        w = _write_weights(tmp_path, "yolov8n-seg.pt")
        monkeypatch.setattr(ultralytics, "YOLO", _FakeYoloCtor)
        _FakeYoloCtor.last_instance = None

        eng = SegYoloEngine()
        eng.load(str(w), device="cpu")

        assert _FakeYoloCtor.last_instance is not None
        assert _FakeYoloCtor.last_instance.weights_path == str(w)
        assert eng._model is _FakeYoloCtor.last_instance
        assert eng._weights_path == str(w)
        assert eng._device == "cpu"

    @pytest.mark.unit
    def test_load_missing_raises(self, tmp_path):
        eng = SegYoloEngine()
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.load(str(tmp_path / "nope.pt"))
        assert exc_info.value.details.get("task") == TaskType.SEG.value

    @pytest.mark.unit
    def test_infer_not_loaded_raises(self):
        eng = SegYoloEngine()
        with pytest.raises(SupervisedEngineError) as exc_info:
            eng.infer(_ZEROS_IMG)
        assert exc_info.value.details.get("task") == TaskType.SEG.value

    @pytest.mark.unit
    def test_infer_full_parse_with_masks_and_mapped_labels(self):
        img = np.zeros((16, 16, 3), dtype=np.uint8)
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 10, 10], [1, 2, 3, 4]], [0.9, 0.8], [0, 1]),
            masks=_FakeMasks(2),
        )
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(img, threshold=0.5, labels=["scratch", "dent"])

        assert res.task == TaskType.SEG
        assert res.boxes == ((0.0, 0.0, 10.0, 10.0), (1.0, 2.0, 3.0, 4.0))
        assert res.scores == (pytest.approx(0.9), pytest.approx(0.8))
        assert res.labels == ("scratch", "dent")
        assert isinstance(res.masks, torch.Tensor)
        assert tuple(res.masks.shape) == (2, 8, 8)
        # 模型调用契约：原图透传 + conf=threshold + verbose=False
        call_img, call_conf, call_verbose = eng._model.calls[0]
        assert call_img is img
        assert call_conf == 0.5
        assert call_verbose is False

    @pytest.mark.unit
    def test_infer_cls_out_of_labels_range_falls_back(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5], [2, 2, 8, 8]], [0.7, 0.6], [0, 5]),
            masks=_FakeMasks(2),
        )
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG, labels=["only_one"])
        assert res.labels == ("only_one", "defect_5")  # cls 5 越界 → defect_5

    @pytest.mark.unit
    def test_infer_no_labels_uses_defect_prefix(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5], [2, 2, 8, 8]], [0.7, 0.6], [3, 4]),
            masks=_FakeMasks(2),
        )
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.labels == ("defect_3", "defect_4")

    @pytest.mark.unit
    def test_infer_empty_boxes_early_return(self):
        result = _fake_result(boxes=_FakeBoxes([], [], []), masks=None)
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.task == TaskType.SEG
        assert res.boxes == ()
        assert res.scores == ()
        assert res.labels == ()
        assert res.masks is None

    @pytest.mark.unit
    def test_infer_masks_none_boxes_present(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.9], [0]), masks=None
        )
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert len(res.boxes) == 1
        assert res.masks is None

    @pytest.mark.unit
    def test_infer_masks_zero_len_treated_as_none(self):
        """len(masks)==0 → masks_tensor 保持 None（行 54 len>0 守卫）。"""
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.9], [0]), masks=_FakeMasks(0)
        )
        eng = SegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert len(res.boxes) == 1
        assert res.masks is None


# ============================== pose_yolo ============================== #
class TestPoseYoloFake:
    """PoseYoloEngine load 成功 + infer 全分支（行 28-32, 42-62）。"""

    @pytest.mark.unit
    def test_load_success_via_fake_yolo(self, monkeypatch, tmp_path):
        import ultralytics

        w = _write_weights(tmp_path, "yolov8n-pose.pt")
        monkeypatch.setattr(ultralytics, "YOLO", _FakeYoloCtor)
        _FakeYoloCtor.last_instance = None

        eng = PoseYoloEngine()
        eng.load(str(w), device="cpu")

        assert _FakeYoloCtor.last_instance.weights_path == str(w)
        assert eng._model is _FakeYoloCtor.last_instance
        assert eng._weights_path == str(w)
        assert eng._device == "cpu"

    @pytest.mark.unit
    def test_infer_maps_labels_by_class_id(self):
        """labels 必须按类别 id 映射（cls=[5,7] → p5/p7），
        不得按置信度取整索引（W10-T3 修复前：int(conf)=0 → 恒 labels[0]）。"""
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 10, 20], [5, 5, 15, 25]], [0.9, 0.8], [5, 7]),
            keypoints=_FakeKeypoints(2, k=3),
        )
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        labels = [f"p{i}" for i in range(10)]
        res = eng.infer(_ZEROS_IMG, labels=labels)

        assert res.task == TaskType.POSE
        assert res.boxes == ((0.0, 0.0, 10.0, 20.0), (5.0, 5.0, 15.0, 25.0))
        assert res.scores == (pytest.approx(0.9), pytest.approx(0.8))
        assert res.labels == ("p5", "p7")
        assert tuple(res.keypoints.shape) == (2, 3, 3)

    @pytest.mark.unit
    def test_infer_labels_shorter_than_cls_falls_back_to_person(self):
        """cls 越界（cls=5 但 labels 仅 1 项）→ person_i 回退（W10-T3 修复）。"""
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 10, 20]], [0.9], [5]),
            keypoints=_FakeKeypoints(1, k=3),
        )
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG, labels=["only"])
        assert res.labels == ("person_0",)

    @pytest.mark.unit
    def test_infer_no_labels_person_prefix(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 10, 20], [5, 5, 15, 25]], [0.9, 0.8], [0, 0]),
            keypoints=_FakeKeypoints(2, k=3),
        )
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.labels == ("person_0", "person_1")

    @pytest.mark.unit
    def test_infer_keypoints_none_early_return(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.9], [0]), keypoints=None
        )
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.task == TaskType.POSE
        assert res.keypoints is None
        assert res.boxes is None  # 早返走默认构造，未触 boxes 解析
        assert res.scores == ()
        assert res.labels == ()

    @pytest.mark.unit
    def test_infer_keypoints_empty_early_return(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.9], [0]),
            keypoints=_FakeKeypoints(0),
        )
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.keypoints is None
        assert res.boxes is None

    @pytest.mark.unit
    def test_infer_boxes_none_keypoints_present(self):
        """boxes None + keypoints 有 → boxes/scores/labels 空但 keypoints 保留
        （行 50-51 else None 与 55/56/60 else () 分支）。"""
        result = _fake_result(boxes=None, keypoints=_FakeKeypoints(1, k=17))
        eng = PoseYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.boxes == ()
        assert res.scores == ()
        assert res.labels == ()
        assert res.keypoints is not None
        assert tuple(res.keypoints.shape) == (1, 17, 3)


# ============================== pseg_yolo ============================== #
class TestPsegYoloFake:
    """PsegYoloEngine load 成功 + infer 全分支（行 29-33, 43-58）。"""

    @pytest.mark.unit
    def test_load_success_via_fake_yolo(self, monkeypatch, tmp_path):
        import ultralytics

        w = _write_weights(tmp_path, "yolov8x-seg.pt")
        monkeypatch.setattr(ultralytics, "YOLO", _FakeYoloCtor)
        _FakeYoloCtor.last_instance = None

        eng = PsegYoloEngine()
        eng.load(str(w), device="cuda")

        assert _FakeYoloCtor.last_instance.weights_path == str(w)
        assert eng._model is _FakeYoloCtor.last_instance
        # W19 device 护栏后 _device 走 resolve_device 契约：cuda 可用透传、
        # 不可用回退 cpu（显式双态断言——CI 无 GPU = cpu，本地 RTX 3060 = cuda，
        # 两侧都非恒真：引擎若回退verbatim透传，无 GPU 环境立即红）
        import torch

        expected = "cuda" if torch.cuda.is_available() else "cpu"
        assert eng._device == expected

    @pytest.mark.unit
    def test_infer_full_parse_with_masks_and_mapped_labels(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 10, 10], [1, 2, 3, 4]], [0.9, 0.8], [0, 1]),
            masks=_FakeMasks(2),
        )
        eng = PsegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG, threshold=0.4, labels=["scratch", "dent"])

        assert res.task == TaskType.PSEG
        assert res.boxes == ((0.0, 0.0, 10.0, 10.0), (1.0, 2.0, 3.0, 4.0))
        assert res.scores == (pytest.approx(0.9), pytest.approx(0.8))
        assert res.labels == ("scratch", "dent")
        assert isinstance(res.masks, torch.Tensor)
        assert tuple(res.masks.shape) == (2, 8, 8)
        # conf 阈值透传契约
        _, call_conf, call_verbose = eng._model.calls[0]
        assert call_conf == 0.4
        assert call_verbose is False

    @pytest.mark.unit
    def test_infer_cls_out_of_labels_range_falls_back(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.7], [9]),
            masks=_FakeMasks(1),
        )
        eng = PsegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG, labels=["only_one"])
        assert res.labels == ("defect_9",)

    @pytest.mark.unit
    def test_infer_boxes_none_early_return(self):
        result = _fake_result(boxes=None, masks=_FakeMasks(1))
        eng = PsegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.task == TaskType.PSEG
        assert res.boxes is None  # 早返走默认构造
        assert res.masks is None
        assert res.scores == ()

    @pytest.mark.unit
    def test_infer_boxes_zero_len_early_return(self):
        """len(boxes)==0 → 同样早返（行 47 len==0 分支）。"""
        result = _fake_result(boxes=_FakeBoxes([], [], []), masks=None)
        eng = PsegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert res.boxes is None
        assert res.labels == ()

    @pytest.mark.unit
    def test_infer_masks_none_boxes_present(self):
        result = _fake_result(
            boxes=_FakeBoxes([[0, 0, 5, 5]], [0.9], [0]), masks=None
        )
        eng = PsegYoloEngine()
        eng._model = _FakeYoloModel(result)

        res = eng.infer(_ZEROS_IMG)
        assert len(res.boxes) == 1
        assert res.labels == ("defect_0",)
        assert res.masks is None


# ============================== 真模型 integration（yaml 随机权重，不联网） ============================== #
_SEG_IMG = np.random.RandomState(7).randint(0, 256, (128, 128, 3), dtype=np.uint8)
_POSE_IMG = np.random.RandomState(11).randint(0, 256, (320, 320, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def real_seg_yolo():
    """yolov8n-seg 架构 yaml → 随机权重模型（无权重下载）。

    构建前固定 torch 种子：yaml 直建是按全局 RNG 抽随机权重，不固定则
    个别种子（如 seed=6）在 conf=0.0 下产出 0 框使断言翻车（对抗验证员
    实测 12 种子复现）；seed=0 实测稳定 300 框。
    """
    import torch
    from ultralytics import YOLO

    torch.manual_seed(0)
    return YOLO("yolov8n-seg.yaml")


@pytest.fixture(scope="module")
def real_pose_yolo():
    """yolov8n-pose 架构 yaml → 随机权重模型。

    构建前固定 torch 种子（理由同上，seeds 0-4 实测均稳定 300 框）。
    ultralytics 8.4.81 的 yaml 直建 pose 模型在 predict 时缺 kpt_shape 属性
    （.pt 权重加载路径无此问题）；测试侧从 yaml 补上该属性以驱动真推理分支。
    """
    import torch
    from ultralytics import YOLO

    torch.manual_seed(0)
    model = YOLO("yolov8n-pose.yaml", task="pose")
    model.model.kpt_shape = list(model.model.yaml["kpt_shape"])
    return model


@pytest.mark.integration
class TestRealYoloInfer:
    """真模型（随机权重）驱动的 infer 端到端契约。"""

    def test_seg_base_real_model_infer(self, real_seg_yolo):
        eng = SegYoloEngine()
        eng._model = real_seg_yolo

        res = eng.infer(_SEG_IMG, threshold=0.0)
        assert res.task == TaskType.SEG
        assert len(res.boxes) > 0
        assert len(res.boxes) == len(res.scores) == len(res.labels)
        assert res.masks is not None
        assert res.masks.shape[0] == len(res.boxes)
        assert all(lbl.startswith("defect_") for lbl in res.labels)

        # 高阈值 → 无检出 → 早返空结果（行 58-62）
        empty = eng.infer(_SEG_IMG, threshold=0.9999)
        assert empty.boxes == ()
        assert empty.scores == ()
        assert empty.labels == ()
        assert empty.masks is None

    def test_pseg_real_model_infer(self, real_seg_yolo):
        eng = PsegYoloEngine()
        eng._model = real_seg_yolo

        res = eng.infer(_SEG_IMG, threshold=0.0)
        assert res.task == TaskType.PSEG
        assert len(res.boxes) > 0
        assert len(res.boxes) == len(res.scores) == len(res.labels)
        assert res.masks is not None

        labels80 = [f"c{i}" for i in range(80)]
        mapped = eng.infer(_SEG_IMG, threshold=0.0, labels=labels80)
        assert all(lbl in labels80 for lbl in mapped.labels)

        empty = eng.infer(_SEG_IMG, threshold=0.9999)
        assert empty.boxes is None
        assert empty.masks is None

    def test_pose_real_model_infer(self, real_pose_yolo):
        eng = PoseYoloEngine()
        eng._model = real_pose_yolo

        res = eng.infer(_POSE_IMG, threshold=0.0)
        assert res.task == TaskType.POSE
        assert res.keypoints is not None
        assert tuple(res.keypoints.shape[1:]) == (17, 3)  # COCO 17 关键点 (x,y,conf)
        assert len(res.boxes) == len(res.scores) == len(res.labels)
        assert all(lbl.startswith("person_") for lbl in res.labels)

        empty = eng.infer(_POSE_IMG, threshold=0.9999)
        assert empty.keypoints is None
        assert empty.boxes is None
