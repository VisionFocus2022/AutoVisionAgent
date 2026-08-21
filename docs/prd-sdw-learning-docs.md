# SDW learning 经验文档制 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-21 | 档位: 🟡 L2 | 确定性: 高（4 项设计未知已由探索门禁裁决） | 影响半径: 大（跨项目元技能资产，管未来所有会话的经验回路；未命中 7 类硬触发器，按协议自身定义「改规则/模板=大改」→ L2 起步） | 可逆性: 双向门（纯 Markdown 资产，可整文件还原）
> 前置：Phase 0 需求探索（精简三栏）已过探索门禁（2026-08-21，4 问全裁决）。

## 1. 背景与目标

- **背景**：SDW 已有 evolve/ 沉淀机制（一行 EXP + lessons-learned 详情 + backlog ≥3 攒批反哺），但实际使用出现偏差：2026-08-21 一份完整经验文档（uia-integration，4 条发现）游离在 `.claude` 技能目录 `evolve/` 下，未落协议位置、未入索引——证明一行 EXP 承载不了完整发现。用户显式要求：新发现 → learning 模板经验文档 → 攒量 → 学习反哺优化技能。
- **目标**：
  1. 新发现按统一模板沉淀为完整 learning 文档，集中存放于 `evolve/learning/`，与现有 EXP 行 / lessons-learned 分层不打架
  2. 未消化 learning 文档 ≥5 时，收尾门禁出示「综合学习 + 反哺提案」，消化后文档有终态标记
  3. 存量偏差清零：游离文档迁移规范化 + FB-001 裁决落地

## 2. 功能需求 (FR)

- **FR-001**: learning 模板 — 新建 `templates/learning.md`（双拷贝）。结构：元信息（日期/项目/档位/关联 EXP-NNN/状态）→ §1 运行背景 → §2 发现清单（每条：现象→根因→处置→可复用判断）→ §3 反哺建议草稿（按 6 分类标注小改/大改）→ 消化状态 `[未消化]` / `[已消化 日期+去向]`。 | P0
- **FR-002**: 沉淀路径扩展 — 修订 experience-feedback.md §1/§3：有新发现的运行（L1 偏差时 / L2 / L3），在现有「index 一行 EXP + lessons-learned 跨项目教训」之外，同步写一份完整 learning 文档到 `evolve/learning/learn-YYYYMMDD-{slug}.md`（AI 自动，无需门禁）。分层职责写明：learning=原始素材层（可含项目细节），lessons-learned=提炼层（剥离细节的跨项目模式，仅综合学习时更新）。 | P0
- **FR-003**: ≥5 阈值综合学习反哺 — experience-feedback.md 新增机制：收尾沉淀检查时统计 learning/ 下 `[未消化]` 文档数，**≥5** → 该次收尾门禁出示综合学习与反哺提案（提炼跨文档模式 → 更新 lessons-learned / 生成 FB → 用户裁决 → 反哺写入 → 参与消化的文档标 `[已消化 日期+去向]`）。搭载现有收尾门禁，不新增独立门禁。 | P0
- **FR-004**: 分类法第 6 类 — experience-feedback.md §2 分类表追加 `工具环境` 类（沙箱限制/终端特性/平台差异类发现），默认反哺路径 = lessons-learned 或协议修订。（FB-001 采纳落地） | P1
- **FR-005**: 存量迁移 — 游离文件 `.claude/skills/structured-dev-workflow/evolve/exp-20260821-uia-integration.md` 迁移至 `~/.qoder/rules/structured-dev-workflow/evolve/learning/learn-20260821-uia-integration.md`（按模板结构规范化重排，状态 `[未消化]`），experience-index.md 补 EXP-005 行指向；原游离文件删除。 | P0
- **FR-006**: SKILL.md Phase 4.6 速查同步 — Phase 4.6 段落补 learning 文档机制（模板路径 + ≥5 阈值）一句，保持速查与协议一致。 | P1
- **FR-007**: 双拷贝同步 — 所有改动先写 `.qoder` SoT，再整文件复制 `.claude` 同名路径，核对大小一致（协议 §5 既有约定）。 | P0

## 3. 验收标准 (AC)

- **AC-001**: 给定两个技能目录，`templates/learning.md` 均存在且逐字节一致（diff 为空）[FR-001, FR-007]
- **AC-002**: 给定更新后的 experience-feedback.md（两拷贝一致），grep 分别命中 `工具环境`（§2 六分类）、`learning/`（§3 evolve/ 清单含目录与 `learn-YYYYMMDD-{slug}` 命名规约）、`≥5` 或 `未消化`（阈值机制）[FR-002, FR-003, FR-004]
- **AC-003**: 给定 SKILL.md（两拷贝一致），Phase 4.6 段落 grep `learning` 命中 ≥1 行 [FR-006]
- **AC-004**: 给定 `evolve/learning/`，存在 `learn-20260821-uia-integration.md`，含 `[未消化]` 标记与模板节结构；experience-index.md 存在 EXP-005 行且指向该文档 [FR-005]
- **AC-005**: 原游离文件 `C:\Users\888\.claude\skills\structured-dev-workflow\evolve\exp-20260821-uia-integration.md` 已不存在 [FR-005]
- **AC-006**: feedback-backlog.md 中 FB-001 状态流转为 `已反哺(2026-08-21 · experience-feedback.md §2)` [FR-004]
- **AC-007**: 新写/改写文件无歧义词：`grep -inE "快速|友好|高效|灵活|强大"` 命中 = 0

## 4. 范围

- ✅ **In Scope**: `templates/learning.md`（新建）；`references/experience-feedback.md`（§1/§2/§3/§4 修订）；`SKILL.md`（Phase 4.6 速查句）；`evolve/learning/` 目录与迁移文档；`experience-index.md`（EXP-005）；`feedback-backlog.md`（FB-001 状态流转）
- ❌ **Out of Scope**: 不改 `~/.claude/skills/` 其他技能；不改 ai-coding-loop / loop-review-fix；三件套既有结构（index 表列 / lessons-learned 格式）不动；不写自动化阈值脚本（收尾时 AI 读目录计数）；不迁移 ai-coding-loop 经验库

## 5. 风险与假设（含需求探索三栏）

- **已知（确证事实）**: 现有机制全貌与存量（4 EXP / 3 lessons / 1 FB-001）；用户 4 项裁决 = 叠加式整合（现有三件套保留）+ 未消化 ≥5 + `evolve/learning/` + 迁移与 FB-001 采纳；经验库在工作区外（`~/.qoder/`），Write 工具受沙箱限制（EXP-002 两阶段写入模式可解）
- **假设（待验证）**: learning 文档与 EXP 行一一对应（一次运行一份，EXP 行指向文档）——若未来发现粒度不合适，再调规约；`[未消化]` 状态以文档内标记为准，无外部状态文件
- **未知**: 无残留（探索门禁 4/4 已裁决）
- **风险**: ① 双轨重复（learning 原始层 vs lessons-learned 提炼层职责混淆）→ 协议明文写分层职责，lessons-learned 仅在综合学习时更新；② 沙箱写入失败 → 暂存区编辑 + 提权 Bash 二进制复制；③ 双拷贝漂移 → 每文件写后核对大小一致

## 6. 实现思路

- **拟采用**: 纯 Markdown 资产改动，5 任务顺序执行：新建模板 → 修订协议 → SKILL.md 速查句 → 存量迁移 → 集成验证。全部 `.qoder` 先写、`.claude` 复制覆盖。
- **复用**: evolve/ 三件套现有结构与编号规约；FB-001 既定建议原文；EXP-002 两阶段写入模式
- **注意**: 迁移文档要按模板**规范化重排**（补状态标记与节结构），不是原样搬运；`≥5` 阈值与既有 backlog `≥3` 阈值并存但计数对象不同（learning 文档数 vs backlog 条数），协议中须写清避免混淆

---

## 自检（5 项，提交前核对）

- [x] **完整性**〔流程事件〕: 每条需求有 FR 编号（FR-001~007）
- [x] **无歧义**〔可执行判定〕: `grep -iE "快速|友好|高效|灵活|强大"` 本文件命中 = 0
- [x] **可追溯**〔流程事件〕: 每个 FR 有对应 AC（FR-001→AC-001 … FR-007→AC-001/002）
- [x] **范围清晰**〔流程事件〕: In / Out Scope 已列
- [x] **指标可量化**〔可执行判定〕: AC 全部有命令或明确预期

## ✅ 门禁（3 项）

- [x] 门禁 1 探索门禁：AskUserQuestion 4 问已裁决（2026-08-21）
- [x] 门禁 2 PRD：AskUserQuestion 确认本 PRD → 进入执行（2026-08-21 用户确认「进入执行」）
- [x] 门禁 3 收尾：AC-001~007 全过 + 总检完成（2 项例外申报）+ 沉淀完成（EXP-006 + learning 文档）（2026-08-21 用户确认收尾并批准 commit docs）
