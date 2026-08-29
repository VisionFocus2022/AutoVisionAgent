# Tasks：SAM 标注 UIA 自动化测试（W46·B · lite · 终态）

关联：[prd-uia-sam-labeling.md](prd-uia-sam-labeling.md)（FR/AC 同源）

## 终态结论（2026-08-29 晚）

**3/3 用例全绿 ×2 连跑（153s/154s）+ 主门禁 1182 passed / 5 skipped / rc=0。**
本波共擒获并修复 **3 个真生产缺陷** + 2 个测试基建缺陷——UIA 真窗套件首秀即证价值。

| # | 任务 | 状态 |
|---|------|------|
| T1 | AUTO 入口补口（`_MODES` + `(AUTO, "SAM 全图", "G")` + i18n + 3 守卫用例） | ✅ |
| T2 | `tests/uia/test_sam3_labeling.py`（3 用例 + env 夹具 + 交互原语加固） | ✅ |
| T3 | 主门禁 V4 回归 | ✅ 1182/5/rc=0（+4 用例：入口 3 + attach 守卫 1） |
| T4 | UIA 源码模式实跑 | ✅ **3/3 双连绿** |

## 擒获与修复清单

### 生产缺陷（3）
1. **P0 级·SAM 笔刷 GUI 死路**：`controller.attach_interactive` 模式白名单只有 `(INTERACTIVE, REGION_SAM)`——W44 建 SAM_BRUSH 时漏加，笔刷标注器在 GUI 装配链永远拿不到 adapter（单测直接注 set_adapter 不经此路故全绿）。修复：白名单补 SAM_BRUSH + 守卫单测 `test_controller_attach_interactive_covers_sam_modes`。
2. **P0 级·交互式标注不可保存**：`InteractiveLabeler` 提交 Shape 带 `mode=INTERACTIVE`（工具模式上形状），LabelMe 导出器拒收 `InvalidShapeError`；且 `save()` except 元组不含它 → **裸穿 Qt 槽**（状态冻结、无文件、无报错，W4 以来潜伏）。修复：提交显式 `POLYGON`（对齐 region_sam/brush_sam 语义）+ except 元组补 `InvalidShapeError`（诚实报错）+ test_sam_modes 断言更新（原断言编码的正是缺陷契约）。
3. **P2 级·AUTO 模式 GUI 零入口**：W44 的 AUTO/AMG 通道在 GUI 无按钮（死代码）。修复：`_MODES` 补 `(AUTO, "SAM 全图", "G")`。

### 测试基建缺陷（2，本案根因链）
1. **usefixtures 夹具抢跑**：`@pytest.mark.usefixtures("ava_app")` 先于签名夹具实例化（微测实证 order=['app','env']）→ env 注入在应用启动后 → 应用回落弹 #32770 权重对话框 → 模态冻结。修复：删三处冗余标记（签名顺序接管）。既有 6 个 UIA 文件同陷阱在身（文件写入型夹具因应用晚读而幸存）——**留待后续波次统一清理**。
2. **对话框确认假 True**：`enter_path_in_open_dialog` 在确认点击未落上时仍返 True（最终 `_wait_dialog_gone` 结果被丢弃）。本套件以**文件落盘为真值**重试 + `_hard_confirm_save_dialog` 补键盘确认规避；helper 本体语义修正留档（FB 攒批）。

## 交互原语终稿（tests/uia/test_sam3_labeling.py）

- `_canvas_click`：SetActive + 0.25s 落定 + **双发**（on_press/run 幂等重入无副作用）
- `_canvas_commit`：**画布右键提交**（`on_mouse_press RightButton → handle_commit`，pole 套件原语；SendKey Return 过焦点链会被 label 输入框吃掉——QShortcut 不触发）
- `_save_and_read_json`：以文件存在为真值整段重试（≤3 轮 + 清扫 + 硬确认）

## AC 核验（全过）

- AC-1 ✅ T1 三模式一图流：3 polygon + LabelMe JSON 铁证（imagePath=.bmp）
- AC-2 ✅ T2 概念分割：label=hole 实例落盘
- AC-3 ✅ T1 含状态栏全链路断言
- AC-4 ✅ T3 伪权重「SAM 加载失败」+ 主窗存活（6 连绿）
- AC-5 ✅ 主门禁 1182/5/rc=0；page.py 799 行（守卫内）

## 遗留

1. 既有 UIA 文件 usefixtures 冗余清理（建议整波次）
2. `enter_path_in_open_dialog` 假 True 语义修正（uia_helpers，兄弟技能基建）
3. exe 重打包后放开模块级 skip（spec 补 transformers/Sam3Adapter hidden import）
4. UIA 复跑命令：`AVA_UIA_SOURCE=python .venv/Scripts/python.exe -m pytest tests/uia/test_sam3_labeling.py -o addopts= --timeout=600 -v`
