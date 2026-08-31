# 架构审查 2026-08-24 补救落地（AVA-R1..R7）— 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-31 | 档位: 🟡 L2 | 确定性: 高（上游 remediation-plan.md 已书面给定动作与验收）| 影响半径: 大（打包链 / 门禁棘轮 / CI / 远端推送；未命中 7 类硬触发器，git push 为外发动作须用户显式批准）| 可逆性: 双向门（git 可回滚、产物可重建）
>
> **定档声明**：确定性高 × 影响半径大 → 🟡 L2；规模×可逆性粗估（中 × 双向门）同判 L2，无冲突。
> **门禁降级记录**（AskUserQuestion 不可用 · 自治会话）：探索门禁 = S1 用户显式指令（`/structured-dev-workflow 根据路径的文档制定修复计划`）；方案方向 = S2 锁定上游 `remediation-plan.md` 书面推荐（P1-1..P3-3 含验收标准）；自主决策 = S3 留痕于本文档各「S3 留痕」标记处。**不降级项**：git commit / git push（执行铁律 7）在执行期仍须用户显式批准。
> **上游输入**：`architecture-review.md`（AVA-R1..R7，2026-08-24）· `remediation-plan.md` · `quality-scenarios.md` · `risk-map.dot`（同目录）。
> **现状差分**（2026-08-31 实测）：P1-1 的 spec 机械防呆**已有人写好但未提交**（`autovisionagent.spec` L12-38 双断言 + `R01-module-build.md` 登记 +2 行，均为工作区未提交改动）；其余 6 项全部仍开放（分支领先双远端各 8 提交、`dist-lite/` 不存在、spec L48-51 仍条件打包 `configs/user_settings.json` 且该文件现存）。

## 1. 背景与目标

- **背景**：2026-08-24 架构审查结论——进程内工程质量扎实（1222 用例全绿 / 覆盖 92.87%），但**交付链路系统性薄弱**：打包环境无防呆（已实际产出过 3.5MB 残废 exe）、门禁证据单机孤岛（8 提交未推、CI 从未在本分支跑）、双产物断链（lite 缺失而守卫静默 skip）、体积与覆盖率棘轮无余量。审查同时给出了带验收标准的补救计划（remediation-plan.md），本 PRD 将其转为可执行需求。
- **目标**（3 条以内）：
  1. **交付链止血**：打包防呆收尾验收 + 推送双远端并取得 CI 首跑记录（消灭单机孤岛）。
  2. **守卫补强**：dist-lite 重建且棘轮真实生效、完整 dist 体积棘轮建立、覆盖率缓冲恢复 ≥1.5pt。
  3. **清账闭环**：审查 §4 未知项全部回填，审查工件（复选框/风险图）按维护注记回填。

## 2. 功能需求 (FR)

- **FR-001**: 打包环境机械防呆收尾（AVA-R1 / P1-1）— spec 双断言已在工作区，完成反测验收、R01 登记核对并提交 | 优先级 P0
- **FR-002**: 远端同步 + CI 首跑验证（AVA-R2 / P1-2）— 推送 feature 分支至双远端，取得 ci.yml 双 job 运行记录；更新 ci.yml 过时注释 | 优先级 P0（**外发动作，执行须用户显式批准**）
- **FR-003**: 重建 dist-lite + 棘轮硬化（AVA-R3 / P2-1）— 以现有 dist 派生 lite（<2GiB），lite 相关 skip 归零，评估守卫语义收窄 | 优先级 P1
- **FR-004**: 覆盖缺口定向补测（AVA-R6 / P2-2）— 聚合 term-missing 定位 668 缺口 top 模块，优先补发布包与 gui 交互路径，恢复缓冲至 ≥93.5% | 优先级 P1
- **FR-005**: 完整 dist 体积棘轮（AVA-R5 / P2-3）— 体积构成分析留档 + 新守卫（dist 存在时 <7GiB，缺失时 skip 同 lite 语义）| 优先级 P1
- **FR-006**: spec 移除 user_settings.json 条件打包（AVA-R7 / P3-2）— 删 spec L48-51 条件 datas，exe 首启默认态走代码路径，守卫产物内无该文件 | 优先级 P2
- **FR-007**: UIA 回归定期化（AVA-R4 / P3-1）— 无自托管 runner 条件下降级为流程登记：发版检查单强制项 + spec/页面结构变更后手动跑并登记执行记录 | 优先级 P2
- **FR-008**: 审查未知项清账 + 工件回填（P3-3）— §4 未知表逐项回填；remediation-plan.md 复选框打勾；risk-map.dot 已消节点灰化（不删除）| 优先级 P2

## 3. 验收标准 (AC)

- **AC-001**: 给定任意非 `.venv` 解释器（系统 python / 其他 venv），当执行 `python -m PyInstaller autovisionagent.spec --noconfirm`，应该在 Analysis 阶段前（<5s）以非 0 退出码失败，输出含 `[BUILD-ABORT]` 与 `.venv` 字样（QS-1 度量）[FR-001]
- **AC-002**: `git show HEAD:.qoder/rules/R01-module-build.md`（提交后）含打包防呆机械登记段——规则→机制闭环 [FR-001]
- **AC-003**: `git branch -r` 含 `gitee/feature/sam3-auto-discovery` 与 `github/feature/sam3-auto-discovery`（或经用户批准的合并 master 路线）[FR-002]
- **AC-004**: GitHub Actions（或 Gitee 流水线）存在本分支 CI 运行记录且红绿可追溯；若红，修复提交与结论留档 [FR-002]
- **AC-005**: ci.yml 头部"本仓当前无 git 远程"过时注释已更新为现状（双远端已接入）[FR-002]
- **AC-006**: `dist-lite/` 存在且 <2GiB（产品字节口径，排 `__pycache__`/*.pyc），`tests/test_w19_lite_dist.py` 棘轮由 skip 转 pass [FR-003]
- **AC-007**: `pytest -rs` 中 lite 相关 skip 归零（其余 skip 逐项归因留档）[FR-003 / FR-008]
- **AC-008**: 主门禁覆盖率 ≥93.5% 且 pytest.ini `--cov-fail-under=92` 不动（棘轮只升不降）[FR-004]
- **AC-009**: 668 缺口分布结论（top 模块与处置：补测 / omit / 删除）留档本目录 [FR-004]
- **AC-010**: 新体积守卫测试入主门禁：`dist/` 存在时断言 <7GiB，缺失时 skip（语义对齐 lite 守卫）[FR-005]
- **AC-011**: dist 体积构成分析（top-20 目录，6.36GiB 增量来源）留档 `docs/benchmarks/` [FR-005]
- **AC-012**: 重打包后产物内无 `configs/user_settings.json`，且守卫测试锁定该断言 [FR-006]
- **AC-013**: exe 首启为主题/语言默认态（配置缺失走 `gui/core/settings_io.py` 代码路径，无残留依赖）[FR-006]
- **AC-014**: 发版检查单含 UIA 真窗回归强制项与执行记录登记栏；RELEASES.md 或检查单注明触发条件（发版 / spec / 页面结构变更后）[FR-007]
- **AC-015**: 审查 §4 未知表 5 项逐项回填；remediation-plan.md 全部复选框打勾；risk-map.dot 已消风险节点改灰色 `fillcolor="#e2e8f0"` 标「已消」[FR-008]

## 4. 范围

- ✅ **In Scope**: spec 防呆验收与提交；推送 + CI 观察；lite 派生重建与守卫硬化；覆盖率定向补测；完整 dist 体积守卫；spec datas 清理；UIA 流程登记；未知项清账与审查工件回填；一次最终重打包 + 冒烟（合并 FR-001 正测与 FR-006 验收）
- ❌ **Out of Scope**: .NET lease/FetchRegion 解冻接线（ADR-0002 冻结状态不动）；自托管 Windows UIA runner 搭建（FR-007 仅流程登记）；dist 瘦身实施（本计划只做构成分析 + 棘轮；若需 v2.1.0 式 PYZ 清场另行立项）；master 合并与发版决策（属用户职权）；v4 旧审查 P3 遗留项（页面文件爬升等，非本次范围）；覆盖率冲 95%+

## 5. 风险与假设（含需求探索三栏）

> D4 三栏账（L2 精简版；D1 快剥结论：remediation-plan 的"必须"均有审查证据支撑，无虚构假设，唯一被剥出的是"计划须覆盖全部 7 项"——属实，7 项均有独立验收，不做裁剪）。

- **已知（确证事实 · 2026-08-31 实测）**：spec L12-38 防呆 + R01 登记 +2 行为**未提交**工作区改动；`feature/sam3-auto-discovery` 领先 gitee/github master 各 8 提交、领先本地 master 5 提交；`dist-lite/` 不存在、`dist/` 存在；spec L48-51 条件打包仍在且 `configs/user_settings.json` 现存；pytest.ini `--cov-fail-under=92`、`--ignore=tests/uia`；ci.yml L2 含"本仓当前无 git 远程"过时注释；lite 守卫 skip 语义见 `tests/test_w19_lite_dist.py:16,347`；RELEASES.md 头部宣称双产物；最近提交记录主门禁 1222 用例双采样绿。
- **假设（待验证 · 不成立则…）**：
  1. 现有 `dist/`（6.36GiB）是正确 `.venv` 产物（审查述 W-2 重建）→ 否则 lite 派生前须先完整重打包，Task 4 前置加打包步骤
  2. 未提交 spec 改动不进主门禁分母（spec 非 --cov 包）→ 否则 T1 基线即红，先提交基线再动工
  3. lite 派生脚本与 6.36GiB dist 兼容（`6124e01` 刚维护过 logs/ 豁免）→ **不成立的风险最实质**：W26 时点 lite 余量仅 17.5MiB，源 dist 增大后 lite 可能超 2GiB——届时启动 spec 已写明的 matplotlib Agg 杠杆，仍不够则体积治理单独立卡（升 L3），不阻塞其余任务
  4. CI 首跑可直接绿（上次 CI 绿为 08-19 d2018ab）→ 否则按 remediation P1-2 原文"这正是 CI 存在的意义"，修复留档后复跑
- **未知（由任务内取证消解，不阻塞计划）**：5 个 skip 具体构成（T1 `-rs`）；668 缺口语句分布（T1 term-missing 聚合）；CI 是否曾在任一提交绿（T3 回填）；6.36GiB 增量来源（T6 分析）；.NET 客户端生产使用状态（T9 问询用户留档——唯一需用户输入项）
- **风险**: ①lite 超线（假设 3，应对如上）；②推送网络（GitHub HTTPS 全断，走已配 SSH-over-443；Gitee 正常，可先推 Gitee）；③UIA 冒烟对机器负载敏感（需空闲时段跑，复跑即绿归因已有先例）；④覆盖补测工作量超 1-2 天（分批：首批先至 93.0+ 保缓冲，top 缺口继续按批补）

## 6. 实现思路（给定方向，非完整方案对比）

- **拟采用**: 守卫类改动全部仿既有模式——体积守卫参照 `tests/test_w19_lite_dist.py`（marker 字节对账，**产品字节口径**统一排 `__pycache__`/*.pyc，W19 冷知识）；spec 防呆只做验收不重写（工作区现成实现已达标）；推送按 R01"双发"规则执行。
- **复用**: `scripts/make_lite_dist.py`（lite 派生）；`tests/test_w19_lite_dist.py`（棘轮模式）；`gui/core/settings_io.py`（首启配置代码路径，W13 已建 CONFIG_DIR 单源）；`tests/test_w26_spec_packaging.py`（spec 守卫 AST 解析不 exec 的既有约定）；发版检查单（UIA 冒烟复用）。
- **注意**: ①spec 改动（防呆 + 清 datas）与守卫测试同文件不并行，统一由任务序列管住；②`make_lite_dist.py` 须从仓库根目录调用（memory：根目录调用否则 Errno 2）；③lite 派生对已存在目标目录拒绝覆盖（rc=2 护栏非 bug）；④打包正测与 FR-006 验收**合并为最后一次重打包**（避免两次十几分钟级打包）；⑤bash 管道 `| tail` 吃退出码——门禁判定一律 `> log 2>&1; echo RC=$?`。

---

## 自检（5 项，提交前核对）

- [x] **完整性**〔流程事件〕: 每条需求有 FR 编号（FR-001..008）
- [x] **无歧义**〔可执行判定〕: 本文件无"快速/友好/高效/灵活/强大"类歧义词（AC 均含命令或度量）
- [x] **可追溯**〔流程事件〕: 每个 FR 有对应 AC（FR-001→AC-001/002 … FR-008→AC-007/015）
- [x] **范围清晰**〔流程事件〕: In / Out Scope 已列
- [x] **指标可量化**〔可执行判定〕: 目标 / AC 均有可判定标准（<5s、<2GiB、<7GiB、≥93.5%、退出码、grep/show 可验）

## ✅ 门禁（3 项 · 降级留痕）

- [x] **探索门禁** → S1 用户显式指令（`/structured-dev-workflow` 携带明确路径与"制定修复计划"指令）；S2 上游 remediation-plan.md 书面推荐锁定方向；三栏账见 §5（未知项全部设计为任务内取证输入，无阻塞残留）
- [x] **PRD 门禁** → S2/S3 替代：本 PRD 即交付物，方向锁定自上游补救计划；用户审阅本文件后如对任何 FR/AC 有异议，按任务调整协议回改（P3-2 般的拍板项已在 Out Scope 注明用户职权）
- [ ] **收尾门禁** → 执行期末（Task 9）：AC-001..015 全过 + 主门禁全量绿 + 总检；git commit/push 全程逐次用户批准，不自动执行
