# 任务表 — wave13-config-resume-audit

| 任务 | 内容 | 文件所有权（互斥） | FR | AC |
|---|---|---|---|---|
| TASK-001 | 工作流初始化 + PRD/任务表 + G1/G3 | — | 全部 | 全部 |
| TASK-002 | C1 config 删除收敛 + device 回灌（RED） | core/config.py、configs/default.yaml（删）、gui/main.py、gui/pages/predict/page.py、gui/pages/settings/page.py（仅读侧收敛）、tests/test_config.py、tests/test_gui_predict_tail.py（仅追加） | FR-001,002 | AC-001,002 |
| TASK-003 | C2 trainer resume 边界（RED） | training/generic_trainer.py、tests/test_trainer_save_fail.py（追加）或新文件 | FR-003 | AC-003 |
| TASK-004 | C3 审计用户归属 + 登录审计（RED） | core/audit_logger.py 或新 core/session.py、gui/pages/login/page.py、gui/pages/deploy/page.py、gui/pages/predict/page.py（仅审计调用行）⚠️与 C1 共享 predict/page.py——见下方串行约束 | FR-004 | AC-004 |
| TASK-005 | 对抗验证三簇（复跑+RED stash+假绿+越界） | 只读 | FR-005 | AC-005 |
| TASK-006 | 门禁全量 + 棘轮判定 + pytest.ini 注释 + state 终态 + validate + 提交 + 记忆 | pytest.ini | FR-005 | AC-005 |

> 并行约束：C1 与 C3 都触碰 gui/pages/predict/page.py——C1 只改设备解析段（:245-267 附近），
> C3 只改审计调用行（:324-326 附近），两者不相交；若编排为并行簇，各自 Edit 前重读文件即可，
> 验证员越界判定按"段落归属"而非整文件。
