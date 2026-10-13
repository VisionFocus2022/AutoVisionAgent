#!/usr/bin/env bash
# test-changed.sh —— T1 改动驱动快跑（工程保障团队 2026-10-07 方案 · Tessa 设计）
#
# 取最近一次提交 + 工作区改动涉及的顶层包，跑包名命名的测试文件子集；
# 命中不到（如只改了 scripts/ 或 docs/）则退回 unit 子集，不追求完备。
#
# 用法：bash scripts/test-changed.sh
set -u
cd "$(dirname "$0")/.." || exit 1
PYTHON="${PYTHON:-.venv/Scripts/python.exe}"

files=$( { git diff --name-only HEAD~1 2>/dev/null; git diff --name-only; } | sort -u )
pkgs=$(echo "$files" | grep -oE '^(core|dataset|project|models|labeling|training|inference|evaluation|exporter|industrial_vision_platform|serving|gui)/' | sort -u | cut -d/ -f1)

if [ -z "$pkgs" ]; then
  echo "无包级改动，退回 unit 子集"
  exec bash scripts/test-fast.sh
fi

echo "改动包: $pkgs"
targets=""
for p in $pkgs; do
  # 包名→测试文件名启发式映射：tests/test_<pkg>*.py / tests/test_*<pkg>*.py
  matches=$(ls tests/test_*.py 2>/dev/null | grep -i "$p" || true)
  targets="$targets $matches"
done

if [ -z "$(echo $targets | tr -d ' ')" ]; then
  echo "包名未命中任何测试文件，退回 unit 子集"
  exec bash scripts/test-fast.sh
fi

exec "$PYTHON" -m pytest --no-cov -q $targets
