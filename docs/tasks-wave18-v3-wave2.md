# v3 第二波可测化解耦 — 任务列表 (L2)

> 关联: prd-wave18-v3-wave2.md v1.0 | 估算: ~3 人日 | 执行形态: 六簇并行（A1→A2 顺序链），主审终审

## 任务列表

### Task 1 (簇 A1): RED→GREEN 退出链补完 + train INFO
- **步骤**: 1. RED：批量 cancel 置位即停用例（Event 置位→循环 ≤1 批退出）；TrainWorker 无 parent+deleteLater 源码/行为断言；closeEvent 超时日志语义用例 2. GREEN：predict 批量 `_work(cancel)` 并联检查；train/page.py 去 parent + finished.connect(deleteLater)；shell.py 超时告警日志；train 页训练开始/完成 INFO 3. 回归：shell 退出守卫/jobs/predict/train 页测试族
- **涉及文件**: `gui/pages/predict/page.py`、`gui/pages/train/page.py`、`gui/pages/train/worker.py`、`gui/core/shell.py`、相关测试
- **验证**: `pytest tests/test_gui_predict_tail.py tests/test_gui_train_page.py tests/test_gui_shell_exit_guard.py tests/test_jobs.py -o addopts= -q` 全绿

### Task 2 (簇 A2, 依赖 Task 1): RED→GREEN registry 直连正式化
- **步骤**: 1. RED：gui 包 dispatcher 引用=0 守卫、_EngineStub=0 守卫、exporter 新签名直测、label 零样本桥删除后诚实报错用例 2. GREEN：删 label 桥；exporter.export_onnx 改签名（先全仓 grep 调用点）；deploy 页改造；vision_dispatcher/gui 注释声明正式架构；torch.load 两处注释 3. 回归：exporter/deploy/label/flaw_gen/serving 测试族
- **涉及文件**: `gui/pages/label/page.py`、`exporter/supervised_exporter.py`、`gui/pages/deploy/page.py`、`industrial_vision_platform/vision_dispatcher.py`(docstring)、`training/generic_trainer.py`(注释)、gui 各页 registry 注释、相关测试
- **验证**: `pytest tests/test_exporter*.py tests/test_gui_deploy*.py tests/test_gui_label_page.py tests/test_serving_server.py tests/test_dispatcher*.py -o addopts= -q` 全绿

### Task 3 (簇 B): RED→GREEN 角色枚举化 + login 诚实文档
- **步骤**: 1. RED：中文旧值迁移用例、en_US 显示/持久分离用例、新注册写枚举断言 2. GREEN：稳定枚举常量+迁移映射+下拉 userData；login_success 传枚举；QTimer 死导入删；license docstring/checklist/chmod 注释改诚实表述 3. 回归：login/audit/session 测试族
- **涉及文件**: `gui/pages/login/page.py`、`docs/release-checklist.md`、相关测试
- **验证**: `pytest tests/test_gui_login*.py tests/test_gui_misc_pages.py -o addopts= -q` 全绿（以实际 login 测试文件为准）

### Task 4 (簇 C): RED→GREEN serving 告警 + serialization 回滚
- **步骤**: 1. RED：非回环 host WARNING 用例；keypoints 写失败→masks 区域释放故障注入用例 2. GREEN：create_server 告警；detection_result_to_proto 局部回滚 3. 回归：serving 全族
- **涉及文件**: `serving/server.py`、`serving/serialization.py`、相关测试
- **验证**: `pytest tests/test_serving_server.py tests/test_serving_serialization.py tests/test_shm_lifecycle.py -o addopts= -q` 全绿

### Task 5 (簇 D): det_map 拆分（纯重构，数值零变化）
- **步骤**: 1. 记录拆分前既有期望值锚（不改断言） 2. 按职责拆内部函数（全部 ≤100 行） 3. AST 复测 + _extract_state_dict_safe 豁免注释
- **涉及文件**: `evaluation/metrics_supervised.py`、`core/interfaces_supervised.py`(注释)、tests（仅新增 AST/注释断言，不改既有期望）
- **验证**: `pytest tests/test_metrics_supervised.py tests/test_eval_flow.py tests/test_m2_matrix.py -o addopts= -q` 全绿 + AST 全部函数 ≤100 行

### Task 6 (簇 E): spec 图标 + FID 样本帽
- **步骤**: 1. RED：max_images 参数化用例（传 5 → fid 收 ≤5 张 mock 断言） 2. GREEN：run_generative_eval/run_eval_task 加参；spec 删死图标条件+注释 3. 回归
- **涉及文件**: `evaluation/eval_flow.py`、`autovisionagent.spec`、相关测试
- **验证**: `pytest tests/test_eval_flow.py -o addopts= -q` 全绿 + spec 无死条件

### Task 7 (簇 F): ci.yml 就绪
- **步骤**: 1. 加 pip cache 2. 加 dotnet job（与本地命令一致） 3. 注释 cu121/cpu 权衡与首跑前置 4. yaml.safe_load 解析验证 + dotnet job 步骤自检
- **涉及文件**: `.github/workflows/ci.yml`
- **验证**: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))"` rc=0（无 yaml 包则用 ruamel/手检缩进并记偏差）

### Task 8 (主审): 全量验证
- **步骤**: AC-001~012 逐条核对；全量 pytest（≥92%）；dotnet test；AST 巨石复测；状态验证器
- **验证**: `pytest` rc=0 + `dotnet test` rc=0 + `validate_workflow.py` rc=0

## 执行约定

- **每任务完成**跑自己的验证命令，全过才标记 completed；TDD 先红后绿留痕。
- **簇并行、簇内顺序**（A1→A2 共享文件必须顺序）；各簇不得越界改他人簇文件。
- **修复尝试上限**: 连续失败 2 轮先诊断；只精确还原本任务修改。
- **偏差记录**: 实际与计划不符写入状态（含测试文件名与实际入口差异）。

## 依赖与顺序

Task1→Task2（共享 shell/train/predict 文件）；Task3/4/5/6/7 与 A 链并行；Task8 末位收口。
