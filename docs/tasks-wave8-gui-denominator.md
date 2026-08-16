# 任务表 — wave8-gui-denominator

| 任务 | 内容 | FR | AC |
|---|---|---|---|
| TASK-001 | eval 页补测：_run_eval 全分支（校验/fid/lpips/supervised 回退/NaN）、三槽、混淆矩阵组件含 paintEvent 离屏 | FR-001 | AC-001 |
| TASK-002 | deploy 页补测：_do_export 全分支（校验/装载解包/格式拒绝/TRT 降级/异常）、完成+失败槽、审计日志 | FR-002 | AC-002 |
| TASK-003 | login 补测：注册许可证三态、锁定持久化、must_change、哈希迁移、默认 admin 首启 | FR-003 | AC-003 |
| TASK-004 | predict+flaw_gen 补测：批/单图推理路径、渲染与导出、缺陷生成 worker | FR-004 | AC-004 |
| TASK-005 | pytest.ini 增 --cov=gui，组合覆盖 ≥74%，棘轮升门至新地板；全量 rc=0、state 终态、validate_workflow、提交、记忆 | FR-005 | AC-005 |
