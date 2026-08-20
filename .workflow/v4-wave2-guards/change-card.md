# W24（v4 第二波）变更卡：守卫与决策 + logs 清档 + exe 重打包

- **change_id**: v4-wave2-guards
- **日期**: 2026-08-21
- **档位**: L1（可逆/局部/测试可见/低不确定；用户指令「重新打包合并下一波，logs存量1990行污染，可直接删除，继续」）
- **来源**: v4 §9 第二波 #4-#7 + W23 risks_open 留下一波项 + 用户两项拍板

## What

1. **logs/ 存量污染清档**（用户批准）：autovision.log 删 1,990 行 pytest-of；audit_20260630.jsonl 整文件删（7 行全单测：test_user/tester/u1-u3/alice/bob 群发时间戳）；audit_20260817/18 删 fake.png 各 25/22 行；history 各日删 `"image_path": "/test` 前缀与 fake.png 共 13+44+136+42+8 行。备份 %TEMP%\w24-logs-backup-20260821。
2. **文件级规模守卫（v4 P3-1 #4）**：tests/test_w24_scale_guards.py——全 cov 包（pytest.ini --cov 12 包动态解析，与覆盖率口径同源）文件 ≤800 行（棘轮 gui/pages/label/page.py=850，现测 828，v4 §9「先设 850 再收敛」；棘轮失效断言强制收敛后删条目）+ 函数/方法 AST 度量 ≤100 行全包化（原 W18 守卫仅 metrics 单文件）；豁免带数值上限。
3. **豁免上限声明（v4 P3-6 #5）**：core/interfaces_supervised.py 形态豁免 docstring 补「AST 度量约 200 行，豁免上限 220 行，超出须复审拆分」（替换陈旧「约 195 行」近似值）；守卫钉住「上限 220 行」文本。
4. **协议演进决策（v4 P3-2 #6）**：ADR-0002 状态行补冻结声明——双方向维持 PoC/协议能力形态不接线（W24 取证：C# 客户端零 lease/FetchRegion 调用，消费形态为内联+MMF 直读双路径、Release 不带 lease_id），跨机场景再启（重开条件见 ADR §决策 4）。二选一取「冻结」，证据：回环拓扑（ADR-0001）+ 直读 3.55GB/s vs 流式 11.7x 劣势 + 无跨机需求。
5. **凭据删除补删（v4 P3-7 #7）**：gui/pages/login/page.py 新增模块级 `sweep_residual_initial_credentials()` 四态（absent/deleted/kept_pending_change/remove_failed），LoginPage.__init__ 在 _ensure_default_admin 后接线——补此前 os.remove 失败仅记日志无重试的缺口；users.json 不可读保守保留；must_change=True 保留（登录流程仍强制改密）。
6. **UIA 失败提示语按模式分支**（W23 遗留）：tests/uia/uia_helpers.py 新增 `app_log_path()`（AVA_UIA_SOURCE=python→AVA_LOG_DIR 会话目录；exe→exe 目录 logs），test_full_workflow.py/test_pole_dataset_flows.py 两处提示语去写死路径。
7. **PRD 模板『新增落盘文件→忽略策略』栏**（v4 §10.3）：prd-lite.md §6 落盘产物条目+自检 5→6 项；prd-full.md §3.3 落盘文件子表+自检 9→10 项（用户级技能仓 structured-dev-workflow）。
8. **exe 重打包并入本波**（用户拍板）：full 88,414,000B @2026-08-21 03:56（旧 88,412,195，+1,805B=W23+W24 生产码）；PYZ TOC 守卫 labeling=28/data_manage=6/predict|sam_adapter=48 全过；lite 重派生 LITE_RC=0 + 守卫 14 passed。

## Why

- v4 审查第二波四项整改全部闭环（P3-1/P3-6/P3-2/P3-7）+ W23 risks_open 三项留下一波项 + 用户两项拍板（logs 清档、重打包并入）。
- 门禁中擒获的意外：test_real_lite_dist_guard 失败——非 W24 改动，系用户 08-19 16:42 运行 lite exe 追加 406B 日志（3,832-3,426=406 精确吻合 marker 差值），重派生自然复位。

## Files

- 新增：tests/test_w24_scale_guards.py（5 用例）、tests/test_w24_credentials_sweep.py（6）、tests/test_w24_wave2_meta.py（2）
- 修改：tests/test_w23_log_isolation.py（+1 污染守卫）、core/interfaces_supervised.py（豁免 docstring）、gui/pages/login/page.py（sweep 函数+接线）、docs/adr/0002-serving-large-payload-evolution.md（状态行）、tests/uia/uia_helpers.py（app_log_path）、tests/uia/test_full_workflow.py、tests/uia/test_pole_dataset_flows.py（提示语+import）
- 仓外：~/.claude/skills/structured-dev-workflow/templates/prd-lite.md、prd-full.md
- 数据：logs/ 下 7 个文件行级过滤/整删（备份在 %TEMP%）
- 产物：dist/AutoVisionAgent（重打包）、dist/AutoVisionAgent-lite（重派生）

## Verify

- RED 11 failed（豁免键限定名前函数守卫擒获 201 行违例、豁免声明缺 220、sweep 六用例、ADR/UIA 两守卫）→ GREEN 15 passed（含 W18 守卫无回归）
- 中场门禁 989 passed+1 failed（lite 漂移，环境归因）→ 封版门禁 **990 passed/4 skipped/93%（8552/592）/RC=0**（.workflow/arch-review-v4/w24-gate-sealed.log；976 基线+14 新用例）
- 清档后新基线冻结：封版门禁前后四文件 mtime/字节 diff 为空（FROZEN-OK）
- 打包：BUILD_RC=0 / PYZ 28/6/48 / LITE_RC=0 / lite 守卫 14 passed / 新 lite 无 logs 残留

## Rollback

- 代码：git checkout 全部修改文件；测试：删 3 个新测试文件
- logs：从 %TEMP%\w24-logs-backup-20260821 复原（w24 前 logs/ 整目录）
- exe：dist 可重派生（源=仓库），无不可逆
- PRD 模板：技能仓自带 .git，可 revert
