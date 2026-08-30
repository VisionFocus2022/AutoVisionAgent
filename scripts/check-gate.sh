#!/usr/bin/env bash
# L0 聚合门禁（R01 §2）：命名规范 + ruff 棘轮 + 主门禁 pytest
# 用法：bash scripts/check-gate.sh
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0

echo "== [1/3] check-naming（R00 命名规范）=="
bash scripts/check-naming.sh || fail=1

echo "== [2/3] ruff 棘轮（基线 scripts/ruff-baseline.txt，只降不升）=="
# 只数真实违规行（path:line:col: 形态）——ruff 零违规时会打印一行
# "All checks passed!"，用 wc -l 会恒计 1，基线清零后必假红（W54 实证）
cur=$(.venv/Scripts/python.exe -m ruff check . --output-format=concise 2>/dev/null | grep -cE ':[0-9]+:[0-9]+:')
base=$(tr -d '[:space:]' < scripts/ruff-baseline.txt)
if [ "${cur:-999999}" -gt "${base:-0}" ]; then
  echo "[FAIL] ruff 问题数 $cur > 基线 $base —— 新增代码不得加债；清偿存量后请同步降基线"
  fail=1
else
  echo "[PASS] ruff $cur <= 基线 $base（清偿后记得降基线）"
fi

echo "== [3/3] 主门禁 pytest（覆盖率 fail-under=92 棘轮，pytest.ini 单一真源）=="
.venv/Scripts/python.exe -m pytest || fail=1

if [ "$fail" -eq 0 ]; then
  echo "== check-gate: 全部通过 =="
else
  echo "== check-gate: 有红灯，未完成 =="
  exit 1
fi
