#!/usr/bin/env bash
# ai-review.sh —— 组装 AI 审查提示词（单人项目的"第二审查者"）
# 来源：工程保障团队 2026-10-07 方案（Cody 设计 §4.4）
#
# 用法：
#   bash scripts/ai-review.sh                # 审 staged（git diff --cached）
#   bash scripts/ai-review.sh HEAD~1         # 审最近一次提交
#   bash scripts/ai-review.sh main..HEAD     # 审范围（与远端对照时）
#
# 触发约定（写入 docs/self-review.md 档 A）：
#   feat/fix 且源码 diff ≥50 行 → 必跑；触碰 gui/worker/模型加载卸载/文件IO/serving → 无论行数必跑
# 只读 git，零网络；产物进 outputs/（已 gitignore）。
set -u
cd "$(dirname "$0")/.." || exit 1
RANGE="${1:---cached}"
mkdir -p outputs
OUT="outputs/ai-review-prompt.md"

DIFF_EXCLUDE=(':!*.lock*' ':!*_pb2*.py' ':!*.md')

{
  echo "# AI 代码审查请求（AutoVisionAgent 2.2.0 · Windows 优先 · PySide6+PyTorch+C# serving）"
  echo
  echo "## 环境硬约束（审查必须代入）"
  cat scripts/ai-review-context.md
  echo
  echo "## 改动意图"
  git log -1 --format=%B 2>/dev/null || echo "(待填：本提交想解决什么问题)"
  echo
  echo "## 变更概览"
  git diff --stat "$RANGE" -- "${DIFF_EXCLUDE[@]}"
  echo
  echo "## 完整 diff"
  git diff --unified=6 "$RANGE" -- "${DIFF_EXCLUDE[@]}"
  echo
  echo "## 审查清单与产出契约"
  cat scripts/ai-review-checklist.md
} > "$OUT"

lines=$(wc -l < "$OUT")
echo "提示词已生成: $OUT ($lines 行) —— >800 行时按文件分批，非测试源码优先"
# Windows Git Bash 顺手进剪贴板（clip 不可用则静默跳过）
cat "$OUT" | clip 2>/dev/null && echo "已复制到剪贴板，可直接粘贴给 AI 会话" || true
