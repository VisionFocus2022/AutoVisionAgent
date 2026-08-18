# 任务清单：wave19-v3-wave3

每项任务关联 PRD 的 FR/AC；执行遵循 TDD（RED→GREEN→REFACTOR），证据记入 `.workflow/wave19-v3-wave3/state.json`。

## 阶段一：并行簇（Workflow 六簇，文件面互不相交）

### TASK-001（簇A）性能基线体系 → FR-1 / AC-1.1~1.3
1. RED：tests/test_w19_benchmarks_meta.py（collect-only 守卫，目录不存在时必红）。
2. GREEN：benchmarks/bench_infer.py、bench_vram.py、bench_coldstart.py + conftest（如需）。
3. 本机实测跑三组 → benchmarks/summarize.py 生成 docs/benchmarks/baseline-2026-08-18.json + README 表。
4. 证据：collect 守卫绿 + 基线运行 rc=0 + 基线文件三组数字。

### TASK-002（簇B）协议双方向 PoC → FR-2 / AC-2.1~2.4
1. RED：lease 归属三态测试（正确释放/错误拒绝/lease 期内 TTL 不回收）+ FetchRegion 逐字节相等测试。
2. GREEN：proto additive 字段 6/7 + ArrayChunk/FetchRegion rpc + pb2 重生成 + shared_memory lease 注册表 + server 流式实现。
3. 微基准脚本（≥64MiB，直读 MMF vs 流式，≥10 轮）跑数。
4. ADR-0002 撰写（数据先行，结论按数据写）。
5. 回归：tests/test_serving_*、test_shm_lifecycle、test_mask_codec 全绿；C# dotnet build+test 复验（主审亦可收口复核）。

### TASK-003（簇C）dist lite → FR-3 / AC-3.1~3.3
1. RED：resolve_device 护栏测试（torch 系引擎 cuda 不可用→cpu）+ make_lite_dist 假树匹配单测（含负例）。
2. GREEN：公共助手 + 各 torch 引擎 load 接入 + scripts/make_lite_dist.py + tests/test_w19_lite_dist.py。
3. 证据：单测绿 + 既有引擎测试回归绿。（重打包与真派生归主审 TASK-006。）

### TASK-004（簇D）数据集版本管理 → FR-4 / AC-4.1~4.4
1. RED：全生命周期 + verify 检出污染 + restore 非破坏性三组测试。
2. GREEN：project/versioning.py。
3. RED：页面入口测试（按钮/后台执行/失败复位）。
4. GREEN：data_manage 页两按钮 + 对比摘要对话框（run_job+on_error+tr+retranslate）。
5. 回归：project 包既有测试绿。

### TASK-005（簇E）密码卫生 + lock → FR-5 / FR-6 / AC-5.1~5.5 / AC-6.1
1. RED：日志无明文 + 一次性文件 + must_change 拦截 + 敏感过滤 + lock diff 校验测试。
2. GREEN：login/page.py（initial_credentials.txt + 改密 QDialog + 拦截逻辑）+ 日志过滤 + lock 补 6 包。
3. 回归：tests/test_gui_login_page.py 等既有登录族测试；freeze↔lock diff 清零证据。

## 阶段二：主审收口（TASK-006）→ 全部 AC

1. 全量门禁 `.venv/Scripts/python.exe -m pytest`（期望 0 failed；覆盖棘轮维持 92 门槛，实测值记录）。
2. AST >100 行函数守卫复跑（不得新增——closeEvent 教训）。
3. exe 重打包 `pyinstaller autovisionagent.spec --noconfirm` → `scripts/make_lite_dist.py` 派生 → 蒸馏冒烟（PYTHONPATH=_internal import torch CPU 回退）→ 双产物体积记录。
4. dotnet build + dotnet test（proto 再生成后）54 绿复验。
5. README/release-checklist 对齐（FR-6.2）。
6. state.json 证据/偏差收口 + validate_workflow.py rc=0。
7. 记忆文件 wave19 段落追加。

## 依赖与并行

- 簇A~E 文件面互斥（benchmarks/、serving/、models+scripts、project+gui/pages/data_manage、gui/pages/login+requirements.lock），可全并行。
- README/release-checklist/ci.yml 仅主审碰。
- proto（簇B）重生成后 C# 编译复验放主审，簇B 内 Python 侧自证。
