# 任务表 — wave6-sv-infra

| 任务 | 内容 | FR | AC |
|---|---|---|---|
| TASK-001 | 滑窗 sv 后端：RED（test_tiling_sv：合成图两后端找回全物体/跨瓦片无重复/sv→DetectionResult 回转）→ 实现 tile_infer_sv → A/B benchmark | FR-001 | AC-001 |
| TASK-002 | 掩码 RLE shm：RED（test_mask_codec：往返/压缩比/shm 读写/环境开关两态）→ 实现 mask_codec + shm/serialization 接线 → 全量回归 | FR-202 | AC-002, AC-003 |
| TASK-003 | 收尾：门禁全量 + 棘轮、state 终态、validate_workflow、提交与记忆 | FR-001, FR-202 | AC-003 |
