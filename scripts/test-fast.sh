#!/usr/bin/env bash
# test-fast.sh —— T0/T1 快跑入口（工程保障团队 2026-10-07 方案 · Tessa 设计）
#
# 用法：
#   bash scripts/test-fast.sh                    # 无参：跑 unit 子集
#   bash scripts/test-fast.sh tests/test_xxx.py  # 指定文件/目录
#   bash scripts/test-fast.sh --lf               # 复跑上次失败（缓存驱动）
#
# 关键取舍：统一用 --no-cov 而非 -o addopts= 清空——
#   --no-cov 保留 --ignore=tests/uia（真窗排除）与 --strict-markers；
#   -o addopts= 全清空会在目录级快跑时误收集 tests/uia 真窗测试。
# 保留 cacheprovider（--lf 依赖 .pytest_cache）。
#
# 注意：pytest-randomly 5.0.0 已装且默认乱序生效（免费的顺序依赖检测器）。
#   失败复现：pytest 打印的 --randomly-seed=<N> 原样重跑；或加 -p no:randomly 定位。
set -u
cd "$(dirname "$0")/.." || exit 1
PYTHON="${PYTHON:-.venv/Scripts/python.exe}"

if [ $# -gt 0 ]; then
  exec "$PYTHON" -m pytest --no-cov -q "$@"
else
  exec "$PYTHON" -m pytest --no-cov -q tests -m unit
fi
