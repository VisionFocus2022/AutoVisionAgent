# PRD-lite：W1-3 模拟训练显式化

- **版本**: v1.0（2026-10-06）
- **档位声明**: 🟡L2 ｜ 确定性：高（存量已有"未装引擎（模拟）"标注，缺真训练能力判定/灰显/启动确认三件）｜ 影响半径：中（改开始训练入口交互，波及 3 个既有测试面）｜ 规模：小-中（4 生产文件 +~60 行 + 测试）｜ 可逆性：双向门
- **上游**: roadmap Wave1 W1-3；W71 F-2 同源（训练可信度）
- **门禁**: 探索 ✅（用户指令 W1-3+W1-1 连续实施）｜ PRD ✅（S2 预裁决：上游 roadmap DoD 锁定）｜ 收尾 ✅（2026-10-06：单测守护/灰显/确认门 23 绿；UIA DoD full_workflow 确认框出现并点穿→训练完成；真训练路径零回归）

## 1. 背景与目标

模拟训练有两形态都表现为"训练完成"：任务引擎缺实装（cls/pose/sseg/
abdet/sgan/super——引擎在≠真训练，仅 det/seg 有 train_epoch）与真任务
未选数据集（W58 诚实回退）。现 UI 仅对"引擎缺失"标"（模拟）"后缀，
引擎在但模拟训练的任务完全无标识；用户点开始即静默跑假 loss。

**目标**：模拟训练在下拉（灰显+说明）与启动（显式确认对话框）两处
可见可拒。DoD（roadmap）：UIA 模拟任务→显式确认出现；单测门禁守护。

## 2. FR

- **FR-1 真训练任务集单源**：`registry.REAL_TRAIN_TASKS = {DET, SEG}` +
  `task_supports_real_training()`；守护测试逐引擎核验 hasattr(train_epoch)
  与集合一致（防新引擎实装后集合同步漂移）。
- **FR-2 下拉灰显+说明**：`populate_task_combo` 增 `simulated` 参数——
  模拟任务项灰前景色 + 后缀"（模拟训练）" + 悬浮说明（推理/评估页不
  传参零影响）。训练页传入非真任务全集。
- **FR-3 启动显式确认**：`_start_training` 在状态变更前判定
  `_will_be_simulated(cfg)`（任务非真 或 无 data.yaml）→ 自定义中文
  按钮确认框（"继续模拟训练"/"取消"）；取消=零状态变更直接返回。
  确认方法独立成缝（`_confirm_simulated`）供测试注入。

## 3. AC

- AC-1 守护：全 TaskType（除 OCR）实例化引擎，hasattr(train_epoch) ⇔
  ∈ REAL_TRAIN_TASKS。〔非 happy-path：集合漂移即红〕
- AC-2 下拉：cls 项灰显+含"（模拟训练）"；det/seg 项无此后缀。
- AC-3 启动：确认拒绝 → 无"训练已启动"、按钮未被禁用、状态"已取消"；
  确认接受 → 原流程继续。〔非 happy-path〕
- AC-4 UIA（借 full_workflow 模拟步）：点开始训练 → "模拟训练确认"
  对话框出现 → 点穿 → 训练完成。
- AC-5 主门禁全绿 + ruff 0 + 行数守卫；真训练路径（pole/wizard UIA）
  不弹框不回归。

## 4. 范围与连带

改：models/supervised/registry.py、gui/core/tasks_ui.py、
gui/pages/train/page.py、gui/core/i18n.py；新 tests/test_w1_3_*；
连带修 tests/test_gui_train_page.py 夹具（注入确认缝）与
tests/uia/test_full_workflow.py（点穿对话框=W1-3 DoD）；
**连带修 W1-6 UIA 回归**：test_wizard_chain_real_train 的
"epochs_completed=2" 断言按自适应轮数收敛（N=2 → 100）。

Out of scope：真训练数据集缺失时的 UIA 拒绝路径（单测覆盖）、W1-1。

## 5. 风险

| 项 | 评估 |
|---|---|
| 模态框挂死既有测试 | 夹具注入缝 + UIA 点穿；真训练路径无框 |
| 灰显被误解为禁选 | 保留可选（灰=视觉标记），确认框是硬门 |
| Qt 按钮本地化不确定 | 自定义 addButton 中文文案，不依赖翻译 |

## 实施纪要（2026-10-06）

- 连带修复 1（真缺陷，UIA wizard 暴露）：P0-1 划分布局击穿 W69 任务探测
  （labels 平铺假设→多边形数据静默训成 det）——布局逆向定位助手
  （candidate_label_dirs/label_txt_files）归口 dataset/format_export.py，
  回归单测锁定划分布局+旧平铺双形态。
- 测试基建：train_page/w31/w18 三处夹具注入确认缝（模态框测试纪律：
  新增 exec() 型 UI 交互必须带可注入缝，否则单测挂死）。
