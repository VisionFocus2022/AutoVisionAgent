---
trigger: model_decision
description: 工程资产统一命名规约。新建/重命名任何规则、agent、skill、command、记录、脚本文件前必须先查阅本规则
---

# R00 命名规范

> 等级：L1 硬约束
> 适用范围：工程约束体系（.qoder/ 下）所有文件与 records 操作记录
> 唯一例外：Java 代码命名不在本规则范围，遵循阿里 Java 开发规约（见 alibaba-java-coding-guidelines-skill）

## 1. 通用原则

1. 文件名一律英文 kebab-case，中文只出现在文件内容中
2. 名字即定义：前缀区分资产类型，主体描述对象，见名知类
3. 日期不进入普通文件名；仅 records 以发起日期作前缀（固定不变，不随内容更新而改）
4. 同目录内名字唯一；重命名必须同步更新 AGENTS.md 索引、skill-bank.json（唯一事实源）
5. 名字表达"是什么"，不表达"版本/状态"（禁止 `-v2`、`-new`、`-final`、`-bak` 后缀）

## 2. 各类资产命名格式

| 资产 | 格式 | 示例 | 说明 |
|---|---|---|---|
| 规则 | `R{两位序号}-{域}.md` | `R01-module-build.md` | 序号按开发动线排序；R00 固定为基础规约 |
| Agent | `{角色}-agent.md` | `reviewer-agent.md` | 角色名即职责，一 agent 一事 |
| Skill | `{层}/{动词}-{对象}/SKILL.md` | `domain/add-hsf-api/SKILL.md` | 层 ∈ process（流程规约）/domain（领域知识）/base（通用能力），不跨层耦合；目录名即 skill 名；一 skill 一原子操作 |
| Command | 编排型 skill：`process/{动词}-{对象}/SKILL.md` | `process/feature-dev/SKILL.md` | Qoder 原生 slash 调用 `/feature-dev`；只做编排不含细节（不建独立 commands 目录，偏离原因见 sys 记录 20260818_skill_agents-skills-command-setup） |
| biz 记录 | `{YYYYMMDD}_{需求名}.md` | `20260815_price-autofill.md` | 日期=需求发起日；存于 `records/biz/{YYYY-MM}/` |
| sys 记录 | `{YYYYMMDD}_{类型}_{主题}.md` | `20260818_rule_naming-convention.md` | 类型 ∈ rule/agent/skill/command/script/doc；存于 `records/sys/{YYYY-MM}/` |
| 技术报告 | `{YYYYMMDD}_{需求名}.md` | `20260819_product-agreement-admin.md` | 与 biz 记录同名同月；存于 `records/reports/{YYYY-MM}/`；已发布需求一份，用于技术方案分享 |
| 校验脚本 | `check-{对象}.sh` | `check-pom-no-version.sh` | 统一 `check-` 前缀，存于 `scripts/` |

## 3. 字符规则

1. 允许字符：小写 `a-z`、数字、连字符 `-`；records 额外允许下划线 `_` 作字段分隔符
2. 禁止：空格、大写字母、中文、其他特殊字符
3. 缩写仅限通用缩写（api / db / config / doc / dep），不得自创新缩写
4. 文件名长度建议 ≤ 40 字符，主题词控制在 3 个以内

## 4. 违反处理

- 偏离本规范必须在当次 sys 记录中书面说明原因
- reviewer-agent 检查时将命名符合性列为 L1 检查项
