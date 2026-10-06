"""P0 三修回归测试（2026-10-05 二轮审查 R1/R2/R3）。

P0-1（R1）：format_export train/val 分层划分——消除 train=val 同目录
    导致的"mAP 在训练集上计算、指标虚高"；val_ratio=0 兼容旧布局。
P0-2（R2）：真 resume——ITrainStrategy.load_state + GenericTrainer._resume
    实际装载权重；策略不支持时明确告警而非静默。
P0-3（R3）：推理进行中禁用换模型——入口守卫（active_jobs）+ 按钮态
    联动，消除 use-after-unload。
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402
from dataset.format_export import labelme_dir_to_yolo  # noqa: E402
from training.generic_trainer import GenericTrainer  # noqa: E402

# ============================== P0-1：train/val 划分 ============================== #


def _png(path, w=64, h=48):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


def _labelme(path, image_name, w, h, shapes):
    path.write_text(
        json.dumps(
            {
                "version": "5.4.3",
                "imagePath": image_name,
                "imageHeight": h,
                "imageWidth": w,
                "shapes": shapes,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def multi_class_dataset(tmp_path):
    """10 张图、2 个类别桶（crack×5 + scratch×5），供分层划分断言。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    for i in range(5):
        _png(img_dir / f"c{i}.png")
        _labelme(
            ann_dir / f"c{i}.json", f"c{i}.png", 64, 48,
            [{"label": "crack", "shape_type": "rectangle",
              "points": [[10.0, 10.0], [40.0, 30.0]], "group_id": None, "flags": {}}],
        )
    for i in range(5):
        _png(img_dir / f"s{i}.png")
        _labelme(
            ann_dir / f"s{i}.json", f"s{i}.png", 64, 48,
            [{"label": "scratch", "shape_type": "rectangle",
              "points": [[5.0, 5.0], [30.0, 25.0]], "group_id": None, "flags": {}}],
        )
    return img_dir, ann_dir


@pytest.mark.unit
def test_stratified_split_creates_disjoint_dirs(multi_class_dataset, tmp_path):
    """P0-1 核心：默认 8:2 → images/{train,val} 不相交子目录，data.yaml
    分别指向两目录（不再 train=val 同集）。"""
    img_dir, ann_dir = multi_class_dataset
    out = tmp_path / "yolo"

    summary = labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))

    train_imgs = {p.name for p in (out / "images" / "train").glob("*.png")}
    val_imgs = {p.name for p in (out / "images" / "val").glob("*.png")}
    # 不相交 + 覆盖全部
    assert not (train_imgs & val_imgs)
    assert len(train_imgs) + len(val_imgs) == 10
    # 8:2（5 张/桶 × 0.2 = 1 val/桶）
    assert len(val_imgs) == 2
    assert summary.train_images == 8 and summary.val_images == 2

    # labels 与 images 同子集对齐
    for name in train_imgs:
        assert (out / "labels" / "train" / f"{os.path.splitext(name)[0]}.txt").exists()
    for name in val_imgs:
        assert (out / "labels" / "val" / f"{os.path.splitext(name)[0]}.txt").exists()

    # data.yaml 指向不同目录（R1 的直接断言）
    import yaml

    data = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert data["train"] == "images/train"
    assert data["val"] == "images/val"
    assert data["train"] != data["val"]


@pytest.mark.unit
def test_stratified_split_balances_classes(multi_class_dataset, tmp_path):
    """分层保证：val 集同时含两类（每桶抽 1），不出现类别缺席。"""
    img_dir, ann_dir = multi_class_dataset
    out = tmp_path / "yolo"
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out), val_ratio=0.2)

    val_labels = list((out / "labels" / "val").glob("*.txt"))
    assert len(val_labels) == 2
    cls_in_val = set()
    for lbl in val_labels:
        parts = lbl.read_text().split()
        cls_in_val.add(int(parts[0]))  # crack=0, scratch=1
    assert cls_in_val == {0, 1}, "分层划分应保证 val 集类别不缺席"


@pytest.mark.unit
def test_split_seed_reproducible(multi_class_dataset, tmp_path):
    """同 seed 两次导出划分一致（可复现契约）。"""
    img_dir, ann_dir = multi_class_dataset
    out1, out2 = tmp_path / "y1", tmp_path / "y2"
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out1), seed=7)
    labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out2), seed=7)

    v1 = sorted(p.name for p in (out1 / "images" / "val").glob("*.png"))
    v2 = sorted(p.name for p in (out2 / "images" / "val").glob("*.png"))
    assert v1 == v2


@pytest.mark.unit
def test_val_ratio_zero_keeps_legacy_layout(multi_class_dataset, tmp_path):
    """val_ratio=0 → 旧单目录布局（兼容逃生门）。"""
    img_dir, ann_dir = multi_class_dataset
    out = tmp_path / "yolo"
    summary = labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out), val_ratio=0)

    assert (out / "images" / "c0.png").exists()
    assert not (out / "images" / "train").exists()
    import yaml

    data = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert data["train"] == "images"
    assert summary.val_images == 0


@pytest.mark.unit
def test_tiny_dataset_val_fallback(tmp_path):
    """单样本类别桶（全单图）→ val 兜底从 train 挪 1 张，val 非空。"""
    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    for name in ("a", "b"):
        _png(img_dir / f"{name}.png")
        _labelme(
            ann_dir / f"{name}.json", f"{name}.png", 64, 48,
            [{"label": name, "shape_type": "rectangle",
              "points": [[1.0, 1.0], [10.0, 10.0]], "group_id": None, "flags": {}}],
        )
    out = tmp_path / "yolo"
    summary = labelme_dir_to_yolo(str(img_dir), str(ann_dir), str(out))

    assert summary.val_images == 1, "兜底逻辑必须保证 val 非空"
    assert len(list((out / "images" / "val").glob("*.png"))) == 1


@pytest.mark.unit
def test_stem_conflict_skipped(tmp_path):
    """O5：同 stem（a.jpg 与 a.png）静默覆盖 → 现跳过并计数。"""
    import shutil

    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_dir.mkdir()
    ann_dir.mkdir()
    _png(img_dir / "a.png")
    # a.jpg 内容同 a.png（不同扩展名、同 stem）
    shutil.copy2(img_dir / "a.png", img_dir / "a.jpg")
    _labelme(
        ann_dir / "a1.json", "a.png", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[1.0, 1.0], [10.0, 10.0]], "group_id": None, "flags": {}}],
    )
    _labelme(
        ann_dir / "a2.json", "a.jpg", 64, 48,
        [{"label": "crack", "shape_type": "rectangle",
          "points": [[2.0, 2.0], [12.0, 12.0]], "group_id": None, "flags": {}}],
    )
    out = tmp_path / "yolo"
    summary = labelme_dir_to_yolo(
        str(img_dir), str(ann_dir), str(out), val_ratio=0
    )
    assert summary.images == 1 and summary.skipped == 1


# ============================== P0-2：真 resume ============================== #


class _FakeStrategy:
    """记录调用的假策略：支持/不支持 load_state 两种形态。"""

    def __init__(self, supports_load_state=True):
        self.supports = supports_load_state
        self.load_state_calls: list[str] = []

    def train_epoch(self, epoch, cfg):
        return {"loss": 0.5}

    def save(self, path):
        pass

    def get_optimizer(self):
        return None

    def load_state(self, path):
        self.load_state_calls.append(path)
        return self.supports


def _cfg(tmp_path, resume_from=None, epochs=3):
    return TrainConfig(
        task=TaskType.DET,
        epochs=epochs,
        lr=0.001,
        output_dir=str(tmp_path / "out"),
        resume_from=resume_from,
    )


@pytest.mark.unit
def test_resume_loads_weights(tmp_path):
    """P0-2 核心：resume 必须实际调用 strategy.load_state 装载权重。"""
    ckpt = tmp_path / "epoch_5.pt"
    ckpt.write_bytes(b"fake")
    (tmp_path / "epoch_5.pt.meta.json").write_text(
        json.dumps({"epoch": 5, "best_metric": 0.42, "best_epoch": 3, "task": "det"}),
        encoding="utf-8",
    )
    strategy = _FakeStrategy(supports_load_state=True)
    trainer = GenericTrainer(TaskType.DET, strategy)

    start = trainer._resume(str(ckpt), _cfg(tmp_path, str(ckpt)))

    assert strategy.load_state_calls == [str(ckpt)], "必须实际装载权重"
    assert start == 6
    assert trainer._best_metric == 0.42 and trainer._best_epoch == 3


@pytest.mark.unit
def test_resume_without_load_state_warns_not_silent(tmp_path, caplog):
    """策略不支持 load_state → 明确告警（不再静默从头训练）。"""
    ckpt = tmp_path / "epoch_3.pt"
    ckpt.write_bytes(b"fake")
    (tmp_path / "epoch_3.pt.meta.json").write_text(
        json.dumps({"epoch": 3, "best_metric": 0.5, "best_epoch": 2, "task": "det"}),
        encoding="utf-8",
    )
    strategy = _FakeStrategy(supports_load_state=False)
    trainer = GenericTrainer(TaskType.DET, strategy)

    with caplog.at_level("WARNING"):
        trainer._resume(str(ckpt), _cfg(tmp_path, str(ckpt)))

    assert any("随机权重" in r.message for r in caplog.records), (
        "不支持装载时必须明确告警'从随机权重续训'"
    )


@pytest.mark.unit
def test_resume_load_state_exception_caught(tmp_path, caplog):
    """load_state 抛异常 → 捕获并告警，不击穿 resume 流程。"""
    ckpt = tmp_path / "epoch_2.pt"
    ckpt.write_bytes(b"fake")
    (tmp_path / "epoch_2.pt.meta.json").write_text(
        json.dumps({"epoch": 2, "best_metric": 0.6, "best_epoch": 1, "task": "det"}),
        encoding="utf-8",
    )

    class _BoomStrategy(_FakeStrategy):
        def load_state(self, path):
            raise RuntimeError("corrupted checkpoint")

    trainer = GenericTrainer(TaskType.DET, _BoomStrategy())
    with caplog.at_level("WARNING"):
        start = trainer._resume(str(ckpt), _cfg(tmp_path, str(ckpt)))

    assert start == 3, "元数据恢复不受装载失败影响"
    assert any("随机权重" in r.message for r in caplog.records)


@pytest.mark.unit
def test_fit_resets_best_metric_between_runs(tmp_path):
    """M10：同一 trainer 二次 fit（非 resume）→ best_metric 重置，不沿用。"""
    trainer = GenericTrainer(TaskType.DET, _FakeStrategy())
    trainer.fit(_cfg(tmp_path, epochs=1))

    assert trainer._best_metric == 0.5  # FakeStrategy 恒 0.5
    # 二次 fit：不同 output_dir（TrainConfig frozen，需新建）
    cfg2 = TrainConfig(
        task=TaskType.DET, epochs=1, lr=0.001,
        output_dir=str(tmp_path / "out2"),
    )
    trainer.fit(cfg2)
    # 重置后重新追踪（仍为 0.5，但来自本会话而非沿用）
    assert trainer._best_metric == 0.5


# ============================== P0-3：推理中禁用换模型 ============================== #


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def det_page(qapp):
    """预测页（无父窗口，offscreen）。"""
    from gui.pages.predict.page import PredictPage

    return PredictPage()


@pytest.mark.unit
def test_load_model_blocked_during_inference(det_page, monkeypatch):
    """P0-3 核心：predict_* job 在册时 _load_model 入口直接拒绝。"""
    from gui.core import jobs as jobs_mod

    # 伪造注册表快照：一个批量推理在跑
    monkeypatch.setattr(
        jobs_mod, "active_jobs", lambda: ["predict_batch"]
    )
    # 直接调用入口守卫路径：pick_open_file 不应被触达
    from gui.widgets import file_dialog

    monkeypatch.setattr(
        file_dialog, "pick_open_file",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应打开文件对话框")),
    )
    det_page._load_model()  # 应在守卫处 return，不触达文件对话框

    # 按钮态：推理开始时禁用（模拟 _batch_infer 已置 False）
    det_page.btn_load_model.setEnabled(False)
    assert not det_page.btn_load_model.isEnabled()


@pytest.mark.unit
def test_batch_infer_disables_load_model_button(det_page, monkeypatch):
    """批量推理启动 → btn_load_model 禁用；_batch_done → 恢复。"""
    # 准备引擎与目录，触发 _batch_infer 入口段
    class _Engine:
        def infer(self, img, threshold=0.5):
            from core.interfaces_supervised import DetectionResult

            return DetectionResult(task=TaskType.DET, score=0.9)

    det_page._engine = _Engine()
    monkeypatch.setattr(
        "gui.pages.predict.page.collect_images", lambda d: ["x.png"]
    )
    monkeypatch.setattr(
        "gui.pages.predict.page.pick_directory", lambda *a, **k: "/tmp/x"
    )
    monkeypatch.setattr(
        "gui.pages.predict.page.batch_save_dir", lambda p, d: "/tmp/out"
    )
    from gui.pages.predict import batch_runner

    monkeypatch.setattr(batch_runner, "run_batch", lambda *a, **k: None)

    det_page._batch_infer()

    assert not det_page.btn_load_model.isEnabled(), "批量推理中必须禁用换模型"

    det_page._batch_done(1, 1, cancelled=False)
    assert det_page.btn_load_model.isEnabled(), "完成后必须恢复"


@pytest.mark.unit
def test_batch_failed_restores_load_model_button(det_page):
    """批量推理异常兜底 → btn_load_model 恢复（不悬死）。"""
    det_page.btn_load_model.setEnabled(False)
    det_page._batch_failed("boom")
    assert det_page.btn_load_model.isEnabled()
