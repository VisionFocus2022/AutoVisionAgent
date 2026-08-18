# PRD：v3 第三波现代化全项 + 第一波尾巴（wave19-v3-wave3）

- **来源**：`docs/AutoVisionAgent-架构解析与优化方案-v3.md` §9 第三波 #14-17 + 第一波遗留 #3（P2-2）/#5 部分（lock）。
- **定档**：L2（structured-dev-workflow v4）。可逆 ✓；影响范围 cross_system（serving proto 契约面 additive 改动，C# 编译期再生成需双端复验；其余模块级）；失败可发现性 test_visible；不确定性 low。无硬触发器：proto 仅 additive 且不切默认路径；lite 只裁**派生副本**内文件；快照恢复非破坏性（不删用户新增文件）。
- **G1 证据**（AskUserQuestion 2026-08-18，用户拍板）：
  1. 范围＝"四项全做+两个尾巴（推荐）"
  2. dist 瘦身＝"双产物派生 lite（推荐）"
  3. 协议演进＝"双方向 PoC+ADR-0002（推荐）"
  4. 版本管理＝"核心库+data_manage 入口（推荐）"
- **波前基线**：门禁 894 passed / 3 skipped / 93.01%（W18 终态）；C# 54 passed；AST >100 行函数仅 _extract_state_dict_safe（201，已声明豁免）。dist 实测 4.4G，torch/lib 3.42G 其中 CUDA 栈 ~3.24G（torch_cuda.dll 885M + cudnn* ~997M + cublasLt 514M + 其余）。

## FR-1 性能基线体系（v3 报告 #14，S1 空白）

推理时延 p50/p95/p99、显存峰值、冷启动时间三项纳入 benchmark 体系并落档基线。

- FR-1.1 新建 `benchmarks/` 目录（**不入 pytest 门禁分母**，与 tests/uia 同法显式命令运行：`.venv/Scripts/python.exe -m pytest benchmarks -o addopts= --benchmark-only`，pytest-benchmark==5.2.3 已在 lock）。三个用例组：
  - `bench_infer.py`：det/cls/seg 三任务引擎 CPU 合成权重推理时延（warmup 2 + ≥30 轮，perf_counter 逐轮计时自算 p50/p95/p99——pytest-benchmark stats 无 p99；随机权重构建前 `torch.manual_seed` 固定防 0 检出 flaky）。
  - `bench_vram.py`：det 引擎 GPU 推理显存峰值（`torch.cuda.reset_peak_memory_stats` + `max_memory_allocated`，RTX 3060 实测）；GPU 不可用 → pytest.skip 诚实标注，不伪造。
  - `bench_coldstart.py`：subprocess 计时 `import gui.main`（PySide6 栊）与 `import serving.server`，5 轮 p50。
- FR-1.2 `benchmarks/summarize.py`：汇总 JSON → `docs/benchmarks/baseline-2026-08-18.json` + 人读 Markdown 表（含机器/GPU/torch 版本/模式标注）。
- AC-1.1：`benchmarks/` 三文件 collect 通过且 `--benchmark-only` 运行 rc=0（本机实测）；docs/benchmarks/ 基线文件存在且含三项实测数字。
- AC-1.2：门禁内新增守卫测试 `tests/test_w19_benchmarks_meta.py`：subprocess `pytest benchmarks -o addopts= --collect-only -q` rc=0 且收集用例数 ≥6（防 benchmarks 腐烂；不实际跑基准，CI 友好）。
- AC-1.3：基准数字不进门禁断言（绝对值机器相关，只落档不卡门禁）。

## FR-2 serving 协议演进双方向 PoC + ADR-0002（v3 报告 #15，P1-1 长期）

W17 已有 TTL+小数组内联打底。本波做两方向可测原型 + 微基准 + 决策记录；**不切默认路径，C# 消费端零改动**。

- FR-2.1 方向 A（lease 归属语义）：proto `SharedMemoryHandle` additive 加 `uint64 lease_id = 6; int64 lease_ttl_ms = 7;`；服务端 `shared_memory.py` 加 lease 注册表（lease_id→region/到期时间；`ReleaseSharedMemory` 带 lease 时校验归属，非本 lease 拒绝并 success=False；与 TTL reaper 共存：lease 未到期不被 TTL 回收）。Python in-process 测试双端验证（TDD RED 先行）。
- FR-2.2 方向 B（流式拉取）：proto additive `message ArrayChunk { bytes data = 1; int64 offset = 2; bool last = 3; }` + rpc `FetchRegion(SharedMemoryHandle) returns (stream ArrayChunk)`；服务端实现按 1MiB 块流式回读 MMF 区域；Python 测试客户端收齐校验逐字节相等。
- FR-2.3 微基准：≥64MiB 掩码数组 ①直读 MMF（现状）②FetchRegion 流式拉取，各 ≥10 轮报吞吐/时延中位数，数字写入 ADR-0002。
- FR-2.4 `docs/adr/0002-serving-large-payload-evolution.md`：现状（W17 TTL+inline 已消除小数组区域压力）→ 两方向 PoC 数据 → 决策与理由（预期形态：流式拉取把回收责任移到消费端 pull、消灭服务端猜测 TTL；lease 语义复杂度回报比低 → 决策"暂不切默认路径，部署规模化后再议"，以实测数据为准写，不预写结论）。
- FR-2.5 pb2/pb2_grpc 重生成（grpcio-tools==1.83.0，命令与 W17 同）；C# 侧 Grpc.Tools 编译期从同一 .proto 再生成——`dotnet build` + `dotnet test`（54）复验 additive 不破。
- AC-2.1：lease 归属校验测试（正确 lease 可释放/错误 lease 拒绝/lease 期内 TTL 不回收）RED→GREEN。
- AC-2.2：FetchRegion 收齐逐字节相等测试 + 微基准脚本 rc=0、数字入 ADR-0002。
- AC-2.3：既有 serving 全量测试零回归；C# build+test 通过。
- AC-2.4：默认序列化路径（serialization.py）行为零改动（守卫：既有 inline/shm 用例原样通过即证）。

## FR-3 dist 双产物派生 lite（v3 报告 #16，P3；4.4G→<2G）

- FR-3.1 引擎 device 回退护栏：新增 `resolve_device(device)`（torch 系公共助手，`"cuda"` 但 `torch.cuda.is_available()` False → `"cpu"` + logger.warning 一次）；接入所有以 torch 为后端的引擎 `load()`（det/seg/pose/pseg/cls/abdet/sseg 等实有 device 参数者；cv2 系无 device 概念不动）。TDD：monkeypatch `torch.cuda.is_available`→False，`load(device="cuda")` 后引擎 `_device=="cpu"`。
- FR-3.2 `scripts/make_lite_dist.py`：`dist/AutoVisionAgent` → 复制为 `dist/AutoVisionAgent-lite` → 按 **allowlist 模式**（`torch_cuda.dll`、`cudnn*`、`cublas*`、`cusparse*`、`cufft*`、`cusolver*`、`curand*`、`nvrtc*`、`nvJitLink*`、`cupti*`、`cudart*`，仅匹配 `torch/lib` 下）删除 → 写 `LITE_MARKER.json`（裁剪清单+逐项大小+总量+体积断言）→ 断言 lite 总体积 <2GiB 否则退出非零。manifest 匹配逻辑与文件系统遍历解耦可单测。
- FR-3.3 守卫测试 `tests/test_w19_lite_dist.py`：tmp 假 DLL 树单测 allowlist 匹配（含"不误删 torch_cpu.dll/nvrtc 假名"负例）；`dist/AutoVisionAgent-lite` 存在时断言无 CUDA DLL+体积 <2G+marker 与目录一致，不存在则 skip（CI 无构建产物）。
- FR-3.4 蒸馏后冒烟：子进程 `PYTHONPATH=dist/AutoVisionAgent-lite/_internal` `import torch` + 算子执行 + `torch.cuda.is_available()==False`（证明 CPU 回退成立），冒烟脚本/命令记入 state 证据。
- FR-3.5 主审重打包：`pyinstaller autovisionagent.spec --noconfirm` 后跑 make_lite_dist 派生真 lite 产物，记录两产物体积。
- AC-3.1：device 护栏测试 RED→GREEN 且既有引擎测试零回归。
- AC-3.2：假树单测全绿；lite 派生 rc=0 且实测体积 <2GiB；蒸馏冒烟 rc=0。
- AC-3.3：full 产物（dist/AutoVisionAgent）保持含 CUDA（体积 ~4.4G 不动，不牺牲 GPU 训练）。

## FR-4 数据集版本管理（v3 报告 #17，领域）

- FR-4.1 `project/versioning.py` 纯函数核心库：
  - `build_manifest(root)`：遍历项目树（跳过 `.snapshots/` 自身），`{相对路径: {sha256, size}}`；manifest 写盘 temp+os.replace 原子化。
  - `create_snapshot(project_root, label)`：`.snapshots/{YYYYmmdd-HHMMSS}_{label}/`，全文件 **NTFS 硬链接**（失败回退 copy2，跨卷/权限场景），附 manifest.json。
  - `diff_manifests(old, new)` → `{"added": [...], "removed": [...], "changed": [...]}`（changed=同路径 sha256 不同）。
  - `verify_snapshot(snapshot_dir)`：重哈希对照 manifest，报告被就地改写/缺失条目（硬链共享块的检测手段）。
  - `restore_snapshot(project_root, snapshot_dir)`：**非破坏性**——先 verify（corrupted 则 raise），恢复改动与被删文件（从快照复制回），**保留**快照后新增文件；文档写明语义。
  - `list_snapshots(project_root)`。
- FR-4.2 data_manage 页入口：工具组加"创建快照"+"版本对比"（最近两快照 diff 摘要对话框），后台走 `run_job` + `ui_on_error`（W17 纪律），文案全 `tr()` + `retranslate`。
- AC-4.1：全生命周期测试（tmp_path 建树→快照→增/删/改→diff 三类精确→恢复→哈希还原）RED→GREEN。
- AC-4.2：verify 检出就地改写（硬链共享块场景）；restore 拒绝 corrupted 快照；restore 不删新增文件。
- AC-4.3：页面入口测试（offscreen：按钮存在、快照后台执行后状态回执、失败走 on_error 复位）。
- AC-4.4：project 包既有测试零回归。

## FR-5 P2-2 密码卫生（v3 报告第一波 #3）

- FR-5.1 初始密码改一次性文件：首次创建 admin 时写 `configs/initial_credentials.txt`（内容含用户名/初始密码/修改提示；attempt chmod 0600）；日志只记"初始密码已写入 configs/initial_credentials.txt"**不含明文**。
- FR-5.2 首登改密成功后自动删除该文件（存在即删，幂等）。
- FR-5.3 must_change 强制拦截：登录验证通过但 `must_change=True` → 弹改密对话框（旧密码校验+新密+确认， QDialog）；**改密成功才清标志并放行**登录成功信号；取消/失败则不进入（标志保持）。既有 users.json（must_change=False）路径零影响——UIA/既有测试不破。
- FR-5.4 root StreamHandler 敏感过滤：日志配置处加 `logging.Filter`，"初始密码: XXX"行替换为 `[REDACTED]` 兜底（防未来回归）。
- AC-5.1：caplog 断言初始化流程日志全文不含密码明文；一次性文件含密码且路径正确。
- AC-5.2：must_change 流程测试（offscreen）：改密成功→标志清除+登录成功；取消→无登录成功+标志保留。
- AC-5.3：改密成功后 initial_credentials.txt 被删除。
- AC-5.4：敏感过滤器单测（构造含密码行 log record → 输出 REDACTED）。
- AC-5.5：既有 login 页测试零回归（首登提示类旧断言按新行为合法更新，deviations 留痕）。

## FR-6 lock 重冻结 + 文档对齐（v3 报告第一波 #5 残留）

- FR-6.1 requirements.lock.txt 补录 6 包：et-xmlfile、onnxconverter-common、onnxsim、openpyxl、pytest-json-report、pytest-metadata（按 venv freeze 实测版本）；补录后 freeze↔lock diff 复验为空。
- FR-6.2 README/release-checklist 若提及 dist 体积或基线的陈述与本波结果对齐（主审收尾统一改，避免多代理碰同一文件）。
- AC-6.1：diff 脚本输出三列表均为空，rc=0 记入证据。

## 明确不做（本波边界）

- 不切 serving 默认序列化路径；C# 消费端代码零改动（仅编译期 proto 再生成复验）。
- 不做训练前自动快照钩子（用户未选）。
- 不跑 UIA 真窗复跑（改动面不含 UIA 断言路径；密码拦截不影响既有 users.json）；不自动 git commit。
- CI 真实首跑仍待用户接 git remote（ci.yml W18 已就绪，本波不动）。

## 风险登记

| 风险 | 缓解 |
|---|---|
| lite 裁剪后 torch 回退不成立（torch_cuda 缺失即崩） | FR-3.4 蒸馏冒烟先行验证；PyTorch Windows 惰性 CUDA 加载为已知机制，冒烟为铁证 |
| 硬链快照被源文件就地改写污染 | verify_snapshot 重哈希检测 + restore 前强制 verify + 文档写明 |
| proto additive 后 C# 编译失败 | additive 字段 protobuf 向后兼容为规范保证；dotnet build+test 复验收口 |
| must_change 拦截改登录流致 UIA/既有测试破 | 仅 must_change=True 新路径；既有库全 False；AC-5.5 回归 |
| 基准绝对值机器相关不可门禁化 | AC-1.3 明确只落档不卡门禁 |
