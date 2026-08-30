# check-gate.sh ruff 段零基线假红缺陷修复
- 日期: 2026-08-30
- 类型: script
- 执行者: 主对话（W54 规则债务清偿波次，SDW L2 流程）
- 等级: L0

## 变更内容

- W54 清偿 ruff 基线 1153→0 后，聚合门禁三连假红：ruff 段以 `wc -l` 统计
  `--output-format=concise` 输出行数，而 ruff 零违规时输出一行
  `All checks passed!` → 恒计数 1 > 基线 0 → 永远 FAIL
- 修复：改用 `grep -cE ':[0-9]+:[0-9]+:'` 只数真实违规行（path:line:col:
  形态）；棘轮比较逻辑不变（只降不升语义保留）
- 该缺陷在基线 1153 时代不可见（计数的恒是真实违规行），基线清零后才暴露
  ——W54 波次的门禁三段全绿实证即本修复的验证

## 涉及文件

- 修改：`scripts/check-gate.sh`（ruff 段计数逻辑一行 + 注释两行）

## 验证结果

- 修复后 `bash scripts/check-gate.sh` 三段全绿实跑：
  check-naming PASS / ruff 0 ≤ 0 PASS / pytest 1220 passed 5 skipped
  coverage 92.93%（≥92 棘轮），rc=0
