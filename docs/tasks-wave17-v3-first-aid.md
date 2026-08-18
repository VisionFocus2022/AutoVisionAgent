# v3 第一波止血 — 任务列表 (L2)

> 关联: prd-wave17-v3-first-aid.md v1.0 | 估算: ~3 人日

## 任务列表

### Task 1: RED — det 评估 M≠N 失败测试族
- **步骤**: 1. 在 tests/test_eval_flow.py 扩展用例：N=0(M=1)、N>M(M=1,N=3)、N<M(M=3,N=1) 三形态（桩引擎返回对应 boxes/scores/labels）断言 run_supervised_eval 不抛 IndexError；scores 真实性用例（两框 0.9/0.4 断言 AP 按分数序）；M==N 回归锚定用例 2. 运行确认因当前缺陷失败（IndexError 或断言失败）
- **涉及文件**: `tests/test_eval_flow.py`
- **验证**: `pytest tests/test_eval_flow.py -o addopts= -q` → 新用例 RED（失败原因正是缺陷行为）

### Task 2: GREEN — build_prediction/det_map 修复
- **步骤**: 1. build_prediction 构造定长三数组（labels=[0]*N、scores=result.scores 优先）2. det_map 长度不一致防御 3. 跑 Task1 用例转绿 + 既有 eval 测试回归
- **涉及文件**: `evaluation/eval_flow.py`、`evaluation/metrics_supervised.py`
- **验证**: `pytest tests/test_eval_flow.py tests/test_metrics_supervised.py -o addopts= -q` → 全绿

### Task 3: RED — shm TTL 清扫失败测试
- **步骤**: 1. 用例：短 TTL 下登记 2 区域→休眠→再写入→断言在册区域回落且文件删除（monkeypatch time 或注入 TTL）2. TTL 关闭(≤0)不回收 3. 清扫后仍超上限保持 RuntimeError 4. 运行确认失败
- **涉及文件**: shm 既有测试文件（tests/ 下 shared_memory 相关，实现时定位）+ 新用例
- **验证**: `pytest tests/<shm 文件> -o addopts= -q` → 新用例 RED

### Task 4: GREEN — SharedMemoryManager TTL
- **步骤**: 1. 区域登记携带 created_at（time.monotonic）2. 写入口 `_reap_expired()`（mm.close→os.close→unlink）先于写盘与上限判定 3. AVA_SHM_REGION_TTL_SECONDS 解析（构造参>环境变量>默认300，≤0 关闭）4. Task3 用例转绿 + 既有 shm 测试回归
- **涉及文件**: `serving/shared_memory.py`
- **验证**: `pytest tests/<shm 文件> -o addopts= -q` → 全绿

### Task 5: proto 内联字段 + pb2 重生成 + Python 序列化内联（RED→GREEN）
- **步骤**: 1. RED：serialization 内联用例（小掩码→masks_inline 非空且不建区域/大掩码→走 shm）2. proto 加 `bytes masks_inline = 10; bytes keypoints_inline = 11;` 3. 安装 grpcio-tools（对齐 grpcio 1.83.0）重生成 pb2/pb2_grpc，lock 追加 4. serialization 实现 nbytes<64KiB 内联分支 5. 用例转绿 + serving 全测试回归
- **涉及文件**: `serving/proto/autovisionagent.proto`、`serving/proto/autovisionagent_pb2*.py`（生成物）、`serving/serialization.py`、`requirements.lock.txt`
- **验证**: `pytest tests/test_serving_serialization*.py tests/test_serving_server.py -o addopts= -q` → 全绿

### Task 6: C# Mapper 内联解码 + xUnit（RED→GREEN）
- **步骤**: 1. 先查 AutoVisionAgentClientTests.cs 是否锚定 Release 恒 True 旧行为（记录）2. RED：Mapper 内联 bool_rle/raw 解码用例 3. DetectionResultMapper 优先读内联（复用/提取 Reader 的 RLE 解码）4. `dotnet test` 全绿
- **涉及文件**: `serving/dotnet_client/Services/Vision/DetectionResultMapper.cs`、`SharedMemoryReader.cs`（如需提取解码）、`Tests/Vision/*`
- **验证**: `cd serving/dotnet_client && dotnet test` → rc=0 全绿

### Task 7: Release 语义与上限文案（RED→GREEN）
- **步骤**: 1. RED：miss 路径 success=False + error 非空用例 2. server.py ReleaseSharedMemory 按 release() 返回值回传 + logger.warning 3. 上限错误文案加 TTL/Release 指引 4. C# 测试若受影响同步更新（Task 6 预查结论）
- **涉及文件**: `serving/server.py`、`serving/shared_memory.py`（文案）、相关测试
- **验证**: `pytest tests/test_serving_server.py -o addopts= -q` → 全绿

### Task 8: on_error 收口（RED→GREEN）
- **步骤**: 1. RED：thread_bridge.ui_on_error 单测（闭包经 invoke_main 到达 @Slot(str)）+ 逐页"元组外异常→按钮恢复+状态栏"offscreen 用例（10 消费点页面各≥1 + eval IndexError 专例 + deploy ModelExportError 专例）+ 守卫测试（源码断言 run_job 调用含 on_error=）2. GREEN：ui_on_error 实现 + 10 处接线 + 缺失败槽页面补 @Slot(str) + deploy/label 元组补 AppError 3. 全部转绿
- **涉及文件**: `gui/core/thread_bridge.py`、`gui/pages/{predict,eval_,label,data_manage,deploy,flaw_gen}/page.py`、新测试文件
- **验证**: `pytest tests/test_thread_bridge*.py tests/<新 on_error 测试> -o addopts= -q` → 全绿

### Task 9: 验证（强制末位任务）
- **步骤**: 逐条核对 AC-001~011；全量门禁；C# 全量；状态验证器
- **验证**: `pytest`（全量，覆盖率≥92）rc=0 + `dotnet test` rc=0 + `python <skill>/scripts/validate_workflow.py .workflow/wave17-v3-first-aid/state.json` rc=0

---

## 执行约定

- **每任务完成**跑自己的验证命令，全过才标记 completed。
- **修复尝试上限**: 连续失败 2 轮先诊断需求、设计或环境；只精确还原本任务修改，不触碰无关变更。
- **进度汇报**: 每完成 3 个任务汇报一次。
- **偏差记录**: 实际与计划不符时写入状态；任一风险维度变重或命中硬触发器时重新定档。

## 依赖与顺序

T1→T2（评估）；T3→T4（TTL）；T5→T6→T7（proto/C#/Release 有序）；T8 独立可并行；T9 末位收口。
