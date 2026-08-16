# wave1-stabilize — 任务列表 (L2)

> 关联: prd-wave1-stabilize.md v1.0 ｜ 每任务独立验证、独立提交（回滚粒度）

## 任务列表

### Task 1: git 基线（FR-001）
- **步骤**: .gitignore 追加 .codegraph/ → git init → add -A → 基线提交
- **涉及文件**: `.gitignore`
- **验证**: `git log --oneline` 有基线提交 + `git status --short` 干净 → AC-001
- **状态**: ✅ af972d6

### Task 2: venv 归位 + 锁定（FR-002）
- **步骤**: cp -a 兄弟树 .venv → 验证 import + cuda → 用 venv 跑测试链 → pip freeze 生成 lock
- **涉及文件**: `.venv/`（不提交）、`requirements.lock.txt`
- **验证**: venv python 导入 PySide6/torch 且 cuda=True；pytest 全收集 → AC-002

### Task 3: RED — dispatcher 线程安全测试（FR-003）
- **步骤**: 新建 tests/test_dispatcher_threading.py（单线程语义回归 + 8 线程压力），先跑确认基线（压力不炸属预期——竞态窗口窄，记偏差；语义回归应全绿）
- **涉及文件**: `tests/test_dispatcher_threading.py`
- **验证**: `py -3.12 -m pytest tests/test_dispatcher_threading.py -q` → 语义回归绿

### Task 4: GREEN — dispatcher 加锁（FR-003）
- **步骤**: vision_dispatcher 加 RLock：load_supervised 驱逐段入锁（unload 锁外）、infer_supervised check+move+get 入锁（infer 锁外）、loaded_tasks 快照入锁
- **涉及文件**: `industrial_vision_platform/vision_dispatcher.py`
- **验证**: Task3 测试全绿 + test_m2_matrix 中 dispatcher 用例不劣化 → AC-003

### Task 5: RED — 中文路径读图测试（FR-004）
- **步骤**: 新建 tests/test_image_io.py：中文目录+中文文件名 PNG，断言 imread_unicode 可读（现状：模块不存在，RED）+ VisionDataset 中文路径 image 非 None（现状：None，RED）
- **涉及文件**: `tests/test_image_io.py`
- **验证**: RED 两处（ModuleNotFoundError / image is None）

### Task 6: GREEN — imread_unicode + 5 处替换（FR-004）
- **步骤**: 新建 core/image_io.py → 替换 label:467,519 / predict:269,362 / dataset:64
- **涉及文件**: `core/image_io.py`、`gui/pages/label/page.py`、`gui/pages/predict/page.py`、`dataset/vision_dataset.py`
- **验证**: Task5 测试全绿 + grep 无残留裸 imread（gui/dataset 内）→ AC-004

### Task 7: RED — 诚实化测试（FR-005）
- **步骤**: 新建 tests/test_tasks_ui.py（populate_task_combo 单元 + TrainPage/PredictPage 下拉 + 假 loss 警告，offscreen）；先跑确认 RED
- **涉及文件**: `tests/test_tasks_ui.py`
- **验证**: RED（ModuleNotFoundError: gui.core.tasks_ui / 下拉项数 3≠9 / 无警告）

### Task 8: GREEN — tasks_ui + 三页接线 + 警告（FR-005）
- **步骤**: gui/core/tasks_ui.py → train/predict 下拉改造（train 首项保持 DET）→ train _make_trainer 两条静默路径警告 → eval GT 回退警告 → engines docstring 6/9
- **涉及文件**: `gui/core/tasks_ui.py`、`gui/pages/train/page.py`、`gui/pages/predict/page.py`、`gui/pages/eval_/page.py`、`models/supervised/engines/__init__.py`
- **验证**: Task7 全绿 → AC-005/006/007

### Task 9: test_gui.py API 对齐（FR-005 附带，偏差记录）
- **步骤**: 对照当前 shell API 修 test_gui（_stack/_pages dict/_toggle_theme 等）
- **涉及文件**: `tests/test_gui.py`
- **验证**: venv 跑 test_gui 全绿

### Task 10: 最终验证（强制末位）
- **步骤**: 逐条核对 AC-001..008；venv 全量测试（已知红：7 项引擎矩阵=W2 范围）；validate_workflow.py
- **验证**: AC 全过 + `pytest` 实际结果如实记录 + 验证器退出码 0

---

## 执行约定

- 每任务完成跑自己的验证命令，全过才标记 completed；每代码任务一个 git 提交。
- 修复尝试上限：连续失败 2 轮先诊断需求/设计/环境；只精确还原本任务修改。
- 偏差记录：Task 3 竞态 RED 不可确定性复现（记偏差）；Task 9 范围扩展（记偏差）。
