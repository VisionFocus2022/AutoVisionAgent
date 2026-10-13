#!/usr/bin/env python
"""marker 防回潮检查（工程保障团队 2026-10-07 方案 · Tessa 设计，防回潮方案①）。

背景：pytest.ini --strict-markers 只防拼错（未知 marker 报错），防不了漏标。
tests/ 顶层仍有 24/148 文件未打 marker（2026-10-07 实测）；本脚本冻结存量、
只拦新增——新测试文件必须带 pytestmark 或 @pytest.mark.*，否则红。

用法（check-gate.sh 第 [4/5] 段调用，亦可单独跑）：
    python scripts/check_markers.py            # 冻结存量模式（默认）
    python scripts/check_markers.py --strict   # 严格模式：存量也须全标（清偿完成后启用）

规则：tests/ 顶层 test_*.py 任一文件既无 pytestmark = 又无 @pytest.mark.<已注册>，
      且不在下方存量豁免清单（BASELINE_UNMARKED）中 → exit 1。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

# 已注册 marker（与 pytest.ini 保持同口径；uia 目录默认 --ignore，不在扫描范围）
KNOWN_MARKERS = ("unit", "e2e", "integration", "gpu", "uia")

# 存量豁免清单（2026-10-07 实测 24 个未打标文件；清偿一个删一个，只降不升）
BASELINE_UNMARKED: set[str] = {
    "tests/test_batch_tools_atomic.py",
    "tests/test_ci_workflow_file.py",
    "tests/test_ci_workflow_wave18.py",
    "tests/test_conftest_offscreen_fallback.py",
    "tests/test_convert_yoloseg.py",
    "tests/test_engine_sgan.py",
    "tests/test_engine_sseg.py",
    "tests/test_exporter_and_utils.py",
    "tests/test_interfaces_safe_extract.py",
    "tests/test_metrics_supervised.py",
    "tests/test_sam3_adapter.py",
    "tests/test_sam3_finetune_script.py",
    "tests/test_sam_adapter.py",
    "tests/test_sam_auto_entry.py",
    "tests/test_uia_log_evidence.py",
    "tests/test_w19_benchmarks_meta.py",
    "tests/test_w19_device_guard.py",
    "tests/test_w19_lite_dist.py",
    "tests/test_w1_2_train_history.py",
    "tests/test_w1_6_small_data_hyperparams.py",
    "tests/test_w2_2_pr_curve.py",
    "tests/test_w43_region_sam.py",
    "tests/test_w44_sam_candidates.py",
    "tests/test_w45_p3_cleanup.py",
}


def _has_marker(text: str) -> bool:
    if "pytestmark" in text:
        return True
    return any(f"@pytest.mark.{m}" in text for m in KNOWN_MARKERS)


def main() -> int:
    strict = "--strict" in sys.argv
    offenders: list[str] = []
    for f in sorted(TESTS.glob("test_*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _has_marker(text):
            continue
        rel = f.relative_to(ROOT).as_posix()
        if strict or rel not in BASELINE_UNMARKED:
            offenders.append(rel)

    if offenders:
        print(f"[FAIL] {len(offenders)} 个测试文件未打 marker（新增文件必须标注）：")
        for o in offenders:
            print(f"  - {o}")
        print(
            "\n标注方法：import 后加一行  pytestmark = [pytest.mark.unit]"
            "\n（真模型/真训练文件用 e2e；触碰 cuda 的追加 gpu）"
        )
        return 1

    left = len(BASELINE_UNMARKED) if not strict else 0
    print(f"[PASS] marker 检查通过（存量豁免 {left} 个待清偿）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
