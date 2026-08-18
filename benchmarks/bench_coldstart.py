"""W19（v3 第三波 FR-1.1）：模块冷启动时间基准（subprocess 5 轮 p50）。

口径：每组 5 轮 subprocess 计时 ``python -c "import <模块>"``（解释器冷进程，
含 import 链全量 IO），报 p50（FR-1.1）；进程不弹窗——env 钉
``QT_QPA_PLATFORM=offscreen``。gui.main 已人工核读：QApplication/窗口只在
``main()`` 且 ``if __name__ == "__main__"`` 守卫内（gui/main.py 尾部），
import 无 UI 副作用；serving/server.py 仅定义类与函数，import 不起服务。

结果追加写入 .benchmarks/wave19-raw.json，由 benchmarks/summarize.py 落档。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import _common

_ROUNDS = 5
_TIMEOUT_S = 180  # 单轮 import 超时（首含磁盘冷缓存，宽松上限）

# (case 名, import 表达式)——PRD FR-1.1 两组：gui 主入口 + gRPC 服务端
_TARGETS = {
    "coldstart_gui_main": "import gui.main",
    "coldstart_serving_server": "import serving.server",
}


def _timed_import_seconds(module_expr: str) -> float:
    """单轮冷启动计时：offscreen 子进程 import，失败即抛（诚实失败不落假档）。"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"  # 防 PySide6 平台插件弹窗
    t0 = time.perf_counter()
    cp = subprocess.run(
        [sys.executable, "-c", module_expr],
        cwd=str(_common.REPO_ROOT),
        env=env,
        capture_output=True,
        timeout=_TIMEOUT_S,
    )
    elapsed = time.perf_counter() - t0
    if cp.returncode != 0:
        err = (cp.stdout + cp.stderr).decode("utf-8", errors="replace")[-800:]
        raise AssertionError(f"冷启动 import 失败 rc={cp.returncode}:\n{err}")
    return elapsed


def _record_coldstart(case: str, module_expr: str) -> None:
    """5 轮计时（秒）→ p50/p95/p99 落档 + 结构自检。"""
    samples_s = [_timed_import_seconds(module_expr) for _ in range(_ROUNDS)]
    stats = _common.summarize_samples(samples_s)
    _common.append_record(
        _common.make_record(
            "coldstart", case, "coldstart_s", stats,
            rounds=_ROUNDS, module=module_expr,
            env_note="QT_QPA_PLATFORM=offscreen",
        )
    )
    # 结构自检：轮数齐全且分位数单调（相对性质，非绝对性能断言）
    assert stats["n"] == _ROUNDS
    assert stats["p50"] <= stats["p95"] <= stats["p99"]


@pytest.mark.integration
def test_coldstart_import_gui_main():
    """`import gui.main` 冷启动 p50（PySide6 全页面注册链）。"""
    _record_coldstart("coldstart_gui_main", _TARGETS["coldstart_gui_main"])


@pytest.mark.integration
def test_coldstart_import_serving_server():
    """`import serving.server` 冷启动 p50（gRPC + proto + shm 链）。"""
    _record_coldstart(
        "coldstart_serving_server", _TARGETS["coldstart_serving_server"]
    )
