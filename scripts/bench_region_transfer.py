"""W19（v3 第三波 FR-2 方向 B）：大区域传输双路径微基准。

对比同一份 >=64 MiB 掩码数组载荷的两种取回路径：

(a) 直读——现 SharedMemoryManager.read_bytes 读回路径（客户端同机
    文件映射，零拷贝通道的消费端形态）；
(b) 流式拉取——真实 gRPC（进程内起临时端口 server + client stub 调
    FetchRegion）按 1 MiB ArrayChunk 收齐。

每路径 >=10 轮（默认 10），输出中位时延（ms）与吞吐（GB/s）。
计时轮只做收齐（非空校验）不逐轮比对——逐字节一致性在每路径全部
轮次结束后以一次额外补读整体校验（防"跑得快是因为读错了"的假基准，
同时不让校验开销混入计时口径）。
结果供 ADR-0002（docs/adr/0002-serving-large-payload-evolution.md）引用。

用法::

    .venv/Scripts/python.exe scripts/bench_region_transfer.py
    .venv/Scripts/python.exe scripts/bench_region_transfer.py --size-mib 128 --rounds 20
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from concurrent import futures
from pathlib import Path

# 以脚本路径自举仓库根到 sys.path（python scripts/bench_region_transfer.py
# 时 sys.path[0] 是 scripts/，直接 import serving 会失败）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import grpc  # noqa: E402
import numpy as np  # noqa: E402

from serving.proto import autovisionagent_pb2_grpc as pb_grpc  # noqa: E402
from serving.server import AutoVisionAgentServicer  # noqa: E402
from serving.shared_memory import SharedMemoryManager  # noqa: E402


class _BenchDispatcher:
    """FetchRegion 不触碰推理路径，占位分发器即可。"""

    loaded_tasks: list[str] = []


def _make_payload(size_mib: float) -> bytes:
    """位置相关的伪随机掩码载荷（避免全零/全同字节的非代表性拷贝路径）。"""
    n = int(size_mib * 1024 * 1024)
    rng = np.random.default_rng(20260819)
    return rng.integers(0, 256, size=n, dtype=np.uint8).tobytes()


def _timed_rounds(action: Callable[[], bytes], rounds: int) -> list[float]:
    """逐轮计时（秒）；每轮返回值由调用方校验。"""
    durations = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        got = action()
        dt = time.perf_counter() - t0
        durations.append(dt)
        if not got:  # pragma: no cover - 防御性：空结果说明流式通道坏了
            raise RuntimeError("取回结果为空")
    return durations


def _bench_direct(mgr: SharedMemoryManager, handle, rounds: int) -> tuple[list[float], bytes]:
    """路径 (a)：现 manager 读回路径（read_bytes，本进程 mmap 切片）。"""
    durations = _timed_rounds(lambda: mgr.read_bytes(handle), rounds)
    return durations, mgr.read_bytes(handle)


def _start_grpc_server(mgr: SharedMemoryManager) -> tuple[grpc.Server, int]:
    """进程内起真实 gRPC server（临时端口 127.0.0.1:0，复用注入的 shm）。"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    pb_grpc.add_AutoVisionAgentServiceServicer_to_server(
        AutoVisionAgentServicer(_BenchDispatcher(), shm=mgr), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    if port == 0:
        raise RuntimeError("临时端口绑定失败")
    server.start()
    return server, port


def _bench_grpc(
    mgr: SharedMemoryManager, handle, rounds: int
) -> tuple[list[float], bytes]:
    """路径 (b)：真实 gRPC FetchRegion 流式收齐（client stub，回环 TCP）。"""
    server, port = _start_grpc_server(mgr)
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb_grpc.AutoVisionAgentServiceStub(channel)

            def _fetch_once() -> bytes:
                chunks = list(stub.FetchRegion(handle.to_proto()))
                return b"".join(c.data for c in chunks)

            grpc.channel_ready_future(channel).result(timeout=10)
            durations = _timed_rounds(_fetch_once, rounds)
            return durations, _fetch_once()
    finally:
        server.stop(grace=0).wait(5)


def _report(name: str, durations: Sequence[float], size_bytes: int) -> dict:
    """输出单路径中位时延与吞吐，返回结构化数字（供 ADR 引用）。"""
    med_s = statistics.median(durations)
    gbps = size_bytes / med_s / 1e9
    print(
        f"[{name}] 轮数={len(durations)} 中位时延={med_s * 1000:.2f} ms "
        f"吞吐={gbps:.3f} GB/s (最小 {min(durations) * 1000:.2f} ms / "
        f"最大 {max(durations) * 1000:.2f} ms)"
    )
    return {
        "rounds": len(durations),
        "median_ms": round(med_s * 1000, 2),
        "min_ms": round(min(durations) * 1000, 2),
        "max_ms": round(max(durations) * 1000, 2),
        "throughput_gbps": round(gbps, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bench_region_transfer",
        description="W19 FR-2 方向 B：共享内存大区域 直读 vs gRPC FetchRegion 微基准",
    )
    parser.add_argument("--size-mib", type=float, default=64.0,
                        help="载荷大小 MiB（默认 64，PRD 下限）")
    parser.add_argument("--rounds", type=int, default=10,
                        help="每路径计时轮数（默认 10，下限 10）")
    args = parser.parse_args(argv)

    rounds = max(10, args.rounds)  # 契约：每路径 >=10 轮
    data = _make_payload(args.size_mib)
    size_bytes = len(data)
    print(f"W19 FR-2 微基准: 载荷 {size_bytes / 1024 / 1024:.1f} MiB, 每路径 {rounds} 轮")

    with tempfile.TemporaryDirectory(prefix="ava_w19_bench_") as tmp:
        mgr = SharedMemoryManager(base_dir=tmp)
        try:
            t0 = time.perf_counter()
            handle = mgr.write_bytes(data, dtype="uint8", shape=(size_bytes,))
            print(f"区域写入: {time.perf_counter() - t0:.2f} s ({handle.file_path})")

            dur_a, got_a = _bench_direct(mgr, handle, rounds)
            dur_b, got_b = _bench_grpc(mgr, handle, rounds)
        finally:
            mgr.cleanup()

    # 逐路径字节一致性（读错了的"快"没有意义）
    assert got_a == data, "直读路径字节不一致"
    assert got_b == data, "gRPC 流式路径字节不一致"
    print("字节一致性: 两路径均与原文逐字节相等")

    r_a = _report("a 直读 read_bytes", dur_a, size_bytes)
    r_b = _report("b gRPC FetchRegion", dur_b, size_bytes)
    ratio = r_b["median_ms"] / r_a["median_ms"]
    print(f"gRPC 流式 / 直读 中位时延比 = {ratio:.1f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
