#!/usr/bin/env bash
# L1 脚本门禁：.qoder 资产命名合规自检（R00 命名规范）
set -u
fail=0

bad=$(find .qoder/rules -name '*.md' 2>/dev/null | grep -Ev '/R[0-9]{2}-[a-z0-9-]+\.md$')
if [ -n "$bad" ]; then echo "[FAIL] rules 命名违规（应为 R{两位序号}-{域}.md）:"; echo "$bad"; fail=1; fi

bad=$(find .qoder/agents -name '*.md' 2>/dev/null | grep -Ev '/[a-z0-9-]+-agent\.md$')
if [ -n "$bad" ]; then echo "[FAIL] agents 命名违规（应为 {角色}-agent.md）:"; echo "$bad"; fail=1; fi

bad=$(find .qoder/skills -name 'SKILL.md' 2>/dev/null | grep -Ev '/(process|domain|base)/[a-z0-9-]+/SKILL\.md$')
if [ -n "$bad" ]; then echo "[FAIL] skills 分层/命名违规（应为 {process|domain|base}/{动词}-{对象}/SKILL.md）:"; echo "$bad"; fail=1; fi

bad=$(find .qoder/records -name '*.md' 2>/dev/null | grep -Ev '/(biz|sys|reports)/[0-9]{4}-[0-9]{2}/[0-9]{8}_[a-z0-9-]+(_[a-z0-9-]+)*\.md$')
if [ -n "$bad" ]; then echo "[FAIL] records 命名违规（biz/sys/reports 三轨，应为 {YYYYMMDD}_{...}.md，存于 {YYYY-MM}/）:"; echo "$bad"; fail=1; fi

if [ "$fail" -eq 0 ]; then
  echo "[PASS] check-naming: .qoder 资产命名合规（R00）"
else
  exit 1
fi
