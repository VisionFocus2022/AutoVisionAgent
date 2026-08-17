# 任务表 — wave14-p2-residuals

| 任务 | 内容 | 文件所有权（互斥） | FR | AC |
|---|---|---|---|---|
| TASK-001 | 工作流初始化 + PRD/任务表 + G1/G3 | — | 全部 | 全部 |
| TASK-002 | C1 eval 诚实化（P2-9） | gui/widgets/ConfusionMatrixWidget 所在文件、gui/pages/eval_/page.py、eval 相关测试 | FR-001 | AC-001 |
| TASK-003 | C2 线程契约（P2-15/16） | gui/pages/deploy/page.py、gui/core/thread_bridge.py、threaded/deploy 测试 | FR-002 | AC-002 |
| TASK-004 | C3 静默 except+死代码+杂修（P2-13/11/18/17/23） | serving/server.py、serving/serialization.py、gui/pages/home/page.py、training/generic_trainer.py（一行注释）、models/supervised/registry.py、run_m3_verification.py、gui/pages/train/page.py（audit 接线）、gui/pages/login/page.py、docs/adr/0001、相关测试 | FR-003 | AC-003 |
| TASK-005 | C4 覆盖尾巴（P2-24） | .coveragerc（新）、tests/（shm/trainer/metrics 补测新文件）、tests/test_gui_predict_tail.py（跟进项）、可选 venv 装包 | FR-004 | AC-004 |
| TASK-006 | C5 注册表+单实例+守卫（P2-12/14/10） | gui/pages/__init__.py、gui/main.py、labeling/ui/canvas.py（:220）、tests 新守卫文件 | FR-005 | AC-005 |
| TASK-007 | C6 跨语言（P2-4/P2-8） | models/vision_dispatcher.py、gui/pages/label/page.py（回退 warning）、serving/dotnet_client/**、dotnet 测试同步 | FR-006 | AC-006 |
| TASK-008 | 对抗验证六簇 | 只读 + 文件级 stash | FR-007 | AC-007 |
| TASK-009 | 门禁全量 + 棘轮定板 + pytest.ini + 终态 + validate + 提交 + 记忆 | pytest.ini | FR-007 | AC-007 |

> 并行约束：train/page.py 归 C3（audit 接线）、label/page.py 归 C6（回退 warning）、generic_trainer.py 归 C3（一行）、C4 只写测试与新文件不碰生产（.coveragerc 除外）。
