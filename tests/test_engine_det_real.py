"""DetYoloEngine 真实覆盖测试（离线优先，反 fake-green）。

覆盖目标（models/supervised/engines/det_yolo.py）:
- 行 29-33: load() 成功路径（import YOLO + 设 _model/_weights_path/_device）
- 行 55-58: infer() 多框解析路径（xyxy/conf/cls → DetectionResult）

离线可行性:
- ultralytics YOLO("yolov8n.yaml") 从架构 yaml 构建随机权重模型，不联网下载（已被
  tests/test_supervised_engines.py:29 验证）。infer 用 threshold=0.0 + 320x320
  随机图触发多框预测分支，命中 xyxy/conf/cls 解析行。
- load() 成功行通过 monkeypatch ultralytics.YOLO 构造器为 sentinel fake（I/O 边界
  mock，合法）+ tmp_path 假 .pt 文件来覆盖，验证 _model/_weights_path/_device 被设。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("ultralytics")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.exceptions import SupervisedEngineError  # noqa: E402
from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from models.supervised.engines.det_yolo import DetYoloEngine  # noqa: E402


# 确定性随机图（RandomState(42)），320x320 足够大让随机权重 YOLO 产生若干预测框
_IMG = np.random.RandomState(42).randint(0, 256, (320, 320, 3), dtype=np.uint8)


# ----------------------------- load() 成功路径（行 29-33）----------------------------- #
@pytest.mark.unit
def test_load_success_sets_attributes(monkeypatch, tmp_path):
    """load() 成功：import YOLO + 设 _model/_weights_path/_device（覆盖行 29-33）。

    用 monkeypatch 替换 ultralytics.YOLO 构造器为 sentinel fake（I/O 边界 mock），
    配合 tmp_path 假 .pt 文件使 os.path.exists 通过，从而覆盖 import + 三行属性赋值。
    """
    # 准备一个存在的假权重文件，让 load() 第 25 行 os.path.exists 通过
    fake_pt = tmp_path / "fake.pt"
    fake_pt.write_bytes(b"not-a-real-checkpoint")

    # I/O 边界 mock：替换 ultralytics.YOLO 构造器为返回 sentinel 的 fake
    sentinel = object()
    import ultralytics

    class _FakeYOLO:
        def __init__(self, weights_path, *args, **kwargs):
            # 记录传入路径，便于断言
            self.weights_path = weights_path

        # no-op；只验证 load 设属性逻辑，不进入真推理

    monkeypatch.setattr(ultralytics, "YOLO", _FakeYOLO)

    eng = DetYoloEngine()
    assert eng._model is None  # 初始态
    assert eng._weights_path == ""  # 本树 base 用 ""（兄弟树为 None——移植适配）
    assert eng._device == "cpu"

    eng.load(str(fake_pt), device="cpu")

    # 覆盖行 31-33：三个属性被正确设置
    assert eng._model is not None
    assert isinstance(eng._model, _FakeYOLO)
    assert eng._model.weights_path == str(fake_pt)
    assert eng._weights_path == str(fake_pt)
    assert eng._device == "cpu"


@pytest.mark.unit
def test_load_missing_weights_raises(tmp_path):
    """load() 权重不存在 → SupervisedEngineError（错误路径，对照行 26-28）。"""
    eng = DetYoloEngine()
    with pytest.raises(SupervisedEngineError) as exc_info:
        eng.load(str(tmp_path / "nope.pt"))
    # task 通过 details dict 传递（core/exceptions.py:130-137）
    assert exc_info.value.details.get("task") == TaskType.DET.value


# ----------------------------- infer() 多框解析路径（行 55-58）----------------------------- #
@pytest.mark.integration
def test_infer_multi_box_parsing_path():
    """infer() 多框解析：threshold=0.0 强制所有预测过阈值 → 命中 xyxy/conf/cls 解析行（55-57）。

    离线用 YOLO("yolov8n.yaml") 随机权重架构（不下载），320x320 随机图在
    threshold=0.0 下几乎必然产生 ≥1 个预测框，从而走非早返分支。
    """
    from ultralytics import YOLO

    eng = DetYoloEngine()
    eng._model = YOLO("yolov8n.yaml")  # 从架构 yaml 构建（随机权重，不联网）

    result = eng.infer(_IMG, threshold=0.0)

    # 覆盖行 58-67：返回 DetectionResult，字段类型与长度一致
    assert isinstance(result, DetectionResult)
    assert result.task == TaskType.DET
    assert isinstance(result.boxes, tuple)
    assert isinstance(result.scores, tuple)
    assert isinstance(result.labels, tuple)
    # threshold=0.0 下应有框（多框解析分支被执行）
    assert len(result.boxes) > 0
    assert len(result.boxes) == len(result.scores) == len(result.labels)
    # 每个框是 4 个 float
    for box in result.boxes:
        assert len(box) == 4
        assert all(isinstance(v, float) for v in box)
    # 每个 score 是 float
    assert all(isinstance(s, float) for s in result.scores)
    # 无 labels 参数时走 defect_{cls} 分支（行 63-65）
    for lbl in result.labels:
        assert isinstance(lbl, str)
        assert lbl.startswith("defect_")


@pytest.mark.integration
def test_infer_with_custom_labels_uses_label_map():
    """infer() labels 参数走 labels[int(c)] 映射分支（行 63），覆盖带标签的多框解析。"""
    from ultralytics import YOLO

    eng = DetYoloEngine()
    eng._model = YOLO("yolov8n.yaml")

    # 构造一个足够长的标签表，覆盖 COCO 80 类索引，确保 labels[int(c)] 命中
    labels = [f"class_{i}" for i in range(80)]
    result = eng.infer(_IMG, threshold=0.0, labels=labels)

    assert isinstance(result, DetectionResult)
    assert len(result.boxes) > 0
    # 所有 label 都应来自 labels 表（被映射，不是 defect_{c}）
    for lbl in result.labels:
        assert lbl in labels


@pytest.mark.integration
def test_infer_not_loaded_raises():
    """infer() 未 load → SupervisedEngineError（行 49-50 错误路径）。"""
    eng = DetYoloEngine()
    with pytest.raises(SupervisedEngineError) as exc_info:
        eng.infer(_IMG)
    assert exc_info.value.details.get("task") == TaskType.DET.value


# ----------------------------- 注册表集成 ----------------------------- #
@pytest.mark.integration
def test_engine_self_registered_as_det():
    """引擎在模块导入时已自注册到 TaskType.DET（@register_engine 装饰器生效）。

    不调用 register_all_engines()（其会惰性导入 anomalib/cv2 等重依赖），仅验证
    det_yolo 模块本身的副作用：导入即注册。
    """
    # 触发模块导入（若尚未导入），@register_engine 装饰器会注册到全局表
    import models.supervised.engines.det_yolo  # noqa: F401

    from models.supervised import get_default_registry, get_engine

    reg = get_default_registry()
    assert reg.has(TaskType.DET)
    assert get_engine(TaskType.DET).__class__.__name__ == "DetYoloEngine"
