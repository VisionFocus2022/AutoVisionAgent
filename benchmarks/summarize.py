"""W19（v3 第三波 FR-1.2）：汇总 .benchmarks/wave19-raw.json → 基线落档。

产出（docs/benchmarks/）：
- ``baseline-2026-08-18.json``：结构化基线（环境 + 全部记录）；
- ``baseline-2026-08-18.md``：人读 Markdown 表（case/metric/p50/p95/p99/max），
  文件头标注机器/GPU/torch 版本/Python/日期（platform + torch.__version__ 实取）。

独立可运行::

    .venv/Scripts/python.exe benchmarks/summarize.py   # rc=0

AC-1.3：只落档，不进门禁断言。
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 独立运行时找 _common
import _common

OUT_DIR = _common.REPO_ROOT / "docs" / "benchmarks"
BASE_STEM = "baseline-2026-08-18"  # PRD FR-1.2 固定基线日期命名

# 表格列（vram 单值指标仅 max 列有意义，分布列渲染为 —）
_COLS = ["p50", "p95", "p99", "max"]


def load_records() -> list[dict[str, Any]]:
    """读 raw 记录；缺失/空档时返回空表（summarize 仍可独立 rc=0 跑通）。"""
    if not _common.RAW_JSON.exists():
        return []
    try:
        data = json.loads(_common.RAW_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def build_baseline(records: list[dict[str, Any]]) -> dict[str, Any]:
    """组装结构化基线（环境实取于 summarize 时刻，非缓存）。"""
    return {
        "wave": _common.WAVE,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline_date": str(date.today()),
        "env": _common.env_info(),
        "raw_source": str(_common.RAW_JSON.relative_to(_common.REPO_ROOT)),
        "record_count": len(records),
        "records": records,
    }


def _fmt_cell(rec: dict[str, Any], col: str) -> str:
    """渲染单元格：None → —；数值去尾零（g 格式）。"""
    val = rec.get(col)
    if val is None:
        return "—"
    return f"{val:g}"


def _env_line(env: dict[str, str]) -> str:
    gpu = env.get("gpu") or "（无 CUDA）"
    return (
        f"- 机器：{env.get('system', '?')} / {env.get('machine', '?')}"
        f" / {env.get('processor', '?')}\n"
        f"- GPU：{gpu}\n"
        f"- torch：{env.get('torch', '?')}　|　Python：{env.get('python', '?')}\n"
        f"- 基线日期：{date.today()}"
    )


def render_markdown(baseline: dict[str, Any]) -> str:
    """渲染人读基线文档（表：case/metric/p50/p95/p99/max）。"""
    lines = [
        "# W19 性能基线（v3 第三波 FR-1.2 落档）",
        "",
        _env_line(baseline["env"]),
        "",
        "口径：合成权重（`torch.manual_seed(0)`，yaml 直建不联网；cls 为"
        " resnet18(weights=None)）；infer 为 CPU、warmup 2 + 30 轮"
        " `perf_counter` 逐轮计时；vram 为 `reset_peak_memory_stats` →"
        " 10 轮 → `max_memory_allocated`（单值指标，仅 max 列）；"
        " 冷启动为 subprocess 5 轮（`QT_QPA_PLATFORM=offscreen`）。",
        "",
        "声明（AC-1.3）：绝对值机器相关，只落档不进门禁断言。",
        "",
        "| case | metric | p50 | p95 | p99 | max |",
        "|---|---|---|---|---|---|",
    ]
    for rec in baseline["records"]:
        cells = " | ".join(_fmt_cell(rec, col) for col in _COLS)
        lines.append(f"| {rec.get('case', '?')} | {rec.get('metric', '?')} | {cells} |")
    if not baseline["records"]:
        lines.append("| （raw 为空——尚未执行基准） | — | — | — | — | — |")
    lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    """原子写（临时文件 + replace，与仓库 JSON 落盘惯例一致）。"""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main() -> int:
    """入口：读 raw → 写 json/md 基线 → 控制台摘要。"""
    records = load_records()
    baseline = build_baseline(records)
    json_path = OUT_DIR / f"{BASE_STEM}.json"
    md_path = OUT_DIR / f"{BASE_STEM}.md"
    _atomic_write(
        json_path,
        json.dumps(baseline, ensure_ascii=False, indent=2),
    )
    _atomic_write(md_path, render_markdown(baseline))
    print(f"W19 summarize：{len(records)} 条记录 → {json_path.name} / {md_path.name}")
    for rec in records:
        print(
            f"  - {rec.get('case', '?')} [{rec.get('metric', '?')}] "
            f"p50={_fmt_cell(rec, 'p50')} max={_fmt_cell(rec, 'max')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
