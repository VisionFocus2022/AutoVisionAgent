# 任务表 — wave5-supervision

| 任务 | 内容 | FR | AC |
|---|---|---|---|
| TASK-001 | sv 桥接与渲染：RED（test_sv_bridge：字段映射/类别配色/掩码可见/语义图/空结果）→ 实现 inference/sv_bridge.py → predict `_show_result` 接线（sv 缺失回退旧画法+告警）→ GUI 冒烟 | FR-001 | AC-001, AC-003 |
| TASK-002 | 训练集导出：RED（test_format_export：矩形归一化行/多边形行/data.yaml/COCO 结构/sv 回读闭环/坏 JSON 计数）→ 实现 dataset/format_export.py → data_manage"导出训练集"按钮（worker 线程+格式下拉+i18n）→ FakeThread 测试 | FR-002 | AC-002, AC-003 |
| TASK-003 | 收尾：requirements/spec/lock 随迁 → 全量门禁 rc=0 → state 终态 → validate_workflow → 提交与记忆 | FR-003 | AC-004 |
