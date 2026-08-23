# v6 深度审查 — 任务列表 (L2)

> 关联: prd-w37-v6-deep-review.md v1.0（门禁 2 已过，2026-08-23）
> RED 基线：v6 报告不存在；增量审查条目=0；v5 四条 P2 核销结论=无；五视角产出=无。

## 任务列表

### Task 1: 主线增量深审（codegraph + diff 逐文件）
- **步骤**: 1. 读 `ea1013b..HEAD` 全部生产/脚本 diff 2. codegraph 追四条关键链（action 门控注册→消费 / i18n 回退 / session 生命周期 / batch_prelabel imagePath 流）3. 逐文件记审查笔记（定位/疑点/证据）
- **涉及文件**: 只读 core/session.py、gui/core/{i18n,permissions}.py、gui/main.py、gui/pages/*、scripts/make_lite_dist.py 等
- **验证**: 增量文件清单全覆盖（对照 `git diff --name-only`）→ AC-001 主线部分

### Task 2: 五视角并行 agent 横切（Wave A×4 + Wave B×1）
- **步骤**: 1. Wave A 并行 4 agent：code-reviewer（资深工程·增量）/ security-reviewer（全仓安全·门控与路径重点）/ Explore（一致性·i18n+分层+页面规模）/ Explore（冗余·死代码+重复+孤儿）2. 汇总候选发现 3. Wave B：Explore 事实核查 agent 复核全部 P0/P1 候选（file:line 对照 HEAD）
- **涉及文件**: 只读全仓
- **验证**: 5 视角各有产出或显式无发现；P0/P1 双源一致 → AC-002

### Task 3: v5 核销 + 异常核实
- **步骤**: 1. v5 §4 四条 P2 清偿宣称逐条验证（证据命令实测）2. `705f1ee` 历史折叠异常核实（git log 查 SDW 文档落点）3. v5 覆盖矩阵抽查仍成立性
- **涉及文件**: 只读 + 实测命令
- **验证**: 四条各含结论（闭环/部分/证伪）+ 证据 → AC-003

### Task 4: 攻方复核 + 实测证据
- **步骤**: 1. 对每条 P0/P1 自我反驳一轮（「这个发现会不会是误读/已被别处处理/测试已守护」）2. 实测：pytest 收集与关键套件（w35 双测 / w36 / i18n 完整性）、grep 计数（中文残留/密钥/TODO）
- **涉及文件**: 只读 + 运行测试
- **验证**: 证据命令输出留档进报告 → AC-006

### Task 5: v6 报告落盘 + 收尾（强制末位任务）
- **步骤**: 1. 写 docs/AutoVisionAgent-架构解析与优化方案-v6.md（v5 体例）2. AC-001~007 逐条核对 3. 门禁 3 AskUserQuestion 4. 沉淀 EXP + learning 文档 5. git status 只读守恒确认
- **验证**: 全 AC 过 + 报告五元组完备 + 只读零变更 → AC-004/005/007

## 执行约定

- 修复尝试上限 3 次；每 3 任务汇报；agent 全程只读。
- 风险预案：若审查中 `git status` 出现他方在途改动 → 暂停复核（EXP-202608-23d 处置模式）。
