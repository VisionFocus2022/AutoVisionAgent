"""收尾批次测试清债（T#3/T#4/L12/M16，2026-10-05 两轮审查遗留）。

T#3：detection_history.query_from_file——坏行跳过/task 过滤/limit 截尾/
     不存在日期返回空（拉高 79.6% 死区）。
T#4：server.Detect 错误矩阵——prompts 透传、结果序列化失败、FetchRegion
     短读 abort（Tessa 盲区 #4）。
L12：core/path_io 直测 3 例（ASCII 快路径/中文路径内容一致/源缺失上抛），
     摆脱对超分引擎测试的间接覆盖耦合。
H5：Detect threshold=0.0 显式传递（proto optional presence）。
M16：exceptions 三个异常类构造面直测。
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")


# ============================== T#3：query_from_file ============================== #


@pytest.fixture
def history(tmp_path):
    from core.detection_history import DetectionHistory

    # 单例重置（__new__ 缓存 _instance，测试间必须隔离）
    DetectionHistory._instance = None
    hist = DetectionHistory(history_dir=tmp_path / "hist")
    yield hist
    DetectionHistory._instance = None


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(lines) + "\n", encoding="utf-8",
    )


@pytest.mark.unit
def test_query_from_file_filters_and_limit(history, tmp_path):
    """T#3：task 过滤 + limit 截尾 + 坏 JSON 行跳过。"""
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    lines = [
        json.dumps({"task": "det", "score": 0.9}),
        "{corrupt line",  # 坏行必须跳过
        json.dumps({"task": "seg", "score": 0.8}),
        json.dumps({"task": "det", "score": 0.7}),
        json.dumps({"task": "det", "score": 0.6}),
    ]
    _write_jsonl(
        tmp_path / "hist" / f"history_{today}.jsonl", lines
    )

    all_det = history.query_from_file(task="det", limit=100)
    assert len(all_det) == 3, "坏行跳过后 det 共 3 条"

    limited = history.query_from_file(task="det", limit=2)
    assert len(limited) == 2
    # 末尾截取（最新优先语义与 query 一致）
    assert limited[-1]["score"] == 0.6

    seg_only = history.query_from_file(task="seg")
    assert len(seg_only) == 1 and seg_only[0]["score"] == 0.8


@pytest.mark.unit
def test_query_from_file_missing_date_returns_empty(history):
    """T#3：不存在的日期 → 空列表（不抛错）。"""
    assert history.query_from_file(date_str="19990101") == []


# ============================== T#4 + H5：Detect 错误矩阵与 threshold presence ============================== #


class _FakeDispatcher:
    loaded_tasks: list[str] = []

    def __init__(self):
        self.infer_calls: list[dict] = []

    def infer(self, task, image, mode="auto", **kwargs):
        self.infer_calls.append({"task": task, "mode": mode, **kwargs})
        from core.interfaces_supervised import DetectionResult, TaskType

        return DetectionResult(task=TaskType.DET, score=0.9, boxes=[[1, 2, 3, 4]])


@pytest.fixture
def shm(tmp_path):
    from serving.shared_memory import SharedMemoryManager

    return SharedMemoryManager(base_dir=str(tmp_path / "shm"))


@pytest.fixture
def servicer(shm):
    from serving.server import AutoVisionAgentServicer

    return AutoVisionAgentServicer(_FakeDispatcher(), shm=shm)


def _png_bytes(w=8, h=8):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    return buf.tobytes()


@pytest.mark.unit
def test_detect_prompts_forwarded(servicer):
    """T#4：prompts 透传到 dispatcher.infer 的 kwargs（此前零验证）。"""
    from serving.proto import autovisionagent_pb2 as pb

    req = pb.DetectRequest(
        task="det", image_bytes=_png_bytes(),
        prompts=["crack", "hole"],
    )
    resp = servicer.Detect(req, None)
    assert resp.success
    call = servicer._dispatcher.infer_calls[-1]
    assert call["prompts"] == ["crack", "hole"]


@pytest.mark.unit
def test_detect_threshold_zero_explicitly_forwarded(servicer):
    """H5 核心：显式 threshold=0.0 必须透传（presence 语义，不再被吞）。"""
    from serving.proto import autovisionagent_pb2 as pb

    req = pb.DetectRequest(
        task="det", image_bytes=_png_bytes(),
    )
    req.threshold = 0.0  # 显式设置 0
    resp = servicer.Detect(req, None)
    assert resp.success
    call = servicer._dispatcher.infer_calls[-1]
    assert call["threshold"] == 0.0, "显式 0 阈值必须生效（H5）"


@pytest.mark.unit
def test_detect_threshold_unset_not_forwarded(servicer):
    """H5：未设置 threshold → 不进 kwargs（引擎用自身默认）。"""
    from serving.proto import autovisionagent_pb2 as pb

    req = pb.DetectRequest(task="det", image_bytes=_png_bytes())
    resp = servicer.Detect(req, None)
    assert resp.success
    call = servicer._dispatcher.infer_calls[-1]
    assert "threshold" not in call, "未设置时不得传默认值覆盖引擎行为"


@pytest.mark.unit
def test_detect_serialization_failure_returns_error(servicer, shm, monkeypatch):
    """T#4：结果序列化失败 → success=False + error 含'结果序列化失败'。"""
    from serving.proto import autovisionagent_pb2 as pb

    def _boom(result, shm):
        raise RuntimeError("proto encode boom")

    monkeypatch.setattr(
        "serving.server.detection_result_to_proto", _boom
    )
    req = pb.DetectRequest(task="det", image_bytes=_png_bytes())
    resp = servicer.Detect(req, None)

    assert not resp.success
    assert "结果序列化失败" in resp.error


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
def test_fetch_region_truncated_file_aborts(servicer, shm, tmp_path):
    """T#4：文件被截断（length 声称 > 实际）→ NOT_FOUND abort（短块）。"""
    grpc = pytest.importorskip("grpc")
    from serving.proto import autovisionagent_pb2 as pb

    # 在 shm 目录内造一个合法命名但内容被截断的 ava 文件
    short = shm._base_dir / "ava_truncated.bin"
    short.write_bytes(b"ONLY10BYTE")  # 10 字节

    ctx = _AbortCapture()
    req = pb.SharedMemoryHandle(
        file_path=str(short), offset=0, length=1024,  # 声称 1KB
        dtype="uint8",
    )
    with pytest.raises(_Aborted):
        list(servicer.FetchRegion(req, ctx))

    assert ctx.code == grpc.StatusCode.NOT_FOUND
    assert "短块" in ctx.details, "截断细节须可排障"


# ============================== L12：path_io 直测 ============================== #


@pytest.mark.unit
def test_path_io_ascii_fast_path(tmp_path):
    """L12：ASCII 路径快路径——was_copied=False（不触发窄字符拷贝）。"""
    from core.path_io import ascii_path_copy

    src = tmp_path / "plain.pb"
    src.write_bytes(b"ASCII-CONTENT")

    with ascii_path_copy(str(src)) as (path, was_copied):
        assert not was_copied, "ASCII 路径不得走拷贝"
        assert path == str(src)
        with open(path, "rb") as f:
            assert f.read() == b"ASCII-CONTENT"


@pytest.mark.unit
def test_path_io_unicode_path_content_preserved(tmp_path):
    """L12：中文路径——拷贝到 ASCII 临时名后内容逐字节一致，退出即清理。"""
    from core.path_io import ascii_path_copy

    src = tmp_path / "权重文件.pt"
    src.write_bytes(b"\x00\x01\x02BINARY\xff")

    tmp_seen: list[str] = []
    with ascii_path_copy(str(src)) as (path, was_copied):
        assert was_copied, "中文路径必须走拷贝慢路径"
        tmp_seen.append(path)
        with open(path, "rb") as f:
            assert f.read() == b"\x00\x01\x02BINARY\xff", "内容必须逐字节一致"

    # 上下文退出后临时文件已删除
    assert not os.path.exists(tmp_seen[0]), "退出即清理临时文件"


@pytest.mark.unit
def test_path_io_missing_source_raises(tmp_path):
    """L12：源文件不存在 → OSError 上抛（诚实报错不静默）。"""
    from core.path_io import ascii_path_copy

    with pytest.raises(OSError), ascii_path_copy(str(tmp_path / "幽灵不存在.pb")):
        pass


# ============================== M16：exceptions 构造面直测 ============================== #


@pytest.mark.unit
def test_exceptions_construction_and_details():
    """M16：AppError 家族构造与 details 属性直测（此前仅散布于引擎测试）。"""
    from core.exceptions import (
        AnnotationIOError,
        AppError,
        InvalidShapeError,
        ModelExportError,
        SupervisedEngineError,
        UnsupportedTaskError,
    )

    # 基类
    assert str(AppError("boom")) == "boom"
    assert str(AppError()) == "AppError"  # 空消息回退类名

    # SupervisedEngineError 携带 task
    e3 = SupervisedEngineError("load failed", task="det")
    assert e3.details == {"task": "det"}
    assert SupervisedEngineError("x").details == {}

    # UnsupportedTaskError 默认消息 + task 携带
    e2 = UnsupportedTaskError("vlm")
    assert "不支持的任务类型" in str(e2)
    assert e2.task == "vlm"
    assert UnsupportedTaskError().task == ""

    # ModelExportError details 副本语义
    d = {"fmt": "onnx"}
    e4 = ModelExportError("export fail", details=d)
    assert e4.details == d
    assert ModelExportError("x").details == {}

    # AnnotationIOError / InvalidShapeError
    assert AnnotationIOError("bad json", path="a.json").details == {"path": "a.json"}
    assert InvalidShapeError("oob", mode="polygon").details == {"mode": "polygon"}
