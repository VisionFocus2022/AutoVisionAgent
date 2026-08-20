# AutoVisionAgent 2.0.0 架构解析与优化方案（v4）

> 审查档位：L2（标准档全面复审）｜ 审查日期：2026-08-19
> 审查对象：`E:\学习项目\视觉大模型`（AutoVisionAgent 2.0.0，git master；审查时 HEAD d2018ab，工作树 clean，tag v2.0.0 之后 7 个提交）
> 方法：architecture-review 技能——整改核验（v3 全部发现逐项 file:line 取证）+ W17-W22 新增代码审查 + 18 视角覆盖矩阵 + 主审两次独立重跑门禁（第二次由事实核查员执行）+ 2 个对抗代理终审（事实核查员 14 项、对抗工程师 4 结论组×多攻击点含 2 项临时脚本实测）；关键数字带复核状态。
> **与 v3 的关系**：v3（`docs/AutoVisionAgent-架构解析与优化方案-v3.md`，2026-08-17，HEAD 43a1538，P0×0+P1×2+P2×10+P3×12）为基线；本文为 v3 §9 三波路线图（W17 止血/W18 解耦/W19 现代化）全量落地 + W20-W22 连续修复（3d993f4/3f9e7fa/181cd6d/36b4e43/6749467/52c8769/d2018ab，119 文件 +10,086/-547）之后的**全新基线审查**。**本文为当前真源**；文末附录 D 给出 v3 全部发现的现状对照。
> 标注约定：`（已验证）`= ≥2 类证据交叉印证；`（已验证·对抗复核）`= 独立代理复测确认；`（实证）`= 可复现实验裁决；`（引用记录，时点：…）`= 采纳历史验证记录但本轮未复跑；`（推断，依据：…）`= 单源推理。
> 诚实声明：本文降低误判概率，不保证零遗漏。对抗驳回/修正记录见 §13，未验证范围见 §12。**主审本轮仍被纠正 3 处**（users.json 跟踪状态误读、"50-100 行"口径、jobs.py:93 定性——见 §13），测量复核纪律持续必要。

---

## 1. 文档摘要与阅读对象

AutoVisionAgent 2.0.0 是 **PySide6 桌面工业视觉平台**（登录→标注→训练→推理→评估→发布全流程，9 种有监督视觉任务 + SAM 交互式标注），带 **gRPC + 内存映射文件（MMF）混合传输的对外服务层**（供 .NET 客户端跨进程调用）与 **UIA 真窗端到端测试**，发布形态为 full（GPU 4.4G）/ lite（CPU 1.97GiB）双产物。本轮审查时点：v3 三波 17 项整改全部落地、CI 双远端真实运行、门禁 966 passed/93.05%。

一句话总评：**v3 的两条 P1 与十条 P2 中九条已真实闭环（整改核验 11/12，唯一未修是仓库卫生），新代码（versioning/device 护栏/SAM 快路径/自然排序两级键/协议 lease PoC）经对抗审查质量高于存量；架构债务曲线三轮连续下行（v2 P0×1/P1×7/P2×27 → v3 P1×2/P2×10 → v4 P2×1），首次出现"无 P0 无 P1"基线。** 残余债务收敛为一个主题：**仓库卫生与敏感文件边界**（瞬态工具产物被跟踪 + 公开仓明文凭据文件的 .gitignore 缺口 + 测试态/生产态日志未隔离），外加 8 条 P3 观察。架构已进入"改动有安全网、债务守恒"状态。

阅读对象：本项目开发者 / 后续 wave 的执行代理 / 复用本骨架的新项目架构师。§8.2 缺点编号被 §9 改进路线直接引用。

---

## 2. 系统概览

### 2.1 定位

对标商业软件 SKolpha 的去 DRM 复刻 + 自研扩展：9 种有监督视觉任务、6 种标注模式（含 SAM 交互式）、项目管理（W19 起新增数据集版本管理：快照/差异/校验/非破坏恢复）、双语双主题 GUI、ONNX 导出、PyInstaller 双产物打包、gRPC 服务化供 .NET 调用（已验证：pyproject/代码/docs 一致）。

### 2.2 技术栈（每项验证依据）

| 层 | 技术 | 验证依据 |
|---|---|---|
| 语言 | Python 3.10+（venv 3.12.9） | pyproject.toml:5 + .venv 实测（基准落档 docs/benchmarks/baseline-2026-08-18.md 环境） |
| GUI | PySide6 6.11.1 | requirements.lock.txt；本轮 966 测试跑通印证 |
| 深度学习 | torch 2.5.1+cu121 / torchvision 0.20.1+cu121（lock 首行 --extra-index-url） | lock；lock↔freeze 零漂移独立复验（§7） |
| 检测引擎 | ultralytics（det/pose/pseg）+ torchvision（cls）+ 惰性（sseg/sgan/super）+ anomalib（abdet）共 9 引擎 + device 护栏（W19） | engines/ 9 模块 + models/supervised/device.py:19；spec 五方守卫测试 |
| 服务桥 | grpcio + protobuf + MMF 零拷贝 + bool RLE + 小载荷内联（W17）+ 区域 TTL（W17）+ 租约/流式 PoC（W19） | serving/ 源码精读 + proto 字段实证（§4.1） |
| C# 客户端 | .NET gRPC 客户端 + SharedMemoryReader（内联优先，W17） | DetectionResultMapper.cs:37-58 + 54 测试（引用记录，时点：CI 08-19） |
| 测试 | pytest + pytest-cov（fail-under=92 棘轮）+ uiautomation 真窗 UIA + xUnit + 基准套件（W19） | pytest.ini:39；本轮两次独立重跑（§7） |
| 打包 | PyInstaller onedir ×2：full 4.4G（GPU）/ lite 2.1G=1.97GiB 产品字节（CPU 轮子整替换，W19） | dist/ du 实测 + lite 守卫测试随产物激活 |
| CI | GitHub Actions windows-latest 双 job（test+dotnet-test）+ Gitee 镜像远端 | .github/workflows/ci.yml；CI 记录绿（引用记录，时点：d2018ab 同 sha 重触发） |
| 运行平台 | Windows 10 专用（MMF/UIA/QLockFile/NTFS 硬链快照均平台绑定） | 实测；跨平台无声明（合理，不立案） |

### 2.3 规模度量

| 指标 | 值 | 复核状态 |
|---|---|---|
| 生产 LOC | **19,215** / 117 文件（gui 7,716/36 · labeling 2,096/16 · serving 1,821/9 · core 1,510/10 · models 1,260/14 · evaluation 731/3 · inference 426/3 · project 771/6 · dataset 396/3 · training 375/2 · exporter 307/1 · ivp 292/2 · scripts 781/4 · benchmarks 604/6 · 根级 129/2） | 实测 cat\|wc（与 v3 同口径）；**重验: 事实核查员分包逐一复核一致**（v3 16,754/107 → +2,461/+10） |
| 最大单文件 | gui/pages/label/page.py **828 行**（v3 时 840）；第 2/3 名 data_manage 792 / predict 784 | 重验: wc 一致（828/792/784 确为前三） |
| >100 行函数 | **1 个**：_extract_state_dict_safe=**201**（已声明豁免；v3 时 195，+6） | 重验: AST 独立扫描一致 |
| >50 且 ≤100 行函数 | 40 个（口径：严格 >50；恰好 50 行的另有 2 个） | AST 实测；口径经事实核查员修正澄清 |
| 函数总数 | 815 | AST 实测；重验一致 |
| 测试 | tests/ **91 个 .py / 22,269 行**（含 uia） | 重验: wc 一致（v3 ≈18.9k → +3.3k） |
| 测试:生产代码比 | ≈**1.16** | 实测（22.3k/19.2k；v3 1.13） |
| C# | 54 测试（引用记录，时点：CI 08-19） | 未复跑（§12） |
| 门禁 | **966 passed / 4 skipped / 覆盖 93.05% / 62.01s / rc=0** | **主审独立重跑 + 事实核查员二次独立重跑（59.52s）双一致**（本轮最强验证） |
| v3→W17-22 整改核验 | 12 项主案：**11 ✅ / 1 ❌**（P2-6 仓库卫生） | 主审逐项 file:line 取证 + 对抗工程师抽查 3 项确认（§13） |

---

## 3. 整体架构

### 3.1 分层图（依赖方向自上而下，实测 import 关系绘制；行数为本轮实测）

```
┌──────────────── 入口层 ────────────────────────────────────────────┐
│ python -m gui.main（桌面 GUI）   python -m serving（gRPC 服务）     │
│ benchmarks/（W19 度量套件：冷启动/推理时延/显存峰值）                │
├──────────────── 表现层 gui（7,716 行）──────────────────────────────┤
│ gui/core: shell(主壳+退出链) theme i18n thread_bridge              │
│           jobs(任务注册表+协作取消,W15/18) settings_io(单源,W13)   │
│           main(SensitiveRedactFilter 敏感过滤,W19)                 │
│ gui/pages ×11: login(角色枚举,W18) home label data_manage          │
│               (+workers.py 纯函数,W20) train predict eval_         │
│               deploy flaw_gen project settings（注册表单源导入）    │
│ gui/widgets ×3: file_dialog loss_chart thumbnail_loader(QRunnable) │
├────────── 服务层 serving（1,821 行 ‖ C# 客户端）────────────────────┤
│ server(Servicer+非回环告警) serialization(内联+部分失败回滚,W17)   │
│ shared_memory(MMF+TTL 惰性清扫+租约 PoC,W17/19) mask_codec         │
│ proto(lease_id/lease_ttl_ms/masks_inline/keypoints_inline/FetchRegion)
│ ‖ 跨进程 ‖ C# VisionAgent.Shared: Client/Reader/Mapper(内联优先)   │
├────────── 平台分发层 industrial_vision_platform（292 行）──────────┤
│ VisionModelDispatcher(统一入口+LRU显存+RLock)——serving 专用        │
│   （W18 正式化：GUI 进程 registry 直连为声明架构，dispatcher        │
│     在 gui 内引用=0，gui/core/tasks_ui 守卫测试锁定）              │
├──────────────────────────── 领域层 ────────────────────────────────┤
│ models/supervised(1,260): registry + engines×9 + device 护栏(W19)  │
│ training(375): GenericTrainer 策略循环（resume 边界已修,W13）       │
│ labeling(2,096): 6 模式 + canvas/controller + SAM 适配器(快路径,W21)│
│ inference(426): 滑窗分块+跨瓦片NMS                                 │
│ evaluation(731): metrics + eval_flow(三数组定长,W17)               │
│                 + generative_metrics(FID 已修+样本帽参数化,W12/18) │
│ exporter(307): ONNX 导出（显式签名，_EngineStub 已消灭,W18）        │
├──────────────── 数据层 ─────────────────────────────────────────────┤
│ dataset(396): 图像×LabelMe 配对   project(771): 存储/计数           │
│                                  + versioning(快照/diff/verify/恢复,W19)│
├────────── 基础设施层 core（1,510 行，零内部依赖）───────────────────┤
│ config(95) interfaces_supervised(478·契约单源+RCE加固+豁免声明)    │
│ auth(PBKDF2 600k) audit_logger(user 归属) session image_io         │
│ detection_history exceptions constants                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 分层质量

- core 零内部依赖、包间单向依赖、无包级循环（v2 import 矩阵实测沿用 + 本轮 codegraph 复核，已验证）。
- v3 的 P2-7（dispatcher 在 GUI 进程从未接线）已由 W18 **二选一收敛**：registry 直连正式化为 GUI 声明架构（vision_dispatcher docstring 正式声明 dispatcher=serving 专用；gui 内引用=0，重验: 事实核查员一致；守卫测试 tests/test_w18_gui_registry_direct.py 锁定四个关键词）。"接口倒逼造假对象"的 _EngineStub 已随 export_onnx 显式签名消灭（已验证）。
- serving 与 GUI 进程完全解耦保持（gui 零引用 serving；v3 穷尽 grep 沿用，spec/PYZ 守卫绿）。
- 页面清单单源保持：gui/pages/__init__.py 导出 11 页，gui/main.py 全经注册表导入（已验证）。
- 新增横向能力均落在正确层位：device 护栏在 models（16 个调用方）、排序纯函数在 data_manage/workers、版本管理在 project、敏感过滤在 gui/main——无一越层（已验证）。

---

## 4. 关键机制剖析

### 4.1 shm 结果区域三重治理：内联 + TTL + 租约 PoC（v3 P1-1 修复，已验证·对抗复核）

W17/W19 对 v3 P1-1（C# 结果区域结构性无法回收 × 64 上限）做了三重修复：
1. **小载荷内联**（serialization.py:162-166）：序列化后（bool 掩码经 RLE）< 64KiB（`_SHM_MIN_BYTES`，:29）的 masks/keypoints 直接内联进 proto `masks_inline`(field 10)/`keypoints_inline`(field 11)——句柄仅携带 dtype/shape 元数据（file_path 空、length 0），不建区域、不占配额；v3 指认的"死分支 pass"已激活，docstring 与实现一致。C# Mapper 内联优先（DetectionResultMapper.cs:37-58，`!proto.MasksInline.IsEmpty` 先走内联解码）。
2. **TTL 惰性清扫**（shared_memory.py）：区域登记带 created_at，**三写入口（write_array/write_bytes/write_mask_compact）全部汇入 `_write_raw`，创建前先 `_reap_expired()`**（:320-322，对抗工程师接线核验）；TTL 构造参数 > `AVA_SHM_REGION_TTL_SECONDS` > 默认 300s，≤0 关闭（合法档位）；5 个专项测试（reap-on-write/frees-slots/disabled/env-override）实跑 13 passed。
3. **租约 + 流式 PoC**（W19，ADR-0002）：proto additive 字段 lease_id(6)/lease_ttl_ms(7)（.proto L28/L30 实证），服务端 `acquire_lease`/`release_leased` 校验归属（shared_memory.py:227-262；server.py:169-175 非 0 lease_id 才走校验路径），`FetchRegion` 流式 RPC（1MiB 块，L166）作跨机回退备选——**默认路径未动（PoC 定位诚实声明），64MiB 微基准直读 MMF 3.549GB/s vs 流式 0.302GB/s = 11.7x 是不接线的决策依据**（引用记录，时点：ADR-0002/bench_region_transfer）。
另：序列化部分失败回滚（v3 P3⑤）落地——masks/keypoints 写入期间异常先逐个 release 已落地区域再上抛（serialization.py:72-104）。

### 4.2 评估流诚实性：三数组定长 + 失配防御（v3 P1-2 修复，已验证·对抗复核）

build_prediction（eval_flow.py:100-139）：boxes/scores/labels 三数组长度恒等于预测框数 N（:121-136），scores 用引擎真实逐框置信度（缺失/不足回退全局 score 均匀填充），labels 恒单类 0 并在注释中记录 v3 预警的"字符串 labels 直喂 mAP 归零"陷阱；`_match_class_detections` 兜底防御（metrics_supervised.py:59-62，labels/scores 与 boxes 失配时按单类 0/零分对齐）。**对抗工程师临时脚本实测**：M=2 GT 对 N=3 与 N=0 两向失配全管线不崩；直接喂失配三元组给防御层亦不崩。det_map 已拆为 `_match_class_detections` + `_interpolated_ap` 两纯函数（112→43 行，:34-126/:129-171），AST 守卫测试锁死 ≤100 行（tests/test_w18_metrics_ast.py:45-52）。残余：:131 `float(result.score)` 未防御直取——引擎 per-box scores 短于 N **且** 无 `.score` 属性时 AttributeError 逃出 except 元组（引擎契约违反型边缘，上游 on_error 可兜住）→P3-3。

### 4.3 数据集版本管理：project/versioning.py（W19 FR-4，已验证）

快照=项目树硬链镜像（`_link_or_copy` O(1)，OSError 跨卷/权限回退 copy2）+ manifest 原子写（tmp+os.replace，:173-182）；`_sha256_file` 64KiB 分块哈希不整读大图（:49-58）；manifest 遍历跳过 `.snapshots` 任意深度（快照不入清单）；verify 检出污染（硬链共享块被写穿→corrupted，:170-177 测试实证）；restore 先 verify 拒绝 corrupted、非破坏恢复保留新增文件（test_w19_versioning.py:201-220）；标签净化 Windows 保留字符（:123-126）；同秒同名碰撞序号后缀（:154-157）。页面侧两入口（data_manage 快照/差异按钮）经 run_job+on_error 接线。质量评价（对抗工程师复扫）：未发现 P1/P2 级缺陷；两趟 walk（manifest 哈希→硬链）间的 TOCTOU 属单用户桌面低危观察（→P3-4，verify 可检出、restore 前置拦截兜底）。

### 4.4 device 护栏与 lite 发行版（W19 FR-3，已验证）

resolve_device（device.py:19-49）：仅精确 `"cuda"` 请求且 `torch.cuda.is_available()` 为 False 时诚实回退 cpu + warning 留痕；其余（cpu/None/"cuda:0"）原样透传并在 docstring 声明"由调用方自担"；torch 不可导入按 cuda 不可用处理（lite 兜底）。16 个调用方接线（9 引擎 + SAM 适配器——W21 补齐第 8 处 label 页漏项 + 守卫测试）。lite 派生：**方案 v1"仅裁 CUDA DLL"被蒸馏冒烟三次递进否定后改 v2"CPU 轮子整目录替换"**（torch CUDA wheel 的 PE 导入表硬链 torch_cuda/c10_cuda/cudart/cudnn，torch/__init__ 对 lib 内每个 DLL 强制加载——ADR 级教训留档）；full 4.4G 保 GPU / lite 1.97GiB（产品字节口径，排除 __pycache__/*.pyc），守卫测试随产物存在自动激活。

### 4.5 后台任务注册表与协作取消：gui/core/jobs.py（W15 建立，W18 补取消接线，已验证）

run_job(fn, name, on_error) → 登记后 start（失败回滚摘除）→ 执行（fn 声明 cancel 参数则透传同一 threading.Event）→ 异常路由 on_error → finally 自摘除。v3 的两个已知缺口均闭合：**on_error 零使用**→10 个页面消费点全部接线（本轮重验: gui 全域缺 on_error 的 run_job 调用=0 处，事实核查员独立复扫一致；守卫测试 tests/test_gui_on_error.py）；**协作取消空转**→predict 批量 `_work(cancel)` 接注册表 Event（tests/test_w18_batch_cancel.py，退出时 ≤1 批可停）。全生产包唯一 `threading.Thread(` 直调仍是本工厂（jobs.py:146）。退出链：TrainWorker 去 parent + finished 先清引用再 deleteLater（train/page.py:299-316，对抗工程师核验"谁负责 deleteLater"有答案且页面先销毁不 RuntimeError）；closeEvent 三路活跃检测 + request_stop_all(1s) + TrainWorker wait(1.5s) + QThreadPool waitForDone(0.5s) 全有界，超时放弃路径留痕告警（shell.py:341-347）。

---

## 5. 启动链与生命周期

### 5.1 GUI 桌面链（已验证）

```
python -m gui.main
 → setup_logging()            # RotatingFileHandler(UTF-10MB×5)+stdout；W19: 全 handler 挂
                              #   SensitiveRedactFilter（"初始密码: XXX"→[REDACTED]，main.py:73-92）
 → load_user_settings() → set_language / QApplication
 → acquire_single_instance_lock()   # QLockFile %TEMP%
 → ThemeManager.apply → build_window()
     一次性构造 11 页（注册表导入）+ 信号枢纽接线
     （login_success→跳主页并携带 user/role 枚举,W18；language_changed 单点广播）
 → win.select("login") → app.exec()

 首启凭据（W19 FR-5）：无 users.json → 生成随机密码写
   configs/initial_credentials.txt（一次性文件，改密成功即删）+ must_change=true
   强制改密拦截（login/page.py:359-360，取消不放行）；日志/控制台零明文

 退出 closeEvent（shell.py:287+）：
   活跃检测三路并集（jobs 注册表真相源 + TrainWorker isRunning + 批量按钮约定）
   → 确认后有界停机 request_stop_all(1s) → TrainWorker stop+wait(1.5s)
     → QThreadPool×2 waitForDone(0.5s) → registry.clear_cache() → 审计 flush → accept
   ⚠ 超时后线程随进程强杀（已留痕告警）——有界停机的固有放弃路径（P3 观察）
```

### 5.2 gRPC 服务链（已验证·对抗复核）

```
python -m serving [--host 127.0.0.1 --port 50051 --max-workers 8]
 → serve() → create_server()
     → 非回环 host 即 logger.warning（ADR-0001 执行补丁,server.py:324-334）✅v3 P2-9
     → SharedMemoryManager()（构造清扫陈旧 ava_*.bin + 区域上限 64）
     → setup_file_logging()（轮转 5MB×3,幂等）
     → 延迟 get_dispatcher() + grpc.server(ThreadPoolExecutor)
 → wait_for_termination()
 RPC: Ping / ListTasks / GetTaskInfo / LoadModel / UnloadModel / Detect
      / ReleaseSharedMemory(lease_id≠0 时校验租约归属) / FetchRegion(流式,PoC)
 Detect 热路径: dispatcher.infer → serialization(bool RLE+<64KiB 内联)
   → 大载荷才写 shm（写入口先 _reap_expired TTL 清扫）→ 登记区域
```

---

## 6. 核心协作关系

| 组件 | 层 | 职责（规模） |
|---|---|---|
| core/interfaces_supervised | 基础 | 类型契约单源 + 安全加载（478 行，豁免声明+AST 守卫） |
| core/session + audit_logger | 基础 | 会话通道 + 审计（74/74 条带非空 user 与枚举角色，本轮实测） |
| models/supervised | 领域 | EngineRegistry + 9 真引擎 + device 护栏（1,260 行） |
| training / labeling / inference / evaluation / exporter | 领域 | GenericTrainer（375）/ 6 模式标注+SAM（2,096）/ 滑窗 NMS（426）/ 指标+eval_flow（731）/ ONNX（307） |
| dataset / project | 数据 | LabelMe 配对+导出（396）/ 文件系统存储（443）+ versioning 快照（328） |
| industrial_vision_platform | 平台 | VisionModelDispatcher + LRU 显存（292 行）——**serving 专用（W18 正式化）** |
| gui / serving / benchmarks | 表现/服务/度量 | 11 页桌面壳（7,716）/ gRPC+MMF+C#（1,821+C#）/ 基准套件（604） |

三条主协作链（已验证）：

1. **GUI 推理链**：predict 页 → run_job 后台线程（on_error 复位按钮）→ get_engine（registry 直连+device 护栏）→ frozen DetectionResult → invoke_main 回主线程渲染（预览自适应：全分辨率留存+KeepAspectRatio+8px 边距+resizeEvent 重适配，predict/page.py:563-582，W21）。
2. **训练链**：train 页 → TrainWorker（无 parent，协作停止）→ GenericTrainer.fit（save 失败 raise）→ finished 先清引用再 deleteLater；审计带真实用户。
3. **服务链**：C# Client → gRPC → Servicer（每方法 try/except+success=False）→ dispatcher → serialization（内联优先）→ 小载荷内联返回 / 大载荷 MMF+TTL → C# Reader（内联优先解码）→ 结果区域由 TTL 兜底回收（客户端无需主动 release 小载荷；大载荷仍可显式 Release 或等 TTL）。

---

## 7. 实测指标表（含复核状态；阈值命中项即关键数字，逐项带重验 token）

| 指标 | 实测值 | 复核状态 | 阈值定级/备注 |
|---|---|---|---|
| 门禁全量 | 966 passed / 4 skipped / 62.01s / rc=0 | **主审独立重跑 + 事实核查员二次独立重跑（59.52s）双一致** | 正常 |
| 覆盖率 | **93.05%**（8,513 语句/592 缺；fail-under=92） | 两次独立重跑输出一致 | 正常（棘轮 89→90→92→现值 93.05） |
| 生产 LOC | 19,215 / 117 文件 | 重验: 事实核查员分包复核一致 | —（v3 16,754/107） |
| 单文件最大 | label/page.py 828 | 重验: wc 一致 | 300–1000 = P2 档阈值；校准观察（→P3-1） |
| >100 行函数 | 1 个（201，豁免声明+守卫） | 重验: AST 一致 | >100 = P0 档阈值；校准 P3（豁免边界生长→P3-6） |
| broad except 密度 | 59 处/19,215 行 = **3.07/千行** | 重验: 独立 grep 一致 | **P2 档**（1–5/千行；v3 3.10 持平）；新增处多数带日志留痕 |
| 纯静默 except | 0（v3 已治理保持）；裸 except 0；TODO/FIXME 0；生产包 print 0（仅 scripts/benchmarks CLI 26 处） | 实测 | 正常 |
| threading.Thread | 生产代码 1 处（jobs.py:146 工厂本体） | 重验: grep+守卫测试 | 正常 |
| on_error 接线 | gui 全域 run_job 缺 on_error = **0 处** | 重验: 事实核查员独立复扫 | 正常（v3 P2-1 闭环实锤） |
| lock↔venv | lock 212 包 = freeze 212 包，PEP503 归一**双向差集空** | 重验: 独立脚本复验（v3 漂移 6 包→0） | 正常（v3 P2-4② 闭环） |
| git 卫生 | `.autofix-loop/`×6、`_i18n_report.txt`、`_missing_keys.txt`、`.benchmarks/wave19-raw.json` 被跟踪且 .gitignore 零覆盖（check-ignore 全 rc=1） | 重验: git ls-files + check-ignore 双证 | →P2-1 |
| 敏感文件边界 | `configs/initial_credentials.txt` **不在 .gitignore**（check-ignore rc=1）；users.json/license.key/user_settings.json 已忽略 | 重验: 一致 | →P2-1（fresh clone 首启明文凭据可被 add -A 入库） |
| 测试日志污染 | autovision.log 含 "pytest-of" **1,904 行**（v3 时 326） | 重验: grep -c 一致 | →P2-1c（本地可观测性污染，logs/ 已忽略不入库——对抗修正定性） |
| 审计健康 | audit_20260818.jsonl 74 条，74/74 含非空 user，角色为枚举值 | 实测 JSON 逐行解析 | 正常 |
| CI | test job 954 passed/93.00% + dotnet-test 54 绿（同 sha 重触发验证） | 引用记录，时点：d2018ab（08-19） | 正常（v3 P2-4① 从未运行→双远端真实绿） |
| UIA 真窗 | 6/6（三轮取证各轮全取得） | 引用记录，时点：d2018ab 提交内记录（同日） | 优点 |
| C# | 54 passed | 引用记录，时点：CI 08-19 | 优点（未复跑，§12） |
| dist 产物 | full 4.4G / lite 2.1G（du；lite 产品字节 1.97GiB） | 重验: du 一致 | 正常（lite 守卫 14 passed 引用记录） |
| 性能基线 | det CPU p50 516.6ms / cls 20.5ms / 显存峰值 38.8MiB / 冷启动 0.678s | 引用记录，时点：docs/benchmarks/baseline-2026-08-18.md（落档） | 正常（v3 S1 空白已填；不进门禁断言——机器相关只落档） |
| 协议字段 | lease_id=6/lease_ttl_ms=7/masks_inline=10/keypoints_inline=11/FetchRegion 流式 | 重验: .proto L28/L30/L119/L120/L166 | 正常（additive，Grpc.Tools 编译期再生成） |

---

## 8. 多视角评估

### 8.1 优点（均（已验证），对抗复核为主）

1. **v3 整改闭环率 11/12 且真实**：两条 P1（shm 三重治理、评估三数组）经对抗工程师临时脚本实测闭合；P2 九条落地均有 file:line+守卫测试；唯一未修是仓库卫生（P2-6）——**未修项也如实可见，无失联条目**（附录 D 全对照）。
2. **门禁独立可复现且双跑一致**：两次独立重跑 966/93.05%/rc=0（62.0s 与 59.5s）；覆盖率棘轮四波爬升（89→90→92→93.05）后地板稳固；三层金字塔（离屏 966 + UIA 6 真窗 + C# 54）+ 基准套件。
3. **构建链从 v3 主缺口翻转为正资产**：CI 双远端真实运行绿（含同 sha 重触发排除宿主偶发）、lock↔freeze 双向零漂移（独立复验）、full/lite 双产物带守卫、dotnet job 进 CI——"第二台机器"问题闭环。
4. **新代码质量持续高于存量**（对抗工程师 8 攻击面结论）：versioning（硬链回退/原子写/污染检出/诚实失败）、device 护栏（精确 cuda 契约+16 调用方）、_natural_key 两级键（17/20 位混长时间戳组内单调实测）、predict 预览自适应（None/空图守卫齐）、SAM 哈希快路径（稳态零哈希）、make_lite_dist（rmtree 有守卫且目标在暂存目录）——**8 个攻击面无一达 P1**。
5. **安全水位再上台阶**：RCE 名级白名单+persistent_load 保持；密码卫生三件套（一次性文件+强制改密拦截+全 handler REDACT 过滤）；非回环绑定告警；CSV/xlsx 公式注入消毒；encoding="utf-8" 全覆盖。
6. **决策可追溯体系持续运转**：ADR-0001/0002（含被否决方案与微基准依据）、22 个 wave 的 PRD+tasks+state、每修复带 W 注释回归锚；lite 方案"三次递进否定 v1 才定 v2"的探索过程留档。
7. **性能可观测性从零到一**：基准三件套+基线落档（绝对值机器相关只落档不进门禁——诚实口径），覆盖率/LOC/AST 均有守卫测试棘轮。
8. **UI 细节质量**：预览自适应修复竖图裁切、缩略图确定性自然排序（真实 1288 文件实证 281 组时间戳单调）、i18n 缺译清扫——用户可见的"混乱/裁切"类缺陷在本轮被系统性消灭。

### 8.2 缺点清单（终版：P0×0 / P1×0 / P2×1 / P3 观察 8 项）

> 主审 4 视角 + 对抗工程师 4 结论组（全部存活，含 2 处表述修正与 1 条新 P3）合并定稿。每条带实测数字/复核 token + 定级依据。

#### P2 级

**P2-1 仓库卫生与敏感文件边界：瞬态产物被跟踪 + 明文凭据文件无忽略条目 + 测试态/生产态日志未隔离**（已验证·对抗复核；v3 P2-6 未修 + W19 引入新缺口）
三子项：**a) 被跟踪的瞬态/工具产物 9 个**——`.autofix-loop/`×6（循环工作态）、`_i18n_report.txt`/`_missing_keys.txt`（检查器每次重写）、`.benchmarks/wave19-raw.json`（原始基准数据，提炼版已在 docs/benchmarks/），均被 git 跟踪且 .gitignore 零覆盖（check-ignore 全 rc=1，重验一致）——工具一跑工作区即脏，循环态进产品仓历史；**b) `configs/initial_credentials.txt` 不在 .gitignore**（check-ignore rc=1；.gitignore 仅列 users.json/license.key/user_settings.json）——fresh clone 首启必经 login/page.py:202→207 写出**明文**用户名+密码文件，`git add -A` 即入库；远端为 GitHub VisionFocus2022/AutoVisionAgent（据 2026-08-18 推送记录为公开仓——**条件式断言**，本轮离线未复核可见性，对抗工程师指正），公开仓+明文凭据的潜在入库路径是实质敞口；**c) 测试态/生产态日志未隔离**——autovision.log 1,904 行 pytest-of 污染（v3 326 行，加重 5.8 倍；对抗修正定性：logs/ 已被忽略**从未入库**，属本地可观测性污染非仓库污染），真实用户操作与测试噪音混写排障不可分。定级依据：威胁模型=公开仓+无意识提交（非主动攻击）+ 修法 <1 人时（.gitignore 补 5 条 + git rm --cached 9 文件 + conftest 日志重定向）→ P2（不升 P1：当前盘面无该文件、无实际泄漏、单工位）。注：`.workflow/` 36 文件为 structured-dev-workflow 有意审计轨迹（"阻止无证据完成"），与瞬态工具产物不同类不计入加重（对抗工程师裁定无失公允）；其中一次性脚本 `.workflow/wave11-arch-uia/extract_digest.py` 含外部会话绝对路径宜顺手清理（观察）。

#### P3 观察（不编号立案，随 wave 顺手处理）

- **P3-1 页面文件规模爬升**：label 828 / data_manage 792（W20 时 769→792）/ predict 784——阈值表 300–1000=P2 档，但趋势性问题是**文件级无守卫**（函数级 AST 守卫仅覆盖 metrics_supervised 单文件）：page.py 类文件在"近上限"注释下继续生长。建议文件级 ≤800 守卫测试（现状值棘轮）或继续下沉 workers/纯函数层（data_manage workers.py 是好样板）。
- **P3-2 协议演进半成品（声明过的 PoC）**：lease_id/lease_ttl_ms/FetchRegion 服务端+proto+专项测试就绪，C# 客户端未消费（ADR-0002 定位"默认路径不动"）——现状诚实，但需择期决策"接线 C# 或冻结标注"，否则双端协议面持续分叉。
- **P3-3 eval_flow.py:131 `float(result.score)` 裸取**（对抗工程师新发现，实测复现）：引擎 per-box scores 短于 N 且无 `.score` 属性时 AttributeError 逃出 except 元组（引擎契约违反型边缘，上游 on_error 可兜住不卡死）——`getattr(result, "score", 0.0)` 一行修。
- **P3-4 versioning 两趟 walk TOCTOU**：create_snapshot 的 manifest 哈希与硬链镜像两次遍历间文件变动会产生 manifest 与快照内容不一致（单用户桌面低危；verify 可检出、restore 前置 verify 拦截兜底）。
- **P3-5 broad except 密度持平**：59 处/3.07 千行（v3 3.10）——新增 7 处多带日志留痕；维持观察不立案。
- **P3-6 豁免函数边界生长**：_extract_state_dict_safe 195→201（+6，W17-22 间）——豁免声明无上限，建议在声明处写明上限（如 ≤220）防无界生长后守卫失义。
- **P3-7 凭据文件删除路径残余**（对抗工程师）：os.remove 失败（Windows 占用）仅记日志无重试/下次启动补删；用户反复取消改密对话框→文件长存（内容自附删除提示，设计可接受）。
- **P3-8 遗留目录**：unused/ 零引用仍在树（v1 时代遗留）；退出超时线程随进程强杀为有界停机固有放弃路径（已留痕，不立案）。

### 8.3 18 视角覆盖矩阵（C1-C6 必查 / S1-S12 适用性判定 + 扩展视角）

| 视角 | 状态 | 已查 | 关键发现 |
|---|---|---|---|
| C1 架构合理性 | 必查 | ✓ | 分层无环保持；dispatcher 定位 W18 正式化（gui 引用=0+守卫）；新增能力层位正确；观察 P3-2 协议半成品 |
| C2 可维护性 | 必查 | ✓ | TODO 0、i18n 缺 1 键（测试串）、注册表单源保持；P3-1 文件规模爬升+文件级守卫缺位 |
| C3 可靠性 | 必查 | ✓ | v3 两条 P1 修复经实测闭合；on_error 10/10；退出链有界；P3-3 result.score 边缘 |
| C4 可测试性 | 必查 | ✓ | 93.05% 双跑一致 + 三层金字塔 + 守卫测试资产（AST/on_error/jobs/dispatcher/lite）；文件级规模守卫缺位（P3-1） |
| C5 可运维性 | 必查 | ✓ | 审计 74/74 user、基准落档、CI 双远端；P2-1c 日志污染（测试态隔离未做） |
| C6 安全性 | 必查 | ✓ | RCE/密码卫生/告警全达标；P2-1b 公开仓明文凭据 .gitignore 缺口 |
| S1 性能伸缩 | 适用 | ✓ | **v3 空白已填**：基准三件套+落档（det p50 516ms CPU/显存 38.8MiB/冷启动 0.68s）；MMF vs 流式 11.7x 微基准支撑 ADR-0002 |
| S2 数据持久化 | 适用 | ✓ | 原子写保持；新增 versioning 快照/恢复（非破坏）；manifest 原子写；P3-4 TOCTOU |
| S3 并发 | 适用 | ✓ | jobs 单入口+协作取消接线；TTL 清扫线程安全（_lock）；TrainWorker 生命周期修复 |
| S4 API 契约 | 适用 | ✓ | proto additive 字段+Grpc.Tools 编译期再生成+跨语言测试；P3-2 lease 半成品（PoC 声明） |
| S5 依赖健康 | 适用 | ✓ | lock↔freeze 零漂移（独立复验）；setuptools 84 出 CVE 区间保持 |
| S6 灾备 | 不适用 | ✓ | 单机学习项目，无生产部署/备份承诺（不适用原因） |
| S7 合规 | 适用 | ✓ | AGPL LICENSE 在树（35KB）；公开仓场景许可证合规；无 PII/监管面 |
| S8 可观测性深化 | 适用 | ✓ | 三轨（运行/审计/历史）活跃带 user；P2-1c pytest 污染；无 metrics/tracing（规模未到） |
| S9 i18n/a11y | 适用 | ✓ | 缺译 1 键（测试串）；角色枚举化完成（i18n×持久层交叉缺陷已解） |
| S10 演进/ADR | 适用 | ✓ | ADR-0001/0002 + 22 wave 决策链 + v2→v3→v4 审查对照闭环——最大资产之一 |
| S11 构建链 | 适用 | ✓ | **v3 主缺口翻转为正资产**：CI 真跑绿+lock 零漂移+双产物守卫+基准落档 |
| S12 资源泄漏/生命周期 | 适用 | ✓ | shm 三重治理（内联+TTL+租约）；TrainWorker deleteLater；SAM/预览资源有界；退出放弃路径留痕 |
| 扩展：指标诚实性（领域，v3 沿用） | 适用 | ✓ | P1-2 闭环实测；FID/LPIPS 样本帽参数化；eval 空态诚实保持 |
| 扩展：公开仓边界（v4 新增） | 适用 | ✓ | P2-1 主案（b 子项）——开源暴露面下的敏感文件治理 |
| 扩展：测试态/生产态隔离（v3 沿用） | 适用 | ✓ | P2-1c 未闭环（污染加重 5.8 倍，定性修正为本地噪声） |

---

## 9. 改进路线（三波 × ROI，动作回引缺点编号）

### 🚑 第一波·止血（低风险，约 0.5-1 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 1 | 仓库卫生与敏感边界收口 | P2-1 | .gitignore 补 5 条（.autofix-loop/、_i18n_report.txt、_missing_keys.txt、.benchmarks/、**configs/initial_credentials.txt**）+ `git rm --cached` 9 文件 + 顺手清理 .workflow 内含绝对路径的一次性脚本；对 .workflow/ 的保留策略写一行决策（有意审计轨迹） |
| 2 | 测试日志隔离 | P2-1c | conftest 把测试态日志重定向独立目录（或 per-run 文件名），生产 autovision.log 不再混入 pytest-of 路径 |
| 3 | result.score 防御 | P3-3 | eval_flow.py:131 `float(getattr(result, "score", 0.0) or 0.0)`，补一条契约违反引擎用例 |

### 🔧 第二波·守卫与决策（中风险，约 2-3 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 4 | 文件级规模守卫 | P3-1 | AST 守卫测试扩为全生产包文件 ≤800 行（现状 828 棘轮：先设 850 再收敛）+ >100 行函数全包守卫（现仅 metrics 单文件） |
| 5 | 豁免上限声明 | P3-6 | _extract_state_dict_safe 豁免注释补"上限 220 行，超出须复审拆分" |
| 6 | 协议演进决策 | P3-2 | ADR-0002 补状态行：接线 C# lease（读后自动续租/释放）或冻结 PoC 标注"跨机场景再启"——二选一收敛双端协议面 |
| 7 | 凭据删除补删 | P3-7 | 下次启动时扫残留 initial_credentials.txt（改密已完成则补删；未改密则提示），os.remove 失败告警保留 |

### 🚀 第三波·演进（高风险/大价值，充分 PoC 后）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 8 | 角色权限面 | v3 P2-8 观察 | 当前角色纯展示枚举（对抗工程师证实零门控）——若需多角色工位，按 role 对页面/按钮 setEnabled 门控；单工位则文档明示 |
| 9 | C# lease 接线（若第 6 项选接线） | P3-2 长期 | Mapper 保留句柄→读后 release_leased；跨机场景启用 FetchRegion 流式（11.7x 损失换网络可达） |
| 10 | versioning 增强（可选） | P3-4/领域 | 单趟 walk（边哈希边镜像）消 TOCTOU；快照 pruning 策略（数量/年龄上限） |

> v3 §9 三波 17 项全部闭环后，第三波清单首次接近空置——现代化主题（性能基线/协议 PoC/dist 瘦身/版本管理/角色）已在 W19 完成，本表第三波为可选演进非必做。

---

## 10. 决策者建议

1. **总体判断：架构债务清偿完毕，从"整改波次"切换到"守恒守护"模式。** 三轮审查债务曲线连续下行（v2 35 条 → v3 12 条 → v4 1 条 P2），且本轮"无 P0 无 P1"经对抗工程师 8 攻击面+2 项实测攻击后存活——继续演化、无重写议题，也**无待清偿的骨架债**。建议投入从"修债"转向"防再生"：守卫测试棘轮（文件级/豁免上限）+ 卫生习惯（.gitignore 影响面检查）。
2. **若只做一件事：第一波动作 1（半小时）。** 公开仓+明文凭据 .gitignore 缺口是当前唯一有真实暴露面的安全卫生项，且修法极便宜。动作 1-3 合计不足一人日即可把 P2-1 与 P3-3 清零，届时仓库将达到"零已知 P1/P2"状态。
3. **公开仓边界意识制度化（v4 新教训）。** W19 引入 initial_credentials.txt 时未同步评估 .gitignore 影响面——建议 PRD 模板加一栏"新增落盘文件→忽略策略"；这是仓库从私有转公开后唯一需要补的心智模型。

---

## 11. 完整性批判记录（九问实答）

1. **最关键风险面覆盖了吗？** 已覆盖：公开仓敏感文件边界（P2-1，主审+对抗双证）、协议半成品状态（P3-2，ADR 声明核验）、测试态隔离（P2-1c，污染定量）、两条 v3 P1 修复的实证闭合（对抗脚本实测）。无"已识别未审查"的最高风险面遗留。
2. **有没有没打开过的子系统？** 有并如实声明：labeling 内部 modes（W21 仅动 sam_adapter 且经对抗复扫）、inference/tiling、gui/widgets×3、C# 未整体逐行（v1/v2/v3 背书沿用 + 本轮 Mapper 内联点核验）；scripts/make_lite_dist.py 与 benchmarks/ 以"对抗工程师 8 攻击面扫查+守卫/元测试在门禁绿"背书，主审未逐行细读。
3. **外部边界错误路径看了吗？** 看了：TTL 过期路径（_reap_expired 三写入口接线，对抗核验）、租约过期与错误归属（release_leased 校验+测试）、M≠N 失配（对抗实测两向不崩）、部分失败回滚（serialization:72-104）、initial_credentials 删除失败路径（P3-7）。未做：真实跨机网络（n/a 回环设计）、CUDA OOM 路径。
4. **非功能默认成立了吗？** 没有：性能四项全部有落档基准（引用 baseline-2026-08-18，绝对值机器相关只落档不进门禁——口径诚实）；推理时延/显存/冷启动数字不再空白。
5. **运行产物的异常信号解释了吗？** 解释了：autovision.log 的 versioning INFO 系本轮门禁重跑所写（即 P2-1c 污染的活证据）；audit 74/74 user；serving.log 60 行健康；无 dump/崩溃文件；.snapshots 使用痕迹与 versioning 日志一致。
6. **只看主路径忽略边界？** 边界经对抗工程师专责攻击：M≠N、TTL 未接线假设（被驳倒——确已接线）、SAM 哈希碰撞（理论残余 P3）、versioning TOCTOU（P3-4）。
7. **文档自相矛盾？** 本轮抓到并处理：README 权威链接指 v3（本文产出后已顺手更新为 v4，见 §13）；v3 P2-4"CI 从未运行"与现状矛盾属演进非矛盾；主审中途三次自误（users.json 跟踪状态/函数区间口径/jobs.py:93 定性）均被复核纠正并留痕 §13。
8. **单一证据源结论？** 两条 P1 修复结论均 ≥2 源（主审查码+对抗实测）；50-100 行函数计数、C# 54、UIA 6/6、CI 结果为引用记录或单源（已标注时点）；核心数字全部经事实核查员独立重验（14 项 13 全一致+2 口径修正）。
9. **本领域该加的视角？** 已加并用上：公开仓边界（P2-1 主案）、指标诚实性（沿用，已闭环）、测试态隔离（沿用，未闭环）。可再补未补：数据漂移检测（版本管理已提供 diff 基础，属产品功能非架构债）。

---

## 12. 验证范围与局限

**已验证**：§7 全部数字（门禁两次独立重跑；LOC/文件数经事实核查员分包复核；broad except/AST/lock/污染/忽略状态/git 跟踪/proto 字段/dist 均独立重验）；v3→W17-22 整改核验 12 项主案（含对抗工程师对 P2-2/P2-3/P2-8 三项抽查与 M≠N/TTL 两项脚本实测）；8 个新代码攻击面的对抗扫查。

**未验证/未做**：
1. C# dotnet test 未本地复跑（54 绿引用 CI 08-19 记录；距 HEAD 无 proto/C# 契约改动，漂移风险低——对抗工程师评估"勉强可接受"）；UIA 6/6 引用 d2018ab 提交内同日记录（时点差≈0）。
2. GitHub 仓库可见性（公开/私有）离线未复核——P2-1b 按"据 08-18 推送记录为公开仓"的条件式断言处理；无论可见性，.gitignore 缺口本身成立。
3. lite 产物冒烟未本轮执行（守卫 14 passed 引用记录）；exe 未重建（HEAD 后无代码改动）。
4. 真实 C# 客户端 65 次连续 Detect 压测未做（v3 已声明，W17 修复以代码路径+测试+对抗核验背书）。
5. 圈复杂度（radon 未装，AST 行数代理沿用）；真实 CUDA OOM、跨机网络路径。
6. labeling modes/inference/widgets/C# 全量未逐行重读（依据：diff 枚举 W17-22 改动不含它们+对抗扫查+守卫测试）；make_lite_dist/benchmarks 主审仅签名级浏览（对抗+门禁背书）。
7. lock↔freeze 复验基于 pip freeze 与 lock 的包名集合比对（版本串未逐字符 diff——包名集相等且均为 == 锁定，版本漂移风险极低）。

---

## 13. 对抗验证与修正记录（审计轨迹）

**事实核查员（14 项）**：13 项完全一致 + 2 处口径修正：①"50-100 行=40"实为严格 >50 区间（恰 50 行另 2 个）——本文 §2.3 已改口径并注记；②主审称 jobs.py:93 为"docstring 示例"有误——它是 `def run_job(` 定义本身（签名含 on_error 形参），**且 gui 全域不存在缺 on_error 的 run_job 调用**，结论比主审表述更强。事实核查员另完成第二次全量门禁独立重跑（966/4/93.05%/rc=0/59.52s）。

**对抗工程师（4 结论组全部存活，产出 1 新 P3 + 3 修正）**：
1. **A（无 P0/P1）存活**：8 个新代码攻击面（versioning/device/natural_key/preview/SAM 快路径/make_lite_dist/lease/FetchRegion）无一达 P1；M≠N 两向失配实测不崩（P1-2 闭合）；TTL 接线确凿（`_write_raw` 创建前 `_reap_expired`，三写入口全覆盖，13 个专项测试实跑，P1-1 闭合）。**新发现 P3-3**：eval_flow.py:131 `float(result.score)` 裸取在"per-box scores 短于 N 且无 .score 属性"的契约违反型引擎下 AttributeError 逃逸（实测复现，上游 on_error 兜底）。
2. **B（仓库卫生）存活但修正两处**：①autovision.log 污染从未入库（logs/ 已忽略）——从"仓库卫生加重"改判"本地可观测性污染单列"（P2-1c）；②"公开仓"离线不可验证——改条件式断言（P2-1b）。`.workflow/` 有意审计轨迹不计入加重（裁定主审未混计为正确）。
3. **C（整改抽查 3 项）全部闭合**：退出链 deleteLater 责任明确+页面先销毁不 RuntimeError（超时强杀为留痕过的固有放弃路径）；密码明文通道关闭、must_change 强制改密使"永不改密"走不通（残余 P3-7）；角色枚举迁移 `_migrate_role` 全仓唯一读点、gui/core 零角色比较残留（附带观察：角色纯展示不门控——第三波第 8 项素材）。
4. **D（引用证据）可接受**：UIA 时点差≈0；C# 隔三波未触契约；建议引用记录带提交号时点——本文 §7 已照办。

**主审自身被纠正 3 处**（全程留痕）：①users.json 跟踪状态误读——单行输出把 `ls configs/` 的结果误当归属 `git ls-files`，后经 `git cat-file -e HEAD:` + `diff --cached` 三口径纠正为**未跟踪**（.gitignore 对未跟踪文件有效）；此误读若未纠正会虚构一条"哈希入库"的假 P1——**规则①"测量也需复核"的又一活例**（与 v3 的 16,861→16,754 同性质）。②"50-100 行"区间口径（事实核查员）。③jobs.py:93 定性（事实核查员，结论反向加强）。

**本轮顺手修复 1 处**（审查过程即时落地，非整改波次）：README.md:42 架构文档权威版链接 v3→v4（本文产出后）。

---

**【落地后记 2026-08-19 W23】§9 第一波三动作当日全部落地**（`.workflow/v4-wave1-hygiene/` L1 档案，三段 TDD RED 先行）：①动作 1——.gitignore 补 5 条 + 9 瞬态文件出库 + extract_digest.py 删除 + .workflow 决策注释（P2-1 a/b 闭环）；②动作 2——AVA_LOG_DIR 环境变量约定四写入方接线（gui/serving/audit/history）+ 根 conftest 会话重定向 + UIA exe env 剥离，**全量门禁前后 logs/ 四文件逐字节冻结**（51,666 行不再增长；P2-1c 闭环）；③动作 3——build_prediction score/boxes 裸取 getattr 防御（P3-3 闭环，附带统一 boxes：同函数同族同逃逸路径，调查员实证 NoBoxes AttributeError 活复现）。门禁 966→**976 passed / 4 skipped / 93.06% / rc=0**（+10 用例：3+5+2）。**对抗验证（4 验证员并行）全部存活**：无第五日志写入方（全仓扫描实证）、冻结值经验证员独立重放复验、防御属性族 13 形态探针零逃逸；带回 MEDIUM×1 已修（元守卫 pathspec 补 configs/initial_credentials.txt）+ low×1 已修（sessionfinish 先关 FileHandler 再清理，%TEMP% 零残留实证），封版门禁复跑 976/93.06%/rc=0。待办移交：exe 重打包合并下一波做（eval 防御对合规引擎零行为变化）；logs/ 存量污染清档由用户拍板；v4 余项=第二波（文件级守卫/豁免上限/协议决策/凭据补删）+ 第三波（可选）。

**【落地后记 2026-08-21 W24】§9 第二波四项 + 用户拍板三项当日全部落地**（`.workflow/v4-wave2-guards/` L1 档案，TDD RED 11 先行）：①**#4 文件级规模守卫（P3-1）**——tests/test_w24_scale_guards.py 全 cov 包（pytest.ini --cov 12 包动态解析与覆盖率口径同源）文件 ≤800（棘轮 label/page.py=850 现测 828，§9"先设 850 再收敛"+棘轮失效断言强制删条目）+ 函数 ≤100 全包化（原 W18 守卫仅 metrics 单文件；RED 期限定名键失配擒获 201 行违例正是咬合实证）；②**#5 豁免上限（P3-6）**——形态豁免 docstring 补"上限 220 行，超出须复审拆分"（替换陈旧"约 195 行"）+ 守卫钉文本；③**#6 协议决策（P3-2）**——ADR-0002 状态行补**冻结**声明（二选一取冻结：取证 C# 客户端零 lease/FetchRegion 调用，回环拓扑+直读 3.55GB/s 对流式 11.7x 劣势+无跨机需求；跨机场景再启，重开条件见 ADR §决策 4）+ 守卫；④**#7 凭据补删（P3-7）**——gui/pages/login/page.py 模块级 `sweep_residual_initial_credentials()` 四态（absent/deleted/kept_pending_change/remove_failed），LoginPage.\_\_init\_\_ 接线补"删除失败仅记日志"缺口，users.json 不可读保守保留；⑤**用户拍板 logs 清档**——铁证签名行删（autovision.log -1,990 pytest-of、audit_20260630 整删、audit/0817/18 -25/-22 fake.png、history 五日 -13/-44/-136/-42/-8，逐文件与预测吻合，备份 %TEMP%），污染守卫 RED→GREEN 锚定，清档后新基线门禁前后逐字节冻结；⑥**W23 遗留 UIA 提示语分支**——uia_helpers.app_log_path() 按 AVA_UIA_SOURCE 分支（python→AVA_LOG_DIR 会话目录/exe→exe 目录 logs），两测试文件去写死路径+守卫；⑦**v4 §10.3 PRD 模板栏**——prd-lite §6 落盘产物+自检 6 项、prd-full §3.3 落盘文件表+自检 10 项（用户级技能仓）；⑧**用户拍板 exe 重打包并入**——full 88,414,000B@08-21 03:56（+1,805B=W23+W24 生产码）+ PYZ 28/6/48 全过 + lite 重派生 14 passed（中场门禁擒获 lite 406B 漂移=用户 08-19 16:42 运行 lite exe 追加日志，环境归因非代码，重派生复位）。门禁 976→**990 passed / 4 skipped / 93%（8552/592）/ rc=0**（+14 用例）。**对抗验证（4 验证员并行）**：规模守卫员/打包员**存活**（AST 独立复算与豁免表精确闭合；exe 内嵌 PYZ sha256=build PYZ、W23/W24 码逐常量核验在场、lite 独立字节对账 2,115,177,716B<2GiB、full/lite exe sha256 相同）；凭据员/清档员**部分成立**带回 **HIGH×1**（首轮清档漏第四铁证签名 tests\\test_ traceback 帧——autovision.log 仍残留 641 条测试异常记录 6,334 行，验证员 diff 备份独立计数精确吻合）+ **MEDIUM×2**（sweep 对 users.json 合法 JSON 非字典形态抛未捕获 AttributeError→启动崩溃，探针 X1-X4 实证；ADR 冻结行"仅内联路径"措辞与 ADR 决策 1 自身矛盾——实为内联+MMF 直读双路径）+ low×3（cov 正则空格形态、TOCTOU 误标、app_log_path 缺 __all__/未锚 REPO_ROOT）。**全部修复（TDD RED 7 先行→GREEN 25）**：sweep isinstance 收口+FileNotFoundError→absent+接线守卫升 AST；autovision.log 字节级记录删除恰 641 记录/6,332 行（49,676→43,344）；ADR/守卫措辞改"内联+MMF 直读双路径，Release 不带 lease_id"；cov 正则加固+解析数==出现次数断言；__all__+REPO_ROOT 锚定。**终版门禁 996 passed / 4 skipped / 93.08%（8559/592）/ rc=0**，r2 清档基线门禁前后逐字节冻结。留档：exe PYZ 内含完整 pytest 运行时（79 模块，pydub 依赖链静态分析误拉——spec excludes 候选）；lite 距 2GiB 余量 30.8MiB；PYZ 28/6/48 为手工 grep 绊线（唯一名实数 16/3/24）重定基流程见 state.json。UIA 未复跑：打包时机器不空闲（微信 7 进程+ToDesk+CPU 86%，W16/21/22 环境归因签名），机器空闲时复跑 tests/uia 可取 6/6。v4 余项=第三波（可选演进：角色权限面/C# lease 若解冻/versioning 增强）。

---

## 附录 D：v3 全部发现现状对照（W17-W22 落地 + 本轮核验）

**v3 P1×2**：P1-1 shm 结果区域 → ✅ 根治（内联激活+TTL 三写入口接线+租约 PoC+C# 内联优先；对抗工程师脚本实测闭合）；P1-2 评估构造失真 → ✅ 根治（三数组定长+失配防御+det_map 拆分守卫；M≠N 两向实测不崩；残余 P3-3 score 裸取）。

**v3 P2×10**：P2-1 异常路由 → ✅（10 消费点 on_error 全接+ui_on_error 桥+守卫；本轮复扫 gui 全域缺 on_error=0）；P2-2 密码 → ✅（一次性文件+强制改密拦截+REDACT 过滤三件套；残余 P3-7）；P2-3 退出链 → ✅（TrainWorker 去 parent+deleteLater+批量 cancel 接注册表+有界等待；超时强杀为留痕固有路径）；P2-4 CI/lock → ✅（CI 双远端真跑绿含同 sha 重触发；lock↔freeze 零漂移本轮独立复验；dotnet job 进 CI）；P2-5 文档漂移 → ✅（README/checklist v3 期已修；复刻计划横幅定位"方法论/决策档案"准确——两树分叉后其指向的外树真源声明成立）；P2-6 仓库卫生 → ❌ 未修且加重（→**v4 P2-1**：新增 .benchmarks 原始数据入库+initial_credentials.txt 忽略缺口；日志污染改判本地噪声单列）；P2-7 dispatcher → ✅（registry 直连正式化+gui 引用 0+守卫+export_onnx 显式签名灭 _EngineStub）；P2-8 角色枚举 → ✅（枚举+legacy 迁移唯一读点+userData；角色纯展示留第三波决策）；P2-9 非回环告警 → ✅（server.py:324-334 带 ADR 引用）；P2-10 巨石宣称 → ✅（det_map 112→拆分+AST 守卫+豁免声明；豁免生长→P3-6）。

**v3 P3×12**：serialization 死分支 ✅（激活）；部分失败回滚 ✅（:72-104）；上限先写后查 ✅（内联+TTL 后小载荷不再触上限，大载荷清扫兜底）；request_stop_all 快照语义 ◐ 未变（小窗口，仍观察）；torch.load 两处直调 ✅（豁免声明+注释）；train 页 INFO ✅（2 条）；home projects 硬编码 ✅（计数已真实接线 set_value，本轮核验）；QTimer 死导入 ✅（已清）；spec 图标 ✅（诚实注释"将来补图标"）；FID 样本帽 ✅（max_images 参数化）；xlsx lock 可达 ✅（lock 补齐后 openpyxl 在锁环境）；check_i18n 测试串 ◐ 仍在（无害，_missing_keys.txt 应出库并入 P2-1）；dist 体积 ✅（lite 1.97GiB 提供替代，full 保 GPU 为设计）。

**统计**：v3 主案 12 条（P1×2+P2×10）→ 根治 11 / 未修 1（P2-6→v4 P2-1）；P3×12 → 根治 9 / 部分 3（快照语义/测试串/上限场景已消但观察保留）。未修与部分项全部转入 v4 对应编号，无失联条目。

---

*本报告由 architecture-review 技能流程产出：整改核验（主审 file:line 逐项）+ 新代码审查 + 18 视角矩阵 → 主审独立重跑门禁 + 事实核查员二次重跑与 14 项数字复核 + 对抗工程师 4 结论组攻击（含 2 项临时脚本实测）→ 主审裁定与终稿。主审自身 3 处误读被复核机制纠正（users.json 跟踪状态误读最险——差一步虚构假 P1），全程留痕于 §13：这套流程连"裁判自己"也照审不误。*
