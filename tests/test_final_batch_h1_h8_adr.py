"""收尾批次测试（H1/H8/ADR-0005/0006 + Tessa TOP5 #1/#2，2026-10-06）。

H1：LoadModel 权重路径白名单（AVA_MODEL_ROOTS）。
H8：生命周期 RPC 串行化（并发 Load/Unload 无交错崩溃）。
ADR-0005：UnloadModel 元数据一致性。
ADR-0006：Detect 未知 task fail-closed（INVALID_ARGUMENT）。
TOP5#1：shm 并发压力（8 线程读写释放 + TTL 回收，无泄漏无错数据）。
TOP5#2：in-process 真 gRPC 通道 E2E（Ping/Detect/FetchRegion 流式/Release）。
"""
from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
grpc = pytest.importorskip("grpc")


# ============================== H1：权重路径白名单 ============================== #


class _FakeDispatcher:
    loaded_tasks: list[str] = []

    def load_supervised(self, task, weights_path, device="cuda"):
        pass

    def unload_supervised(self, task):
        return True

    def infer(self, task, image, mode="auto", **kwargs):
        from core.interfaces_supervised import DetectionResult, TaskType

        return DetectionResult(
            task=TaskType.DET, score=0.9,
            labels=("crack",), boxes=np.array([[1.0, 2.0, 3.0, 4.0]]),
        )


@pytest.fixture
def h1_servicer(tmp_path, monkeypatch):
    from serving.server import AutoVisionAgentServicer
    from serving.shared_memory import SharedMemoryManager

    monkeypatch.setenv("AVA_MODEL_ROOTS", str(tmp_path / "models"))
    (tmp_path / "models").mkdir()
    return AutoVisionAgentServicer(
        _FakeDispatcher(), shm=SharedMemoryManager(base_dir=str(tmp_path / "shm"))
    )


@pytest.mark.unit
def test_load_model_rejects_path_outside_roots(h1_servicer, tmp_path):
    """H1 核心：白名单外的权重路径 → success=False（含"不允许"错误）。"""
    from serving.proto import autovisionagent_pb2 as pb

    secret = tmp_path / "elsewhere" / "evil.pt"
    secret.parent.mkdir()
    secret.write_bytes(b"fake")

    resp = h1_servicer.LoadModel(
        pb.LoadModelRequest(task="det", weights_path=str(secret)), None
    )
    assert resp.success is False
    assert "不允许" in resp.error or "模型根目录" in resp.error


@pytest.mark.unit
def test_load_model_allows_path_inside_roots(h1_servicer, tmp_path):
    """H1：白名单内的路径正常加载。"""
    from serving.proto import autovisionagent_pb2 as pb

    ok_weights = tmp_path / "models" / "best.pt"
    ok_weights.write_bytes(b"fake")

    resp = h1_servicer.LoadModel(
        pb.LoadModelRequest(task="det", weights_path=str(ok_weights)), None
    )
    assert resp.success is True


@pytest.mark.unit
def test_load_model_rejects_traversal_escape(h1_servicer, tmp_path):
    """H1：相对路径穿越出根（../escape.pt）同样拒绝。"""
    from serving.proto import autovisionagent_pb2 as pb

    escape = tmp_path / "escape.pt"
    escape.write_bytes(b"fake")
    traversal = str(tmp_path / "models" / ".." / "escape.pt")

    resp = h1_servicer.LoadModel(
        pb.LoadModelRequest(task="det", weights_path=traversal), None
    )
    assert resp.success is False


# ============================== ADR-0006：fail-closed ============================== #


class _AbortCapture:
    def __init__(self):
        self.code = None
        self.details = None

    def abort(self, code, details=""):
        self.code = code
        self.details = details
        raise _Aborted()


class _Aborted(Exception):
    pass


@pytest.mark.unit
def test_detect_unknown_task_aborts_invalid_argument(tmp_path):
    """ADR-0006 核心：未知 task → INVALID_ARGUMENT（不再静默回退 DET）。"""
    from serving.proto import autovisionagent_pb2 as pb
    from serving.server import AutoVisionAgentServicer
    from serving.shared_memory import SharedMemoryManager

    servicer = AutoVisionAgentServicer(
        _FakeDispatcher(),
        shm=SharedMemoryManager(base_dir=str(tmp_path / "shm")),
    )
    ctx = _AbortCapture()
    req = pb.DetectRequest(task="vlm", image_bytes=b"\x89PNG fake")

    with pytest.raises(_Aborted):
        servicer.Detect(req, ctx)

    assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
    assert "未知任务类型" in ctx.details
    assert "vlm" in ctx.details


@pytest.mark.unit
def test_detect_known_lowercase_still_works(tmp_path):
    """ADR-0006：合法 task（含大写）正常进入推理链路。"""
    from serving.proto import autovisionagent_pb2 as pb
    from serving.server import AutoVisionAgentServicer
    from serving.shared_memory import SharedMemoryManager

    class _Disp(_FakeDispatcher):
        def infer(self, task, image, mode="auto", **kwargs):
            from core.interfaces_supervised import DetectionResult, TaskType

            return DetectionResult(task=TaskType.DET, score=0.9)

    servicer = AutoVisionAgentServicer(
        _Disp(), shm=SharedMemoryManager(base_dir=str(tmp_path / "shm"))
    )
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((8, 8, 3), np.uint8))
    req = pb.DetectRequest(task="DET", image_bytes=buf.tobytes())  # 大小写不敏感

    resp = servicer.Detect(req, None)
    assert resp.success is True


# ============================== H8：生命周期串行化 ============================== #


@pytest.mark.unit
def test_concurrent_load_unload_no_interleave_crash(tmp_path, monkeypatch):
    """H8 核心：多线程并发 Load/Unload——互斥锁保证无交错异常。"""
    from serving.proto import autovisionagent_pb2 as pb
    from serving.server import AutoVisionAgentServicer
    from serving.shared_memory import SharedMemoryManager

    monkeypatch.setenv("AVA_MODEL_ROOTS", str(tmp_path))
    weights = tmp_path / "w.pt"
    weights.write_bytes(b"f")

    class _SlowDispatcher(_FakeDispatcher):
        def __init__(self):
            self.load_n = 0
            self.unload_n = 0
            self.in_load = False
            self.overlap_detected = False

        def load_supervised(self, task, weights_path, device="cuda"):
            # 检测交错：load 进行中若发现另一个 load/unload 已进入则违规
            if self.in_load:
                self.overlap_detected = True
            self.in_load = True
            import time

            time.sleep(0.005)  # 制造并发窗口
            self.load_n += 1
            self.in_load = False

        def unload_supervised(self, task):
            if self.in_load:
                self.overlap_detected = True
            import time

            time.sleep(0.003)
            self.unload_n += 1
            return True

    disp = _SlowDispatcher()
    servicer = AutoVisionAgentServicer(
        disp, shm=SharedMemoryManager(base_dir=str(tmp_path / "shm"))
    )
    errors: list[Exception] = []

    def worker():
        for _ in range(10):
            r = servicer.LoadModel(
                pb.LoadModelRequest(task="det", weights_path=str(weights)), None
            )
            if not r.success:
                errors.append(RuntimeError(r.error))
            r2 = servicer.UnloadModel(pb.UnloadModelRequest(task="det"), None)
            if not r2.success:
                errors.append(RuntimeError(r2.error))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发生命周期 RPC 出现失败: {errors}"
    assert not disp.overlap_detected, "生命周期操作出现交错（锁失效）"
    assert disp.load_n == 40 and disp.unload_n == 40


# ============================== TOP5#1：shm 并发压力 ============================== #


@pytest.mark.unit
def test_shm_concurrent_write_read_release_stress(tmp_path):
    """Tessa TOP5#1：8 线程写读释循环 + 数据完整性 + 目录清洁。"""
    from serving.shared_memory import SharedMemoryManager

    shm_dir = tmp_path / "shm"
    mgr = SharedMemoryManager(base_dir=str(shm_dir), region_ttl_seconds=1.0)
    errors: list[Exception] = []
    barrier = threading.Barrier(8)
    iterations = 30

    def worker(wid: int):
        try:
            barrier.wait()
            rng = np.random.default_rng(wid)
            for i in range(iterations):
                data = rng.integers(0, 256, size=2048, dtype=np.uint8).tobytes()
                h = mgr.write_bytes(data, dtype="uint8", shape=(2048,))
                back = mgr.read_bytes(h)
                assert back == data, f"w{wid}i{i} 数据不一致"
                mgr.release(h.file_path)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"并发压力出错: {errors[:3]}"
    mgr.cleanup()
    # 收尾：目录内无 ava_*.bin 残留（release 全命中）
    leftovers = list(shm_dir.glob("ava_*.bin"))
    assert not leftovers, f"泄漏 {len(leftovers)} 个区域文件"


# ============================== TOP5#2：真 gRPC 通道 E2E ============================== #


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("AVA_E2E") != "1",
                    reason="E2E 默认跳过（AVA_E2E=1 启用，回环无外网依赖）")
def test_grpc_real_channel_full_roundtrip(tmp_path):
    """Tessa TOP5#2：in-process 真 gRPC 通道——create_server 启动 +
    insecure_channel stub + Ping/Detect/FetchRegion 流式/Release 全链路。"""
    import time

    from serving.proto import autovisionagent_pb2 as pb
    from serving.proto import autovisionagent_pb2_grpc as pb_grpc
    from serving.server import create_server

    port = 50971  # 高位避撞
    server = create_server(
        "127.0.0.1", port, dispatcher=_FakeDispatcher(),
        shm=None if False else __import__("serving.shared_memory",
                                          fromlist=["SharedMemoryManager"]
                                          ).SharedMemoryManager(
            base_dir=str(tmp_path / "shm")),
    )
    server.start()
    try:
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        stub = pb_grpc.AutoVisionAgentServiceStub(channel)

        # Ping
        pong = stub.Ping(pb.PingRequest(), timeout=10)
        assert pong.dispatcher_ready

        # Detect（真通道：图像经 image_bytes 进，结果 mask 经内联回）
        import cv2

        ok, buf = cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))
        resp = stub.Detect(
            pb.DetectRequest(task="det", image_bytes=buf.tobytes()), timeout=30
        )
        assert resp.success

        # FetchRegion（外部管理器写区域 → 服务端流式取回；读路径不要求
        # 区域在服务端注册表——白名单内 ava_*.bin 即可读）
        shm_mgr = __import__("serving.shared_memory",
                             fromlist=["SharedMemoryManager"]
                             ).SharedMemoryManager(base_dir=str(tmp_path / "shm"))
        data = bytes(range(256)) * 8  # 2 KiB
        h = shm_mgr.write_bytes(data, dtype="uint8", shape=(len(data),))
        chunks = []
        for c in stub.FetchRegion(h.to_proto(), timeout=10):
            chunks.append(c.data)
            if c.last:
                break
        assert b"".join(chunks) == data

        # Release（对端创建的区域 → 服务端诚实拒绝 success=False，
        # W17 契约：未命中不得假报成功）；本端自回收
        rel = stub.ReleaseSharedMemory(
            pb.ReleaseSharedMemoryRequest(file_path=h.file_path), timeout=10
        )
        assert rel.success is False, "非本服务创建的区域须诚实拒绝"
        assert shm_mgr.release(h.file_path) is True
        channel.close()
    finally:
        server.stop(grace=0)
        time.sleep(0.2)
