"""serving/server 单元测试（W4-T2：23% → 补测）。

直调 Servicer RPC 方法（无网络、无真模型）：假 dispatcher 注入，
覆盖 Ping/ListTasks/GetTaskInfo/LoadModel/UnloadModel/Detect/
ReleaseSharedMemory 的成功与错误路径 + create_server 组装。
"""
from __future__ import annotations

import io

import pytest

np = pytest.importorskip("numpy")
grpc = pytest.importorskip("grpc")

from core.interfaces_supervised import DetectionResult, TaskType  # noqa: E402
from serving.proto import autovisionagent_pb2 as pb  # noqa: E402
from serving.server import AutoVisionAgentServicer, create_server  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402


class FakeDispatcher:
    """假分发器：记录调用、可脚本化失败。"""

    def __init__(self):
        self.loaded = ["det"]
        self.fail_list = False
        self.fail_info = False
        self.fail_load = False
        self.fail_infer = False
        self.load_calls = []
        self.infer_calls = []

    @property
    def loaded_tasks(self):
        return list(self.loaded)

    def list_all_tasks(self):
        if self.fail_list:
            raise RuntimeError("boom")
        return [
            {"task": "det", "paradigm": "supervised", "requires_training": True},
            {"task": "abdet", "paradigm": "zero_shot", "requires_training": False},
        ]

    def get_task_info(self, task: str):
        if self.fail_info:
            raise RuntimeError("boom")
        return {"task": task, "paradigm": "supervised",
                "loaded": task in self.loaded, "requires_training": True}

    def load_supervised(self, task, weights_path, device="cuda"):
        if self.fail_load:
            raise RuntimeError("权重不存在")
        self.load_calls.append((task, weights_path, device))
        self.loaded.append(task.value)

    def infer(self, task, image, mode="auto", **kwargs):
        if self.fail_infer:
            raise RuntimeError("引擎未加载")
        self.infer_calls.append((task, mode, kwargs))
        return DetectionResult(
            task=TaskType.DET,
            score=0.75,
            scores=(0.75,),
            labels=("crack",),
            boxes=np.array([[1.0, 2.0, 3.0, 4.0]]),
        )


@pytest.fixture
def shm(tmp_path):
    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.fixture
def servicer(shm):
    return AutoVisionAgentServicer(FakeDispatcher(), shm=shm)


def _ctx():
    return None  # 直调方法不触碰 context


def _png_bytes(w=6, h=4):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------- Ping ------------------------------- #
@pytest.mark.unit
def test_ping_reports_ready_and_loaded(servicer):
    pong = servicer.Ping(pb.PingRequest(), _ctx())
    assert pong.dispatcher_ready is True
    assert pong.server_version
    assert list(pong.loaded_tasks) == ["det"]


@pytest.mark.unit
def test_ping_without_dispatcher(shm):
    pong = AutoVisionAgentServicer(None, shm=shm).Ping(pb.PingRequest(), _ctx())
    assert pong.dispatcher_ready is False


# ------------------------------- ListTasks ------------------------------- #
@pytest.mark.unit
def test_list_tasks_maps_registry(servicer):
    resp = servicer.ListTasks(pb.ListTasksRequest(), _ctx())
    tasks = {t.task: t for t in resp.tasks}
    assert set(tasks) == {"det", "abdet"}
    assert tasks["det"].paradigm == "supervised"
    assert tasks["det"].requires_training is True
    assert tasks["det"].loaded is True       # det 在 loaded 中
    assert tasks["abdet"].loaded is False


@pytest.mark.unit
def test_list_tasks_dispatcher_failure_returns_empty(servicer):
    servicer._dispatcher.fail_list = True
    resp = servicer.ListTasks(pb.ListTasksRequest(), _ctx())
    assert len(resp.tasks) == 0


# ------------------------------- GetTaskInfo ------------------------------- #
@pytest.mark.unit
def test_get_task_info(servicer):
    info = servicer.GetTaskInfo(pb.GetTaskInfoRequest(task="det"), _ctx())
    assert info.task == "det"
    assert info.paradigm == "supervised"
    assert info.loaded is True


@pytest.mark.unit
def test_get_task_info_failure_falls_back_unknown(servicer):
    servicer._dispatcher.fail_info = True
    info = servicer.GetTaskInfo(pb.GetTaskInfoRequest(task="sgan"), _ctx())
    assert info.task == "sgan"
    assert info.paradigm == "unknown"
    assert info.loaded is False


# ------------------------------- LoadModel / UnloadModel ------------------------------- #
@pytest.mark.unit
def test_load_model_success(servicer):
    resp = servicer.LoadModel(
        pb.LoadModelRequest(task="cls", weights_path="a.pth", device="cpu"), _ctx()
    )
    assert resp.success is True
    (task, path, device), = servicer._dispatcher.load_calls
    assert task is TaskType.CLS
    assert path == "a.pth" and device == "cpu"


@pytest.mark.unit
def test_load_model_defaults_and_failure(servicer):
    resp = servicer.LoadModel(
        pb.LoadModelRequest(task="cls", weights_path="a.pth"), _ctx()
    )
    assert resp.success is True
    assert servicer._dispatcher.load_calls[0][2] == "cuda"  # 缺省 device

    servicer._dispatcher.fail_load = True
    resp = servicer.LoadModel(
        pb.LoadModelRequest(task="cls", weights_path="bad"), _ctx()
    )
    assert resp.success is False
    assert "权重不存在" in resp.error


@pytest.mark.unit
def test_unload_model_via_registry_cache(servicer, monkeypatch):
    cleared = []

    import models.supervised.registry as reg_mod

    class _FakeReg:
        def clear_cache(self, task):
            cleared.append(task)

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _FakeReg())
    resp = servicer.UnloadModel(pb.UnloadModelRequest(task="det"), _ctx())
    assert resp.success is True
    assert cleared == [TaskType.DET]


@pytest.mark.unit
def test_unload_model_failure(servicer, monkeypatch):
    import models.supervised.registry as reg_mod

    def _boom():
        raise RuntimeError("no registry")

    monkeypatch.setattr(reg_mod, "get_default_registry", _boom)
    resp = servicer.UnloadModel(pb.UnloadModelRequest(task="det"), _ctx())
    assert resp.success is False
    assert resp.error


# ------------------------------- Detect ------------------------------- #
@pytest.mark.unit
def test_detect_success_from_bytes(servicer):
    req = pb.DetectRequest(task="det", mode="supervised",
                           threshold=0.4, labels=["crack"])
    req.image_bytes = _png_bytes()
    resp = servicer.Detect(req, _ctx())

    assert resp.success is True
    assert resp.result.score == pytest.approx(0.75)
    assert resp.result.box_count == 1
    assert list(resp.result.labels) == ["crack"]

    (task, mode, kwargs), = servicer._dispatcher.infer_calls
    assert task == "det" and mode == "supervised"
    assert kwargs["threshold"] == pytest.approx(0.4)
    assert kwargs["labels"] == ["crack"]


@pytest.mark.unit
def test_detect_defaults_task_and_mode(servicer):
    req = pb.DetectRequest()
    req.image_bytes = _png_bytes()
    servicer.Detect(req, _ctx())
    (task, mode, kwargs), = servicer._dispatcher.infer_calls
    assert task == "det" and mode == "auto"
    assert kwargs == {}  # 未提供的可选参数不透传


@pytest.mark.unit
def test_detect_image_decode_failure(servicer):
    resp = servicer.Detect(pb.DetectRequest(task="det"), _ctx())
    assert resp.success is False
    assert "图像解码失败" in resp.error


@pytest.mark.unit
def test_detect_infer_failure(servicer):
    servicer._dispatcher.fail_infer = True
    req = pb.DetectRequest(task="det")
    req.image_bytes = _png_bytes()
    resp = servicer.Detect(req, _ctx())
    assert resp.success is False
    assert "引擎未加载" in resp.error


# ------------------------------- ReleaseSharedMemory ------------------------------- #
@pytest.mark.unit
def test_release_shared_memory(servicer, shm):
    handle = shm.write_array(np.zeros(4, dtype=np.uint8))
    resp = servicer.ReleaseSharedMemory(
        pb.ReleaseSharedMemoryRequest(file_path=handle.file_path), _ctx()
    )
    assert resp.success is True
    import os
    assert not os.path.exists(handle.file_path)


# ------------------------------- create_server ------------------------------- #
@pytest.mark.unit
def test_create_server_assembles_with_injected_dispatcher(shm):
    server = create_server(dispatcher=FakeDispatcher(), shm=shm, port= 50097)
    assert server is not None
    server.stop(grace=0)


# ------------------------------- 诚实宣称（P1-1 残留） ------------------------------- #
@pytest.mark.unit
def test_list_all_tasks_advertises_only_registered(monkeypatch):
    """未注册的有监督任务不得被广告（W4-T2：静态硬编码 10 任务 → 按注册表）。"""
    from industrial_vision_platform.vision_dispatcher import VisionModelDispatcher
    import models.supervised.registry as reg_mod

    class _FakeReg:
        def list(self):
            return [TaskType.DET]

        def has(self, t):
            return t is TaskType.DET

    monkeypatch.setattr(reg_mod, "get_default_registry", lambda: _FakeReg())
    tasks = {t["task"] for t in VisionModelDispatcher.list_all_tasks()}
    assert tasks == {"zero_shot", "det"}  # 只有零样本 + 已注册的 det


# ------------------------------- 入口与生命周期（W7-T2） ------------------------------- #
@pytest.mark.unit
def test_build_arg_parser_defaults(monkeypatch):
    from serving.server import _build_arg_parser

    for key in ("AVA_HOST", "AVA_PORT", "AVA_MAX_WORKERS"):
        monkeypatch.delenv(key, raising=False)
    args = _build_arg_parser().parse_args([])
    assert (args.host, args.port, args.max_workers) == ("127.0.0.1", 50051, 8)


@pytest.mark.unit
def test_build_arg_parser_env_and_cli_override(monkeypatch):
    from serving.server import _build_arg_parser

    monkeypatch.setenv("AVA_HOST", "0.0.0.0")
    monkeypatch.setenv("AVA_PORT", "6001")
    monkeypatch.setenv("AVA_MAX_WORKERS", "4")
    args = _build_arg_parser().parse_args(["--port", "7001"])
    assert args.host == "0.0.0.0"
    assert args.port == 7001  # CLI 覆盖环境变量
    assert args.max_workers == 4


@pytest.mark.unit
def test_serve_graceful_on_keyboard_interrupt(monkeypatch):
    from serving import server as srv

    stops = []

    class _FakeServer:
        def start(self):
            pass

        def wait_for_termination(self):
            raise KeyboardInterrupt

        def stop(self, grace):
            stops.append(grace)

    monkeypatch.setattr(srv, "create_server", lambda *a, **k: _FakeServer())
    srv.serve()  # 不得抛出 KeyboardInterrupt
    assert stops == [3]


@pytest.mark.unit
def test_main_entry_invokes_serve(monkeypatch):
    import runpy
    import sys

    from serving import server as srv

    calls = []
    monkeypatch.setattr(
        srv, "serve",
        lambda host, port, max_workers: calls.append((host, port, max_workers)),
    )
    monkeypatch.setattr(sys, "argv", ["serving"])
    runpy.run_module("serving", run_name="__main__")
    assert calls == [("127.0.0.1", 50051, 8)]
