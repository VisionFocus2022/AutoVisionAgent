"""train 页 + TrainWorker + EngineTrainStrategy 测试（W9-T4：65%/62% → 填平）。

预设应用、_build_config 全字段、运行中拒绝重启、训练器构建三回调
（FakeWorker 信号注入：进度→图表/进度条、完成、失败）、_make_trainer
真实引擎/无 train_epoch/未注册三分支（GenericTrainer 打桩捕获策略）、
EngineTrainStrategy 全路径、TrainWorker 直调 run（真实 Qt 信号）。
"""
from __future__ import annotations

import logging
import time

import pytest

pytest.importorskip("PySide6")

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.interfaces_supervised import TaskType, TrainConfig  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Sig:
    """极简信号替身：connect/emit 同线程直发。"""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for s in list(self._slots):
            s(*args)


class _Artifact:
    epochs_completed = 3
    task = TaskType.DET


class FakeWorker:
    """TrainWorker 替身：start() 同步发进度+完成（或按 script 发失败）。

    W18（P3①）：补 QThread.finished 语义（真实 QThread 无论成败都发）与
    deleteLater 记录，供生命周期断言。
    """

    mode = "finish"
    on_delete_later = None  # deleteLater 时刻回调（顺序断言用）

    def __init__(self, trainer, cfg, parent=None):
        self.trainer, self.cfg = trainer, cfg
        self.progress, self.finished_sig, self.failed = _Sig(), _Sig(), _Sig()
        self.finished = _Sig()
        self.stopped = False
        self._running = False
        self.deleteLater_calls: list[bool] = []

    def start(self):
        if FakeWorker.mode == "finish":
            self.progress.emit(0.5, {"loss": 0.42})
            self.finished_sig.emit(_Artifact())
        else:
            self.failed.emit("boom")
        self.finished.emit()  # 真实 QThread 在 run() 结束后必发 finished

    def isRunning(self):
        return self._running

    def stop(self):
        self.stopped = True

    def wait(self, ms=None):
        return True

    def deleteLater(self):
        self.deleteLater_calls.append(True)
        hook = FakeWorker.on_delete_later
        if hook is not None:
            hook()


@pytest.fixture
def train_page(qapp, monkeypatch):
    from gui.pages.train import page as train_mod

    monkeypatch.setattr(train_mod, "TrainWorker", FakeWorker)
    page = train_mod.TrainPage()
    msgs = []
    page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    page._msgs = msgs
    return page


# ============================== 预设与配置 ============================== #
@pytest.mark.unit
def test_apply_preset_fills_form(train_page):
    train_page.cmb_preset.setCurrentIndex(3)  # ultra
    assert train_page.txt_backbone.text() == "yolov8x"
    assert train_page.spin_batch.value() == 2
    assert train_page.spin_lr.value() == pytest.approx(0.0003)
    assert train_page.spin_img_size.value() == 1280
    assert any(t == "预设" and a == "ultra" for t, a in train_page._msgs)


@pytest.mark.unit
def test_build_config_full_fields(train_page):
    cfg = train_page._build_config()
    assert cfg.task is TaskType.DET  # 首项保持 DET（W1 约定）
    assert cfg.epochs == 100
    assert cfg.lr == pytest.approx(0.001)
    assert cfg.batch_size == 8
    assert cfg.backbone == "yolov8n"
    assert cfg.patience == 20
    assert cfg.device == "cuda"
    assert cfg.img_size == 640
    assert cfg.lr_scheduler == "cosine"
    assert cfg.warmup_epochs == 3
    assert cfg.amp is True
    assert cfg.workers == 4


# ============================== 启动/停止/回调 ============================== #
@pytest.mark.unit
def test_start_training_progress_finish_flow(train_page, monkeypatch):
    monkeypatch.setattr(train_page, "_make_trainer",
                        lambda cfg: object())
    train_page._start_training()

    assert any(t == "训练已启动" for t, _ in train_page._msgs)
    assert train_page.progress_bar.value() == 100  # finished 置满
    assert len(train_page.chart._series["loss"]) == 1  # 进度回调喂了曲线
    assert train_page.btn_start.isEnabled() is True
    assert train_page.btn_stop.isEnabled() is False
    assert "训练完成" in train_page.lbl_log.text()


@pytest.mark.unit
def test_start_training_rejects_while_running(train_page):
    train_page._worker = FakeWorker(object(), None)
    train_page._worker._running = True
    train_page._start_training()
    assert any("请等待上一轮训练结束" in t for t, _ in train_page._msgs)


@pytest.mark.unit
def test_start_training_trainer_build_failure(train_page, monkeypatch):
    def _boom(cfg):
        raise RuntimeError("registry down")

    monkeypatch.setattr(train_page, "_make_trainer", _boom)
    train_page._start_training()
    assert any(t == "训练失败" for t, _ in train_page._msgs)
    assert train_page.btn_start.isEnabled() is True


@pytest.mark.unit
def test_worker_failed_signal_restores(train_page, monkeypatch):
    FakeWorker.mode = "fail"
    try:
        monkeypatch.setattr(train_page, "_make_trainer", lambda cfg: object())
        train_page._start_training()
    finally:
        FakeWorker.mode = "finish"
    assert any(t == "训练失败" and a == "ERROR" for t, a in train_page._msgs)
    assert "boom" in train_page.lbl_log.text()


@pytest.mark.unit
def test_stop_training_flags_worker(train_page):
    train_page._worker = FakeWorker(object(), None)
    train_page._worker._running = True
    train_page._stop_training()
    assert train_page._worker.stopped is True
    assert any(t == "训练中止" for t, _ in train_page._msgs)

    train_page._worker._running = False
    train_page._stop_training()  # 未运行 no-op


# ============================== _make_trainer 三分支 ============================== #
@pytest.mark.unit
def test_make_trainer_engine_with_train_epoch(train_page, monkeypatch):
    import models.supervised.registry as reg_mod
    import training.generic_trainer as gt_mod
    from gui.pages.train.page import EngineTrainStrategy

    captured = {}

    class _FakeGT:
        def __init__(self, task, strategy):
            captured["task"], captured["strategy"] = task, strategy

    class _Engine:
        def train_epoch(self, epoch, cfg):
            return {"loss": 0.1}

    class _Reg:
        def has(self, t):
            return True

        def get(self, t):
            return _Engine()

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _Reg())
    monkeypatch.setattr(gt_mod, "GenericTrainer", _FakeGT)

    trainer = train_page._make_trainer(TrainConfig(task=TaskType.DET))
    assert trainer is not None  # _FakeGT 实例（打桩捕获策略）
    assert isinstance(captured["strategy"], EngineTrainStrategy)
    assert captured["task"] is TaskType.DET
    assert not any("模拟" in t for t, _ in train_page._msgs)


@pytest.mark.unit
def test_make_trainer_fallbacks_warn(train_page, monkeypatch):
    import models.supervised.registry as reg_mod
    import training.generic_trainer as gt_mod

    strategies = []

    class _FakeGT:
        def __init__(self, task, strategy):
            strategies.append(strategy)

    # 分支 1：引擎无 train_epoch → 模拟 + 警告
    class _BareEngine:
        pass

    class _RegNoEpoch:
        def has(self, t):
            return True

        def get(self, t):
            return _BareEngine()

    monkeypatch.setattr(gt_mod, "GenericTrainer", _FakeGT)
    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _RegNoEpoch())
    train_page._make_trainer(TrainConfig(task=TaskType.DET))
    assert any("引擎不支持逐轮训练" in t for t, _ in train_page._msgs)

    # 分支 2：未注册 → 模拟 + 警告
    train_page._msgs.clear()

    class _RegNo:
        def has(self, t):
            return False

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _RegNo())
    train_page._make_trainer(TrainConfig(task=TaskType.DET))
    assert any("任务引擎未注册" in t for t, _ in train_page._msgs)
    assert len(strategies) == 2  # 两次均回退模拟策略


# ============================== EngineTrainStrategy ============================== #
@pytest.mark.unit
def test_engine_train_strategy_paths():
    from gui.pages.train.page import EngineTrainStrategy

    cfg = TrainConfig(task=TaskType.DET)

    class _DictEngine:
        def train_epoch(self, epoch, cfg):
            return {"loss": 0.2, "map": 0.5}

    s = EngineTrainStrategy(_DictEngine(), cfg)
    assert s.train_epoch(1, cfg) == {"loss": 0.2, "map": 0.5}

    class _FloatEngine:
        def train_epoch(self, epoch, cfg):
            return 0.7

    s2 = EngineTrainStrategy(_FloatEngine(), cfg)
    assert s2.train_epoch(1, cfg) == {"loss": 0.7}

    class _NoEpoch:
        def save(self, path):
            self.saved = path

        def get_optimizer(self):
            return "OPT"

    no_ep = _NoEpoch()
    s3 = EngineTrainStrategy(no_ep, cfg)
    metrics = s3.train_epoch(3, cfg)  # 模拟衰减
    assert metrics["loss"] == pytest.approx(round(1.0 * 2.718281828 ** (-0.15), 4))
    s3.save("w.pt")
    assert no_ep.saved == "w.pt"
    assert s3.get_optimizer() == "OPT"  # 引擎直供透传


@pytest.mark.unit
def test_engine_strategy_sgd_and_none_optimizer():
    from gui.pages.train.page import EngineTrainStrategy

    cfg = TrainConfig(task=TaskType.DET, lr=0.01)

    class _ModelEngine:  # 无 get_optimizer，暴露 _model → 构建 SGD
        _model = None  # 延后赋真 torch 模块

    torch = pytest.importorskip("torch")
    _ModelEngine._model = torch.nn.Linear(2, 2)
    s = EngineTrainStrategy(_ModelEngine(), cfg)
    opt = s.get_optimizer()
    assert isinstance(opt, torch.optim.SGD)

    class _Empty:
        pass

    assert EngineTrainStrategy(_Empty(), cfg).get_optimizer() is None


# ============================== TrainWorker（真实 QThread 直调 run） ============================== #
@pytest.mark.unit
def test_train_worker_run_emits_progress_and_finish(qapp):
    from gui.pages.train.worker import TrainWorker

    events = []

    class _Trainer:
        def fit(self, cfg, progress, should_stop):
            progress(0.25, {"loss": 1.0})
            return _Artifact()

    w = TrainWorker(_Trainer(), TrainConfig(task=TaskType.DET))
    w.progress.connect(lambda r, m: events.append(("progress", r, m)))
    w.finished_sig.connect(lambda a: events.append(("finished", a)))
    w.failed.connect(lambda e: events.append(("failed", e)))
    w.run()  # 直调（同步，不启线程）

    assert events[0] == ("progress", 0.25, {"loss": 1.0})
    assert events[1][0] == "finished"
    assert events[1][1].epochs_completed == 3


@pytest.mark.unit
def test_train_worker_failure_and_stop(qapp):
    from gui.pages.train.worker import TrainWorker

    failures = []

    class _BadTrainer:
        def fit(self, cfg, progress, should_stop):
            raise ValueError("no data")

    w = TrainWorker(_BadTrainer(), TrainConfig(task=TaskType.DET))
    w.failed.connect(failures.append)
    w.run()
    assert failures == ["no data"]

    stop_seen = []

    class _StopTrainer:
        def fit(self, cfg, progress, should_stop):
            stop_seen.append(should_stop())
            return _Artifact()

    w2 = TrainWorker(_StopTrainer(), TrainConfig(task=TaskType.DET))
    w2.stop()
    w2.run()
    assert stop_seen == [True]


# ================ W14-C3 追加：训练完成审计接线（P2-11③） ================ #
@pytest.mark.unit
def test_train_finished_writes_train_complete_audit(train_page, monkeypatch):
    """RED（P2-11③）：core.audit_logger.log_train_complete 全仓 0 调用——
    训练完成无审计（对照 log_detection_complete/log_model_export 均有消费者）。
    _on_finished 成功分支应恰落一条 train_complete，user 取会话当前用户。"""
    from core.audit_logger import get_audit_logger
    from core.session import reset_current_user, set_current_user

    reset_current_user()
    set_current_user("tester")
    audit = get_audit_logger()
    audit._buffer.clear()
    try:
        monkeypatch.setattr(train_page, "_make_trainer", lambda cfg: object())
        train_page._start_training()

        dones = [e for e in audit._buffer if e["action"] == "train_complete"]
        assert len(dones) == 1, "训练完成应恰落一条 train_complete 审计"
        assert dones[0]["user"] == "tester"          # 归属会话当前用户
        assert dones[0]["details"]["task"] == "det"  # _Artifact.task = TaskType.DET
        assert dones[0]["details"]["epochs"] == 3    # _Artifact.epochs_completed
    finally:
        reset_current_user()
        audit._buffer.clear()


# ================ W18（TASK-001 / P3①）：TrainWorker 生命周期 + INFO 留痕 ================ #


@pytest.mark.unit
def test_start_training_releases_worker_on_thread_finished(
        train_page, monkeypatch):
    """W18（RED）：QThread.finished → 先清页面引用 self._worker=None、
    再 worker.deleteLater()——顺序关键：closeEvent 的
    getattr(self, "_worker").isRunning() 若拿到已析构的 C++ 包装，
    PySide6 会抛 RuntimeError（对已删除对象调 isRunning）。"""
    order: list = []

    def _hook():
        order.append(("deleteLater", train_page._worker is None))

    FakeWorker.on_delete_later = _hook
    try:
        monkeypatch.setattr(train_page, "_make_trainer", lambda cfg: object())
        train_page._start_training()
    finally:
        FakeWorker.on_delete_later = None

    assert train_page._worker is None, "线程 finished 后页面引用必须清空"
    assert order == [("deleteLater", True)], "清引用必须先于 deleteLater"


@pytest.mark.unit
def test_real_train_worker_parentless_and_reference_cleared(qapp, monkeypatch):
    """W18（RED）真链路（真 TrainPage + 真 TrainWorker 线程）：
    ① 构造不得再以页面作 parent（parent=None 自管生命周期）；
    ② 线程 finished 后页面引用被清（deleteLater 排队销毁）。"""
    from gui.pages.train.page import TrainPage

    page = TrainPage()

    class _SlowTrainer:
        def fit(self, cfg, progress, should_stop):
            time.sleep(0.2)  # 给主线程留捕获 worker 引用的窗口
            return _Artifact()

    monkeypatch.setattr(page, "_make_trainer", lambda cfg: _SlowTrainer())
    page._start_training()

    worker = page._worker
    assert worker is not None
    assert worker.parent() is None, "TrainWorker 不得再以页面作 parent"
    assert worker.wait(5000) is True  # 线程收尾（finished 已直连派发）

    deadline = time.time() + 5.0
    while page._worker is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert page._worker is None, "线程 finished 后页面引用必须已清"


@pytest.mark.unit
def test_train_start_and_finish_leave_info_logs(
        train_page, monkeypatch, caplog):
    """W18（P3① 留痕）：训练开始与完成各落一条 logger.info（操作 + 关键
    参数），使 gui.pages.train.page 在日志中可见（此前该 logger 全程静默）。"""
    monkeypatch.setattr(train_page, "_make_trainer", lambda cfg: object())
    with caplog.at_level(logging.INFO, logger="gui.pages.train.page"):
        train_page._start_training()
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("训练开始" in m for m in msgs), "训练开始须留 INFO 痕"
    assert any("训练完成" in m for m in msgs), "训练完成须留 INFO 痕"
