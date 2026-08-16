# 任务表 — wave9-gui-pages

| 任务 | 内容 | FR | AC |
|---|---|---|---|
| TASK-001 | label 页补测：文件夹/单图加载、导航、模式/标签、撤销重做/删除/复制粘贴、保存三态+自动切图、run_ai_prelabel 双路径、>500 上限 | FR-001 | AC-001 |
| TASK-002 | data_manage 页补测：目录定位/刷新/统计、_run_worker 成败、划分三闸门+确认、七个标注工具与 YOLO/COCO 导出 | FR-002 | AC-002 |
| TASK-003 | train 页+worker+EngineTrainStrategy 补测（FakeWorker 信号注入） | FR-003 | AC-003 |
| TASK-004 | project/home/settings/main/thumbnail 补测 + ThumbnailTask QImage 线程安全化（RED：现 QPixmap 在工作线程） | FR-004, FR-005 | AC-004, AC-005 |
| TASK-005 | 全量组合覆盖、pytest.ini 棘轮升门至新地板、state 终态、validate_workflow、提交、记忆 | FR-006 | AC-006 |
