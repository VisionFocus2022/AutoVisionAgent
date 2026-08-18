# AutoVisionAgent 2.0.0 架构解析与优化方案（v3）

> 审查档位：L2（标准档全面复审）｜ 审查日期：2026-08-17
> 审查对象：`E:\学习项目\视觉大模型`（AutoVisionAgent 2.0.0，git 仓库 master 一线；审查时 HEAD 43a1538，tag v2.0.0）
> 方法：architecture-review 技能——4 视角并行透镜（整改核验 21 项 / 新代码审查 / 并发资源生命周期 / 运维文档漂移安全）+ 主审独立重跑全量门禁 + 2 个对抗代理终审（事实核查员 14 项、对抗工程师 7 结论）+ 主审 numpy 实证裁决；关键数字带复核状态。
> **与 v2 的关系**：v2（`docs/AutoVisionAgent-架构解析与优化方案-v2.md`，2026-08-17 W11，HEAD 0bc218a，P0×1+P1×7+P2×27）为基线；本文为 W12–W16 六个提交（feffe11/4231816/9209d3c/87e19a3/d2f352d/43a1538）落地与 v2.0.0 发版之后的**全新基线审查**。**本文为当前真源**；文末附录 D 给出 v2 全部 35 条发现的现状对照。
> 标注约定：`（已验证）`= ≥2 类证据交叉印证或对抗复核存活；`（已验证·对抗复核）`= 独立代理复测 confirmed；`（实证）`= 主审可复现实验裁决；`（推断，依据：…）`= 单源推理。
> 诚实声明：本文降低误判概率，不保证零遗漏。对抗驳回/降级/修正记录见 §13，未验证范围见 §12。**主审自身测量也曾出错并被事实核查员纠正（生产 LOC 16,861→16,754），如实留痕见 §7/§13。**

---

## 1. 文档摘要与阅读对象

AutoVisionAgent 2.0.0 是 **PySide6 桌面工业视觉平台**（登录→标注→训练→推理→评估→发布全流程，9 种有监督视觉任务），带 **gRPC + 内存映射文件（MMF）混合传输的对外服务层**（供 .NET 客户端跨进程调用）与 **UIA 真窗端到端测试**。本轮审查时点：v2.0.0 已发版（tag 在树、exe 重打包、UIA 6/6 真窗绿、门禁 837 passed/覆盖 92.82%）。

一句话总评：**W12–W16 整改波次把 v2 审查的骨架性债务基本清偿——线程收敛为注册表单入口、配置单源化、退出有界停机、反序列化 RCE 加固、审计复活且带用户归属、原子写与单实例互斥落地，整改核验 21 项中 19 项✅0 项❌，新模块质量经对抗审查高于存量。** 残余债务收敛为两个主题：**跨语言服务资源契约未闭环**（C# 结果 shm 区域结构性无法回收 × 64 上限 = seg/pose 类服务 64 次后软失败直至重启）与**评估指标诚实性收尾**（det 评估预测构造失真，真实数据几乎必崩或数值无意义），外加一批 P2 级工程卫生项（异常路由元组系统性失配、CI 未运行、文档漂移、仓库卫生）。终版 **P0×0 + P1×2 + P2×10 + P3 观察 12 项**——无 P0：当前无"正放大其他风险的偏态级债务"，架构处于"改动有安全网"状态。

阅读对象：本项目开发者 / 后续 wave 的执行代理 / 复用本骨架的新项目架构师。§8.2 缺点编号被 §9 改进路线直接引用。

---

## 2. 系统概览

### 2.1 定位

对标商业软件 SKolpha 的去 DRM 复刻 + 自研扩展：9 种有监督视觉任务、6 种标注模式（含 SAM 交互式）、项目管理、双语双主题 GUI、ONNX 导出、PyInstaller 打包、gRPC 服务化供 .NET 调用（已验证：pyproject/代码/docs 一致）。v1 时期"引擎缺口/假回退"类问题在 v1/v2 两轮审查中已根治，本轮零复发。

### 2.2 技术栈（每项验证依据）

| 层 | 技术 | 验证依据 |
|---|---|---|
| 语言 | Python 3.10+（venv 3.12） | pyproject.toml:5 + .venv 实测 |
| GUI | PySide6 6.11.1 | requirements.lock.txt:138-140；本轮 837 测试跑通印证 |
| 深度学习 | torch 2.5.1+cu121 / torchvision 0.20.1+cu121 | lock:186/188（本地版本标签，lock 首行已带 --extra-index-url，P1-6 已修） |
| 检测引擎 | ultralytics（det/pose/pseg）+ torchvision（cls）+ 惰性（sseg/sgan/super）+ anomalib（abdet）共 9 引擎 | engines/ 9 模块实测；spec hiddenimports 与盘面五方一致性守卫测试（tests/test_dynamic_import_guard.py:122-156） |
| 服务桥 | grpcio 1.83.0 + protobuf 7.35.1 + MMF 零拷贝 + bool RLE | lock:49/119；serving/ 代理全文精读 |
| C# 客户端 | .NET gRPC 客户端 + SharedMemoryReader（生产 6 文件 758 行 + 测试 4 文件 884 行） | serving/dotnet_client 实测（Services/Vision/ 子目录行级核验） |
| 测试 | pytest 9.1.1 + pytest-cov（fail-under=92 棘轮）+ uiautomation 真窗 UIA + xUnit | pytest.ini:39；本轮独立重跑 837 passed（§7） |
| 打包 | PyInstaller 6.21.0（onedir, console=False） | autovisionagent.spec 实测；dist 4.4G / exe 84MB（08-17 19:50 构建） |
| CI | GitHub Actions windows-latest（待命未运行——git remote 为空） | .github/workflows/ci.yml 实读 |
| 运行平台 | Windows 10 专用（MMF/UIA/QLockFile 均平台绑定） | 实测；跨平台无声明（合理，不立案） |

### 2.3 规模度量

| 指标 | 值 | 复核状态 |
|---|---|---|
| 生产 LOC | **16,754** / 107 文件（gui 7,192 / labeling 2,085 / serving 1,514 / core 1,504 / models 1,189 / evaluation 683 / inference 426 / project 443 / dataset 396 / training 372 / exporter 302 / ivp 288 / scripts 231 / 根级 129） | 实测；**修正**——主审 AST 初测 16,861 系每文件 +1 行虚增 107，事实核查员三口径（cat\|wc、逐文件 wc、字节级 count）交叉证实 16,754（§13-4） |
| 最大单文件 | gui/pages/label/page.py **840 行**（v2 时 818） | 实测（重验: wc 一致） |
| >100 行函数 | **2 个**（_extract_state_dict_safe=195、det_map=112） | 实测（重验: AST + 主审直读函数边界双证）；W12"清零"宣称不实（→P2-10） |
| 50-100 行函数 | 33 个 | AST 实测（单源） |
| 测试 | tests/ 除 uia 71 个 .py（70 测试文件+conftest）/ **777 个测试函数**；含 uia 测试代码共 ≈18.9k 行 | 实测（重验: grep/find 一致；文件数修正 72→71 见 §13-4） |
| 测试:生产代码比 | ≈1.13 | 实测（18.9k/16.75k） |
| C# | 10 文件 / 1,642 行（生产 758 + 测试 884） | 实测 wc |
| 门禁 | **837 passed / 3 skipped / 覆盖 92.82% / 65.6s / rc=0** | **主审独立重跑**（本轮最强验证；与 W16 记录完全一致） |
| v2→W12-16 整改核验 | 21 项声称：**19✅ / 2◐ / 0❌** | 整改核验代理逐项 file:line 取证（§13-1） |

---

## 3. 整体架构

### 3.1 分层图（依赖方向自上而下，实测 import 关系绘制，已验证；行数为本轮实测）

```
┌──────────────── 入口层（2 条启动链 + 1 个验证脚本）────────────────┐
│ python -m gui.main（桌面 GUI）    python -m serving（gRPC 服务）   │
├──────────────── 表现层 gui（7,192 行）─────────────────────────────┤
│ gui/core: shell(主壳+退出链) theme i18n thread_bridge              │
│           jobs(后台任务注册表,W15) settings_io(用户设置单源,W13)   │
│ gui/pages ×11: login home label data_manage train predict eval_   │
│               deploy flaw_gen project settings（经 gui.pages 注册 │
│               表单源导入，W14）                                     │
│ gui/widgets ×3: file_dialog loss_chart thumbnail_loader(QRunnable)│
├────────── 服务层 serving（1,514 行 ‖ C# 758 行）───────────────────┤
│ server(gRPC Servicer+文件日志,W15) serialization(bool RLE)        │
│ mask_codec shared_memory(MMF+清扫+64上限,W12) proto(pb2 生成码)    │
│ ‖ 跨进程 ‖ C# VisionAgent.Shared: Client/Reader/Mapper/49 测试    │
├────────── 平台分发层 industrial_vision_platform（288 行）─────────┤
│ VisionModelDispatcher(统一入口+LRU显存+RLock)                     │
│   ⚠ GUI 进程内从未接线（8 处直插 registry，→P2-7）                │
├──────────────────────────── 领域层 ───────────────────────────────┤
│ models/supervised(1,189): registry + engines×9（全部真实现）      │
│ training(372): GenericTrainer 策略循环（resume 边界已修,W13）      │
│ labeling(2,085): 6 模式 + canvas/controller + SAM 适配器          │
│ inference(426): 滑窗分块+跨瓦片NMS                                 │
│ evaluation(683): metrics + generative_metrics(FID已修,W12)        │
│                 + eval_flow(评估纯函数层,W12)                     │
│ exporter(302): ONNX 导出（opset14 动态轴）                         │
├──────────────────────────── 数据层 ───────────────────────────────┤
│ dataset(396): 图像×LabelMe 配对+格式导出   project(443): 存储/计数 │
├────────── 基础设施层 core（1,504 行，零内部依赖）──────────────────┤
│ config(95行,W13收敛) interfaces_supervised(472·契约单源+RCE加固)  │
│ auth(PBKDF2 600k) audit_logger(复活+user归属,W12/13)              │
│ session(会话通道,W13) image_io(unicode 读图)                       │
│ detection_history(实时落盘) exceptions constants                   │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 分层质量

- core 零内部依赖，包间单向依赖，无包级循环（v2 import 矩阵实测沿用 + 本轮 codegraph 复核 gui→引擎方向，已验证）。
- gui 是组合根，直接 import 领域层——桌面单体合理形态；但 dispatcher 分发层在 GUI 进程内**从未接线**（7 文件 8 处直插 registry，→P2-7；serving 进程正常走 dispatcher）。
- serving 与 GUI 进程完全解耦：GUI 零引用 serving，生产代码 subprocess/QProcess = 0 处（穷尽 grep，已验证·对抗复核）；spec hiddenimports 不含 serving，exe 无法也不启动 serving。
- 页面清单单源：gui/pages/__init__.py 导出全部 11 页，gui/main.py:24-36 全经注册表导入（W14 修复，已验证）。

---

## 4. 关键机制剖析

### 4.1 后台任务注册表：gui/core/jobs.py（已验证·对抗复核）

run_job(fn, name, on_error) → 先登记后 start（start 失败回滚摘除，W16 补）→ 执行（fn 声明 cancel 参数则透传同一 threading.Event）→ 异常路由（on_error 回调或 logger.exception 兜底）→ finally 注册表自摘除。零 Qt 依赖（纯 threading+logging），保持 FakeThread monkeypatch 接缝（调用期属性解析创建线程，tests 10 个文件依赖）。全生产包唯一 `threading.Thread(` 直调即本工厂（jobs.py:146）；10 个页面消费点全部经 run_job，且被两个**源码守卫测试**锁死防回退（tests/test_w15_j2_jobs_migration.py:89-97 三页 + tests/test_gui_jobs_migration.py:99-110 六调用点）。对抗审查无新缺陷；覆盖率 100%。**已知缺口**：10 个迁移任务无一声明 cancel 参数 → 协作取消全空转（→P2-3）。

### 4.2 gRPC + MMF 混合传输：上限 64 + 启动清扫（已验证·对抗复核）

W12 给 SharedMemoryManager 加了启动清扫（构造时 glob ava_*.bin、mtime ≥2h 才删——持有打开句柄的在飞区域天然删不掉，判定不误删并发实例）与区域上限（构造参数 > AVA_SHM_MAX_REGIONS > 默认 64；超限回滚刚建区域并 RuntimeError，Windows 下先关映射再删文件顺序正确）。atexit cleanup 正常退出可靠；taskkill/崩溃由下次启动 2h 清扫兜底。**但消费端根因未修**：每次含非空 masks/keypoints 的 Detect 泄漏 1 个区域，C# 结果对象无 FilePath、类库无自动 release，累积 64 后所有需写 shm 的 Detect 软失败（success=False）直至重启（→P1-1）；且 serialization.py:114-117 的 `_SHM_MIN_BYTES` 64KiB "小数组内联"是死分支（`if nbytes < _SHM_MIN_BYTES: pass`），docstring 宣称与实现矛盾（→P1-1 修复入口）。

### 4.3 评估纯函数层：evaluation/eval_flow.py（已验证；含 P1 级缺陷）

W12 把 eval_ 页 141 行 _run_eval/115 行 _work 下沉为 11 个无 Qt 依赖纯函数（扫描→引擎加载→逐张推理→指标→行格式化；进度/翻译经回调注入），页面侧 _run_eval 瘦身至 45 行只做取参+run_job 编排。范式与 data_manage/workers.py 一致，是 v2 P0-1 拆分的正确落地。**但下沉时逐字携带了存量缺陷**：build_prediction（:100-128）的预测构造在 GT 框数与预测框数不一致时产生长度失配（→P1-2，实证见 §7）。

### 4.4 反序列化安全单元：core/interfaces_supervised._extract_state_dict_safe（已验证·对抗复核）

W12 RCE 加固后为全仓最大函数（195 行）：名级精确白名单（(module,name) 字典直查，无 startswith 前缀、无 super().find_class 兜底）+ persistent_load 五元组校验（storage 类型白名单、location 只认 cpu/空、numel×element_size 与实际字节双验证）+ 2GiB 存储总量/256MiB pickle 流双上限。对抗审查未见绕过路径（zip 内 key 经 zf.read 不可越出归档）；10 个专项测试覆盖（tests/test_interfaces_safe_extract.py），文件覆盖 91%。形态为"函数+嵌套安全类"的连贯单元，按阈值 >100 行立案但校准为观察（→P2-10）。

---

## 5. 启动链与生命周期

### 5.1 GUI 桌面链（已验证）

```
python -m gui.main
 → setup_logging()            # RotatingFileHandler(UTF-8 10MB×5)+stdout 控制台（main.py:72-115）
 → load_user_settings()       # settings_io 单源（W13）；device 由 predict 页加载时消费（:263-274）
 → set_language / QApplication
 → acquire_single_instance_lock()  # QLockFile %TEMP%，占用则弹窗退出（P2-14 修复，W15）
 → ThemeManager.apply → build_window()
     一次性构造 11 页（经 gui.pages 注册表）+ 信号枢纽接线
     （project_opened→data/predict/home；login_success→跳主页——user/role 仍被丢弃，→P2-8；
       language_changed→全页 retranslate 单点广播）
 → win.select("login") → app.exec()

 退出 closeEvent（shell.py:263-358，W15 重写）：
   活跃检测三路并集：① jobs.active_jobs() 注册表（真相源）
     ② TrainWorker isRunning ③ 批量按钮禁用约定（btn_batch 双名兼容，过渡期）
   → 用户确认后有界停机：request_stop_all(1.0s 总预算)
     → TrainWorker stop()+wait(1500ms) → QThreadPool clear()+waitForDone(500ms)
     → registry.clear_cache()（GPU 显存）→ 审计 flush（atexit 双保险）→ accept
   ⚠ 超时后无兜底直接 accept：parented QThread 析构 qFatal 窗口（→P2-3）
```

### 5.2 gRPC 服务链（已验证·对抗复核）

```
python -m serving [--host 127.0.0.1 --port 50051 --max-workers 8]
 → serve() → create_server()
     → SharedMemoryManager()（构造即清扫陈旧 ava_*.bin，W12）
     → setup_file_logging()（RotatingFileHandler 5MB×3 → logs/serving.log，W15）
     → 延迟 get_dispatcher() + grpc.server(ThreadPoolExecutor(8))
     → add_insecure_port（默认回环；ADR-0001 已固化决策；非回环无运行时告警，→P2-9）
 → wait_for_termination()
 RPC: Ping / ListTasks(不再广告 zero_shot,W14) / GetTaskInfo / LoadModel
      / UnloadModel / Detect / ReleaseSharedMemory(恒 success=True,→P1-1 附带)
 Detect 热路径: dispatcher.infer → serialization(bool RLE) → shm 写入+登记
   （区域无 TTL/reaper；上限 64 达到即 RuntimeError→success=False，→P1-1）
```

---

## 6. 核心协作关系

| 组件 | 层 | 职责（规模） |
|---|---|---|
| core/interfaces_supervised | 基础 | 类型契约单源 + 安全加载（472 行，全仓生产引用单源） |
| core/session + audit_logger | 基础 | 会话通道（33 行）+ 审计（atexit/flush/user 归属复活） |
| models/supervised | 领域 | EngineRegistry（RLock+双检缓存+锁外卸载）+ 9 真引擎（1,189 行） |
| training / labeling / inference / evaluation / exporter | 领域 | GenericTrainer（372）/ 6 模式标注（2,085）/ 滑窗 NMS（426）/ 指标+eval_flow（683）/ ONNX（302） |
| dataset / project | 数据 | LabelMe 配对+导出（396）/ 文件系统项目存储（443） |
| industrial_vision_platform | 平台 | VisionModelDispatcher 统一入口 + LRU 显存(max_loaded=2) + RLock（288 行）——GUI 进程未接线（→P2-7） |
| gui / serving | 表现/服务 | 11 页桌面壳（7,192）/ gRPC+MMF+C#（1,514 + C# 758） |

三条主协作链（已验证）：

1. **GUI 推理链**：predict 页 → run_job 后台线程 → get_engine（LRU 仅 dispatcher 侧；GUI 直插 registry 无显存上限）→ frozen DetectionResult → invoke_main 回主线程渲染。
2. **训练链**：train 页 → TrainWorker(QThread，协作停止 threading.Event，epoch 边界生效) → GenericTrainer.fit（save 失败 raise，W12）→ finished_sig/failed → UI；审计带真实用户（W13）。
3. **服务链**：C# AutoVisionAgentClient → gRPC 信令 → Servicer（每方法 try/except + success=False 回传）→ dispatcher → serialization（bool RLE）→ MMF+mmap → C# SharedMemoryReader 零拷贝读 → DetectionResultMapper（**丢弃句柄，结果区域无人回收 → P1-1**）。

---

## 7. 实测指标表（含复核状态；阈值命中项即关键数字，逐项带重验 token）

| 指标 | 实测值 | 复核状态 | 阈值定级/备注 |
|---|---|---|---|
| 门禁全量 | 837 passed / 3 skipped / 65.6s / rc=0 | **主审独立重跑**（同日 W16 记录一致） | 正常 |
| 覆盖率 | **92.82%**（7,992 语句/574 缺；fail-under=92） | 主审独立重跑输出 | 正常（>80 档；棘轮 92） |
| 生产 LOC | 16,754 / 107 文件 | 重验: 三口径一致；**修正**（初测 16,861 为 AST 脚本每文件+1 虚增，§13-4） | — |
| 单文件最大 | label/page.py 840 | 重验: wc 一致 | 300–1000 = **P2 档**（并入 P2-10 观察） |
| >100 行函数 | 2 个（195/112） | 重验: AST+直读双证 | >100 = **P0 档阈值**，校准降 P2（均已测试、内聚，见 P2-10 校准说明） |
| broad except 密度 | 52 处/16,754 行 = **3.10/千行**（Exception 50 + BaseException 2：jobs.py:155/batch_tools.py:48） | 重验: 独立 grep 一致 | **P2 档**（1–5/千行；v2 时 2.77） |
| 纯静默 except | 11/52（其中 image_io×2 有意契约、scripts×2 循环跳过 → 有效约 7） | 单代理逐处分类+主审抽读 | 改善（v2 时 13/44）；→P3 观察 |
| 裸 except / TODO / 生产包 print | 0 / 0 / 0（print 仅 scripts/ 14 处） | 实测 | 正常 |
| threading.Thread | 生产代码 **1 处**（jobs.py:146 工厂本体）+ run_job 消费 10 处 | 重验: 穷尽 grep + 2 个源码守卫测试 | 正常（W15 收敛达成） |
| 原子写 | os.replace 6 处（batch_tools/predict 批量等） | 实测 | 正常（W15）；predict .tmp 失败清理缺口 →P2-1 |
| v2 整改核验 | 21 项声称：19✅/2◐/0❌ | 代理逐项 file:line 取证 | 见附录 D |
| 审计健康 | audit_20260817.jsonl 79 行，**79/79 含非空 user**；当日活跃 | 重验: JSON 逐行解析 | 正常（P1-4 根治实锤） |
| GUI 日志 | autovision.log 1.4MB/12,809 行，8 页 INFO 在写（train 页 0 行 →P3） | 实测 | 正常（v2 P2-19 根治；pytest 污染混写 →P2-6） |
| C# 句柄纪律 | Reader using 即释放、NLog 已接（%TEMP% 内建配置） | 代理行级核验 | 正常；结果区域回收缺位 →P1-1 |
| lock↔venv | lock 205 包；freeze 比对**漂移 6 包**（openpyxl/et_xmlfile/onnxsim/onnxconverter-common/pytest-json-report/pytest-metadata 仅在 venv） | 重验: 双向 diff | →P2-4 |
| git 卫生 | `.autofix-loop/` 6 文件 + `_i18n_report.txt`/`_missing_keys.txt` 被跟踪；.gitignore 71 行无对应条目 | 重验: git ls-files | →P2-6 |
| eval 崩溃触发集 | **M>0 且 N≠M**（M=GT 框数,N=预测框数） | **实证**: numpy 复刻 8 组合实验（M=1,N=0 / M=1,N=3 / M=3,N=0 均 IndexError；M=N 或 M=0 不崩） | →P1-2（比两代理结论都宽，§13-3） |
| shm 上限行为 | 达 64 上限 → RuntimeError → Detect success=False（软失败非 crash） | 对抗复核思想实验（server.py:153-157 捕获链） | →P1-1 |
| UIA / C# 测试 | 6 用例真窗绿（W16 第三轮复跑）；C# 49/49（W16 记录） | 引用 W 系列记录（本轮未复跑） | 优点 |

---

## 8. 多视角评估

### 8.1 优点（均（已验证），多数对抗复核）

1. **v2→W12-16 整改闭环率高且真实**：21 项声称核验 19✅/2◐/0❌——线程收敛（注册表单入口+源码守卫防回退+start 失败回滚）、config 545→95 行单源化、退出有界停机、FID 对称化、训练假成功上抛、审计复活带用户归属（79/79）、QLockFile、动态导入五方守卫、原子写、eval 诚实空态，全部落地且形态正确。
2. **门禁独立可复现**：主审本轮独立重跑 837 passed/3 skipped/92.82%/65.6s rc=0——覆盖率棘轮 89→90→92 三波爬升后地板稳固；三层金字塔（777 离屏 + 6 UIA 真窗 + 49 C#）结构健康。
3. **新代码质量高于存量**（对抗审查结论）：jobs.py（注册表时序/快照 join/start 回滚全防御）、closeEvent（三路检测+全链有界+模态阻断+Queued 无死锁）、shared_memory 上限回滚顺序（Windows 先关映射再删）、audit_logger 幂等 flush、trainer resume 边界（与旧实现逐位等价证明）、反序列化加固——本轮 4 条新代码发现中仅 1 条为 W12-16 新引入（predict .tmp 清理缺口）。
4. **安全水位持续领先同规模**：RCE 名级白名单+persistent_load+双上限（对抗无绕过）；PBKDF2 600k+自动迁移旧哈希；torch.load 3 处全 weights_only；CSV/xlsx 公式注入双路消毒；文本写 open 20 处全带 encoding="utf-8"。
5. **决策可追溯体系持续运转**：16 个 wave 的 PRD+tasks+state.json；ADR-0001（serving 回环锁定，含被拒备选）落档；每个修复点带 W 注释回归锚。
6. **诚实性工程文化可观察**：eval 空态不再编造混淆矩阵、zero_shot 从对外广告摘除、错误文案直指动作、FID 修复 docstring 记录成因——本项目的"宣称 vs 实际"差距在持续收窄（本轮仍抓到两处宣称不实，见 P2-10/附录 D，属过程债非系统性）。
7. **资源治理明显改善**：shm 启动清扫+上限+atexit；JSON 原子写×6（含同目录 tmp 守卫测试）；QLockFile 陈旧锁自恢复；serving 轮转文件日志；C# NLog 接线+空 catch 改 Warn。
8. **UI 样板收敛持续**：pick_* 文件对话框、invoke_main 全转发、QImage 线程契约、labeling 三层切分——v2 记录的范式全部保持，零回退。

### 8.2 缺点清单（终版：P0×0 / P1×2 / P2×10 / P3 观察 12 项）

> 4 透镜原始发现 + 对抗工程师 7 结论（6 存活/1 降级）+ 主审实证扩宽 1 处，合并去重后定稿。每条带实测数字/实证 + 阈值定级。

#### P1 级

**P1-1 C# 检测结果 shm 区域结构性无法回收 × 64 上限：seg/pose 类服务 64 次后软失败直至重启**（已验证·对抗复核；v2 P1-1 消费端根因残留）
每次结果含非空 masks/keypoints 的 Detect 在服务端登记 1 个区域（serialization.py:71-76；64KiB "小数组内联"是死分支 `pass`，:114-117——docstring 与实现矛盾）；RLE 压缩只省字节不省区域登记。C# 侧 CallDetect 映射后丢弃 proto 句柄（AutoVisionAgentClient.cs:289-297），DetectionResult POCO 无 FilePath 字段（DetectionResult.cs 11-37），类库无自动 release、生产代码无 ReleaseSharedMemory 调用方——**客户端结构性无法回收结果区域**。服务端 `_regions` 只在显式 Release 或进程重启时缩减：无 TTL/reaper/断连回调（穷尽 grep）。累积至默认 64 上限后，**所有需写 shm 的 Detect（seg/pseg/sseg/pose）以 success=False 软失败**（RuntimeError→server.py:153-157 捕获→错误文案"请先 release"——而客户端恰恰无法执行），det/cls 不受影响；零检出（masks=None）不建区域。唯一恢复=重启 serving。附带（v2 残留、对抗降级 P3 并入本条）：ReleaseSharedMemory 无视 release() 返回 False 恒回 success=True（server.py:167-168，无测试锚定）——协议无"区域归属"概念，与本条根因同源。命中档：主链路资源泄漏默认累积 + 可用性硬顶（64 次）→ P1（单用户学习项目、det 路径无恙、重启即恢复，不升 P0）。

**P1-2 评估页 det 路径预测构造失真：真实数据几乎必崩（M>0∧N≠M 即 IndexError→按钮永久卡死）；不崩时 mAP 数值也无意义**（已验证·实证；v2 P0-1 拆分时逐字携带的存量缺陷，本轮实证扩宽）
build_prediction（evaluation/eval_flow.py:119-124）：`labels` 为 GT 全零标签（长 M）、`p_boxes` 为引擎预测（长 N）；`labels[:n_pred] if n_pred else labels` 在 n_pred=0 时回退全长 M。**实证**（numpy 复刻 8 组合）：M>0 且 N≠M → det_map（metrics_supervised.py:81-84）布尔掩码长度 M ≠ 数组长 N → `IndexError: boolean index did not match`——含"引擎零检出但 GT 有框"（最常见：易图/漏检）与"多检出少标注"（过检）两形态；仅 N==M 或 M==0 幸免。IndexError 不在 eval_/page.py:291-292 元组（ImportError/RuntimeError/OSError/ValueError/TypeError），run_job 无 on_error 仅落日志 → `_eval_failed_slot`(:342-347)/`_set_results_slot`(:306-311) 永不触达，**评估按钮永久禁用**。不崩时（N==M 或 M=0 或 N<M）：labels 取 GT 全零截断、scores=[result.score]*N（det 引擎 score 默认 0.0 → 全零均匀，argsort 退化按收集序）——引擎真实 labels/scores 被整体丢弃，mAP 由插入顺序决定。测试盲区：test_eval_flow.py 桩引擎恒构造 M=N=1。命中档：核心功能（检测评估）在真实数据上不可用 + 指标失真 + UI 卡死 → P1（v2 FID 同主题："结果与指标诚实性"）。**修复陷阱**（对抗预警）：直接改用 result.labels（字符串 "defect_N"）喂 det_map 会使 `np.asarray(['defect_0'])==0` 全 False → mAP 归零；须同步改 det_map 类别比较为字符串/ID 感知。

#### P2 级

**P2-1 worker 异常路由系统性失配：AppError 家族与未枚举异常类型穿透页面 except 元组（3 处已证实）**（已验证·对抗复核；W15 迁移 run_job 时未顺势收口）
模式：页面 `_work` 内 `except (OSError, RuntimeError, ValueError, ...)` 枚举式捕获 → 元组外异常经 run_job 仅 logger.exception → 恢复槽不执行 → 按钮永久禁用或静默失败。已证实：① deploy/page.py:189/:196 两层同元组均不含 `ModelExportError(AppError)`（exporter/supervised_exporter.py:69/96/152/176 抛出）→ TRT 构建失败（装有 TRT 机器的高概率事件）导出按钮卡死；② label/page.py:63-67 未 load 引擎直接 infer → SupervisedEngineError 穿过 :584 元组 → AI 预标注静默失败；③ P1-2 的 IndexError 是同款特例。系统性根因：core/exceptions.py 自有异常家族（AppError(Exception)）与各页枚举元组从未对齐，且 run_job 的 on_error 通道零使用（10 个消费点均未传）。命中档：多处按钮卡死/静默 → P2（修法统一：run_job 传 on_error 或元组改捕 AppError+Exception 兜底路由）。

**P2-2 初始随机密码明文落日志与控制台 + must_change 无强制**（已验证·对抗复核；v2 P2-17 残留变形且加重）
login/page.py:87-95 首启生成随机密码后 `logger.info(msg)`（msg :91 含明文），root logger 同时挂 autovision.log RotatingFileHandler（轮转 5 份）与 stdout StreamHandler（gui/main.py:101-113）——**密码既在磁盘留存随日志保留期，也在控制台打印**；:85-86 注释"不打 stdout"只避免了 print()，是无效安慰。配套：must_change 仅状态栏提示且立即清标志（:226-230），无改密拦截——随机密码可永久有效。命中档：本地单工位威胁模型 → P2（修法：密码只写 users.json 旁一次性文件或只弹窗展示；控制台 handler 加敏感过滤；must_change 加拦截）。

**P2-3 退出链"有界停机"承诺被析构阶段打破 + 协作取消空转**（已验证·对抗复核；v2 P2-3 残留）
① TrainWorker(trainer, cfg, self) 以页面为 parent（train/page.py:299），closeEvent stop()+wait(1500ms) 超时后照常 accept（shell.py:322-331→:358）——长 epoch 中途退出（should_stop 仅 epoch 边界生效）→ 窗口销毁 → QThread 析构 qFatal("Destroyed while thread is still running")，exe 下硬崩于解释器收尾阶段；② 10 个 run_job 任务无一声明 cancel 参数（`_accepts_cancel` 全 False），request_stop_all(1.0s) 对批量推理常见超时，仅留 warning，靠 daemon 强杀+原子写兜底（predict 批量私有 _batch_cancel 也不被退出链置位）；③ 两个 QThreadPool waitForDone(500ms) 超时后析构期无界等待转嫁。命中档：有用户二次确认闸门+崩溃在收尾阶段+数据有原子写保护 → P2（修法：TrainWorker 去 parent + deleteLater、批量任务接 cancel、超时后二次 longer wait 或提示强退）。

**P2-4 构建链三缺口：CI 从未运行 + lock↔venv 漂移 6 包 + C# 无 CI**（已验证；v2 P1-6/P2-26 的"完成一半"状态）
① git remote 为空（实测），ci.yml 自述"推送后生效"——offscreen 兜底在 windows-latest 成立、92 门禁 CI 全绿均属未验证断言；② lock 与 venv 双向 diff 漂移恰 6 包（openpyxl/et_xmlfile/onnxsim/onnxconverter-common/pytest-json-report/pytest-metadata 仅在 venv）——README"依赖以 lock 锁定安装"的承诺与实态不符：lock 装出的环境推理页 Excel 导出必走 CSV 回退、exporter 覆盖分母将漂移；③ ci.yml 仅 Python 单 job，dotnet_client 49 测试无任何门禁；④ cu121 全量锁装 CI（~2.5GB torch 轮子、无 pip cache、10-20 分钟/次）代价高未优化（注释自认解法未落地）。命中档：门禁可复现性的"第二台机器"问题仍未闭环 → P2。

**P2-5 文档漂移三处：README 门槛旧值 + checklist 括注旧值 + docs/复刻计划 反向指认真源**（已验证·对抗复核）
① README.md:21 `--cov-fail-under=89` vs pytest.ini:39 实为 92（**本轮已顺手修正**，见 §13-6）；② docs/release-checklist.md:12 括注"W10 起为 89"旧值滞留（**同上已修正**）；③ docs/复刻计划/ 整目录为外树陈旧物：其 README 横幅宣称"本仓是旧快照、真源在 E:\计算机视觉\视觉大模型（1713 passed/80.77%）"，execution-plan 引用本仓不存在的 ARCHITECTURE.md 与 core/dependency_injection.py，数字与本仓现状（837/92%）完全不符——对新读者是强误导源。命中档：误导补覆盖/发版判断 + 真源声明自相矛盾 → P2（修法：复刻计划目录加 ARCHIVED 横幅或移出 docs/ 主视线）。

**P2-6 仓库卫生三件：循环工作态与检查器产物被 git 跟踪 + 生产日志与 pytest 污染混写**（已验证；重验: git ls-files）
① `.autofix-loop/` 6 文件（baseline/uia-raw/loop-state/report）被跟踪且 .gitignore 无条目——工具回路瞬态进产品仓历史，后续每次循环脏 diff；② `_i18n_report.txt`/`_missing_keys.txt` 被 scripts/check_i18n.py 每次重写又被跟踪，检查器一跑工作区就脏；③ autovision.log 12,809 行中 326 行含 pytest-of-888 临时目录路径，真实用户操作（18:12-18:18 会话）与测试噪音混写同文件，排障不可分。命中档：仓库卫生+可观测性污染 → P2（修法：.gitignore 三条 + git rm --cached 八文件；测试态日志隔离目录或 conftest 重定向）。

**P2-7 dispatcher 在 GUI 进程从未接线：8 处直插 registry + deploy 页 _EngineStub 伪造接口**（已验证·对抗复核；v2 P2-7 完全残留，重新定性）
gui 侧 7 文件 8 处直插 models.supervised.registry/engine（shell.py:345、**gui/core**/tasks_ui.py:33-34、flaw_gen/page.py:178-179、label/page.py:59、predict/page.py:244、train/page.py:317）；deploy/page.py:173-177 `_EngineStub` 伪造 task 属性满足 exporter 形状。对抗复核定性修正：非运行时缺陷（同一 registry 缓存、无 LRU 交叉释放冲突、serving 独立进程正常走 dispatcher）——实质是 **dispatcher 抽象（统一入口/LRU 显存/loaded 观测/设备语义）在 GUI 进程整体未采用**，GUI 内唯一 dispatcher 消费点是 label 页零样本回退桥（无内置检测器必失败，vision_dispatcher.py:77-78）≈ GUI 进程内死代码。命中档：架构一致性债务 + 接口倒逼造假对象 → P2（修法：GUI 接线 dispatcher 或承认 registry 直连为正式形态并删除 GUI 侧 dispatcher 依赖，二选一收敛）。

**P2-8 认证与会话残留四件套：角色 tr() 字面量持久化 + user/role 丢弃 + license 装饰性 + chmod 假保护**（已验证；v2 P2-17/P2-23 残留合并）
① login/page.py:74 `"role": tr("管理员")`、:181 `record.get("role", tr("操作员"))`——角色以翻译值持久化，en_US 下历史账户角色显示与比较错乱；② main.py:188-190 `lambda _u, _r: win.select("home")` 丢弃登录用户/角色，11 页零角色控制（审计归属已由 session 修复，但 UI 权限面为零）；③ license.key 存在性检查（:302-310）+ 注册零校验（:277-297 copy2 任意文件）——离线模式实际无门槛，docstring"需验证本地 License 文件"名不符实（若属去 DRM 有意设计，应改文档诚实表述）；④ os.chmod(db_path, 0o600) 在 NTFS 基本无效，注释宣称"仅所有者可读写"名不符实。命中档：本地单工位威胁模型 → P2。

**P2-9 serving 非回环 --host 无运行时告警**（已验证；v2 P2-18 残留半边，ADR-0001 落地后余项）
ADR-0001 已固化"默认 127.0.0.1 回环锁定"决策；但 serve()/create_server() 对非回环 host 仍零告警（server.py:244/:270/:308 均无 warning），模块 docstring :13 的风险提示在无人读 --help 时形同虚设——`--host 0.0.0.0` 静默把无鉴权 gRPC 暴露到全网。命中档：默认安全+显式越界无提醒 → P2（修法：非回环 host 时 logger.warning 一行）。

**P2-10 W12"巨石函数清零"宣称不实：漏修第 10 个 + 同 commit 新造全仓最大函数**（已验证·对抗复核；阈值校准后按观察档处理，保留为过程宣称记录）
实测 >100 行函数 2 个：det_map=112（v2 文档 :223/:448 明确点名的第 10 个，W12 只清 9 个原样未动）；_extract_state_dict_safe=195（**baseline af972d6 时该文件无任何 >100 行函数——此巨石是 W12 同 commit 的 RCE 加固长出来的**，现为全仓最大）。阈值定级：>100 行=P0 档；校准说明（对抗复核采纳）：两者均为**有测试覆盖的内聚单元**（det_map 纯函数 98% 覆盖；195 行为"函数+嵌套安全类"含 10 个专项测试），不属 v2 P0-1 的真实风险分层（不可单测+嵌套闭包跨线程的业务巨石——那三个确已拆掉），机械拆分安全函数反损审计可读性 → **代码缺陷降为 P3 观察；作为"过程宣称 vs 实际"的记录保留 P2 编号**（W12 commit message"巨石函数清零"与现状不符，含 audit 可读性在内的例外应写入修复说明而非宣称清零）。

#### P3 观察（不编号立案，随 wave 顺手处理）

- serialization "小数组内联"死分支（并入 P1-1 修复入口）；Detect 序列化中途失败已登记区域不回滚（serialization.py:71-76）；shm 上限先写后查（超限请求白付全量写盘+fsync）；上限文案"请先 release"对唯一客户端不可执行（随 P1-1 改）。
- request_stop_all 快照语义：确认框期间新启动的 job 不受停（jobs.py:184-185，小窗口）。
- torch.load 两处直调（deploy/page.py:163、generic_trainer.py:347）未统一走 _safe_torch_load（安全等价、层次不一致）。
- train 页 0 条 INFO 操作日志（其余 8 页均有多行）；home 统计 projects=1 硬编码；login/page.py:14 QTimer 死导入；spec 图标条件永不满足（assets/ 不存在）。
- FID/LPIPS 仅取前 20 张样本（eval_flow.py:194/197，评估方法学弱）；xlsx 导出在 lock 环境不可达（并入 P2-4）。
- check_i18n 扫描 tests/ 把测试夹具当生产文案（缺键"TT 缺引擎"实为测试专用串，生产零影响）；dist 4.4GB 体积未裁剪（exe 84MB + CUDA 栈）。

### 8.3 18 视角覆盖矩阵（C1-C6 必查 / S1-S12 适用性判定 + 扩展视角）

| 视角 | 状态 | 已查 | 关键发现 |
|---|---|---|---|
| C1 架构合理性 | 必查 | ✓ | 分层无环、契约单源、页面注册表单源（§3/§4）；P2-7 dispatcher GUI 未接线、P1-2 评估流构造缺陷 |
| C2 可维护性 | 必查 | ✓ | TODO 0、i18n 缺 1 键（测试串）、config 单源化完成；P2-10 巨石宣称不实、P2-5 文档漂移 |
| C3 可靠性 | 必查 | ✓ | 新模块失败路径处理在线（对抗审查）；P1-2 评估必崩、P2-1 异常路由失配、P2-3 退出析构窗口 |
| C4 可测试性 | 必查 | ✓ | 92.82% 独立复现 + 三层金字塔 + 源码守卫测试是核心资产；P2-4 CI 未运行/lock 漂移、eval M≠N 零测试（P1-2 内） |
| C5 可运维性 | 必查 | ✓ | 审计复活 79/79 user、8 页操作日志、serving 轮转日志；P2-6 日志污染/仓库卫生、P2-5 文档漂移 |
| C6 安全性 | 必查 | ✓ | RCE 加固无绕过、PBKDF2/公式注入/编码全达标；P2-2 密码明文入日志、P2-8 认证残留、P2-9 无告警 |
| S1 性能伸缩 | 适用 | ✓ | 无性能型缺陷立案；微基准存在（native 449µs/sv 3.6ms）；推理时延/显存峰值/启动时间仍未实测（§12） |
| S2 数据持久化 | 适用 | ✓ | 原子写×6+同目录守卫；settings_io save 仍非原子（损坏回默认，低危）；history 健康在写 |
| S3 并发 | 适用 | ✓ | 线程收敛单入口+守卫防回退（W15 达成）；P2-3 cancel 空转/析构窗口；registry/dispatcher 锁纪律良好 |
| S4 API 契约 | 适用 | ✓ | proto+dtype 契约+C# 测试齐备、zero_shot 诚实摘除；P1-1 区域归属语义缺失（Release 恒 True 并入） |
| S5 依赖健康 | 适用 | ✓ | setuptools CVE 出区间、torch weights_only 防护；P2-4 lock↔venv 漂移 6 包；anomalib 全家桶（gradio/fastapi 等）仅 venv 不进 exe |
| S6 灾备 | 不适用 | ✓ | 单机学习项目，无生产部署/备份承诺（不适用原因） |
| S7 合规 | 不适用 | ✓ | 无 PII/监管面、无第三方分发（不适用原因） |
| S8 可观测性深化 | 适用 | ✓ | 三轨（运行/审计/历史）全部活跃且 user 归属；P2-6 pytest 污染、train 页零留痕；无 metrics/tracing（规模未到） |
| S9 i18n/a11y | 适用 | ✓ | 缺译 1 键且为测试串；P2-8 角色字面量是 i18n×持久层交叉缺陷 |
| S10 演进/ADR | 适用 | ✓ | ADR-0001 落档、16 wave 决策链完整是最大资产之一；P2-10"清零"宣称不实是决策记录诚实性小缺口 |
| S11 构建链 | 适用 | ✓ | spec 五方守卫+offscreen 兜底+lock 可装；P2-4 CI 未运行/漂移/C# 缺位是当前主缺口 |
| S12 资源泄漏/生命周期 | 适用 | ✓ | P1-1 shm 结果区域（本轮回主案）、P2-3 退出析构；清扫/上限/atexit/原子写为正面改善 |
| 扩展：指标诚实性（领域） | 适用 | ✓ | 工业质检决策依赖指标正确性——P1-2（det 评估失真）+ FID 已修为正面对照；det_map 修复陷阱已预警 |
| 扩展：测试态与生产态隔离 | 适用 | ✓ | P2-6（日志混写+工作产物入库）；v2 未单列，本轮新增 |

---

## 9. 改进路线（三波 × ROI，动作回引缺点编号）

### 🚑 第一波·止血（低风险，立即，约 3-4 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 1 | 修 det 评估构造 | P1-2 | build_prediction 改用引擎真实 result.labels/scores 并做 numpy→标量归一；**det_map 类别比较同步改字符串/ID 感知**（防 mAP 归零陷阱）；except 元组兜底；补 M≠N（含 N=0）用例 |
| 2 | shm 结果区域止血 | P1-1 | 首选激活 serialization "小数组内联"死分支（RLE 后小掩码内联 protobuf，≤64KiB）；或 C# CallDetect 读后自动 release（需 mapper 保留句柄）或服务端区域 TTL/读后标记可复用；同步修 Release 恒 True 语义与上限文案 |
| 3 | 密码不入日志 | P2-2 | 初始密码只弹窗展示/写一次性文件；root StreamHandler 加敏感过滤；must_change 加首登改密拦截 |
| 4 | 异常路由统一收口 | P2-1 | 10 个 run_job 消费点统一传 on_error 回调（页面经 invoke_main 复位按钮）；deploy/label 元组补 AppError 家族 |
| 5 | 文档对齐+lock 补齐 | P2-4/5 | lock 补 6 包重冻结；release-checklist 括注对齐（README 本轮已修）；复刻计划目录加 ARCHIVED 横幅 |
| 6 | 仓库卫生 | P2-6 | .gitignore 三条 + git rm --cached 八文件；测试日志隔离 |

### 🔧 第二波·可测化解耦（中风险，约 4-6 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 7 | 退出链补完 | P2-3 | 批量/长任务接入 cancel 参数（predict 批量改用注册表 Event）；TrainWorker 去 parent+deleteLater；超时二次 longer wait 或明确强退提示 |
| 8 | dispatcher 二选一收敛 | P2-7 | GUI 接线 dispatcher（享受 LRU/观测）或正式承认 registry 直连、删 GUI 侧 dispatcher 桥；exporter.export_onnx 改签名消灭 _EngineStub |
| 9 | CI 首跑 | P2-4 | git remote 接入→验证 ci.yml 首跑；pip cache+cpu 索引变体；加 dotnet test job（windows runner 自带 .NET） |
| 10 | 角色枚举化+license 诚实化 | P2-8 | 持久层改 admin/engineer/operator 稳定枚举（展示层再 tr()）；login_success 接会话+按角色 setEnabled 或文档明示"单工位无权限模型"；chmod 注释改为诚实说明 |
| 11 | serving 越界告警 | P2-9 | serve() 对非回环 host logger.warning 一行（ADR-0001 的执行补丁） |
| 12 | 巨石治理（轻） | P2-10 | det_map 按类拆内部函数；_extract_state_dict_safe 保持并加"有意豁免"注释；修复说明禁用"清零"式宣称 |
| 13 | 观察项清扫 | P3 | train 页 INFO 留痕、QTimer 死导入、图标条件、torch.load 统一、serialization 部分失败回滚、FID 样本帽参数化 |

### 🚀 第三波·现代化（高风险，充分 PoC 后）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 14 | 性能基线建立 | S1 空白 | 推理时延 p50/p99、显存峰值、冷启动时间三项纳入 benchmark 体系（已有 pytest-benchmark 骨架） |
| 15 | serving 协议演进 PoC | P1-1 长期 | 区域归属语义进 proto（lease/ownership 字段）或迁移大载荷到流式 gRPC；充分 PoC 后决策 |
| 16 | dist 瘦身 | P3 | 裁剪 CUDA/anomalib 依赖面（4.4G→目标 <2G）；excludes 清单+体积守卫测试 |
| 17 | 数据集版本管理 | 领域 | 纯文件系统项目存储的快照/diff 能力（学习项目可缓） |

---

## 10. 决策者建议

1. **总体判断：架构处于"投资回报递增区"，继续演化、无重写议题。** v2 全部 P0/P1 与 27 条 P2 中 24 条已真实闭环（附录 D），门禁独立可复现、三层测试金字塔+源码守卫使改动有安全网；本轮无 P0 即是证据。
2. **若只做三件事：修 det 评估构造（P1-2，半天）、给 shm 结果区域止血（P1-1，一天）、异常路由 on_error 收口（P2-1，半天）。** 前者是用户可见的"评估不可用"，中者是服务化故事的可用性硬顶，第三件消灭一整类"按钮永久卡死"——合计不足三人日。
3. **警惕"宣称清零"式完成声明（P2-10 教训）。** 本轮实证：W12 宣称"巨石清零"实则漏 1 个+新造 1 个。维持"教训→注释→回归守卫"循环的同时，修复说明应按"修了什么/留了什么/为什么留"三段式书写——项目的决策可追溯体系（ADR+wave state）已经配得上这个纪律。

---

## 11. 完整性批判记录（九问实答）

1. **最关键风险面覆盖了吗？** 已覆盖：跨语言资源契约（P1-1，透镜+对抗双证）、评估指标正确性（P1-2，实证裁决）、异常路由系统性（P2-1，3 实例）、构建链可复现（P2-4）四条主风险面各有独立证据链；无"已识别未审查"的最高风险面遗留。
2. **有没有没打开过的子系统？** 有三类并如实声明：labeling 内部（canvas/controller/6 modes，2,085 行）与 9 个引擎文件本轮未重读（依据：code-review 代理 diff 枚举 0bc218a..HEAD 生产改动不含它们，v2 逐文件覆盖沿用）；C# dotnet_client 未整体逐行复审（接口级+关键文件行级+对抗工程师针对性核查，v1/v2 背书沿用）；gui/widgets×3 中 file_dialog/loss_chart 仅引用计数（thumbnail 全读）。
3. **外部边界错误路径看了吗？** 看了：gRPC 对端强杀（atexit 不跑→2h 清扫兜底）、磁盘满/权限（P1-3 已修上抛）、序列化中途失败（P3 立案）、上限边界（P1-1 思想实验走通）、numpy 掩码错配（实证 8 组合）。未做：真实网络分区（n/a 回环）、CUDA OOM 路径。
4. **非功能默认成立了吗？** 没有：推理时延/显存峰值/启动时间全部标注未实测（S1 空白，进第三波）；唯一运行时量化是 eval 触发集实证与 shm 上限思想实验。
5. **运行产物异常信号解释了吗？** 解释了：autovision.log 1.4MB→8 页日志在写（P2-19 根治实锤）+326 行 pytest 污染（P2-6）；serving.log 仅 9 行测试驱动→serving 从未真实部署过（判定：通道健康、使用面未发生，非缺陷）；audit 79 行全带 user（P1-4 根治实锤）；无 dump/崩溃文件。.gitignore 曾出现瞬态并发编辑（外部来源，终态与 HEAD 一致、树净）——记录未深究（§12）。
6. **只看主路径忽略边界？** 两处反例被抓并实证：eval M≠N 边界（P1-2，比代理结论更宽）、shm 64 边界（P1-1）。
7. **文档自相矛盾？** 本轮抓到 4 处：README 89 vs pytest.ini 92（已顺手修）、checklist 括注（已顺手修）、复刻计划反向指认真源（P2-5）、W12 commit"巨石清零" vs 实测 2 个（P2-10）；本文数字以当日实测覆盖 v2 旧值（生产 15,881→16,754、label/page.py 818→840、覆盖 89.35%→92.82%、门禁 659→837）。
8. **单一证据源结论？** 两条 P1 均 ≥2 源（P1-1：透镜+对抗+思想实验；P1-2：审查+对抗+主审实证）；静默 except 分类与 50-100 行函数计数为单源（已标注）；UIA/C# 门禁数字引用 W16 记录未复跑（已标注）。
9. **本领域该加的视角？** 已加并用上：指标诚实性（P1-2 主案）、测试态/生产态隔离（P2-6）。可再补未补：数据集版本管理/漂移检测（纯文件系统，第三波后评估）。

---

## 12. 验证范围与局限

**已验证**：§7 全部数字（门禁为独立重跑；LOC/文件数经三口径交叉；关键 file:line 经代理 Read+主审抽读）；4 透镜声明的已查项；两条 P1 的完整证据链（含实证实验）；整改核验 21 项。

**未验证/未做**：
1. C# dotnet test 未复跑（49/49 引用 W16 记录）；UIA 6 用例未复跑（6/6 引用 W16 第三轮记录）。
2. P1-1 未做真实 C# 客户端 65 次连续 Detect 压测（结论基于代码路径+协议分析+对抗思想实验，静态证据链完整）。
3. PyInstaller exe 重建未执行；P2-3 的 QThread 析构 qFatal 未实机复现（代码路径静态无歧义 + Qt 语义引用）；退出链超时路径未真机计时。
4. 性能（时延/显存/启动）、圈复杂度（radon 未装，沿用 AST 行数代理）、真实 CUDA OOM 路径。
5. labeling 内部与 9 引擎文件未重读（W12-16 未改动，v2 覆盖沿用——推断，依据：diff 枚举）；C# 未整体逐行复审。
6. docs/复刻计划 仅核验 README 横幅与 2 个断链引用，未逐文件清点。
7. 审查期间 .gitignore 曾被外部并发编辑（瞬态 .benchmarks 条目出现又消失）；终态已核（71 行、与 HEAD 一致、树净），来源未深究——提示多会话并行操作同仓的协调风险。
8. 静默 except 11 处分类为单代理逐处读+主审抽读，未逐条二次复核（清单已列，可复查）。
9. lock 6 包漂移的下游影响（CI 覆盖分母漂移幅度）未实测——CI 未运行故无从测起。

---

## 13. 对抗验证与修正记录（审计轨迹）

**对抗工程师 7 结论**：6 存活（P1-1 加边界条件、P1-2 收紧后存活、P2-2 加重、P2-3 修 3 处表述、P2-7 重新定性、P2-10 双重定性）+ 1 降级（ReleaseSharedMemory 恒 True：P2→P3 并入 P1-1，理由=主用法下 False 本是预期路径、协议无归属概念）。要点留痕：

1. **P1-1 边界修正**：泄漏仅限结果含非空 masks/keypoints 的任务（seg/pseg/sseg/pose）；det/cls 完全不受影响；零检出不建区域；上限命中为软失败非 crash；"小数组内联"死分支实锤（docstring 与实现矛盾——反驳内联假设失败反而加重结论）。
2. **P1-2 触发集修正链**（三方收敛过程）：代码审查员初判 N>M → 对抗工程师收紧为 0<M<N（"零检出不崩"）→ **主审 numpy 实证推翻对抗子断言**：M=1,N=0 与 M=3,N=0 同样 IndexError，终版触发集 M>0∧N≠M（比两代理都宽）。对抗工程师贡献的失真细节（score 默认 0.0→全零均匀、字符串 labels 直喂会 mAP 归零的修复陷阱）全部采纳。
3. **P2-2 加重**："已控控制台"反驳失败（root StreamHandler 照打）；"强制改密"减罪情节不成立（仅提示即清标志）。
4. **事实核查员修正主审自身 3 处**：生产 LOC 16,861→**16,754**（主审 AST 脚本每文件 +1 行虚增 107——技能规则①"测量也需复核"的活案例，与标杆 5900→7832 同性质）；测试文件 72→71（口径含 uia 混入）；eval 成功恢复槽名 `_eval_done_slot`→`_set_results_slot`（:306-311）。另勘误 run_job 消费点 11→10（对抗工程师）、tasks_ui.py 路径 gui/widgets→gui/core。
5. **P2-10 双重定性**：代码缺陷降 P3（有测试、内聚、机械拆分有害）；"宣称 vs 实际"记录保留 P2（含加重情节：195 行巨石系 W12 同 commit 自造，baseline 时该文件无 >100 行函数）。
6. **本轮顺手修复 2 处文档**（审查过程中即时落地，非整改波次）：README.md:21 fail-under 89→92 + 架构文档链接补 v3 为权威版；docs/release-checklist.md:12 括注 89→92。P2-5 相应子项标记"已顺手修复"。
7. **整改核验 2 处 ◐ 的裁定**：device 回灌生效点在 predict 页而非 main.py（功能等效，W13 记录未指明 main.py，判"表述偏差非缺陷"）；load_zero_shot 保留为文档化预留注入点（有诚实测试锚定 0 调用，判"有意设计非残留"）。

---

## 附录 D：v2 全部 35 条发现现状对照（W12-W16 落地 + 本轮核验）

**v2 P0×1**：P0-1 巨石函数 → ◐ 9/10 修（_run_eval 141→39、fit 118→72、_build_* 全拆、det_map 112 漏修）；W12 同 commit 新造 195 行（→本版 P2-10）。

**v2 P1×7**：P1-1 shm → ◐ 服务端清扫+上限落地，消费端根因残留（→本版 **P1-1**）；P1-2 config → ✅ 根治（545→95 行+settings_io 单源+device 生效）；P1-3 训练假成功 → ✅ 根治（save 失败 raise）；P1-4 审计停摆 → ✅ 根治（atexit+closeEvent+session 归属，79/79 user 实证）；P1-5 FID → ✅ 根治（对称积走 eig 真平方根）；P1-6 lock 不可装 → ✅ 根治（extra-index-url+README；新漂移 6 包转本版 P2-4）；P1-7 安全回退零覆盖 → ✅ 根治（10 专项测试）。

**v2 P2×27**：P2-1 线程样板 → ✅ 根治（jobs.py+10 迁移+守卫；cancel 空转转本版 P2-3）；P2-2 退出守卫 → ✅（注册表真相源+原子写；析构窗口转 P2-3）；P2-3 QThread 生命周期 → ◐ 有界停机落地，超时析构窗口转 P2-3；P2-4 异常退出兜底 → ✅（shm 清扫+serving 日志+C# NLog）；P2-5 版本纪律 → ✅（tag v2.0.0）；P2-6 ADR → ✅（ADR-0001）；P2-7 dispatcher 绕过 → ❌ 未修（重新定性转本版 P2-7）；P2-8 zero_shot 死线 → ✅（广告摘除+DINOv3/CLIP 删；load_zero_shot 留注入点）；P2-9 编造混淆矩阵 → ✅（诚实空态）；P2-10 动态导入双列表 → ✅（五方守卫测试）；P2-11 死代码 4 项 → ✅；P2-12 页面注册表漏页 → ✅（11 页单源）；P2-13 静默 except → ◐ 13→11（5 处补日志 W14）；P2-14 单实例 → ✅（QLockFile）；P2-15 deploy 跨线程读 → ✅（主线程预读）；P2-16 thread_bridge 潜伏面 → ✅（None/tuple/numpy+False 告警）；P2-17 认证链 → ◐ print→logger.info 反而入日志（转 P2-2）、user/role 丢弃与 license 装饰性转 P2-8；P2-18 gRPC 暴露 → ◐ ADR 落地，非回环告警转 P2-9；P2-19 GUI 操作日志 → ✅（8 页 INFO 实证；train 页缺转 P3）；P2-20 serving 日志 → ✅（轮转 5MB×3）；P2-21 CVE → ✅（setuptools 84）；P2-22 DataManagerExt → ✅（删除）；P2-23 角色字面量 → ❌ 未修（转 P2-8）；P2-24 proto 噪声 → ✅（.coveragerc omit，A/B 实证）；P2-25 文档漂移 → ◐ README/checklist 本轮顺手修、复刻计划转 P2-5；P2-26 无 CI → ◐ 文件待命从未运行（转 P2-4）；P2-27 offscreen → ✅（conftest 无桌面兜底+行为测试）。

**统计**：35 条 → 根治 24 / 部分 8 / 未修 3（P2-7、P2-23、P2-17 半边）。未修与部分项全部转入本版对应编号，无失联条目。

---

*本报告由 architecture-review 技能流程产出：4 视角并行透镜 → 主审独立重跑门禁 + AST/实证测量 → 事实核查员（14 项）+ 对抗工程师（7 结论）终审 → 主审实证裁决与终裁定稿。主审自身测量错误（LOC 虚增 107 行）被事实核查员发现并修正，全程留痕于 §13——这套流程连"裁判自己"也照审不误。*
