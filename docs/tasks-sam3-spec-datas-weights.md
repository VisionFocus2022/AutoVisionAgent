# Tasks — SAM3 权重 spec datas 纳入（lite）

> PRD：docs/prd-sam3-spec-datas-weights.md v1.0 | 日期：2026-09-01
> 门禁 1/2 已过（2026-09-01：三栏+硬失败裁决 / PRD 确认）

## T1 — spec datas + 缺失防呆（FR-001/002，RED：AST 守卫先红）

- [x] RED：tests/test_w26_spec_packaging.py 增 datas 守卫用例（AST 断言 datas 含 ("weights/sam3","weights/sam3")）→ 跑红 ✓
- [x] GREEN：autovisionagent.spec 头部防呆区加权重存在性断言（缺失→[BUILD-ABORT]）+ datas 加元组 ✓
- [x] 验证：守卫用例绿；spec 守卫套件 8/8 绿 ✓

## T2 — lite 裁剪清单（FR-003，RED：假树单测先红）

- [x] RED：tests/test_w19_lite_dist.py 增用例——假树含 `_internal/weights/sam3` → derive_lite 后目录不存在 + marker 留档 → 跑红 ✓
- [x] GREEN：make_lite_dist.py `_prune_optional_packages` 调用清单加 `"weights/sam3"` + 注释 ✓
- [x] 验证：lite 套件 15/15 绿（偏差：首版把 "weights/sam3" 误放 tuple 外成第 3 位置参数→TypeError 10 红，修正入 tuple 即绿）

## T3 — 重打包实证（AC-1/AC-2，依赖 T1）

- [x] 全量重打包（--noconfirm，后台化）→ `_internal/weights/sam3/model.safetensors` 字节数=3,439,938,512 ✓（290s；cmp 字节级相同，dist 侧时间戳 09:41 确认本次 COLLECT 复制）
- [x] AC-2 可逆验证：临时改名 weights/sam3 → 打包秒级 [BUILD-ABORT] 非零退出+缺失提示 → 恢复 ✓（TRUE_EXIT=1；spec 评估阶段退出，dist 未波及）
- 偏差：首次重打包失败 WinError 32（dist 内 logs/autovision.log 被残留 exe 实例 PID 47280 握句柄，Removing dir 被拦）——taskkill 清场后重跑即通；打包前 taskkill 验零为既有纪律再证实

## T4 — UIA 抽验 + 文档 + 主门禁（AC-3/AC-4，依赖 T3）

- [x] UIA exe 模式：`test_sam3_auto_discovery_no_env` 在重打包产物上实跑（非 skip）且绿 ✓（57.6s，1 passed）
- [x] docs/release-checklist.md 打包节补「权重自动带入；缺失=BUILD-ABORT 须先下载；lite 自动裁剪」说明 ✓
- [x] 主门禁全量 rc=0 覆盖率 ≥92 不降 ✓（1237 passed + 5 deselected，92.51%）
- 偏差：首轮全量 5 红全在 tests/test_labeling.py（AnnotationController 缺 handle_double_click）——三信号（盘上有/HEAD 无/mtime 09:37-09:44 活跃）坐实为**并行会话在途批 RED 相位**（test +207 行已落、实现未落），非本批回归；按共享仓纪律 deselect 划清门禁面复跑全绿
- [x] 收尾门禁 3（AskUserQuestion）+ 经验沉淀 ✓（EXP-2026-09-01b + learn-20260901-sam3-spec-datas.md；提交 a33b319）
