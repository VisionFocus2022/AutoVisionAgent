---
name: init-pipeline
description: 将六工序流水线入驻到新项目：实探目标项目八领域、交互确认后生成项目层资产（rules/domain skill/门禁脚本/索引），并显性化环境坑。当新项目首次接入流水线时使用，每项目仅跑一次。
---

# init-pipeline：流水线入驻向导

> 原子范围：单个项目入驻；调研结论必须带证据（文件路径/命令输出），禁止无证据断言（R05 §7 证据链）。
> 前提：框架层资产已就位——插件模式：本 skill 基目录 `assets/framework/` 资产包；模板模式：pipeline-template 拷贝。含 agents(6) + rules(R00/R05) + skills(process 2 + base 3) + scripts/check-naming.sh + records 骨架 + templates。

## 阶段一：调研（八领域固定清单，逐项出证据）

| 领域 | 调研对象 | 输出结论 |
|---|---|---|
| 1 模块与依赖 | 构建文件（pom.xml/package.json/go.mod…）、模块结构、依赖方向 | 模块依赖图 + 版本管理方式 |
| 2 编码与错误处理 | 存量代码的错误码/返回包装/日志体系 | 统一返回体与错误码机制（路径#符号） |
| 3 服务分层 | 存量包结构（provider/service/controller/dao…）+ 一条真实调用链 | 分层动线一句话（A→B→C） |
| 4 数据访问 | ORM 配置、数据源配置、存量表访问三件套先例 | 数据源归属规则 + mapper 先例路径 |
| 5 配置与开关 | 配置文件目录、动态配置中间件 | 配置文件清单与修改边界 |
| 6 测试 | 测试目录、runner、分类先例 | 测试位置 + 框架 + 单用例运行命令 |
| 7 构建与发布 | Makefile/CI、打包方式；**必须实跑一次构建** | 构建命令 + 环境坑（JDK/依赖/特殊参数） |
| 8 流程与文档 | git 分支/commit 规范、既有文档体系 | 需沿用的约定清单 |

规则：
1. 每条结论带 `文件路径#符号` 或命令原始输出；项目无先例的领域标注「无先例」，转阶段二由用户拍板，禁止套用其他项目惯例
2. 领域 7 的构建实跑失败本身就是产出：错误原因即「环境坑」候选

## 阶段二：交互确认（AskUserQuestion，≤5 问）

1. 分层动线确认（项目存在多套分层时选主动线）
2. 门禁挂载点：现有构建脚本加 target，还是独立命令
3. domain skill 清单：从项目高频重复操作中勾选（加表/加接口/加错误码/加任务/…）
4. L0 红线拍板：调研给出候选清单（构建失败级/不兼容级），用户确认
5. 环境坑清单确认

## 阶段三：生成项目层资产

| 资产 | 内容 |
|---|---|
| 框架层拷贝 | 将框架层资产包原样拷入目标项目：agents/rules/skills/records → `.qoder/`，check-naming.sh → `scripts/`（插件模式取 `assets/framework/`，模板模式取 pipeline-template 同名目录） |
| `rules/R01~R04` | 按领域 1~7 调研结论撰写（R00/R05 框架层已就位，不动） |
| `skills/domain/*` | 勾选的重复操作各一 skill，动线引用调研到的代码先例 |
| `scripts/check-*.sh` | L0 红线中能脚本化的条目，挂构建门禁（make check 或等价命令） |
| `skill-bank.json` | 按 `templates/skill-bank.json.tmpl` 渲染：登记三层 skill + 角色白名单（entry/orchestrator/执行/评估/门禁/聚合） |
| `AGENTS.md` | 按 `templates/AGENTS.md.tmpl` 渲染：项目速览 + L0 红线 + 资产索引 + 常用命令（含环境坑） |
| `records/{biz,sys,reports}/{YYYY-MM}/` | 目录骨架 |

## 阶段四：环境坑显性化 + 验收

1. 环境坑（JDK 版本/依赖冲突/测试特殊参数等）必须写入 AGENTS.md 常用命令节——团队共享，不留在任何人的个人记忆里
2. 验收三件套：门禁命令实跑绿；首次 sys 记录写入（入驻事件）；建议用一个真实小需求跑 `/feature-dev` 端到端验证

## 自检

- [ ] 八领域调研每条结论带证据，无先例项已标注并经用户拍板
- [ ] 生成资产全部登记：AGENTS.md 索引 + skill-bank.json + sys 记录
- [ ] 门禁命令实跑通过（附命令+输出）
- [ ] 环境坑已显性化入 AGENTS.md
