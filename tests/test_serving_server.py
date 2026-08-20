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


@pytest.mark.unit
def test_release_shared_memory_miss_returns_false_with_error(servicer, shm):
    """W17（v3 P1-1 附带）：未命中本进程区域的 Release 不得假报成功——

    旧行为恒 success=True，客户端把"什么都没回收到"当成功 ACK，
    与区域泄漏互为盲区（v2/v3 审查点名）。未命中须 success=False + 非空 error。
    """
    resp = servicer.ReleaseSharedMemory(
        pb.ReleaseSharedMemoryRequest(file_path=r"C:\nonexistent\ava_x.bin"), _ctx()
    )
    assert resp.success is False
    assert resp.error  # 非空错误说明（供客户端/排障分辨"未命中"与"异常"）


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
    assert tasks == {"det"}  # 只有已注册的 det；zero_shot 已摘除（W14 P2-8）


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


# ================ W14-C3 追加：静默 except 补日志（P2-13）+ P2-18 ================ #
@pytest.mark.unit
def test_list_tasks_dispatcher_failure_logs_error(servicer, caplog):
    """RED（P2-13）：ListTasks 整体失败此前静默返回空列表——客户端把
    故障当"无任务"；必须落 ERROR 日志（行为不变，仍返回空）。"""
    import logging

    servicer._dispatcher.fail_list = True
    with caplog.at_level(logging.ERROR, logger="serving.server"):
        resp = servicer.ListTasks(pb.ListTasksRequest(), _ctx())
    assert len(resp.tasks) == 0
    errs = [r for r in caplog.records
            if r.levelno == logging.ERROR and "ListTasks" in r.getMessage()]
    assert errs, "ListTasks 失败应落 ERROR（服务端可辨识故障 vs 真无任务）"


@pytest.mark.unit
def test_release_shared_memory_failure_logs_warning(servicer, monkeypatch, caplog):
    """RED（P2-13）：Release 失败此前无服务端日志（与 P1-1 互为盲区）。"""
    import logging

    def _boom(path):
        raise RuntimeError("release boom")

    monkeypatch.setattr(servicer._shm, "release", _boom)
    with caplog.at_level(logging.WARNING, logger="serving.server"):
        resp = servicer.ReleaseSharedMemory(
            pb.ReleaseSharedMemoryRequest(file_path="x.bin"), _ctx()
        )
    assert resp.success is False
    assert "boom" in resp.error
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "ReleaseSharedMemory" in r.getMessage()]
    assert warns


@pytest.mark.unit
def test_module_examples_stay_loopback():
    """RED（P2-18）：模块 docstring 用法示例曾示范 --host 0.0.0.0
    （无 TLS/token 下的暴露路径）；示例必须与 ADR-0001 回环锁定一致。"""
    from pathlib import Path

    src = Path(__import__("serving.server", fromlist=["__file__"]).__file__).read_text(
        encoding="utf-8"
    )
    assert "0.0.0.0" not in src, "serving/server.py 不得示范非回环监听（ADR-0001）"


# ============ W15-L1 追加：P2-20 serving 独立进程文件日志 ============ #


@pytest.fixture(autouse=True)
def root_handler_guard():
    """（模块级 autouse）测试后摘除本测试新增到 root 的 handler。

    双重职责：防 tmp_path 句柄泄漏；也防既有 serve() 用例经真实
    _resolve_log_dir() 挂上的 logs/serving.log handler 泄漏到会话
    后续测试（实测曾把 W14-C3 用例的 ERROR 串写进 logs/serving.log）。
    不改动任何既有用例本体（快照差集，只摘"本测试新增"的 handler）。"""
    import logging

    before = list(logging.getLogger().handlers)
    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()


@pytest.mark.unit
def test_setup_file_logging_installs_rotating_handler(tmp_path):
    """RED（P2-20）：setup_file_logging(tmp_path) 后 root 上存在
    RotatingFileHandler，baseFilename/上限/备份数与参数一致（含自定义注入）。"""
    import logging
    import logging.handlers
    from pathlib import Path

    from serving.server import setup_file_logging

    handler = setup_file_logging(str(tmp_path))
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler in logging.getLogger().handlers
    assert Path(handler.baseFilename) == tmp_path / "serving.log"
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3

    # 参数化注入：文件名/上限/备份数可覆盖
    h2 = setup_file_logging(
        str(tmp_path), filename="custom.log", max_bytes=1024, backup_count=7
    )
    assert Path(h2.baseFilename) == tmp_path / "custom.log"
    assert h2.maxBytes == 1024 and h2.backupCount == 7


@pytest.mark.unit
def test_setup_file_logging_persists_record_to_disk(tmp_path):
    """RED（P2-20）：挂载后写一条日志必须落盘（独立进程脱离终端后可追溯）。"""
    import logging

    from serving.server import setup_file_logging

    setup_file_logging(str(tmp_path))
    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(logging.INFO)
    try:
        logging.getLogger("serving.server").info("P2-20 文件落盘探针")
        for h in root.handlers:
            h.flush()
    finally:
        root.setLevel(prev_level)
    content = (tmp_path / "serving.log").read_text(encoding="utf-8")
    assert "P2-20 文件落盘探针" in content


@pytest.mark.unit
def test_setup_file_logging_idempotent_replaces_old(tmp_path):
    """RED（P2-20）：重复调用不得重复挂载（重复写同一份日志）——
    先摘除旧 handler 再挂新（幂等替换）。"""
    import logging
    import logging.handlers
    from pathlib import Path

    from serving.server import setup_file_logging

    h1 = setup_file_logging(str(tmp_path))
    h2 = setup_file_logging(str(tmp_path / "second"))
    root = logging.getLogger()
    marked = [
        h
        for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "_ava_serving_file", False)
    ]
    assert len(marked) == 1, "重复调用后 root 上应恰有一个 serving 文件 handler"
    assert marked[0] is h2
    assert h1 not in root.handlers, "旧 handler 必须被摘除（不得双写）"
    assert Path(h2.baseFilename) == tmp_path / "second" / "serving.log"


@pytest.mark.unit
def test_import_serving_server_adds_no_root_handler():
    """RED（P2-20 契约）：setup_file_logging 只允许 serve() 入口调用，
    import serving.server 期零副作用——root logger 不得新增 handler。"""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import logging, sys;"
        "before = list(logging.getLogger().handlers);"
        "import serving.server;"
        "after = logging.getLogger().handlers;"
        "leaked = [h for h in after if h not in before];"
        "print('LEAKED', len(leaked));"
        "sys.exit(1 if leaked else 0)"
    )
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"import serving.server 泄漏 root handler:\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.unit
def test_resolve_log_dir_reads_config_with_gui_fallback(monkeypatch, tmp_path):
    """RED（P2-20）：log_dir 解析与 GUI（gui/main.setup_logging）同源——
    core.config LoggingConfig.log_dir，配置不可用回退 ./logs。"""
    # W23（v4 P2-1c）：显式测生产行为——剥掉根 conftest 设置的会话级
    # AVA_LOG_DIR（env 优先于 config，不剥则两断言必红）。
    monkeypatch.delenv("AVA_LOG_DIR", raising=False)
    from types import SimpleNamespace

    import core.config as cfg_mod
    from serving.server import _resolve_log_dir

    monkeypatch.setattr(
        cfg_mod, "get_config", lambda: SimpleNamespace(logging=SimpleNamespace(log_dir=str(tmp_path)))
    )
    assert _resolve_log_dir() == str(tmp_path)

    def _broken():
        raise ValueError("config unavailable")

    monkeypatch.setattr(cfg_mod, "get_config", _broken)
    assert _resolve_log_dir() == "./logs"


@pytest.mark.unit
def test_serve_wires_file_logging_and_keeps_interrupt_path(tmp_path, monkeypatch):
    """RED（P2-20）：serve() 入口接线文件日志（目录可注入），且
    KeyboardInterrupt 优雅退出路径不因接线破坏。"""
    import logging
    import logging.handlers
    from pathlib import Path

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

    root = logging.getLogger()
    prev_level = root.level
    root.setLevel(logging.INFO)  # 对齐生产 basicConfig(INFO)（pytest 下 root 已有 handler，basicConfig 为 no-op）
    try:
        srv.serve(log_dir=str(tmp_path))
    finally:
        root.setLevel(prev_level)

    assert stops == [3], "KeyboardInterrupt 必须仍走优雅停止（grace=3）"
    log_file = tmp_path / "serving.log"
    assert log_file.exists(), "serve() 应在注入目录创建 serving.log"
    content = log_file.read_text(encoding="utf-8")
    assert "gRPC 服务已启动" in content, "启动行必须落盘"
    assert "收到中断信号" in content, "中断退出行必须落盘"
    marked = [
        h
        for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "_ava_serving_file", False)
    ]
    assert len(marked) == 1
    assert Path(marked[0].baseFilename) == log_file


@pytest.mark.unit
def test_serve_file_logging_failure_does_not_block_startup(
    tmp_path, monkeypatch, caplog
):
    """RED（P2-20）：文件日志初始化失败（如目录不可写）不得阻断服务启动，
    且必须留痕（不得静默吞——W14 教训）。"""
    import logging

    from serving import server as srv

    started = []

    class _FakeServer:
        def start(self):
            started.append(True)

        def wait_for_termination(self):
            return None  # 立即正常返回

        def stop(self, grace):
            pass

    monkeypatch.setattr(srv, "create_server", lambda *a, **k: _FakeServer())

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(srv, "setup_file_logging", _boom)
    with caplog.at_level(logging.WARNING, logger="serving.server"):
        srv.serve(log_dir=str(tmp_path))  # 不得抛 OSError
    assert started == [True], "文件日志失败后服务仍应启动"
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns, "文件日志失败必须落 WARNING 留痕"


# ============ W17 簇C 追加：P2-9 非回环绑定告警 ============ #


@pytest.mark.unit
def test_create_server_non_loopback_host_logs_warning(shm, caplog):
    """RED（P2-9）：host 非回环时绑定前必须落 WARNING——本服务无
    TLS/token 鉴权（ADR-0001），非回环监听等于把 gRPC 接口裸奔给整个
    网段，用户须被显式提醒暴露风险。"""
    import logging

    with caplog.at_level(logging.WARNING, logger="serving.server"):
        server = create_server(
            host="0.0.0.0", dispatcher=FakeDispatcher(), shm=shm, port=50098
        )
    server.stop(grace=0)

    warns = [
        r for r in caplog.records
        if r.name == "serving.server" and r.levelno == logging.WARNING
    ]
    assert warns, "非回环绑定应落 WARNING"
    msg = warns[0].getMessage()
    assert "非回环绑定" in msg
    assert "鉴权" in msg, "告警须点明无鉴权 gRPC 暴露风险"
    assert "ADR-0001" in msg, "告警须引用 ADR-0001"


@pytest.mark.unit
def test_create_server_loopback_host_no_warning(shm, caplog):
    """RED（P2-9）：回环绑定（默认推荐，ADR-0001）不得产生告警。"""
    import logging

    with caplog.at_level(logging.WARNING, logger="serving.server"):
        server = create_server(
            host="127.0.0.1", dispatcher=FakeDispatcher(), shm=shm, port=50099
        )
    server.stop(grace=0)

    warns = [
        r for r in caplog.records
        if r.name == "serving.server" and r.levelno >= logging.WARNING
    ]
    assert not warns, f"回环绑定不应告警: {[r.getMessage() for r in warns]}"
