# AGENTS.md — AutoVisionAgent 工程约束总纲

> 模板版本：pipeline-v1.0 | 入驻日期：2026-08-30
> 本文件是唯一常驻入口：只放 L0 红线与资产索引，细则一律按索引跳转加载，禁止在本文件堆积细节。

## 1. 项目速览

- 工业视觉智能平台（AutoVisionAgent 2.1.0）：数据/标注管理、模型训练、评估、推理与部署，PySide6 桌面 GUI + PyTorch 后端；12 顶层包（gui / labeling / training / inference / exporter / evaluation / core / serving / industrial_vision_platform / models / dataset / project）
- 技术底座：Python 3.10+ · PySide6 · PyTorch(cu121, requirements.lock.txt 钉死) · pytest+coverage · ruff · PyInstaller · gRPC+共享内存对接 .NET（serving/dotnet_client）
- 分层动线：`gui/pages → 领域包(labeling/training/inference/…) → core(异常/配置/IO/审计)`；serving 独立对外层
- 事实性背景知识查 knowledge cards，本体系只管"允许/禁止/怎么做"

## 2. L0 红线（违反即事故/构建失败，任何操作前必须自查）

1. **主门禁绿**：`.venv/Scripts/python.exe -m pytest` rc=0（覆盖率 ≥92 棘轮，pytest.ini 单一真源）——聚合入口 `bash scripts/check-gate.sh`
2. **命名规范**：`bash scripts/check-naming.sh`（.qoder 资产 R00 命名合规）
3. **ruff 棘轮**：问题数 ≤ `scripts/ruff-baseline.txt`（2026-08-30 基线 1153；只降不升，清偿后降基线）
4. **规模/打包守卫沿用**：page.py ≤800 行、lite 产物 <2GiB、i18n zh/en 键集配对——既有守卫测试随主门禁生效，守卫红=修复不是绕过

## 3. 资产索引（新增资产必须在此登记，唯一事实源）

| 资产 | 路径 | 状态 | 触发方式 |
|---|---|---|---|
| R00 命名规范 | `.qoder/rules/R00-naming.md` | ✅ | 新建/重命名文件前必查 |
| R01 模块与构建发布 | `.qoder/rules/R01-module-build.md` | ✅ | 改依赖/spec/CI/打包脚本时 |
| R02 编码与错误处理 | `.qoder/rules/R02-coding-error.md` | ✅ | 写异常/日志/审计/i18n 时 |
| R03 分层数据配置 | `.qoder/rules/R03-layer-data-config.md` | ✅ | 加页面/模式/引擎、动配置时 |
| R04 测试工作流 | `.qoder/rules/R04-test-workflow.md` | ✅ | 写测试/提交/发版/写 PRD 时 |
| R05 流水线与 Eval | `.qoder/rules/R05-pipeline-eval.md` | ✅ | 执行流水线、质检判定、四态决策 |
| skill-bank.json | `.qoder/skill-bank.json` | ✅ | 三层清单+角色白名单 |
| agents（6 角色） | `.qoder/agents/` | ✅ | 执行/评估/门禁/聚合 |
| skills 三层 | `.qoder/skills/{process,domain,base}/` | ✅ | process: feature-dev, init-pipeline；domain: add-annotation-mode, add-inference-engine, add-gui-page, run-eval-experiment；base: sync-biz-record, sync-sys-record, archive-tech-report |
| 操作记录 | `.qoder/records/{biz,sys,reports}/` | ✅ | 按月分层，文件名含日期 |
| 脚本门禁 | `scripts/check-gate.sh`（聚合）+ `scripts/check-naming.sh` | ✅ | 提交前必跑聚合门禁 |

## 4. 约束等级定义

| 等级 | 含义 | 处置 |
|---|---|---|
| L0 红线 | 违反=事故/构建失败/不兼容 | 本文件常驻 + 脚本校验 |
| L1 硬约束 | 违反=架构腐化/返工 | 各 rules 文件，按触发条件加载 |
| L2 推荐 | 首选模式，偏离需在记录中说明理由 | 各 rules 文件 |
| L3 参考 | 背景知识/通用规约 | knowledge cards 等 |

## 5. 常用命令（含环境坑）

| 命令 | 用途 |
|---|---|
| `bash scripts/check-gate.sh` | L0 聚合门禁（命名+ruff 棘轮+pytest），提交前必跑 |
| `.venv/Scripts/python.exe -m pytest` | 主门禁（1216 用例 ~2min，覆盖率 92） |
| `.venv/Scripts/python.exe -m pytest tests/test_x.py -o addopts= -q` | 单测快跑（清覆盖率参数） |
| `.venv/Scripts/python.exe -m pytest tests/uia -o addopts=` | UIA 真窗（需桌面会话+打包 exe，默认排除） |
| `.venv/Scripts/python.exe -m gui.main` | 桌面应用启动 |
| `.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm` | 打包 exe（发版走 docs/release-checklist.md） |
| `dotnet test serving/dotnet_client` | C# 共享库测试（CI 并行 job 同款） |
| 环境坑① | 中文路径 venv：pip/PyInstaller 一律 `.venv/Scripts/python.exe -m` 调用，禁裸命令 |
| 环境坑② | PyTorch cu121：lock 首行已含索引；CI 下载 ~2.5GB，缓存键挂 requirements.lock.txt |
| 环境坑③ | ruff 于 2026-08-30 首次安装（此前 pyproject 有配置、venv 无模块）；存量 1153 问题走棘轮基线 |
| 环境坑④ | 管道 `| tail` 会吞退出码——判绿用 `echo ${PIPESTATUS[0]}` 或无管道复跑 |
| 环境坑⑤ | 双远端 gitee+github：github 443 间歇阻断时先落 gitee 留档追平 |
| 环境坑⑥ | GPU 训练/重推理前查大内存 python 残留进程（IDE 代理僵尸 pytest 会耗尽提交内存） |

## 6. 工作流约定（最小集）

1. 需求开发：统一走 `/feature-dev` 六工序流水线（R05），入口只驱动不设计
2. 体系变更：写 `.qoder/records/sys/{YYYY-MM}/{YYYYMMDD}_{类型}_{主题}.md`，并同步更新本文件索引表
3. 命名一律先查 `R00-naming.md`；约束细节查对应 R 文件，不在本文件展开
4. 提交前必跑门禁命令（不通过 = 未完成）
