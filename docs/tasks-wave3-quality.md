# 任务表 — wave3-quality

> 追溯映射：每个 TASK 关联 FR/AC（见 PRD）。执行顺序 = 用户指定：labeling → sseg → 主线程 → 覆盖率门禁。

| 任务 | 内容 | FR | AC |
|---|---|---|---|
| TASK-001 | labeling era-2 语义恢复：先移除 8 个 xfail 得 RED → 实现矩形阈值丢弃/多边形 commit 闭合+points 属性/画笔 <3 点丢弃/canvas add_shape(Shape)+浅快照 undo/redo+replace_all → GREEN → 全量回归 | FR-001 | AC-001 |
| TASK-002 | sseg 真化：移植兄弟树 test_engine_sseg.py（RED）→ 移植 sseg_smp.py → git rm sseg_mmseg.py → 同步 engines/__init__、test_m2_matrix、spec、run_m3_verification → 引擎电池+全量回归 | FR-002 | AC-002 |
| TASK-003 | 主线程迁移：data_manage 导入/划分/批量工具、label AI 预标注、predict 单张推理 → worker 线程 + invoke_main；先读现有实现与测试，纯逻辑抽函数保持可测；页面测试回归 | FR-003 | AC-003 |
| TASK-004 | 覆盖率门禁：serving serialization/shared_memory 单测 → pytest.ini 移植适配（-m "not uia"、strict-markers、包集合）→ 实测覆盖率设 fail-under → pyproject 冲突段收敛 | FR-004 | AC-004 |
| TASK-005 | 最终验证：门禁生效全量 rc=0；state.json 终态；validate_workflow.py；记忆更新；git 提交 | FR-001..004 | AC-001..004 |
