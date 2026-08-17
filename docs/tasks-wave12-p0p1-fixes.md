# 任务表 — wave12-p0p1-fixes

| 任务 | 内容 | 文件所有权（互斥） | FR | AC |
|---|---|---|---|---|
| TASK-001 | 工作流初始化 + PRD/任务表 + G1/G3 | — | 全部 | 全部 |
| TASK-002 | R1 generic_trainer：fit 分段拆 + 最终 save 失败上抛（RED） | training/generic_trainer.py + 新测试 | FR-001,003 | AC-001,003 |
| TASK-003 | R2 eval_ 页：_run_eval/_work 业务抽 evaluation 层纯函数 + 直测 | gui/pages/eval_/page.py + evaluation/（新函数所在文件）+ 新测试 | FR-001 | AC-001 |
| TASK-004 | R3 gui 机械拆 ×6：train/data_manage/label/predict _build_ui、theme._build_qss、shell._build_shell + closeEvent audit flush | gui/pages/{train,data_manage,label,predict}/page.py、gui/core/theme.py、gui/core/shell.py | FR-001,004 | AC-001,004 |
| TASK-005 | F1 shm：启动清扫陈旧文件 + 区域上限（RED） | serving/shared_memory.py + 新/扩测试 | FR-002 | AC-002 |
| TASK-006 | F2 FID sqrtm 对称化（RED + scipy 对照） | evaluation/generative_metrics.py + 新/扩测试 | FR-005 | AC-005 |
| TASK-007 | F3 audit atexit + deploy 审计日志（RED） | core/audit_logger.py、gui/pages/deploy/page.py + 测试 | FR-004 | AC-004 |
| TASK-008 | F4 RCE 3 用例 + lock index-url + README | tests/ 新文件、requirements.lock.txt、README.md | FR-006,007 | AC-006,007 |
| TASK-009 | 对抗验证全部簇 → 闭环 needs_fix | 只读 + 文件级 stash 复现 | FR-008 | AC-008 |
| TASK-010 | 门禁全量 + 棘轮 + pytest.ini 注释刷新 + exe 重打包 + UIA 回归 | pytest.ini（注释） | FR-008 | AC-008 |
| TASK-011 | state 终态 + validate + 提交 + 记忆 | .workflow/、记忆 | FR-008 | AC-008 |

> 并行约束：TASK-002 与 003/004 文件不相交；shell.py 归 TASK-004（audit 的 closeEvent flush 在其内）；audit_logger.py 归 TASK-007。TASK-005/006/007/008 各自独占其生产文件。
