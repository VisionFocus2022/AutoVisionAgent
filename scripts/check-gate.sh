#!/usr/bin/env bash
# L0 聚合门禁（R01 §2）：命名规范 + ruff 棘轮 + marker 防回潮 + 主门禁 pytest
# 用法：bash scripts/check-gate.sh
# 解释器参数化（W56·v7 P2-2）：本地默认 .venv，CI/其他机可用
#   PYTHON=python bash scripts/check-gate.sh
# mypy 可选段（AVA_MYPY=1 启用；阶段 1 非阻塞摸底，见 docs/quality-gates.md）：
#   AVA_MYPY=1 bash scripts/check-gate.sh
set -u
cd "$(dirname "$0")/.." || exit 1
PYTHON="${PYTHON:-.venv/Scripts/python.exe}"
fail=0

echo "== [1/5] check-naming（R00 命名规范）=="
bash scripts/check-naming.sh || fail=1

echo "== [2/5] ruff 棘轮（基线 scripts/ruff-baseline.txt，只降不升）=="
# 只数真实违规行（path:line:col: 形态）——ruff 零违规时会打印一行
# "All checks passed!"，用 wc -l 会恒计 1，基线清零后必假红（W54 实证）
cur=$("$PYTHON" -m ruff check . --output-format=concise 2>/dev/null | grep -cE ':[0-9]+:[0-9]+:')
base=$(tr -d '[:space:]' < scripts/ruff-baseline.txt)
if [ "${cur:-999999}" -gt "${base:-0}" ]; then
  echo "[FAIL] ruff 问题数 $cur > 基线 $base —— 新增代码不得加债；清偿存量后请同步降基线"
  fail=1
else
  echo "[PASS] ruff $cur <= 基线 $base（清偿后记得降基线）"
fi

echo "== [3/5] marker 防回潮（新测试文件必须打标，存量豁免见 check_markers.py）=="
"$PYTHON" scripts/check_markers.py || fail=1

echo "== [4/5] 主门禁 pytest（覆盖率 fail-under=92 棘轮，pytest.ini 单一真源）=="
"$PYTHON" -m pytest || fail=1

# mypy 可选段：阶段 1 摸底（AVA_MYPY=1 时非阻塞汇报）；阶段 2 起转阻塞棘轮。
# 复刻 ruff 段计数逻辑：只数真实 "path:line: error:" 行，避免 summary 行假红。
if [ "${AVA_MYPY:-0}" = "1" ]; then
  echo "== [5/5·可选] mypy 存量摸底（非阻塞；阶段 2 起转棘轮阻塞）=="
  if ! "$PYTHON" -m mypy --version >/dev/null 2>&1; then
    # 未装 mypy 时不得数出 0——那会让基线文件记录假零
    echo "[SKIP] mypy 未安装/不可用——不生成计数（建基线请先 pip install mypy）"
  else
    "$PYTHON" -m mypy . --show-error-codes | grep -cE ':[0-9]+: error:' | tee /tmp/mypy_count.txt
    echo "（当前错误数见上；建基线：见 docs/quality-gates.md mypy 三阶段）"
  fi
fi

if [ "$fail" -eq 0 ]; then
  echo "== check-gate: 全部通过 =="
else
  echo "== check-gate: 有红灯，未完成 =="
  exit 1
fi
