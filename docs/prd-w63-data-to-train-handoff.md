# PRD-Lite：W63 数据管理「下一步：训练」数据集上下文交接

- 版本：v1.0（2026-09-22）
- 档位：🟡L2（三门禁：探索✅ / PRD 并入本轮✅ / 收尾✅）
- 关联：W62（标注→数据管理交接，同日落地）——本笔补全向导链最后一跳

## 1. 背景与目标

用户指令：「同样，检查从数据管理页面点击下一页进入训练页面的时候，是否自动
载入前面的设置」。取证结论：**现态零交接**（W62 有意划出范围）——只切页，
刚导出的训练集不会带入训练页，训练保持「未选择（模拟训练）」。

真实任务（JTBD）：用户当在数据管理导出完训练集时，希望点「下一步：训练」
落地即见该数据集已选好、样本统计已回显，以便直接开始训练不用再找 yaml。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 导出成功记产物 | YOLO 导出成功后 `last_dataset_yaml`==`{out}/yolo/data.yaml`（真实落盘）；COCO 分支不记（无 yaml，诚实） | `test_export_yolo_captures_dataset_yaml` / `test_export_coco_does_not_capture` ✅ |
| FR-2 训练页接收外部数据集 | `apply_external_dataset(yaml)`：txt_data 填入+统计回显（train=N val=M） | `test_train_apply_external_dataset` ✅ |
| FR-3 向导接线 | emit request_page("train") 自动带入；未导出（空串）零操作不覆盖既有选择 | `test_build_window_handoff_data_to_train` / `..._no_export_noop` ✅ |
| FR-4 存量不回归 | W62 交接、W58 真训练通道行为不变 | 20 定向绿 + 主门禁 ✅ |

## 3. 范围与实现

- `gui/pages/data_manage/page.py`（759 行）：`__init__` 记 `_last_export_yaml=""`；
  YOLO 导出 work() 成功路径记产物路径（worker 线程单次 attr 写，GIL 原子，
  invoke_main 跳给先后序）；`last_dataset_yaml` 只读属性。
- `gui/pages/train/page.py`（595 行）：`apply_external_dataset`（镜像
  `_browse_data_yaml` 无对话框版：填入+`_echo_dataset_stats`）。
- `gui/main.py`：`_wire_data_to_train_handoff`（对称 W62 wire 函数；
  空串零操作）；build_window 一行调用。
- 测试：`tests/test_w63_data_to_train_handoff.py` 6 用例（RED 5 败→GREEN）。

**Out of Scope**（探索门禁已示）：全向导链延伸（推理/评估页交接）未纳入；
向导点击时现场生成 data.yaml 已否决（惊吓 IO+与导出按钮职责重叠）。
训练页 epochs 等超参不属数据管理「设置」，无从交接。

## 4. 语义要点（与 W58 诚实回退的相容性）

- 未导出过 → 零操作 → 训练页仍「未选择（模拟训练）」（W58 设计不变）。
- 有导出 → 覆盖 txt_data=最新导出意图；**真实训练仍需显式「开始训练」**，
  交接只带上下文不触发任何重活。
- data.yaml 的 `path:` 键为绝对路径（format_export 写入 `out.resolve()`），
  换机会话仍有效。

## 5. 门禁记录

- 门禁 1（探索）：出示未响应（~1 分钟）→ S1 按用户消息（即显式指令）实施
  推荐项「带最近 YOLO 导出」，记偏差。
- 门禁 2（PRD）：并入门禁 1 出示。
- 门禁 3（收尾）：主门禁全绿；**commit 与 W62 一并待用户显式批准**（铁律 7）。

## 6. AC 核验回填

| AC | 结果 |
|---|---|
| 定向 20 用例（W63+W62+W58 真训练通道） | ✅ 3.42s |
| 主门禁 | ✅ 1256 passed + 6 skipped / 77.95s / ruff 0 / 行数 759/595 守卫内 |
