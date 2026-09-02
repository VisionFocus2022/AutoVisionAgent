# 发版窗批次 W61（SKolpha 复刻程序收尾）— 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-09-02 | 档位: 🟡 L2 | 确定性: 高（五项均有仓内先例） | 影响半径: 大（dist 重建+UIA 真窗；生产代码零改动） | 可逆性: 双向门
> **门禁偏差（自治留痕）**：探索门禁=S1（用户显式指令「按照推荐执行序实施」=对留项清单五项的逐项批准）；PRD/收尾=S3 留痕。执行序=用户裁定：**重打包→计时→UIA→CI→RELEASES**。

## 1. 背景与目标

SKolpha 复刻程序（W56-W60）已收官并推送，留四类发版窗项。目标：一次机器空闲窗内完成五项，使 PRD 追溯矩阵除 AC-010（用户配合）外全绿。

## 2. 功能需求 (FR)

- **FR-001** exe 重打包 + PYZ 守卫（新模块 cut_line/operation/batch_actions/api_actions/train_augment_actions 入包核验）+ lite 派生实测（14 用例 + <2GiB marker） | P0
- **FR-002** NFR-001 并行吞吐 benchmark 基线补录（D-14 收口：50 图 A/B 并发 1 vs 4，实测数字落 docs/benchmarks/；不落硬计时断言——flaky 风险，宽容口径记录） | P0
- **FR-003** UIA 回归：12 既有用例零改动复跑（新 exe）+ 新增切割线硬断言用例 1 条；前置静态核查 transferType 联动对既有用例默认模式假设的影响 | P0
- **FR-004** CI 结果确认（9 提交 push 触发的 run；匿名 API 可达则查结论，不可达则留证 N/A） | P1
- **FR-005** RELEASES.md 补 W56-W60 五波条目（历史档惯例） | P1

## 3. 验收标准 (AC)

- **AC-001**: dist/AutoVisionAgent 重建成功；PYZ 含 5 个新模块；lite 派生 rc=0 且 <2GiB
- **AC-002**: benchmark 脚本可复跑、基线数字落档；并发=4 不劣化（或如实记录反向结论）
- **AC-003**: UIA 复跑 12+1 用例（环境窗内全绿；flaky 按既有环境归因纪律处置，断言零修改）
- **AC-004**: CI 结论留档（绿/失败详情/不可达证据三态之一）
- **AC-005**: RELEASES.md 条目与波次提交一一对应

## 4. 范围

- ✅ 上述五项 + 偏差/记忆/沉淀收尾
- ❌ 生产代码改动（零）；D-4 实机核对（用户配合项）；同 stem/count_annotated 两 LOW 债

## 5. 风险与假设

- **已知**: 环境预检已过（零残留/14% CPU/干扰因子 2 个轻度）；spec BUILD-ABORT 前提（SAM3 权重）在场。
- **假设**: UIA 环境窗内可全绿（若 flaky 按冷知识⑦空闲复跑；两轮仍漂移则留环境归因档案不硬凑）。
- **风险**: 重打包被残留句柄拦（前科 WinError 32——已 taskkill 清场）；CI API 网络不可达（HTTPS 断网常态→N/A 留证）。

## 6. 实现思路

沿用 W26 重打包口径 / W19 benchmark 惯例 / W25 UIA 冷知识全套（PATH 导出、每用例独立启动、find timeout 英文断言）。

---

## 自检（5 项）
- [x] 完整性: FR-001..005 | [x] 无歧义: 无禁用词 | [x] 可追溯: FR↔AC 全挂 | [x] 范围清晰 | [x] 指标可量化: AC 全可判定

## ✅ 门禁（3 项 · 自治留痕）
- [x] 探索门禁 → S1 用户显式指令（推荐执行序=清单批准）
- [x] PRD 门禁 → S3 留痕（本文档；用户复核翻案权保留）
- [x] 收尾门禁 → S3 留痕（2026-09-02）：

> ✅ **W61 批次执行结果**（门禁回填）：
> - **AC-001 ✅** dist 重打包 249s RC=0；PYZ 8 新模块全过 + labeling 30 处口径；lite 派生 RC=0、15 守卫绿、1.980GiB<2GiB（零净增量）
> - **AC-002 ✅** benchmark：50 图串行 0.36s / 并发4 0.34s = **0.96x 不劣化**；基线落 docs/benchmarks/batch-concurrency-baseline-w61.md（宽容记录口径非硬断言，负载偏轻如实注明）；首跑挂死=模态坑二犯（EXP 留档）
> - **AC-003 ◐** UIA：**21/23 绿**；2 挂（full_workflow deploy、cut_line）四轮取证判**输入注入环境归因**（ToDesk×2+8 钩子族进程在场，raw SendInput 间歇被吞）——OS 级证据：deploy 无模态+按钮 enabled+点击已发+handler 零日志；cut_line 控制器打点左键 3 达右键 0 达（Return 等价路径同挂=注入介质问题非语义问题）。按冷知识⑦纪律：断言零修改、留档待空闲窗复跑
> - **AC-004 ✅（失败详情态）** CI 自 08-31（88f1fb5=W55，先于本程序）test job 全红；失败步=pytest 覆盖率门禁步；注记级取证无测试名、本地 CI 差仿真嫌疑文件 134 绿——根因需日志级取证（owner PAT 过期），留档
> - **AC-005 ✅** RELEASES.md v2.2.0 条目 + pyproject/README/settings 版本三同步（W38 四向守卫逮住漏改后补齐）
> - 主门禁 **1324 passed / 5 skipped / rc=0**；ruff 0 error
> - 顺手：test_label_edit_vertex 按自注解除仅源码守卫；full_workflow 失败分支加现场取证（不参与断言）
