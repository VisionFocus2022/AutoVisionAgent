"""P1 修复回归测试（2026-10-05 二轮审查 R5/R4/O1/O6/O9/M5/M6）。

R5：_stop_training 去掉 UI 线程 wait(5000) 阻塞（协作式停止）。
R4：单张推理结果请求 ID 守卫（过期结果丢弃并留痕，不静默覆盖）。
O1：标注损坏抛错跳过样本（不再降级为空标注负样本）。
O6：跨瓦片 NMS 按类别分组（class-aware，低分类别重叠框不误删）。
O9：_load_model 失败路径清理半加载引擎。
M5：合并结果类型显式记录（不依赖循环变量泄漏）。
M6：compute_tiles 参数防御（overlap >= tile_size 抛 ValueError）。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")


# ============================== R5：停止训练不阻塞 ============================== #


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def train_page(qapp):
    from gui.pages.train.page import TrainPage

    return TrainPage()


class _NeverFinishesWorker:
    """模拟长 epoch 中不检查 stop_flag 的训练线程（R5 最坏场景）。"""

    def __init__(self):
        self.stop_called = False

    def isRunning(self):
        return True

    def stop(self):
        self.stop_called = True


@pytest.mark.unit
def test_stop_training_does_not_block(train_page, monkeypatch):
    """R5 核心：_stop_training 不再 wait()——stop 置标志后立即返回，
    UI 状态即时更新（不等线程退出）。"""
    import time

    worker = _NeverFinishesWorker()
    train_page._worker = worker

    t0 = time.monotonic()
    train_page._stop_training()
    dt = time.monotonic() - t0

    assert worker.stop_called, "必须调用 worker.stop() 置停止标志"
    assert dt < 1.0, f"UI 线程不得阻塞等待（耗时 {dt:.2f}s）"
    assert not train_page.btn_stop.isEnabled(), "停止按钮须禁用防重复点击"


# ============================== R4：单张结果请求 ID 守卫 ============================== #


@pytest.fixture
def predict_page(qapp):
    from gui.pages.predict.page import PredictPage

    return PredictPage()


def _fake_result(score=0.9):
    from core.interfaces_supervised import DetectionResult, TaskType

    return DetectionResult(task=TaskType.DET, score=score)


@pytest.mark.unit
def test_single_done_consumes_matching_request(predict_page):
    """R4：请求 ID 匹配 → 结果正常消费。"""
    r = _fake_result(0.87)
    predict_page._single_req_id = 1
    predict_page._pending_single = (1, "/tmp/x.png", r)

    predict_page._single_done("x.png", 0.87)

    assert predict_page._pending_single is None
    assert predict_page.btn_single.isEnabled()


@pytest.mark.unit
def test_single_done_discards_stale_request(predict_page, caplog):
    """R4 核心：旧请求迟到回调（req_id 落后）→ 丢弃并留痕，不消费。"""
    r_old = _fake_result(0.5)
    predict_page._single_req_id = 2  # 用户已发起第二次
    predict_page._pending_single = (1, "/tmp/old.png", r_old)  # 第一次结果迟到

    with caplog.at_level("WARNING"):
        predict_page._single_done("old.png", 0.5)

    assert predict_page._pending_single is None, "过期结果必须被清掉"
    assert any("过期" in m for m in caplog.messages), "丢弃须留痕不静默"


@pytest.mark.unit
def test_single_infer_increments_req_id(predict_page, monkeypatch):
    """R4：每次 _single_infer 请求 ID 单调递增（新请求使旧结果失效）。"""
    from core.image_io import imread_unicode  # noqa: F401

    monkeypatch.setattr(
        "gui.pages.predict.page.pick_open_file", lambda *a, **k: "/tmp/a.png"
    )
    predict_page._engine = type("E", (), {"infer": staticmethod(lambda i, threshold: _fake_result())})()


    monkeypatch.setattr(
        "gui.pages.predict.page.run_job",
        lambda fn, name, on_error=None: fn(),  # 同步执行（模拟立即完成）
    )
    before = predict_page._single_req_id
    predict_page._single_infer()
    assert predict_page._single_req_id == before + 1
    # 同步完成后结果已消费
    assert predict_page._pending_single is None


# ============================== O1：损坏标注跳过 ============================== #


@pytest.mark.unit
def test_corrupt_annotation_raises_not_empty(tmp_path):
    """O1 核心：标注 JSON 损坏 → ValueError 抛出（DataLoader 据此跳过），
    不再静默降级为空 boxes 负样本。"""
    from dataset.vision_dataset import VisionDataset

    img = tmp_path / "img.png"
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((48, 64, 3), np.uint8))
    img.write_bytes(buf.tobytes())
    bad_ann = tmp_path / "img.json"
    bad_ann.write_text("{corrupt json", encoding="utf-8")

    ds = VisionDataset(image_dir=str(tmp_path), annotation_dir=str(tmp_path))
    assert len(ds) == 1

    with pytest.raises(ValueError, match="标注文件损坏"):
        ds[0]


# ============================== O6：class-aware NMS ============================== #


@pytest.mark.unit
def test_nms_class_aware_keeps_lowclass_overlap():
    """O6 核心：不同类别完全重叠的框都保留（全局抑制会误删低分者）。"""
    from inference.tiling_inferencer import _nms

    boxes = [
        (0, 0, 10, 10),    # crack 高分
        (0, 0, 10, 10),    # pore 低分（完全重叠，不同类别）
        (1, 1, 11, 11),    # crack 重叠 81%（同类，抑制低分）
    ]
    scores = [0.9, 0.6, 0.5]
    labels = ["crack", "pore", "crack"]

    kept_boxes, keep = _nms(boxes, scores, 0.5, labels=labels)

    # crack 高分保留；pore 完全重叠但类别不同必须保留；crack 低分被抑制
    assert 0 in keep and 1 in keep, "不同类别的重叠框不得互相抑制"
    assert 2 not in keep, "同类高 IoU 框仍应被抑制"
    assert len(kept_boxes) == 2


@pytest.mark.unit
def test_nms_without_labels_keeps_legacy_behavior():
    """O6 兼容：不传 labels → 全局抑制（旧行为不变）。"""
    from inference.tiling_inferencer import _nms

    boxes = [(0, 0, 10, 10), (1, 1, 11, 11)]
    _, keep = _nms(boxes, [0.9, 0.6], 0.5)
    assert keep == [0]


# ============================== M6：compute_tiles 防御 ============================== #


@pytest.mark.unit
def test_compute_tiles_rejects_invalid_overlap():
    """M6：overlap >= tile_size（步长非正）→ ValueError（防死循环挂死）。"""
    from inference.tiling_inferencer import compute_tiles

    with pytest.raises(ValueError, match="overlap"):
        compute_tiles(4096, 4096, tile_size=1024, overlap=1024)
    with pytest.raises(ValueError, match="overlap"):
        compute_tiles(4096, 4096, tile_size=1024, overlap=2000)
    with pytest.raises(ValueError, match="tile_size"):
        compute_tiles(4096, 4096, tile_size=0, overlap=0)
    # 合法参数不受影响
    tiles = compute_tiles(2048, 2048, 1024, 128)
    assert tiles, "合法参数必须正常产出瓦片"


# ============================== O9：失败清理半加载引擎 ============================== #


@pytest.mark.unit
def test_load_model_failure_clears_engine(predict_page, monkeypatch):
    """O9 核心：load 抛异常 → 半加载引擎被清理（unload + 置 None + 清缓存）。"""
    from core.exceptions import SupervisedEngineError

    monkeypatch.setattr(
        "gui.pages.predict.page.pick_open_file",
        lambda *a, **k: "C:/fake/weights.pt",
    )

    unloaded = []

    class _HalfLoadEngine:
        def load(self, path, device="cpu"):
            raise SupervisedEngineError("corrupted checkpoint")

        def unload(self):
            unloaded.append(True)

    class _FakeRegistry:
        def has(self, task):
            return True

        def get(self, task):
            return _HalfLoadEngine()

        def clear_cache(self, task=None):
            unloaded.append("cache-cleared")

    monkeypatch.setattr(
        "models.supervised.registry.get_default_registry",
        lambda: _FakeRegistry(),
    )

    predict_page._load_model()

    assert predict_page._engine is None, "失败后引擎必须置 None"
    assert True in unloaded and "cache-cleared" in unloaded, "须 unload 且清缓存"
