"""W58 真训练通道单测（PRD FR-1：GUI 真 ultralytics 训练使能件）。

覆盖面：
① TrainConfig.data_yaml 字段（additive 缺省不破坏既有构造）；
② _YoloSegBase.train_epoch 一次性适配器（首轮全量 ultralytics 训练、
   后续轮次空转返末轮 metrics、backbone 归一化 -seg.pt、无数据集纵深
   防御 ValueError）；
③ save：ultralytics best.pt 拷贝到训练器目标路径（无产物 no-op）；
④ 训练页回退语义：真引擎 + 未选数据集 → 诚实警告 + 模拟（不炸）；
   选定数据集 → EngineTrainStrategy 真策略。
"""
from __future__ import annotations

import os
import types

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402

# ============================== ① TrainConfig ============================== #


@pytest.mark.unit
def test_train_config_data_yaml_additive_default():
    cfg = TrainConfig(task=TaskType.PSEG)
    assert cfg.data_yaml == ""
    cfg2 = TrainConfig(task=TaskType.PSEG, data_yaml="x:/d/data.yaml")
    assert cfg2.data_yaml == "x:/d/data.yaml"


# ============================== ②③ 引擎适配器 ============================== #


class _FakeYOLO:
    created: list[_FakeYOLO] = []

    def __init__(self, backbone: str):
        self.backbone = backbone
        self.train_calls: list[dict] = []
        self.trainer = types.SimpleNamespace(loss=[1.0, 0.5, 0.25])
        _FakeYOLO.created.append(self)

    def train(self, **kw):
        self.train_calls.append(kw)


@pytest.fixture
def fake_yolo(monkeypatch):
    import ultralytics

    _FakeYOLO.created = []
    monkeypatch.setattr(ultralytics, "YOLO", _FakeYOLO)
    return _FakeYOLO


@pytest.mark.unit
def test_train_epoch_one_shot_adapter(fake_yolo, tmp_path):
    from models.supervised.engines.seg_yolo import SegYoloEngine

    cfg = TrainConfig(
        task=TaskType.SEG,
        epochs=2,
        img_size=640,
        batch_size=4,
        device="cpu",
        workers=0,
        backbone="yolov8n",
        output_dir=str(tmp_path),
        data_yaml=str(tmp_path / "data.yaml"),
    )
    engine = SegYoloEngine()

    m1 = engine.train_epoch(1, cfg)

    assert len(fake_yolo.created) == 1
    assert fake_yolo.created[0].backbone == "yolov8n-seg.pt", "骨干名须归一化 -seg.pt"
    kw = fake_yolo.created[0].train_calls[0]
    assert kw["data"] == cfg.data_yaml
    assert kw["epochs"] == 2
    assert kw["imgsz"] == 640 and kw["batch"] == 4 and kw["device"] == "cpu"
    # W1-6：metrics 增补 epochs_effective（真实内部轮数）——收敛为按键断言
    assert m1["loss"] == 0.25, "末轮 loss 提取（trainer.loss 末元素）"
    assert m1.get("epochs_effective") == 2, "W1-6：一次性适配器回传真实内部轮数"

    m2 = engine.train_epoch(2, cfg)
    assert len(fake_yolo.created) == 1, "后续轮次不得重跑（一次性适配器）"
    assert m2 == m1


@pytest.mark.unit
def test_train_epoch_frozen_forces_zero_workers(fake_yolo, monkeypatch, tmp_path):
    """冻结态（PyInstaller exe）DataLoader 多进程会重_exec 自身——workers 清零。"""
    import sys

    from models.supervised.engines.seg_yolo import SegYoloEngine

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cfg = TrainConfig(
        task=TaskType.SEG, epochs=1, device="cpu", workers=4,
        output_dir=str(tmp_path), data_yaml=str(tmp_path / "data.yaml"),
    )
    SegYoloEngine().train_epoch(1, cfg)
    assert fake_yolo.created[0].train_calls[0]["workers"] == 0, (
        "冻结态 workers 必须 0（exe 模式 DataLoader 崩溃实证）"
    )


@pytest.mark.unit
def test_train_epoch_backbone_pt_path_passthrough(fake_yolo, tmp_path):
    """.pt 全路径 backbone 原样使用（微调口径，免下载）。"""
    from models.supervised.engines.seg_yolo import SegYoloEngine

    cfg = TrainConfig(
        task=TaskType.SEG, epochs=1, device="cpu", workers=0,
        backbone="x:/weights/best.pt", output_dir=str(tmp_path),
        data_yaml=str(tmp_path / "data.yaml"),
    )
    SegYoloEngine().train_epoch(1, cfg)
    assert fake_yolo.created[0].backbone == "x:/weights/best.pt"


@pytest.mark.unit
def test_train_epoch_requires_data_yaml(tmp_path):
    from models.supervised.engines.seg_yolo import SegYoloEngine

    cfg = TrainConfig(task=TaskType.SEG, output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="data.yaml"):
        SegYoloEngine().train_epoch(1, cfg)


@pytest.mark.unit
def test_save_copies_ultralytics_best_pt(tmp_path):
    from models.supervised.engines.seg_yolo import SegYoloEngine

    engine = SegYoloEngine()
    # 直接注入产物状态（不经 ultralytics——save 只依赖路径契约；
    # W58 口径：_train_output_dir 即 ultralytics save_dir，best 在其 weights/ 下）
    engine._train_output_dir = str(tmp_path)
    best_dir = tmp_path / "weights"
    best_dir.mkdir(parents=True)
    (best_dir / "best.pt").write_bytes(b"FAKE_WEIGHTS_123")

    target = tmp_path / "out" / "seg_final.pt"
    engine.save(str(target))

    assert target.read_bytes() == b"FAKE_WEIGHTS_123", "best.pt 须拷贝到训练器目标路径"

    # 无产物场景 no-op（不抛、不产空壳）
    target2 = tmp_path / "out" / "none.pt"
    engine2 = SegYoloEngine()
    engine2._train_output_dir = str(tmp_path / "nonexistent")
    engine2.save(str(target2))
    assert not target2.exists()


# ============================== ④ 训练页回退语义 ============================== #


@pytest.fixture
def train_page(qapp):
    from gui.pages.train.page import TrainPage

    page = TrainPage()
    msgs: list[tuple[str, str]] = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _select_task(page, task: TaskType) -> None:
    combo = page.cmb_task
    for i in range(combo.count()):
        if combo.itemData(i) is task:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"任务下拉未找到 {task}")


@pytest.mark.unit
def test_train_page_fallback_without_dataset(train_page):
    """真引擎 + 未选数据集 → 诚实警告 + 模拟策略（不炸、不触 ultralytics）。"""
    from gui.pages.train.page import EngineTrainStrategy

    _select_task(train_page, TaskType.SEG)
    assert train_page.txt_data.text() == ""

    strategy = train_page._make_trainer(train_page._build_config())

    assert not isinstance(strategy._strategy, EngineTrainStrategy), (
        "未选数据集不得进真策略（train_epoch 将抛 ValueError）"
    )
    assert any(t == "未选择数据集，使用模拟训练" for t, _ in train_page._msgs), (
        "回退必须显式警告（W1 消灭静默假 loss 语义延续）"
    )


@pytest.mark.unit
def test_train_page_real_strategy_with_dataset(train_page, tmp_path):
    from gui.pages.train.page import EngineTrainStrategy

    _select_task(train_page, TaskType.SEG)
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text("path: .\n", encoding="utf-8")
    train_page.txt_data.setText(str(data_yaml))

    cfg = train_page._build_config()
    assert cfg.data_yaml == str(data_yaml), "表单 → TrainConfig.data_yaml 接线"

    strategy = train_page._make_trainer(train_page._build_config())
    assert isinstance(strategy._strategy, EngineTrainStrategy), (
        "选定数据集 + 真引擎 → EngineTrainStrategy（GUI 真训练通道激活）"
    )
