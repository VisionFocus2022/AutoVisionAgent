# 架构审查 2026-08-24 补救落地 — 任务列表 (L2)

> 关联: [prd-remediation.md](prd-remediation.md) v1.0 · 上游: [remediation-plan.md](remediation-plan.md)（P1/P2/P3 排序与依赖图的执行版）
> 日期: 2026-08-31 | 分支: `feature/sam3-auto-discovery`
> 并行安全：Task 4 / 5 / 7 互不同文件可并行；Task 2→3（推送前须提交）、Task 1→5（缺口数据）、Task 4→6（产物全貌）有依赖；spec 相关（Task 2/7）不与其他 spec 改动并行。
> 铁律：git commit / push 逐次经用户批准；门禁判定 `> log 2>&1; echo RC=$?` 不用管道吃码。

## 任务列表

### Task 1: ✅ 基线确认与 skip/缺口取证（FR-004/008 前置 · 只读）——2026-09-01 完成
- **步骤**:
  1. 主门禁全量跑：`.venv/Scripts/python.exe -m pytest > gate-baseline.log 2>&1; echo RC=$?`——确认 1222 passed / 5 skipped / 92.87% 量级仍真，记录为改动前基线
  2. `pytest -rs` 枚举 5 个 skip 原因（预期含 lite 守卫族），逐项归因留档（回填本文件表格）
  3. 聚合 term-missing 报告，统计 668 缺口 top-10 模块，写入本目录 `coverage-gap-analysis.md`（AC-009 素材）
- **涉及文件**: 无生产码改动（只读 + 新增分析文档）
- **验证**: 门禁 rc=0 且与基线数字一致；skip 归因表与缺口 top 表落档

### Task 2: ✅ 打包防呆收尾验收 + 提交（FR-001 · AVA-R1）——2026-09-01 完成
- **步骤**:
  1. **反测**（TDD 判定即验收）：用系统 python（或任一非 `.venv` 解释器，如 `python -m PyInstaller autovisionagent.spec --noconfirm`）→ 预期 <5s `[BUILD-ABORT]` 非零退出、信息含 `.venv`（AC-001）
  2. 核对工作区 `R01-module-build.md` +2 行登记段完整（AC-002 素材；提交后以 `git show HEAD:...` 终验）
  3. 将 `autovisionagent.spec` + `.qoder/rules/R01-module-build.md` 作为一个原子提交（**commit 前请用户批准**，信息例：`feat: spec 打包环境双断言防呆——错误 venv 即 BUILD-ABORT（AVA-R1/P1-1）`）
  4. 正测（`.venv` 打包成功）**不单独做**——与 Task 7 后的最终重打包合并（S3 留痕：避免两次十几分钟打包；现有 dist 即 .venv 产物，防呆断言只在错误环境触发，不构成正确性风险）
- **涉及文件**: `autovisionagent.spec`（验收既有改动）、`.qoder/rules/R01-module-build.md`
- **验证**: AC-001 反测通过；提交入 git（用户批准后）；`tests/test_w26_spec_packaging.py` 等既有 spec 守卫仍绿

### Task 3: 推送双远端 + CI 首跑观察（FR-002 · AVA-R2）⚠️ 外发动作
- **步骤**:
  1. 更新 ci.yml L2 过时注释（"本仓当前无 git 远程"→ 双远端已接入，AC-005）；单独提交（用户批准）
  2. 推送：`git push -u gitee feature/sam3-auto-discovery` + `git push -u github feature/sam3-auto-discovery`（**push 前请用户批准**；GitHub 若 HTTPS 拒连走已配 SSH-over-443）
  3. 观察 CI 双 job（test + dotnet-test）首跑：状态查询用 GitHub PAT 或匿名公开仓接口；含中文 commit 信息的响应须 `curl -o file` + UTF-8 读（memory 冷知识）
  4. 绿 → 记录运行链接与结论；红 → 修复提交后复跑，全过程留档（P1-2 原文："这正是 CI 存在的意义"）
- **涉及文件**: `.github/workflows/ci.yml`（仅注释行）
- **验证**: `git branch -r` 含两远端 feature 分支（AC-003）；CI 运行记录红绿可追溯且留档（AC-004）；注释更新（AC-005）
- **依赖**: Task 2（推送内容须含防呆提交）

### Task 4: 重建 dist-lite + 棘轮硬化（FR-003 · AVA-R3）
- **步骤**:
  1. `.venv/Scripts/python.exe scripts/make_lite_dist.py`（**须从仓库根目录调用**；目标不存在，无防覆盖护栏冲突）
  2. 量测 lite 体积（产品字节口径）：**风险闸**——若 ≥2GiB（源 dist 已从 4.x 涨至 6.36GiB，W26 时余量仅 17.5MiB），先启用 spec 注释已写明的 matplotlib Agg 杠杆重派生；仍超线则体积治理单独立卡（升 L3），本任务降级为"分析留档 + 棘轮维持 skip 并在发版检查单硬核销"（S3 决策，记偏差）
  3. 跑 `tests/test_w19_lite_dist.py`：棘轮由 skip 转 pass（AC-006）；`pytest -rs` 确认 lite 相关 skip 归零（AC-007）
  4. 棘轮硬化（可选增强，S2 默认不实施）：评估"dist 构建时间戳/manifest 对齐 → lite 必须存在"的绑定语义；至少在发版检查单加 lite 硬核销项
- **涉及文件**: `scripts/make_lite_dist.py`（如需豁免适配）、`tests/test_w19_lite_dist.py`（如硬化）、发版检查单
- **验证**: dist-lite 存在且 <2GiB；lite 守卫 pass；skip 归零

### Task 5: 覆盖缺口定向补测（FR-004 · AVA-R6）
- **步骤**:
  1. 按 Task 1 缺口 top 表，优先补「发布包 + gui 交互路径」缺口（TDD：每处先写红测试）
  2. 纯脚本/死代码缺口走 `.coveragerc` omit 或删除，**不硬凑覆盖**；处置结论记入 `coverage-gap-analysis.md`（AC-009）
  3. 跑主门禁确认 ≥93.5%，`--cov-fail-under=92` 不动（AC-008）
- **涉及文件**: `tests/`（新增/补强用例）、`.coveragerc`（omit）、可能的死代码删除
- **验证**: 覆盖率 ≥93.5% 且全量门禁 rc=0
- **依赖**: Task 1（缺口分布数据）；工作量超预期则分批（首批 ≥93.0 保缓冲），记偏差

### Task 6: 完整 dist 体积棘轮（FR-005 · AVA-R5）
- **步骤**:
  1. 体积构成分析：dist top-20 目录（产品字节口径），对照旧基准 4.3GiB/8,272 文件定位增量来源，留档 `docs/benchmarks/`（AC-011）
  2. 新守卫测试 `tests/test_w55_full_dist_ratchet.py`（命名随仓内波次惯例定）：`dist/` 存在时断言 <7GiB，缺失时 skip——语义、口径对齐 lite 守卫；先写红（阈值临时上调复现）再转绿
  3. 守卫入主门禁（testpaths 已覆盖 tests/，无需改 pytest.ini）
- **涉及文件**: `tests/`（新守卫）、`docs/benchmarks/`（分析）
- **验证**: 守卫在主门禁内 pass；分析留档（AC-010/011）
- **依赖**: Task 4（lite 归位后的产物全貌——remediation 依赖图）

### Task 7: spec 移除 user_settings.json 条件打包（FR-006 · AVA-R7）
- **步骤**:
  1. 删 `autovisionagent.spec` L48-51 条件 datas 条目
  2. 守卫测试：产物内不得存在 `configs/user_settings.json`（可并入 lite/full 守卫检查项）；先红后绿
  3. 确认首启默认态走 `gui/core/settings_io.py` 代码路径、无其它打包态依赖（grep spec datas + settings 读取链）
  4. 提交（用户批准）
- **涉及文件**: `autovisionagent.spec`、`tests/`（守卫）
- **验证**: 守卫绿；spec 无该条目（AC-012 静态半）+ 最终重打包产物内实证（Task 9）
- **注意**: 与 Task 2 同文件——顺序执行不并行

### Task 8: UIA 回归流程登记（FR-007 · AVA-R4 · 流程性）
- **步骤**:
  1. 发版检查单加 UIA 真窗回归强制项 + 执行记录登记栏（触发：发版 / spec 改动 / 页面结构变更后）
  2. 登记手动跑命令与已知环境前置（`.venv/Scripts/python.exe -m pytest tests/uia -o addopts=`；机器空闲时段；失败点漂移=环境归因先例已留档，断言永不改）
  3. RELEASES.md 或检查单注明：无自托管 runner 期间 UIA 不入 CI 属**已登记取舍**，非盲区（对齐审查"设计取舍+缺口"定性）
- **涉及文件**: 发版检查单 / `RELEASES.md`
- **验证**: 检查单项与登记栏存在且含命令（AC-014）

### Task 9: 最终重打包 + 冒烟 + 集成验证 + 清账回填（末位强制任务）
- **步骤**:
  1. **最终重打包**（合并 Task 2 正测 + Task 7 验收）：`.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm` 成功 = AC-001 正测半
  2. 冒烟：exe 启动 + UIA 既有冒烟/发版检查单用例（机器空闲时段）；产物内无 `configs/user_settings.json`（AC-012 实证半）+ 首启默认态目测（AC-013）
  3. 全量主门禁 rc=0（含新守卫）；逐条核对 AC-001..015
  4. 工件回填：remediation-plan.md 复选框打勾；risk-map.dot 已消节点灰化标「已消」；审查 §4 未知表 5 项回填（含 CI 首跑结论、skip 归因、缺口分布、体积增量来源）
  5. .NET 客户端生产使用状态问询用户，答案留档（唯一需用户输入项）
  6. 档位回顾（L2 是否合适）+ 经验沉淀（≥1 条 EXP，Phase 4.6）
- **涉及文件**: `remediation-plan.md`、`risk-map.dot`、`architecture-review.md` §4、本目录任务表勾选
- **验证**: AC-001..015 全过 + 主门禁 rc=0 + 冒烟绿 + 工件回填完成
- **UIA 回归**: [ ] 机器空闲时段跑 `tests/uia` 全套并通过（或记录环境归因留档复跑约定）

---

## 执行约定

- **每任务完成**跑自己的验证命令，全过才标记 completed。
- **修复尝试上限**: L2 = 3 次，超限触发回滚决策（git revert 或备份还原）。
- **进度汇报**: 每完成 **3 个任务**汇报一次。
- **偏差记录**: 实际与计划不符时记入汇报；触及单向门（推送/重打包发布）须用户显式批准；升档条件——lite 体积治理若需 PYZ 清场级手术，Task 4 拆出升 L3 立卡。
- **建议执行序**: T1 → T2 → T3 →（T4 ∥ T5 ∥ T7）→ T6 → T8 → T9。

---

## 自检（4 项，提交前核对）

- [x] **原子性**〔流程事件〕: 每个任务聚焦一个 FR（或其前置取证），可独立验证
- [x] **验证可行**〔可执行判定〕: 每任务有命令或可判定预期（<5s / rc=0 / <2GiB / ≥93.5% / grep 实证）
- [x] **AC 覆盖**〔可执行判定〕: AC-001..015 均有归属任务（T2→001/002；T3→003/004/005；T4→006/007；T5→008/009；T6→010/011；T7→012/013；T8→014；T9→全部终验+015）
- [x] **末位验证任务**〔流程事件〕: Task 9 集成验证 + 清账回填存在

---

## 执行进度回填

### 2026-09-01 · Task 1 + Task 2 完成（用户指令：先 1 后 2；.NET 问询项已获答案）

**Task 1 结果**（证据：`.workflow/ava-remediation/gate-baseline-20260901.log` + [coverage-gap-analysis.md](coverage-gap-analysis.md)）：
- 基线：**1222 passed / 5 skipped / 92.87%（668/9369）/ RC=0 / 90.62s**——与审查报告一致，假设 2（spec 不进分母）成立
- 5 skip 归因完成：全部为设计内 opt-in/环境门控（真权重冒烟×2、已装依赖×2、训练流水线×1），**无 lite 守卫——审查推测证伪**；AC-007 口径修正为"归因留档"（见 coverage-gap-analysis.md §2）
- 缺口分布：gui 260 + labeling 142 = 60%；补测量化目标 miss 668→≤609（净补 ≥59 条）；首补池 sam_session(63)+vision_dataset(28)+supervised_exporter(28)+label/page(25)+batch_tools(25)+geometry(25)=194 条
- 顺手实测双产物体积（§4）：lite **1.980GiB 达标**（余量 20.6MiB）；完整 dist **7.588GiB**

**Task 2 结果**（证据：`.workflow/ava-remediation/guard-negative-test.log`）：
- 反测（AC-001）：hermes-agent venv（**08-24 事故同款解释器**）跑 `python -m PyInstaller autovisionagent.spec` → **RC=1 / 564ms / [BUILD-ABORT]×1 / .venv×5**——达标
- AC-002：`git show HEAD` 核实 R01 含机械防呆登记、spec 含 BUILD-ABORT×2（提交 5b94a48）
- 回归：test_w26_spec_packaging + test_dynamic_import_guard = 14 passed
- 正测（AC-001 正向半）：08-31 完整 dist 即 .venv 产物（旁证）；完整重打包合并 Task 7 后于 Task 9

**偏差记录（4 条 · 均因并行会话在计划落盘后先行推进）**：
1. **P1-1 提交已由并行会话完成**（5b94a48，含 spec 防呆 + R01 登记 + 审查四件套落档）——Task 2 收窄为验收，未新增提交
2. **P1-2 大部分已由并行会话完成**：3269a3b 更正 ci.yml 注释（AC-005 ✓）；分支已推**双远端**且指针=cd91e7d（AC-003 ✓，git ls-remote 实证）；剩余=CI 首跑结果确认（cd91e7d 注记"待人工确认"）→ Task 3 收窄为"查 CI 运行记录+留档"
3. **AVA-R3 证伪**：审查查错目录名（`dist-lite/` vs 真实 `dist/AutoVisionAgent-lite/`）；产物存在（08-31 派生）+ 守卫 14 passed → Task 4 收窄为"体积留档+发版检查单 lite 硬核销项"，无需重建
4. **AVA-R5 阈值失效**：完整 dist 实测 7.588GiB（>拟设 7GiB）→ AC-010 阈值重定（建议 8.5GiB 或待 Task 6 构成分析后定）
5. 工作区存在 **85 个旧 docs 文件删除态**（未 staged，非本任务所为）——不触碰、不提交、不还原，待用户处置

**Task 9 问询项已获答案（用户 2026-09-01）**：**.NET 客户端有生产消费方**——Task 9 第 5 步问询免做，直接回填审查 §4 未知表第 5 行。

**下一步**（待用户指令）：Task 3（收窄版：CI 首跑确认）→ Task 4（收窄版）∥ Task 5 ∥ Task 7 → Task 6 → Task 8 → Task 9。
