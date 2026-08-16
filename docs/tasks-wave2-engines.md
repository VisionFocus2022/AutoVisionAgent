# wave2-engines — 任务列表 (L2)

> 关联: prd-wave2-engines.md v1.0 ｜ 每任务独立验证、独立提交

## 任务列表

### Task 1: 移植 det_yolo（FR-001）
- RED 基线=现 10 红；移植 det_yolo.py + test_engine_det_real.py → det 相关 3 红转绿
- 涉及: `models/supervised/engines/det_yolo.py`、`tests/test_engine_det_real.py`、engines/__init__ 清单
- 验证: `pytest tests/test_engine_det_real.py tests/test_m2_matrix.py -q` → det 绿

### Task 2: 移植 _yolo_seg_base + seg_yolo（FR-002）
- 涉及: `models/supervised/engines/_yolo_seg_base.py`、`seg_yolo.py`、清单
- 验证: seg 相关 2 红转绿

### Task 3: 移植 abdet_anomalib（FR-003，适配 extra）
- 涉及: `abdet_anomalib.py`（anomaly_map→extra、score None→0.0）、`tests/test_engine_abdet_real.py`（断言适配）
- 验证: abdet 2 红转绿 + test_all_9_tasks_registered 绿（7 矩阵红清零）

### Task 4: sgan/super 真化（FR-004）
- 涉及: `core/path_io.py`（移植）、`core/image_io.py`（+imwrite_unicode）、`sgan_blend.py`（_to_numpy→imread_unicode）、`super_cv2.py`（同）、删 `sgan_mmedit.py`/`super_mmedit.py`、清单换名、`tests/test_engine_m2_contracts.py` 导入换、`tests/test_engine_sgan.py`（移植）、super 契约测试（新）
- 验证: m2_e2e 3 注册红转绿 + sgan/super 测试绿 + grep 无 score=1.0 假路径

### Task 5: flaw_gen 重写引擎段（FR-005）
- 涉及: `gui/pages/flaw_gen/page.py`（get_engine + load(flaw_database) + infer + imwrite_unicode + 显式 SupervisedEngineError 捕获 + 删 copy2 假回退）
- 验证: 页面构造 offscreen 测试 + 注册接线断言（SGAN→SganBlendEngine）

### Task 6: 跟进项（FR-006）
- 涉及: engines/__init__ docstring 9/9、`autovisionagent.spec` hiddenimports 9 引擎
- 验证: grep 双检

### Task 7: 最终验证（强制末位）
- 全量（排 uia）**0 failed**；AC-001..006 逐条核对；validate_workflow.py 0

## 执行约定

- 每任务独立提交；失败两轮先诊断；偏差记录（如接口适配细节）。
