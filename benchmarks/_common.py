"""W19（v3 第三波 FR-1.1）：基准共用工具（基准侧内部件，不属生产代码）。

职责：
- 逐轮样本手动统计 p50/p95/p99/mean/min/max（pytest-benchmark stats 无 p99，
  PRD FR-1.1 明确要求自算）；
- 环境实取（platform + torch.__version__ + GPU 名）；
- 结果记录原子追加到 ``.benchmarks/wave19-raw.json``（JSON 数组，临时文件 +
  os.replace，与仓库 JSON 落盘惯例一致），供 benchmarks/summarize.py 汇总。

AC-1.3 纪律：本模块与调用方均不携带任何绝对性能断言——数字只落档。
"""
from __future__ import annotations

import json
import os
import platform
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_JSON = REPO_ROOT / ".benchmarks" / "wave19-raw.json"
WAVE = "W19"

# 构建合成权重前固定 torch 种子（FR-1.1：yaml 直建按全局 RNG 抽随机权重，
# 不固定则个别种子 0 检出 flaky；seed=0 与 tests/test_engines_family_deep.py:801
# 实测口径一致——conf=0.0 下稳定 300 框）
TORCH_SEED = 0


def percentile(values: list[float], q: float) -> float:
    """线性插值分位数（与 numpy.percentile 默认法一致，免 numpy 依赖）。"""
    if not values:
        raise ValueError("percentile: 空样本")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def summarize_samples(values: list[float]) -> dict[str, Any]:
    """逐轮样本 → p50/p95/p99/mean/min/max/n（毫秒或秒由调用方语义决定）。"""
    if not values:
        raise ValueError("summarize_samples: 空样本")
    return {
        "n": len(values),
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "p99": round(percentile(values, 0.99), 3),
        "mean": round(sum(values) / len(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def env_info() -> dict[str, str]:
    """环境实取（platform + torch 惰性导入；GPU 名供基线文档头部标注）。"""
    info: dict[str, str] = {
        "system": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
    }
    try:
        import torch

        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
        else:
            info["gpu"] = ""
    except Exception as exc:  # torch 缺失时基准本就无法跑，只作环境留痕
        info["torch"] = f"<unavailable: {exc}>"
        info["gpu"] = ""
    return info


def make_record(
    suite: str,
    case: str,
    metric: str,
    stats: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    """组装一条基准记录（统计字段 + 环境快照 + UTC 时间戳）。"""
    record: dict[str, Any] = {
        "wave": WAVE,
        "suite": suite,
        "case": case,
        "metric": metric,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "env": env_info(),
    }
    record.update(stats)
    record.update(extra)
    return record


def _load_raw_records() -> list[Any]:
    """读 raw JSON；损坏则改名留证并重开（基准数据非门禁资产，不阻断整组）。"""
    if not RAW_JSON.exists():
        return []
    try:
        data = json.loads(RAW_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        corrupt = RAW_JSON.with_suffix(".json.corrupt")
        RAW_JSON.replace(corrupt)
        return []
    if isinstance(data, list):
        return data
    return [data]


def append_record(record: dict[str, Any]) -> None:
    """把一条结果追加进 .benchmarks/wave19-raw.json（原子写防半截文件）。"""
    RAW_JSON.parent.mkdir(parents=True, exist_ok=True)
    records = _load_raw_records()
    records.append(record)
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(RAW_JSON.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, RAW_JSON)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def time_rounds(fn: Callable[[], Any], warmup: int, rounds: int) -> list[float]:
    """warmup N 轮 + rounds 轮 perf_counter 逐轮计时（毫秒，FR-1.1 口径）。"""
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


__all__ = [
    "REPO_ROOT",
    "RAW_JSON",
    "WAVE",
    "TORCH_SEED",
    "percentile",
    "summarize_samples",
    "env_info",
    "make_record",
    "append_record",
    "time_rounds",
]
