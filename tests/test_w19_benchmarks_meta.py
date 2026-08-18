"""W19（v3 第三波 FR-1）：性能基线体系元守卫测试。

门禁语义（AC-1.2 / AC-1.3）：
- 本文件**不测任何绝对性能数字**——时延/显存/冷启动随机器漂移，只落档到
  docs/benchmarks/（summarize.py 生成），绝不进门禁断言。
- 只锁"基线可运行"的结构契约：subprocess 对 benchmarks/ 做 --collect-only，
  rc=0 且收集用例数 ≥6（bench_infer det/cls/seg 三例 + bench_vram 一例 +
  bench_coldstart 两例）——防止 benchmarks/ 目录被误删/改名后静默腐烂。
- 不实际跑基准（CI 友好）：collect-only 只 import 模块层（重依赖 torch/
  ultralytics 均为函数内惰性导入，模块层仅 stdlib + pytest）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# CI 可移植口径（GitHub Actions 首跑实证）：用当前解释器（本地 = 项目 venv
# python，CI = setup-python 装 lock 后的解释器），不硬编码 .venv 路径——
# CI 检出目录无 .venv 会 FileNotFoundError（WinError 2）
_PY = Path(sys.executable)


def test_benchmarks_collect_at_least_6_cases():
    """AC-1.2：pytest benchmarks --collect-only rc=0 且收集 ≥6 用例。"""
    cp = subprocess.run(
        [
            str(_PY), "-m", "pytest",
            "benchmarks",
            "-o", "addopts=",
            "--collect-only", "-q",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=300,
    )
    # Windows 控制台编码不定（cp936/utf-8），按 replace 容错解码仅供诊断输出
    out = (cp.stdout + cp.stderr).decode("utf-8", errors="replace")
    assert cp.returncode == 0, (
        f"benchmarks collect 失败 rc={cp.returncode}（目录缺失/收集错误）:\n{out[-2000:]}"
    )
    m = re.search(r"(\d+) tests? collected", out)
    assert m, f"未能从输出解析收集用例数:\n{out[-500:]}"
    count = int(m.group(1))
    assert count >= 6, (
        f"benchmarks 收集用例不足: {count} < 6（期望 bench_infer 3 + bench_vram 1 "
        f"+ bench_coldstart 2）"
    )
