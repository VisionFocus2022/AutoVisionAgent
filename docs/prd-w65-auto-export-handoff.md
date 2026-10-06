# PRD-Lite：W65 「下一步：训练」向导自动导出补缺

- 版本：v1.0（2026-09-28）
- 档位：🟡L2（三门禁：探索✅方案 A / PRD 并入 / 收尾待批）
- 关联：W63 交接的实弹补全——用户实测「全部标注好 → 下一步 → 数据集空」

## 1. 背景与目标

用户报：数据管理页全部标注好，进训练页数据集空。取证两形态：①「下一步：训练」
按钮直发导航信号，不检查是否导出过——W63 交接只在"本会话导出过 YOLO"才有物
可带；② `_last_export_yaml` 纯内存，跨会话（重启 exe）即丢。

真实任务（JTBD）：用户当标注完成准备训练时，希望点「下一步：训练」数据集即
就绪，以便不必理解"导出"这个中间概念。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 已导出直进 | 产物在盘 → 直接导航（原行为不回归） | `test_goto_train_existing_yaml_navigates` ✅ |
| FR-2 未导出自动补 | 有标注未导出 → 自动 YOLO（**force_yolo 无视格式组合框**）到图像目录兄弟 `_auto_export/yolo`，完成后自动进训练页 | `test_goto_train_auto_export_then_navigate` / `..._forces_yolo` ✅ |
| FR-3 无标注不变 | 空交接进训练页（模拟训练诚实回退） | `test_goto_train_no_annotations_navigates` ✅ |
| FR-4 失败诚实停留 | 导出失败 → 不导航 + 状态报错 + pending 清零（不残留到后续手动导出） | `test_goto_train_export_failure_stays` ✅ |
| FR-5 冻结态权重回退 | PyInstaller 6 datas 落 `_internal`（=sys._MEIPASS），ultralytics 按 CWD 解析裸名会 miss 转联网下载（W64 形态）——`_resolve_backbone` CWD 优先、_MEIPASS 回退、.pt 透传 | 三用例 ✅ |

## 3. 范围与实现

- `gui/pages/data_manage/page.py`（792/800）：`_auto_nav_pending` 态；按钮改挂
  `_goto_train`；`_tool_export_dataset` 抽出 `_run_export_worker(out_root,
  force_yolo)`（手动对话框路径与自动补缺共用）；`_op_done` 完成钩子导航 +
  `_op_failed` 清 pending；i18n +1 键（自动导出训练集中）。
- `models/supervised/engines/_yolo_seg_base.py`：`_resolve_backbone` 模块级
  函数（train_epoch 消费；sys 提升模块级导入）。
- 重启丢态由 FR-2 消解（任何时候点都会按需补，无需持久化）。
- 测试：`tests/test_w65_auto_export_handoff.py` 8 用例（RED 5 败→GREEN）。

**Out of Scope**：导出进度条（worker 状态栏反馈已够）；_auto_export 目录的
自动清理（复用同目录覆盖写，exist_ok）。

## 4. 风险与假设

- 大目录（1288 张）首次自动导出复制图片耗时数分钟——状态栏有「自动导出
  训练集中」反馈，按钮禁用防重复触发；产物目录固定 `_auto_export` 可预期。
- 假设：用户接受向导触发的导出 IO（门禁裁决方案 A 明示此代价）。

## 5. 门禁记录

- 门禁 1（探索）：出示即答——**方案 A 自动导出补缺（推荐）** ✅
- 门禁 2（PRD）：并入门禁 1。
- 门禁 3（收尾）：主门禁 1264 绿+6 skipped / ruff 0 / 行数 792/800；exe 已
  重打包（9/28 15:0x）PYZ 复验 PASS（W65 符号+权重在 _internal）；
  **commit 待用户批准（铁律 7）**。

## 6. AC 核验回填

| AC | 结果 |
|---|---|
| 定向 22 用例（W65+W58+W63） | ✅ 3.00s |
| 主门禁（首轮） | ❌ ruff 2×F401（W64 遗留未用导入）——清理后复跑 |
| 主门禁（复跑） | ✅ 1264 passed + 6 skipped / ruff 0 |
| exe 重打包+PYZ | ✅ `_goto_train`/`_auto_nav_pending`/`_resolve_backbone` 全在位；权重 _internal 就位 |
