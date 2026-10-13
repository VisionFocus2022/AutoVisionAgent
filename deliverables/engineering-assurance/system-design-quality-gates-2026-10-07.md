# 代码审查与测试保障流程搭建报告

**日期**：2026-10-07
**工作流**：工作流 2（系统设计）+ 工作流 1（代码审查）组合
**参与成员**：Archi（架构）/ Cody（代码审查）/ Tessa（测试）/ Rex（SRE），主理人 Zhen 汇编

---

## 📌 TL;DR（执行摘要）

- 整体结论：项目工程化基础扎实（CI 三 job、92% 覆盖率棘轮、ruff 基线 0），缺口集中在「审查无流程、测试无分层入口、mypy 零执行、无本地钩子」。本次以「四层质量门禁」架构补齐全部缺口，**9 个文件已落盘并冒烟验证通过**，不重复造轮子（全部接线既有资产）。
- 严重度分布：本次为流程搭建（无代码缺陷审查对象）；成员方案中识别的设计风险已全部在落盘时消化（ruff 版本未入 lock → local 钩子形态；mixed-line-ending 与缺失 .gitattributes 冲突 → 暂缓启用）。
- 阻塞 / 非阻塞：无阻塞项。2 个待办需要小五哥手动执行（安装 pre-commit、mypy P1 摸底），见行动清单。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（流程已落地，2 项手动激活步骤待执行） |
| 阻塞项数量 | 0 |
| 关键行动项 | 5 条（见下） |
| 建议下一步 | 执行行动清单 #1（pre-commit 安装验证）→ #2（mypy P1 摸底） |

---

## 一、摸底结论（实证）

| 维度 | 已有资产 | 缺口 |
|------|---------|------|
| 静态检查 | ruff 0.16.5（venv）基线=0、check-naming.sh、proto 对账 | ruff/mypy/pre-commit **均未入 requirements.lock.txt**；mypy 已配置零执行 |
| 测试 | 92% 全局门禁 + per-package 地板 + markers 已注册 | 324 文件中 148 个顶层测试文件、**24 个未打标**；快跑口径 README（-o addopts=）与 pytest.ini 注释（--no-cov）自相矛盾；pytest-randomly/timeout/json-report 三插件已装未用 |
| CI | lint/test/dotnet-test 三 job，pip cache 挂 lock 哈希 | 无增量 |
| 审查 | 无（单人直推 master） | 无自审清单、无 AI 审查接入点 |
| 钩子 | 无 | 无 .pre-commit-config.yaml、无 .gitattributes |

**关键事实修正**（成员方案 → 落盘修正）：
1. Cody 草案 ruff 钩子 rev v0.9.6 与 venv 实际 0.16.5 不符且未入 lock → 落盘改为 **local 钩子调 .venv 解释器**（与 Archi ADR-1 决策一致，规避版本双漂移与 Windows Store python 重定向陷阱）。
2. mixed-line-ending 钩子依赖 .gitattributes（不存在）→ **暂缓启用**，列入 backlog；冒烟时 git 的 LF/CRLF 警告佐证此判断。
3. Tessa 实测修正任务书"324 文件"口径：顶层 148 个 test_*.py，24 未标，豁免清单已冻结进 check_markers.py。

## 二、四层门禁架构（Archi）

L1 提交钩子（≤5s，ruff+命名+卫生）→ L2 本地门禁（test-fast/test-changed 快跑 + check-gate 全量 + 自审清单 + AI 快审）→ L3 CI（三 job 保持）→ L4 发版检查单（增第 0 步 AI 深审）。放置判据：耗时 × 修复成本 × 拦截价值，修复成本随发现时机指数上升，左侧能拦的绝不放右侧。

关键决策：ADR-1 pre-commit 框架 + repo:local 钩子（工具版本单一真源 .venv/lock）；ADR-2 mypy 走 CI 全量计数 + 基线棘轮冷启动（P1 摸底 → P2 棘轮收缩 → P3 新文件强制）；ADR-3 单人审查 = 自审清单 + AI 三触发点（push 前/周收官/发版前）；ADR-4 分层入口走 check-gate 体系脚本而非 Makefile（Windows 无 make 摩擦）。

## 三、代码审查流程（Cody）

- **自审清单 25 条**（docs/self-review.md）：档 A 30 秒×8 条（每次提交）+ 档 B 3 分钟×17 条（PySide6/PyTorch/Windows/资源/异常/测试六高风险域），全部锚定项目真实判例（W55 UI 冻结、W58 显存卸载+GBK、W2-4 孤儿控件、W61 i18n 死键等）。
- **.pre-commit-config.yaml**：ruff 仅 check 不 autofix（单人无第二双眼睛，防 --fix 夹带语义性修复）；权重/资产目录显式豁免；mypy 留 manual 钩子占位。
- **mypy 三阶段**：P1 摸底建基线（半天）→ P2 每波一个清偿提交棘轮收缩 → P3 文件清单新文件零容忍。
- **AI 审查三件套**（scripts/ai-review*.sh/md）：触发规则（feat/fix ≥50 行或高风险域必跑）+ 项目硬约束前言 + 七维产出契约（P0-P3+文件:行+证据+改法，禁注水）。

## 四、测试分层（Tessa）

5 档执行矩阵（T0 保存时→T4 发版）；快跑口径统一为 **--no-cov**（保留 uia 排除与 strict-markers，纠正 -o addopts= 会误收集 uia 真窗的缺陷）；marker 防回潮 = check_markers.py 冻结 24 个存量豁免 + 新文件强制打标（check-gate 第 3 段）；增量结论：diff coverage 缓做、变异测试不做、rerunfailures 不装（重试即掩盖）。

## 三份成员产出索引

Archi（架构）、Cody（审查）、Tessa（测试）、Rex（SRE）的完整原始产出已在团队协作中交付主理人，其结论全部消化进以下落盘文件：

| # | 落盘文件 | 内容 | 验证 |
|---|---------|------|------|
| 1 | `.pre-commit-config.yaml` | L1 提交钩子配置 | yaml 语法/钩子口径待 pre-commit install 后全量验证 |
| 2 | `scripts/test-fast.sh` | T0/T1 快跑入口（--no-cov） | ✅ 冒烟 0.20s/4 passed |
| 3 | `scripts/test-changed.sh` | 改动驱动快跑 | ✅ bash -n 通过 |
| 4 | `scripts/check_markers.py` | marker 防回潮（24 存量豁免冻结） | ✅ 运行 PASS |
| 5 | `scripts/ai-review.sh` | AI 审查提示词组装 | ✅ 冒烟输出正确 |
| 6 | `scripts/ai-review-context.md` | 审查硬约束前言 | ✅ 落盘 |
| 7 | `scripts/ai-review-checklist.md` | 七维产出契约 | ✅ 落盘 |
| 8 | `docs/self-review.md` | 自审清单 25 条（两档） | ✅ 落盘 |
| 9 | `docs/quality-gates.md` | 四层门禁总览（含 mypy 三阶段/棘轮 runbook/发版增量） | ✅ 落盘 |
| 10 | `scripts/check-gate.sh`（升级） | 3 段→5 段（+marker 检查 +可选 mypy） | ✅ 前 3 段实测绿 |
| 11 | `pytest.ini`（注释） | 快跑口径统一 --no-cov | ✅ 落盘 |
| 12 | `README.md`（测试/流程节） | 新入口指引 | ✅ 落盘 |
| 13 | `docs/release-checklist.md`（增补） | 第 0 步审查与钩子健康 6 项 | ✅ 落盘 |

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 安装激活 pre-commit：`.venv/Scripts/python.exe -m pip install pre-commit && pre-commit install`，跑 `pre-commit run --all-files` 验证全绿且 0 files modified | 小五哥 | P0 | 下次提交前 |
| 2 | mypy P1 摸底：装 mypy 入 lock → 收紧 pyproject exclude → 跑 `scripts/mypy-stock.txt` → 落 mypy-baseline.txt（半天） | 小五哥 | P1 | 下个 W 波 |
| 3 | 24 个存量未标测试文件补标（P0 先标 _real/_e2e 类）后从 check_markers.py 豁免清单逐个删除 | 小五哥 | P2 | 2-3 个 W 波内 |
| 4 | 将本次 13 个文件变更以 `chore: 工程保障——代码审查与测试保障流程落地（四层门禁+pre-commit+分层快跑+AI 审查接入）` 提交入库 | 小五哥 | P0 | 本次会话后 |
| 5 | backlog：.gitattributes 建立+renormalize → 启用 mixed-line-ending；CI 增量（--durations/--timeout/--json-report）；24 文件 marker P0 批次 | 小五哥 | P3 | 择机 |

---

## ⚠️ 待完善 / 已知局限

- 耗时矩阵中 T0-T4 的耗时为量级估计，未做 baseline 校准（backlog 有此计划：pytest-json-report 供数）。
- pre-commit 尚未实际安装（行动清单 #1），配置文件的托管钩子（pre-commit-hooks v5.0.0）首次运行需联网一次。
- check-gate.sh 第 4 段全量 pytest 未在本次会话完整执行（约 5-15 分钟），前 3 段（命名/ruff/marker）已实测绿。
- mypy P1 尚未执行，基线数字未知；check-gate mypy 段当前为 AVA_MYPY=1 可选非阻塞。

---

## 📚 数据来源 & 成员产出索引

- Archi（系统架构师）：四层门禁架构 + 4 ADR + 接线方案 + 6 风险项 —— 已消化进 docs/quality-gates.md §一/§五
- Cody（代码审查师）：自审清单 25 条 + pre-commit 配置 + mypy 三阶段 + AI 审查四件套 —— 落盘文件 #1/6/7/8 + quality-gates §二/§五
- Tessa（测试专家）：分层矩阵 + marker 事实修正（148/24）+ 已装未用资产 + 增量评估结论 —— 落盘 #2/3/4 + quality-gates §三/§四
- Rex（SRE）：故障模式风险表 + 棘轮 runbook（L1/L2/L3 破线分级）+ 发版检查单增量 + 负担测算（每天 +6~10min）—— 落盘 quality-gates §六/§七/§八
- 实证摸底：pyproject.toml / pytest.ini / ci.yml / check-gate.sh / coverage_floors.py / requirements.lock.txt / .venv pip list / tests glob 实测（2026-10-07）

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
