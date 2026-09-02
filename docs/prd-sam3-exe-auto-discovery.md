# PRD — SAM3 自动发现 exe 侧闭环（不选权重直接标注）

> 档位：🟡L2（lite）｜日期：2026-08-31｜分支：feature/sam3-auto-discovery
> 上游：docs/superpowers/specs/2026-08-31-sam3-auto-discovery-design.md（计划 Task 5 搁置的「exe 侧权重随包分发」项，本次用户裁决解锁）

## 1. 背景与目标

自动发现代码已全部落地（e85591c→e5d7d94，主门禁 1222×2 双采样绿；python 模式 UIA 自动发现用例已实跑绿）。但当前 full exe 构建于 08:44，**早于全部自动发现提交（11:38-12:06）**，且 `_internal/weights/sam3` 不存在 → exe 侧点击「交互式」仍落权重选择弹窗（用户痛点）。

**目标**：exe 侧实现「不选权重直接标注」——重打包 + 权重落地后，无 AVA_SAM3_DIR、无弹窗，交互式直接就绪并可标注；全套 UIA 回归验证。

## 2. 功能需求（FR）

| # | 需求 |
|---|---|
| FR-1 | 重打包 full exe（当前 HEAD 含自动发现代码；命令：`.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm`） |
| FR-2 | 复制 `weights/sam3`（3.3G）→ `dist/AutoVisionAgent/_internal/weights/sam3`（重打包后复制——PyInstaller --noconfirm 会清空 dist 目录） |
| FR-3 | exe 模式跑**全部** UIA 套件（tests/uia/ 9 文件）；`test_sam3_auto_discovery_no_env` 由 skip 变实跑且绿 |

## 3. 验收标准（AC）

| # | 标准 | 判定 |
|---|---|---|
| AC-1 | 重打包 0 error；`_internal/transformers/models/sam3` 在场（深度用例模块级门槛） | ls 实测 |
| AC-2 | `_internal/weights/sam3/{config.json,model.safetensors}` 在场（`_is_sam3_dir` 判据齐全） | ls 实测 |
| AC-3 | `test_sam3_labeling.py`（3）+ `test_sam3_labeling_deep.py`（4）exe 模式全绿，自动发现用例**实跑非 skip** | pytest 输出 |
| AC-4 | 其余 UIA 套件绿；环境类 flaky 按「每用例新鲜单跑复验」口径定谳，不改断言不碰生产码 | pytest 输出 |

## 4. 范围

- **不改生产代码**；不动 lite（无 sam3 栈，模块级 skip 天然豁免）；不改 autovisionagent.spec（spec 纳入 datas 的发布决策延后单独裁决）。

## 5. 风险与假设

- UIA 全套 exe 模式实跑约 30-60+ 分钟，**硬依赖机器空闲**（输入争抢=flaky 源）；期间请勿操作鼠标键盘。
- Bash 单次 10 分钟硬顶 → 全程 run_in_background + 日志落 `%TEMP%`（不进 logs/，W23 隔离守卫）。
- lite 字节守卫不受影响（本次不触碰 lite dist）。
- 重打包后若深度用例模块级 skip（sam3 栈被剪），须先排查 hook 收集再继续。

## 6. 探索三栏（已过门禁 1）

已知/假设/未知见会话记录；用户裁决：标注语义=不选权重直接标注；落地方式=复制到 _internal；重测范围=全部 UIA 套件。

---

✅ 门禁记录
- [x] 门禁 1（探索）：2026-08-31 三项裁决全按推荐项（重测范围用户扩为全套）
- [x] 门禁 2（PRD）：2026-08-31 确认执行（推荐项）
- [x] 门禁 3（收尾）：2026-08-31 确认完成（四任务全绿 + AC 全过）

## 执行结果（2026-08-31）

- T1 ✅ 重打包 0 error（Build complete，22:14 产物；sam3 栈在场）
- T2 ✅ robocopy RC=1 复制成功（model.safetensors 3,439,938,512B + config.json 25,843B）；坑：MSYS 把 `/E` 转成盘符路径致首次 RC=16——`MSYS_NO_PATHCONV=1` 前缀解
- T3 ✅ 全套 UIA（exe 模式，14:29）：**22 passed / 1 failed / 0 skipped**；SAM3 全 7 用例绿，`test_sam3_auto_discovery_no_env` **实跑非 skip**（exe 无 env 无弹窗直接就绪+标注铁证）；唯一红 `test_predict_single_image` 新鲜单跑 38s 转绿=批跑瞬态（分诊协议定谳，与 SAM 改动面零关联）
- AC-1~4 全过
