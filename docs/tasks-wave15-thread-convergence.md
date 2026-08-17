# 任务表 — wave15-thread-convergence

| 任务 | 内容 | 文件所有权（互斥） | FR | AC |
|---|---|---|---|---|
| TASK-001 | 工作流初始化 + PRD/任务表 + G1/G3 | — | 全部 | 全部 |
| TASK-002 | J1 jobs.py 统一入口+注册表+单测 | gui/core/jobs.py（新）、tests/test_jobs.py（新） | FR-001 | AC-001 |
| TASK-003 | L1 serving 文件轮转日志 | serving/server.py（serve 入口段）、tests/test_serving_server.py（追加） | FR-002 | AC-002 |
| TASK-004 | M1 setuptools+待命 CI+offscreen 兜底 | requirements.lock.txt、.github/workflows/ci.yml（新）、tests/conftest.py（新根） | FR-003 | AC-003 |
| TASK-005 | J2 三页迁移+日志+docstring（依赖 J1） | gui/pages/{data_manage,eval_,flaw_gen}/page.py、相关测试追加 | FR-004 | AC-004 |
| TASK-006 | J3 三页迁移+日志+predict 原子写（依赖 J1） | gui/pages/{label,predict,deploy}/page.py、相关测试追加 | FR-004 | AC-004/006 |
| TASK-007 | J4 shell 退出守卫+生命周期（依赖 J1） | gui/core/shell.py、tests（新/追加） | FR-005 | AC-005 |
| TASK-008 | A1 batch_tools 原子化+DataManagerExt 删除 | labeling/batch_tools.py、industrial_vision_platform/{data_manager_ext.py（删）,__init__.py}、tests/test_data_manager_ext_deep.py（删） | FR-006 | AC-006 |
| TASK-009 | 对抗验证七簇 | 只读+文件级 stash | FR-007 | AC-007 |
| TASK-010 | 门禁全量+棘轮+pytest.ini 注释+终态+validate+提交+记忆 | pytest.ini | FR-007 | AC-007 |

> 阶段约束：TASK-005/006/007 必须在 TASK-002 完成后启动（读 jobs.py 实际 API）。
