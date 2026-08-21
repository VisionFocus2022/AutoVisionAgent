# SDW learning 经验文档制 — 任务列表 (L2)

> 关联: prd-sdw-learning-docs.md v1.0（门禁 2 已过，2026-08-21）
> RED 基线（任务前已确认的失败态）：`templates/learning.md` 不存在；experience-feedback.md 无 `工具环境` / `learning/` / `≥5` 阈值；SKILL.md Phase 4.6 无 learning 提及；`evolve/learning/` 目录与 EXP-005 不存在；游离文件仍在 .claude 技能目录；FB-001 仍待确认。

## 任务列表

### Task 1: 新建 learning 模板（双拷贝）
- **步骤**: 1. Write `~/.qoder/skills/structured-dev-workflow/templates/learning.md`（若沙箱拦截→工作区暂存+提权复制，EXP-002 模式） 2. 复制到 `~/.claude/skills/structured-dev-workflow/templates/learning.md` 3. cmp 核对一致
- **涉及文件**: 两拷贝 `templates/learning.md`（新建）
- **验证**: `ls` 两处存在 + `cmp` 退出码 0 + grep 四节结构（§1 运行背景/§2 发现清单/§3 反哺建议草稿/§4 消化记录）→ AC-001

### Task 2: 修订 experience-feedback.md（协议核心）
- **步骤**: 1. §1 分档深度表补 learning 文档 2. §2 分类表追加第 6 类「工具环境」（FB-001 落地） 3. §3 三文件→「三文件 + learning/ 目录」，写分层职责与命名规约 4. §4 新增「learning 未消化 ≥5 综合学习」机制（与 backlog ≥3 并存、计数对象不同） 5. §6 红线补分层职责条 6. 同步双拷贝
- **涉及文件**: 两拷贝 `references/experience-feedback.md`（修改）
- **验证**: grep 命中 `工具环境`、`learning/`、`未消化`（≥5 机制）+ cmp 一致 → AC-002

### Task 3: SKILL.md Phase 4.6 速查同步
- **步骤**: 1. Phase 4.6 沉淀表三行补 learning 文档 2. 分类行 5 类→6 类 3. 反哺段补 ≥5 综合学习一句 4. 同步双拷贝
- **涉及文件**: 两拷贝 `SKILL.md`（修改，限 Phase 4.6 段）
- **验证**: Phase 4.6 段 grep `learning` 命中 ≥1 + cmp 一致 → AC-003

### Task 4: 存量迁移与 FB-001 流转
- **步骤**: 1. 新建 `evolve/learning/learn-20260821-uia-integration.md`（按模板规范化重排原 4 条发现，状态 [未消化]） 2. experience-index.md 追加 EXP-005 行指向该文档 3. 删除游离文件（及空目录） 4. feedback-backlog.md FB-001 状态 → 已反哺(2026-08-21 · experience-feedback.md §2)
- **涉及文件**: `~/.qoder/rules/structured-dev-workflow/evolve/learning/`（新建）、`evolve/experience-index.md`、`evolve/feedback-backlog.md`、删除 `.claude` 技能目录下游离文件
- **验证**: grep `[未消化]` 与四节结构存在于迁移文档；index 有 EXP-005；游离文件 `ls` 不存在；FB-001 标题含 `已反哺` → AC-004/005/006

### Task 5: 集成验证 + 收尾沉淀（强制末位任务）
- **步骤**: 1. 逐条核对 AC-001~007 2. 歧义词 grep 全部新写文件命中=0 3. 按新机制做本次运行收尾沉淀（EXP-006 + learn-20260821-sdw-learning-docs.md） 4. 总检 11 项（代码类标注 N/A） 5. 门禁 3 AskUserQuestion 收尾
- **涉及文件**: `evolve/experience-index.md`、`evolve/learning/learn-20260821-sdw-learning-docs.md`
- **验证**: 全部 AC 通过 + grep 歧义词 = 0 + 沉淀完成（本次 learning 文档即新机制首次实战产物）
- **UIA 回归**: N/A（纯 Markdown 技能资产，无 UI）

---

## 执行约定

- 修复尝试上限 L2 = 3 次；每 3 任务汇报进度；偏差记录见收尾汇报。
- 已知偏差预定记录：双拷贝写入顺序与协议 §5 相反（先改 .claude 已读副本、后复制 .qoder，因 Edit 需先 Read；终态 cmp 一致，意图达成）。
