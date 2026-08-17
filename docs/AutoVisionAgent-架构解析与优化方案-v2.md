# AutoVisionAgent 2.0.0 架构解析与优化方案（v2）

> 审查档位：L2（标准档全面复审）｜ 审查日期：2026-08-17
> 审查对象：`E:\学习项目\视觉大模型`（AutoVisionAgent 2.0.0，git 仓库 master 一线；透镜执行期 HEAD 0bc218a）
> 方法：architecture-review 技能——6 视角并行透镜（演进/泄漏、架构/可维护、可靠/并发、可运维/安全、领域扫雷/v1 复核 + 可测试性/构建链补漏透镜）+ 9 条独立对抗复核 + 主代理终裁；全部关键数字实测可复现。
> **与 v1 的关系**：v1（`docs/AutoVisionAgent-架构解析与优化方案.md`，2026-08-16，4 P1 + 14 P2）为基线，其 4 条 P1 已由 W5-W7 波次根治（本复审零复发）、14 条 P2 中 8 条根治；本文为 v1 之后 36 个提交（W7-W10 落地 + W11 本复审）的全面复审。**P2 编号体系独立重编**，与 v1 不对应；文末附 v1 P2 状态对照表。
> 标注约定：`（已验证）`= ≥2 类证据交叉印证；`（已验证·对抗复核）`= 独立代理复测 confirmed；`（推断，依据：…）`= 单源推理。
> 诚实声明：本文降低误判概率，不保证零遗漏。对抗驳回/降级记录见 §13，未验证范围见 §12。

---

## 1. 文档摘要与阅读对象

AutoVisionAgent 2.0.0 是 **PySide6 桌面工业视觉平台**（标注 → 训练 → 推理 → 评估 → 发布全流程），带 **gRPC + 内存映射文件（MMF）混合传输的对外服务层**（供 .NET 客户端跨进程调用）与 **UIA 真窗端到端测试**。生产码 **15,881 行 / 12 包**，测试 **53 文件 / 13,302 行 / 607 离屏测试函数 + 6 UIA 真窗用例 + 45 C# 测试**（已验证）。

一句话总评：**W7-W10 落地后，骨架与质量基建已进入"可持续投资"水位**——分层无环、类型契约单源、覆盖率棘轮 89.35% 三层测试金字塔、决策可追溯体系（10 个 wave 的 state.json 全字段实装）是本项目最强资产；残余债务集中在三个主题：**长时运行资源治理**（共享内存泄漏）、**结果与指标诚实性**（审计停摆/训练假成功/FID 算法错/编造混淆矩阵）、**双配置死区与巨石函数**。终版 **1 P0 + 7 P1 + 27 P2**（原始 47 条发现合并去重 12 处跨视角重复、1 条 P1 终裁降级而来）；P0/P1 全部有明确修复路径，预计 1-2 周闭环。

阅读对象：本项目开发者 / 复用本骨架的新项目架构师 / 后续 wave 的执行代理。§8.2 缺点编号被 §9 改进路线直接引用。

---

## 2. 系统概览

### 2.1 定位

对标商业软件 SKolpha 的去 DRM 复刻 + 自研扩展：9 种有监督视觉任务、6 种标注模式（含 SAM 交互式）、项目管理、双语双主题 GUI、ONNX 导出、PyInstaller 打包、gRPC 服务化供 .NET 调用（已验证：pyproject/代码/docs 一致）。v1 时期的"引擎 6/9 + GUI 可达性倒挂"已根治：**9 引擎全部在树且为真实现**（engines/__init__ 9 模块全部 import TaskType/DetectionResult，det_yolo.py 等实测存在；test_m2_matrix 全绿由门禁 659 passed 佐证）（已验证）。

### 2.2 技术栈（每项验证依据）

| 层 | 技术 | 验证依据 |
|---|---|---|
| 语言 | Python 3.12 | pyproject.toml:5 + .venv pyvenv.cfg |
| GUI | PySide6 6.11.1 | .venv import 实测（v1 实测沿用，本轮 607 测试跑通间接印证） |
| 深度学习 | torch 2.5.1+cu121 / torchvision 0.20.1 | requirements.lock.txt 实测行（本地版本标签，见 P1-6） |
| 检测引擎 | ultralytics（det/pose/pseg YOLO）+ torchvision（cls）+ mm 系惰性（sseg/sgan/super）+ anomalib（abdet） | engines/ 9 文件实测；引擎侧 labels[int( 守卫逐文件核（det_yolo.py:63 等） |
| 服务桥 | grpcio 1.83.0 + protobuf 7.35.1 + MMF 零拷贝 + bool RLE（W7） | lock 实测；serving/ 全文精读；AVA_SHM_MASK_RLE 逃生门（serialization.py:119） |
| C# 客户端 | .NET gRPC 客户端 + SharedMemoryReader（9 文件 / 1,420 行 / 45 xUnit 测试） | serving/dotnet_client 实测（本轮行号级抽查，整体采信 v1 背书） |
| 测试 | pytest + pytest-cov（fail-under=89 棘轮）+ uiautomation 真窗 UIA + xUnit | pytest.ini:38 实测；tests/uia/ 存在性 + W11 记录 |
| 打包 | PyInstaller ≥6.0（onedir, console=False） | autovisionagent.spec（hiddenimports 57 行逐项比对完备） |
| 运行平台 | Windows 10 专用（MMF/UIA/QT offscreen 均平台绑定） | 本机实测；跨平台无声明（合理，不立案） |

### 2.3 规模度量

| 指标 | 值 | 复核状态 |
|---|---|---|
| 生产 LOC | **15,881**（gui 6,638 / labeling 2,058 / core 1,747 / serving 1,332 / models 1,204 / project 443 / ivp 591 / evaluation 432 / inference 426 / dataset 396 / training 312 / exporter 302） | 实测（12 包求和吻合；v1 14,361 → +1,520） |
| 最大单文件 | gui/pages/label/page.py **818 行**（v1 691） | 代理复核一致（wc 复核精确吻合） |
| 测试 | 53 文件 / 13,302 行 / 607 离屏测试函数 | 实测 |
| C# | 9 文件 / 1,420 行 / 45 测试 | 引用 W 系列记录（C4 采信基线） |
| 门禁 | 659 passed / 1 skipped / rc=0，全量 120s | 引用 W 系列记录 |
| 覆盖率 | 89.35%（fail-under=89；全仓 miss 857） | 实测（当日 .coverage 离线复核吻合） |

---

## 3. 整体架构

### 3.1 分层图（依赖方向自上而下，实测 import 关系绘制，已验证）

```
┌──────────────────────── 入口层（2 条启动链）────────────────────────┐
│ python -m gui.main（桌面 GUI）        python -m serving（gRPC 服务）│
├──────────────────── 表现层 gui（6,638 行）──────────────────────────┤
│ gui/core: shell(无边框主壳) theme(QSS双主题) i18n thread_bridge     │
│ gui/pages ×11: login home label data_manage train predict eval_    │
│               deploy flaw_gen project settings（构造一次·栈内复用）│
│ gui/widgets ×3: file_dialog loss_chart thumbnail_loader(QRunnable) │
├────────── 服务层 serving（1,332 行 ‖ C# 1,420 行）──────────────────┤
│ server(gRPC Servicer·默认127.0.0.1) serialization(bool RLE)        │
│ shared_memory(MMF零拷贝+atexit) proto(pb2生成码)                    │
│ ‖ 跨进程 ‖ C# VisionAgent.Shared: Client/Reader/Mapper/45 测试      │
├────────── 平台分发层 industrial_vision_platform（591 行）──────────┤
│ VisionModelDispatcher(统一入口+LRU显存+RLock)  data_manager_ext    │
├──────────────────────────── 领域层 ────────────────────────────────┤
│ models/supervised(1,204): registry + engines×9（全部真实现）       │
│ training(312): GenericTrainer 策略循环                              │
│ labeling(2,058): 6 模式 + canvas/controller + SAM 适配器(已接线)   │
│ inference(426): 滑窗分块+跨瓦片NMS   evaluation(432): 指标+FID/LPIPS│
│ exporter(302): ONNX 导出（opset14 动态轴）                          │
├──────────────────────────── 数据层 ────────────────────────────────┤
│ dataset(396): 图像×LabelMe 配对+格式导出   project(443): 存储/计数  │
├──────────── 基础设施层 core（1,747 行，零内部依赖）─────────────────┤
│ config(545·双体系脱节→P1-2) interfaces_supervised(323·类型契约单源)│
│ auth(PBKDF2 600k) audit_logger(→P1-4) detection_history(实时落盘)  │
│ image_io(unicode 读图·W10) exceptions constants                     │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 分层质量（已验证）

- core 零内部依赖，包间单向依赖，无包级循环（v1 import 矩阵实测 + 本轮 gui→引擎方向复测；modules 层内部环未全扫，见 §12）。
- gui 是组合根，直接 import 领域层——桌面单体合理形态；但存在 7 文件 8 处绕过分发层直插 registry 的越层访问（P2-7）。
- serving 与 GUI 进程完全解耦：GUI 零引用 serving/subprocess/QProcess（grep 0 命中），无孤儿进程纠缠（已验证）。

---

## 4. 关键机制剖析

### 4.1 类型契约单源：core/interfaces_supervised（已验证，lens 全量 grep）

323 行定义 TaskType×9、frozen 的 DetectionResult/TrainConfig/TrainArtifact、引擎 ABC、ITrainStrategy。**全仓 33 处生产 import**：gui 7 个文件（label/train/predict/eval_/flaw_gen/project/tasks_ui）取 TaskType/DetectionResult/TrainConfig/TrainArtifact，9 个引擎全部、training/serving/exporter/project/inference 亦依赖同源类型——跨层数据形状零平行定义。配套 `_safe_torch_load` 强制 weights_only=True + RestrictedUnpickler 白名单 + zipfile 安全提取（R4-7，:151-165、:179-228），torch.load 全仓 3 处调用全部防护（已验证）。缺口：安全回退块覆盖率 0（P1-7）。

### 4.2 跨线程纪律：invoke_main + 纯函数 worker 范式（已验证）

工作线程回主线程统一走 `gui/core/thread_bridge.invoke_main`（26 处转发调用，0 处裸 QMetaObject.invokeMethod）；W3-T3 后为显式类型映射（无 eval）。**data_manage/workers.py（151 行，0 个 PySide6 引用）是可推广的纯函数 worker 层范式**——页面仅做线程调度。同类教训已被制度化吸收：eval_ worker 的 except 元组显式加 TypeError 并注释"不收则裸穿线程、按钮永久卡禁用（W8 实测）"（eval_/page.py:382-385）。已知缺口：三套线程模型并存（P2-1）、deploy:163 一处 QWidget 工作线程读残留（P2-15）、_to_qarg 无 None/tuple/numpy 标量项且 invokeMethod 返回值被忽略（P2-16，offscreen 实测复现）。

### 4.3 gRPC + MMF 混合传输与 RLE（已验证）

设计动机成文（serving/shared_memory.py:1-26 设计动机段）：protobuf 对 4000×3000 大块的序列化开销 + "一区域一文件"简化所有权契约。大数组不进 protobuf：SharedMemoryManager 写 %TEMP%/autovisionagent_shm/ 下 MMF+mmap，gRPC 消息只传 SharedMemoryHandle{file_path,offset,length,dtype,shape}，dtype 契约与 .NET SharedMemoryReader 对齐。W7（wave7-dotnet-rle）：**bool 掩码 RLE 默认开启**，AVA_SHM_MASK_RLE=0 逃生门，决策依据（用户指令原文 + W6 基线数字）记录于 prd-wave7-dotnet-rle.md 头部（已验证）。C# 读取器每次 ReadBytes 内 using 即释放 MMF+accessor（SharedMemoryReader.cs:29-31），Dispose 链式释放 channel+reader（AutoVisionAgentClient.cs:198-202）。缺口：**区域生命周期完全依赖客户端自觉回收**（P1-1）。

### 4.4 11 页构造一次、栈内复用导航（已验证）

gui/main.py:84-94 一次性构造全部 11 页，shell.py:161-185 add_page/select 仅切 QStackedWidget 索引——无每次重建的泄漏/浪费。跨页状态显式接线（main.py:111-112 project_opened→data/predict set_project_dir、:143 同步主页统计）。Qt 定时器与连接面结构安全：全 gui QTimer 构造 0 处（唯一 QTimer.singleShot(600) 目标为永生页面方法，label/page.py:732）；98 处 .connect 全部发生在 build_window 构建期或以每次新建的临时 worker 为 sender（sender 析构自动断连），永久对象间无重复 connect 路径（已验证，逐条核对）。缺口：页面注册表漏第 11 页（P2-12）。

---

## 5. 启动链与生命周期

### 5.1 GUI 桌面链（已验证）

```
python -m gui.main
 → setup_logging()            # RotatingFileHandler(UTF-8 10MB×5)+控制台（gui/main.py:62-67）
 → _load_user_settings()      # configs/user_settings.json——只回读 theme/language（:198-205，
                              #   设置页写的 device 不回灌 → P1-2）
 → QApplication → ThemeManager.apply
 → build_window()             # main.py:84-94 一次性构造 11 页（flaw_gen 走 deep import :29 → P2-12）
 │   信号枢纽接线（:98-154）：
 │     page.status_changed ───────→ 主壳状态栏
 │     project.project_opened ───→ data/predict set_project_dir + home 统计刷新
 │     login.login_success ──────→ win.select("home")（用户名/角色被丢弃 → P2-17）
 │     shell.language_changed ───→ 全页 retranslate()（:155 单点广播，i18n 缺译 30→1）
 → win.select("login") → app.exec()

 退出 closeEvent（gui/core/shell.py:242-283）：
   活动线程探测（守卫大面积失灵 → P2-2）
   → 用户确认后仅 registry.clear_cache() 释放显存 → event.accept()
      （不 stop/join 训练线程 → P2-3；不 flush 审计缓冲 → P1-4）
```

### 5.2 gRPC 服务链（已验证）

```
python -m serving [--host 127.0.0.1 --port 50051 --max-workers 8]
 → serve() → create_server()
     → 延迟 get_dispatcher()（torch 未就绪不影响模块加载）
     → grpc.server(ThreadPoolExecutor(8)) + add_insecure_port（server.py:190，默认回环 :192/:215）
 → wait_for_termination()     # 仅捕 KeyboardInterrupt（:203-207，无 signal handler → P2-4）
 RPC: Ping / ListTasks / GetTaskInfo / LoadModel / UnloadModel / Detect / ReleaseSharedMemory
 Detect 热路径: dispatcher.infer → serialization（bool RLE）→ SharedMemoryManager 写 MMF+登记区域
   （区域无 TTL/上限/reaper，回收纯靠客户端显式 Release → P1-1）
```

---

## 6. 核心协作关系

| 组件 | 层 | 职责（规模） |
|---|---|---|
| core/interfaces_supervised | 基础 | 类型契约单源（323 行，33 处生产引用） |
| core/config | 基础 | dataclass 配置树（545 行，82% 死区 → P1-2） |
| models/supervised | 领域 | EngineRegistry + 9 真引擎（1,204 行） |
| training / labeling / inference / evaluation / exporter | 领域 | GenericTrainer 策略循环（312）/ 6 模式标注（2,058）/ 滑窗 NMS（426）/ 指标（432）/ ONNX（302） |
| dataset / project | 数据 | LabelMe 配对+格式导出（396）/ 文件系统项目存储（443） |
| industrial_vision_platform | 平台 | VisionModelDispatcher 统一入口 + LRU 显存(max_loaded=2) + RLock（591 行） |
| gui / serving | 表现/服务 | 11 页桌面壳（6,638）/ gRPC+MMF+C#（1,332 + C# 1,420） |

三条主协作链（已验证）：

1. **GUI 推理链**：predict 页 → dispatcher.infer → registry/get_engine → 引擎（LRU 驱逐最久未用）→ frozen DetectionResult → invoke_main 回主线程渲染。除 predict:227 等 8 处直插 registry 的旁路（P2-7）。
2. **训练链**：train 页 → TrainWorker(QThread，协作停止 threading.Event，每 epoch 检查) → GenericTrainer.fit → 引擎侧 ITrainStrategy（前向/反传/checkpoint sidecar .meta.json/断点恢复/早停/LR 调度）→ finished_sig → UI 显示完成（**保存失败被吞时 UI 谎报成功 → P1-3**）。
3. **服务链**：C# AutoVisionAgentClient → gRPC protobuf 信令 → Servicer（每方法 try/except + success=False 回传）→ dispatcher → serialization（bool RLE）→ MMF 文件+mmap → C# SharedMemoryReader 按 Handle 契约零拷贝读 → DetectionResultMapper（**不保留 shm 句柄 file_path → 客户端结构性无法回收 → P1-1**）。

---

## 7. 实测指标表（含复核状态）

| 指标 | 实测值 | 复核状态 | 阈值定级/备注 |
|---|---|---|---|
| >100 LOC 函数 | **9 个**（复核另发现 1 个少报，实际 10） | AST 实测 + 代理复核一致（9/9 精确复现） | **P0 档**（→P0-1） |
| 50-100 LOC 函数 | gui 16（复核 17）+ 引擎层 9 | AST 实测 | 观察档 |
| 单文件最大 | label/page.py 818 | 代理复核一致（wc 吻合） | 300-1000 = P2 档（并入 P0-1 证据） |
| except Exception 密度 | 44 处 / 15,881 行 = **2.77/千行** | 实测（双视角独立计数一致） | P2 档 1-5/千行（→P2-13） |
| 静默吞掉 | 13/44 = 29.5%（纯 pass 2 处） | 实测（逐处 ±3 行分类） | →P2-13 |
| TODO/FIXME | 0 | 实测 | 正常 |
| 裸 except | 0 | 实测（v1 一致） | 正常 |
| 后台线程样板 | threading.Thread 10 处 / invoke_main 26 处 / 按钮复位 16 处 | 实测 + 代理复核一致（计数修正 11→10） | →P2-1 |
| gui logger 密度 | 2.11 处/千行；autovision.log 全生命周期仅 3 行（271B） | 实测 | →P2-19 |
| 审计轨 | audit_20260630.jsonl 7 行，**48 天 0 落盘**；同期 history 342 行（当日 154 行在写） | 实测 + 代理复核一致 | →P1-4 |
| shm 累积实验 | 20 次 Detect → 20 区域 20 文件（无复用/无回收）；显式 release 20→19；cleanup→0；fd `_getmaxstdio()=512`，约 509 次未回收后 EMFILE | 实测（对抗复核运行时复现） | →P1-1 |
| FID 数值实验 | 30 seeds：repo 90.31/86.01/63.28 vs 正确对称化 228.12/229.06/206.31（恒低估 ~2.5 倍）；3,000 次随机最小 FID=−686.42 | 实测（对抗复核复跑） | →P1-5 |
| 四族已知反模式 | numpy 真值 / labels[int( / 工作线程 QPixmap / 生产 cv2.imread 各 **0 处** | 实测（全仓 grep，修复点带 W 注释） | 正常（W7-W10 成果） |
| 门禁 | 659 passed / 1 skipped / rc=0 / 120s | 引用 W 系列记录 | 正常 |
| 覆盖率 | 89.35%（miss 857，其中 proto 生成码 78 = 9.1%） | 实测（.coverage 离线复核） | 正常（>80；棘轮 fail-under=89） |
| UIA | 6 用例真窗双连绿（W11，四轮翻车全归因测试基建、生产码零改） | 引用 W 系列记录 | 优点 |
| git tag | **0**（pyproject 宣称 2.0.0，dist 已产出） | 实测 | 缺陷（→P2-5） |

---

## 8. 多视角评估

### 8.1 优点（6 视角 strengths 汇总去重，均（已验证））

1. **类型契约单源真实生效**：interfaces_supervised 33 处生产引用，跨层零平行定义（§4.1）。
2. **决策可追溯体系是实装而非摆设**：10 个 wave 各配 PRD+tasks+state.json（实测 wc：state.json 合计 1,613 行、PRD/tasks 合计 711 行），含 approvals（用户原话+时间戳）/verification（命令+exit_code）/deviations（wave7 如实记录返工）；两个抽样设计决策（bool_rle 默认开启、gRPC+MMF 混合架构）均可完整回答"为什么"。
3. **同类教训制度化吸收而非点修**：四族已知反模式全仓清零且每处修复点带波次回归注释（如 predict/page.py:514"W7 修复"、thumbnail_loader.py:4-5"W9 修复"）；eval_ except 元组的 W8 教训注释。
4. **质量基建三层金字塔**：607 离屏 + 6 UIA 真窗三通道 + 45 C#；覆盖率棘轮锚定实测（89.35% 定板）；打包漏模块教训固化为守卫（UIA 硬失败 + spec hiddenimports 与动态导入当前比对完备）；分层验证时长合理（门禁 120s / UIA 9min / 打包 13min，各有 runbook）。
5. **UI 样板已系统性收敛且采纳率 100%**：文件对话框 pick_* 被 10 文件采用、全 gui 0 处裸 QFileDialog；invoke_main 26 处、0 处裸 invokeMethod；labeling 三层切分干净（label 页 0 处访问 canvas._/controller._ 私有成员）；workers.py 纯函数范式可推广。
6. **工作线程 UI 纪律整体良好**：30 处 invoke_main 调用点逐一核对只传 Python 原生类型；W9 ThumbnailTask 修复端到端成立（run() 内仅 QImage，QPixmap/QIcon 转换在主线程回调）；11 处 worker 体仅 1 处 QWidget 残留（P2-15）。
7. **serving 热路径错误处理规范 + 进程边界干净**：Load/Unload/Detect/序列化失败均 logger.exception + 结构化 success=False 回传；gRPC 独立进程，GUI 零引用。
8. **并发基础有锁且经验证**：dispatcher RLock 保护 _engines 复合操作（W1-T2）；TrainWorker 协作停止带 5 秒有界等待；registry/shm 自身有锁。
9. **安全实践高于同规模平均**：PBKDF2-HMAC-SHA256 600,000 迭代 + 独立 salt + 失败 5 次锁 300s + 随机初始密码 + chmod 600；torch.load 3 处全部 weights_only=True；gRPC 默认只绑回环；CSV 公式注入防护。
10. **GUI 主进程日志轮转实装 + 检测历史实时落盘**：RotatingFileHandler 10MB×5；history 逐条 append JSONL 当日 154 行在写。
11. **C# 句柄纪律干净**：SharedMemoryReader using 即释放、类无持留状态、Dispose 链式；GUI closeEvent 有显存回收步骤。
12. **i18n 失真实测收敛**：缺译 30→1（_missing_keys.txt 现仅 1 行），语言切换经 main.py:155 单点广播全页 retranslate。

### 8.2 缺点清单（终版：P0×1 / P1×7 / P2×27）

> 原始 47 条发现（5 主透镜 40 条 + 补漏透镜 7 条）合并 12 处跨视角重复、1 条 P1 终裁降级后得 35 条。除标注对抗复核者外，P2 与 P1-6/P1-7 均为（未反驳·单源实测）；跨透镜独立重复发现者标（双透镜一致）。

#### P0 级

**P0-1 巨石函数：9 个函数超 100 LOC，其中 3 个高风险业务函数**（已验证·对抗复核）
AST 实测（end_lineno−lineno+1）9/9 精确复现：train/page.py:76 `_build_ui`=147、eval_/page.py:248 `_run_eval`=141、data_manage/page.py:80 `_build_ui`=133、label/page.py:230 `_build_ui`=118、predict/page.py:80 `_build_ui`=115、eval_/page.py:272 `_work`=115、gui/core/theme.py:63 `_build_qss`=109、gui/core/shell.py:55 `_build_shell`=103、training/generic_trainer.py:92 `fit`=118。复核另发现第 10 个少报（evaluation/metrics_supervised.py:34 `det_map`=112——少报非夸大）。风险分层：业务函数 `_run_eval`(141)/`_work`(115)/`fit`(118) 最高（不可单测、含嵌套闭包跨线程）；5 个 `_build_ui` 巨石次之；另 50-100 档 gui 17 个 + 引擎层 9 个（tile_infer=88、cut_labelme_json=82）。命中阈值档：单函数 >100 LOC = P0 档（任务阈值表）；实测 10 个。

#### P1 级

**P1-1 serving 共享内存区域泄漏是默认路径行为：无 TTL/上限/reaper，随附 C# 客户端结构性无法回收**（已验证·对抗复核；双透镜一致）
每次带 masks/keypoints 的 Detect 必建新区域并登记 `self._regions[path]=(fd,mmap)`（shared_memory.py:169、191-192；serialization.py:71-76、119-123——其中 :112-115 `if nbytes < _SHM_MIN_BYTES: pass` 为空操作死代码，64KiB 阈值形同虚设，注释自认"小数组仍走共享内存"）。服务端唯一回收入口是客户端显式 ReleaseSharedMemory RPC（server.py:156-163），Detect 处理器（server.py:122-152）无任何释放钩子；全 serving grep TTL/上限/后台 reaper/断连回调 = 0 命中；兜底仅 atexit（:117-118、278-286）。消费端（对抗复核加重项）：C# CallDetect 映射后即返回不调 Release（AutoVisionAgentClient.cs:188-196），且 DetectionResultMapper.cs:37-49 不保留 MasksShm/KeypointsShm 的 file_path——随附客户端**结构性无法**回收结果区域；接口文档（IAutoVisionAgentClient.cs:63-64）只要求回收"客户端创建的"文件。运行时复现：20 次 Detect（9,216B 掩码）→ 20 区域 20 文件；release 20→19；cleanup→0（atexit 真实有效）；fd 上限 `_getmaxstdio()=512` 实测，约 509 次未回收 Detect 后 os.open EMFILE、Detect 持续 success=False。服务端强杀时 atexit 不执行且 `__init__` 仅 mkdir 不清扫上轮残留（:110-111）→ %TEMP%\autovisionagent_shm 跨会话累积（单文件可达 36MB）。Release 失败路径 server.py:162 无服务端日志（对比 Load/Unload/Detect 均有）——泄漏排查零线索。测试只锚定 RPC 存在性（tests/test_serving_server.py:249-257、AutoVisionAgentClientTests.cs:231-240），无 Detect→release 配对断言。命中档：主链路资源泄漏默认累积（fd+磁盘随服务生命周期无界增长，恢复需重启）→ P1；未到 P0（显式回收通道可用、atexit 兜底有效、det-only 路径不泄漏、单次量有界）。

**P1-2 core/config.py 545 行双配置体系脱节：82% 配置死区 + 用户可见设置静默失效**（已验证·对抗复核；双透镜一致）
get_config() 全仓生产调用仅 2 处（gui/main.py:41 读 .logging、predict/page.py:245 读 .inference.device）；11 个子配置节中 model/detection/data/prompts/security/monitoring/server/cache/training 共 9 节外部引用 = 0；ConfigManager 全套加载器（load_from_yaml/json/env/reload/save/update）与 load_config 生产调用者 = 0；configs/default.yaml 仅被自身回退链引用、**运行时永不加载**。用户实际配置走另一套手写 JSON：settings/page.py:200 写 device 到 user_settings.json，但 gui/main.py:198-205 只回读 theme/language——**设置页选 CPU 对 predict 页无效**（predict 恒读 dataclass 默认 "cuda"，仅 torch.cuda.is_available() 兜底）。附带死配置：ServerConfig host="0.0.0.0"（config.py:146，与 P2-18 叠加）、security 节 max_image_size/enable_rate_limiting 零消费（安全审查会误判"有限流"）。命中档：545 LOC 落 300-1000 = P2 档，但 82% 生产死区 + 用户可见设置项静默失效 → P1。

**P1-3 训练最终权重保存失败被吞：TrainArtifact.weights_path 可指向不存在的文件**（已验证·对抗复核；下游危害按第 9 条补充判定修正）
training/generic_trainer.py:195-198 `try: self._strategy.save(final_path) except Exception: logger.exception("保存最终权重失败")` 后，:200 无条件 `artifact.weights_path = final_path`（无 exists 校验），:205-208 照常打"训练完成"日志并 return。TrainArtifact 无 status/persisted 字段（interfaces_supervised.py:86-94）；UI 侧 finished_sig → _on_finished（train/page.py:286→365-373）显示"训练完成"、置进度条 100%，不校验 weights_path。定期 checkpoint 同型吞异常（:189-190）。磁盘满/权限拒绝/序列化失败均走此路径。**真实危害（修正后表述）**：假成功浪费整轮训练、产物静默丢失；初判"下游必爆 FileNotFoundError"不成立——全仓无 artifact.weights_path 直接消费者，引擎侧 load 均 exists 预检（det_yolo.py:25 等），deploy:188 有捕获。命中档：关键路径（数据保存）异常被吞，有 logger 留痕（非"无日志=P0"档）；产物指针失真 → P1。

**P1-4 审计轨停摆：100 条内存缓冲 flush 零调用方，48 天 0 条落盘，且无用户归属**（已验证·对抗复核；三透镜一致）
audit_logger.py:57 `_buffer_max=100`，:79-82 仅缓冲满才落盘；全生产包 grep `.flush(` 调用方 = 0；gui/main.py 与 shell.py grep flush/atexit = 0（closeEvent 只查线程+清显存）；全仓唯一 atexit 注册在 shared_memory.py:117-118，与审计无关。实测 logs/audit/ 仅 audit_20260630.jsonl 7 行（2026-06-30），至今 48 天无新文件；同期 logs/history/ 3 文件 342 行、history_20260817.jsonl 当日 154 行仍在写——排除"功能无人用"（predict/page.py:324 每次推理调 log_detection_complete 只进缓冲，重启全丢；6/16-6/17 产生 298 条 history 而审计 0 条）。加重项：登录事件全程无审计（login 页 grep audit=0，而 audit_logger.py:3 docstring 宣称记录"登录"）；审计调用不传 user（deploy:218-221、predict:324-326，:61 默认恒 "system"——与 P2-17 角色丢弃叠加，无法回答"谁做的"）；deploy:222-223 审计写失败 except-pass；明文 append（:104）无哈希链防篡改。命中档：v1 P2-12"崩溃丢尾"实测升级为"常态全丢"——宣称与实现不符 + 可追责性失败 → P1。

**P1-5 FID 的 numpy 版 sqrtm 用 eigh 开非对称协方差积：恒低估 ~2.5 倍且可返回负值**（已验证·对抗复核）
evaluation/generative_metrics.py:109-118 `_sqrtm` 对 mat 直接 `eigh`；调用点 :101（初判引 :96 偏 5 行）传入 mat=Σg@Σr——实测该积非对称（不对称度 0.337），eigh 默认只取下三角。复跑（.venv numpy，30 seeds 走真实 fid_score 路径）：repo 90.31/86.01/63.28 vs 正确对称化 228.12/229.06/206.31，**恒低估 ~2.5 倍**；3,000 次随机试验最小 repo FID=−686.42（trace 项越 AM-GM 界）——负 FID 数学上不可能，普通高斯特征即可触发。消费点 eval_/page.py:289：生成图 vs 真实图分布必不同 → 恒走错误路径，结果以 f"{val:.2f}" 进 UI 表格。测试盲区：test_m2_matrix.py:170-175 只测对称正定输入、test_gui_eval_page.py:274 整体 mock fid_score。命中档：功能正确性缺陷（用户可见指标每次错 2-3 倍且可返回不可能值），GUI 直接消费 → P1。

**P1-6 requirements.lock.txt 无法在干净机器直接安装，且 venv 复现路径零文档化**（未反驳·单源实测）
lock 内 torch==2.5.1+cu121、torchvision==0.20.1+cu121 为本地版本标签（PyPI 不存在），全 205 行无任何 --index-url/--extra-index-url/pytorch.org 指令；全仓对 lock 的引用仅 docs/prd-wave3-quality.md:25 一处；仓库根无 README.md；release-checklist.md 第一步直接假设 .venv 存在。命中档：锁文件存在但不可执行其承诺 = 构建链可复现性核心断点 → P1（学习项目单机单人不升 P0）；与 P2-26（无 CI）叠加意味着第二台机器装不出环境。

**P1-7 R4-7 防反序列化 RCE 的安全回退路径 _extract_state_dict_safe 零直接覆盖**（未反驳·单源实测）
coverage 实测 core/interfaces_supervised.py 161 stmts / 35 miss = 78%，missing 198-203、209-225 恰为 :179-228 的 RestrictedUnpickler + zipfile 提取块（含 find_class 白名单拒绝分支）；现有测试只覆盖"损坏权重 → 诚实 RuntimeError"一路；torch 已装，tmp_path + torch.save 的 state_dict zip 完全可离屏测试。命中档：安全相关代码（RCE 缓解）无测试 + 依赖已装可测 → 较普通覆盖欠账高半档，P1。

#### P2 级

**P2-1 后台任务样板 7 页各自手搓，三套线程模型并存**（原判 P1 经反驳降级；事实经对抗复核证实、计数修正）
实测（复核修正后）：裸 threading.Thread 10 处（data_manage:368/474、deploy:191、eval_:388、flaw_gen:210、label:569/654/686、predict:301/419——初判 11 系差一）；invoke_main 转发 26 处（predict 6/label 5/flaw_gen 5/data_manage 4/deploy 3/eval_ 3）；setEnabled(True) 复位 16 处；槽命名三套并存（flaw_gen `_failed_slot/_done_slot`、eval_ `_eval_failed_slot`、deploy 同文件混用 4 种命名）；deploy/page.py:193-203 "work → 包装方法 → invoke_main → @Slot"三重间接；线程模型三套（TrainWorker(QThread) / 10 处裸 Thread / ThumbnailTask(QRunnable)+QThreadPool）；grep run_job/PageJob = 0，thread_bridge（73 行）只封装 invokeMethod 不封装生命周期，data_manage/page.py:347-368 已现页内私造 `_run_worker`——抽象压力实证。降级理由（终裁留痕）：计数有水分（11→10）且无对应阈值档、不符合本项目复核基准（对抗 verdict 本身记 confirmed，见 §13）。仍列第二波优先项：52 触点/6,638 行复制密度 + 本项目线程模型已实际产过 bug（W8/W9）。

**P2-2 退出守卫大面积失灵：10 处 daemon 线程仅 1 处被感知，属性名失配漏检 predict 批量，非原子写盘可截断标注文件**（双透镜一致·未反驳）
shell.py:249-261 仅探测 `_worker`（全 gui 唯一赋值点 train/page.py:284）与 `_batch_cancel` → `getattr(widget,'_btn_batch')`——predict 页按钮属性名实为 `btn_batch`（predict/page.py:115/:366）→ getattr 返回 None → 批量推理进行中无确认弹窗直接退出；10 处 daemon 线程对象无引用（inline start），其余 8 处均不可见。退出杀 daemon 线程时若正写入：批量标注 JSON 为 truncate-then-write 直写无 temp+rename（labeling/batch_tools.py:102-103、202-203、240），目标 JSON 被截断且旧内容已丢；predict 批量 json.dump（:413-415）同险。档：退出静默丢任务 + 非原子写盘损坏既有数据 → P2（需时机相撞）。

**P2-3 确认退出后不 stop/join 训练 QThread、不清空 QThreadPool：确定性 Qt 崩溃路径 + 退出拖慢**（双透镜一致·未反驳；静态确证未实机复现）
shell.py:263-283 用户确认 Yes 后仅 registry.clear_cache() 即 accept，无任何 stop/wait；TrainWorker 以页面为 parent（train/page.py:284），窗口拆卸即触发 Qt 致命路径"QThread: Destroyed while thread is still running"；stop() 协作停止已实现（worker.py:59-61）但只被按钮调用（grep 唯一命中 train/page.py:345）。两个缩略图 QThreadPool（data_manage/page.py:61-62、label/page.py:216-217）closeEvent 无引用、grep waitForDone = 0——大目录退出时 ~QThreadPool 阻塞等待拖慢关闭。档：有用户确认闸门、窗口有限 → P2。

**P2-4 异常退出无资源回收兜底：无信号处理器、启动不清扫陈旧 shm、C# 空 catch 且零日志设施**（未反驳·单源实测）
serve() 仅捕 KeyboardInterrupt（server.py:203-207），grep signal.signal/add_signal_handler 于 serving/core = 0——taskkill/崩溃/断电无清理；两端启动只 mkdir 不清扫（shared_memory.py:110-111、AutoVisionAgentClient.cs:43-44）；C# 删除失败被空 catch 吞（:161 `try{File.Delete}catch{/*忽略*/}`），且 NLog 5.3.4 被 csproj:20/Directory.Packages.props:14 引入但生产代码 LogManager/ILogger = 0 处（疑似纯依赖残留）——泄漏发生时零日志可查。档：单次残留量有界、随异常退出次数线性增长 → P2。

**P2-5 版本纪律缺失：git tag 总数 0，违反自家发版检查单**（未反驳·单源实测）
git tag -l = 0；pyproject.toml:3 version = "2.0.0"；dist/ 已产出且发版任务（门禁/打包/UIA/冒烟/归档）全部 completed，但 release-checklist.md:45 要求的 tag 一致性未落实——60+ 提交只能靠 commit message 回溯版本定位。档：项目自定硬要求未满足 → P2。

**P2-6 决策债务无追踪：v1 自拍板的服务安全 ADR（127.0.0.1 锁定 vs TLS+token）48 小时未产出**（未反驳·单源实测）
v1 文档 :350 跟进表第 12 项明确要求写 ADR；grep ADR docs/ 仅命中 v1 自身，.workflow/ 各 wave 未收录、无波次认领；server.py:190 仍 add_insecure_port 且 --host 可传 0.0.0.0。档：关键安全拓扑决策"已识别、未决策、未记录"悬置 → P2（实际部署面未知，本机默认尚可）。

**P2-7 gui 绕过分发层直插 models.supervised.registry（7 文件 8 处），注册靠隐式时序耦合；exporter 接口形状迫使 deploy 页伪造 _EngineStub**（未反驳·单源实测）
直连清单：label/page.py:56、train:302、predict:227、eval_:307、flaw_gen:170-171、shell:277、tasks_ui:33-36；而 serving/server.py:183 与 label:87 走 get_dispatcher——label 同一函数双路径（:56 vs :87）。注册触发不对称：predict:95-96/train:112 靠 __init__ 里 populate 触发 register_all_engines，label:56/eval_:307 只用不注册——当前仅因 build_window 全页构造才成立。deploy/page.py:167-168 手造 `class _EngineStub: task = type("T", (), {"value": task_value})()` 伪枚举满足 exporter.export_onnx 形状。档：8 处直连 vs 文档声明的分发层 + 1 处接口倒逼造假对象 → P2。

**P2-8 零样本范式是死线：load_zero_shot 全仓 0 调用、无实现存在，label 页回退必 raise，ListTasks 仍向 C# 广告 zero_shot**（双透镜一致·未反驳）
grep load_zero_shot 生产调用 = 0（仅定义 vision_dispatcher.py:63）；DINOv3/CLIP 仅存在于 config.py:30-42 幽灵字段（:31 dinov3_name="dinov2_vits14" 名值自相矛盾）；label/page.py:87-90 回退经 dispatcher.infer("abdet",…)——_engines 恒空 + 零样本检测器恒 None → 必 raise（dispatcher.py:183），页面 except 吞掉；list_all_tasks（dispatcher.py:234）恒前置 zero_shot 条目，serving/server.py:67 原样返回给 gRPC/C# 客户端；vision_dispatcher.py:1-6 docstring 仍宣称"零样本范式：DINOv3+CLIP"。档：对外广告的能力 0% 可用（诚实宣称原则，W4-T2 曾专项修复同类）→ P2。零样本 RuntimeError 路径未实跑验证（静态 0 调用方证据）（推断，依据：接线推演）。

**P2-9 eval 页无 TP/FP/FN 时展示编造的完美混淆矩阵**（双透镜一致·未反驳；v1 P2-12 残留）
eval_/page.py:424-429 else 分支 `set_matrix([[max(tp,1),max(fp,0)],[max(fn,0),max(tn,1)]])` 恒等于 [[1,0],[0,1]]；ConfusionMatrixWidget.set_matrix（:58-63）与 paintEvent 无"示例"标识——跑 seg/IoU 类指标（无 TP/FP/FN 行）时用户看到编造的完美结果，与 W2 起"缺数据诚实报错"原则相悖。档：工业评估 UI 展示虚构指标 → P2。

**P2-10 动态导入与 spec hiddenimports 为手工双列表，无离线守卫测试；canvas.py:220 冗余动态导入**（双透镜一致·未反驳）
动态导入 3 处：labeling/modes/__init__.py:49-50、models/supervised/engines/__init__.py:35（两处列表型，PyInstaller 静态不可见，spec:30-50 当前比对完备但为手工双份）、canvas.py:220（常量字符串且 :12 已静态导入 PySide6.QtCore——应改静态）。grep tests/ 无一致性校验测试；两处 except ImportError → warning 静默降级——新增第 10 个引擎漏更 spec 时 exe 内将静默缺失（W4 发版检查正是此事故原型），当前唯一守卫是 UIA 硬失败 + 发版人工步骤（最慢反馈层）。档：已发生过的故障模式 + 守卫在最慢层 → P2。

**P2-11 死代码 4 项实测坐实**（双透镜一致·未反驳；v1 P2-13 部分残留）
① models/supervised/registry.py:138 `register_into_container` 引用不存在的 core.dependency_injection（ls 证实；:156 入 __all__、__init__:17/28 再导出——一旦调用必 ImportError）；② core/config.py:537 `load_config` 全仓 0 调用；③ core/audit_logger.py:197 `log_train_complete` 0 调用（训练完成无审计，对照 log_detection_complete/log_model_export 均有消费者）；④ run_m3_verification.py:102 调 `python -m gui._render_preview` 而该文件不存在（v1 文档 :367 仍宣传其为验证入口）。v1 P2-13 其余子项已修（brush_size 0 命中、handle_commit 合理化 controller.py:173-189）。档：4 项逐一验证 0 消费者/断链 → P2。

**P2-12 gui/pages/__init__.py 页面注册表漏第 11 页 flaw_gen，main.py 被迫 deep import**（未反驳·单源实测）
__init__ 导出 10 页无 FlawGenPage；gui/main.py:29 绕过包注册表 from gui.pages.flaw_gen import、:167 add_page——页面清单两处真源，新增页或做懒加载改造时易漏。档：11 页 vs 10 导出不一致 → P2。

**P2-13 except 广捕总分类：44 处中 13 处无日志静默，serving 关键路径占 5 处**（未反驳·单源实测；逐处 ±3 行分类复核）
有 logger/raise/emit 转发的 31 处；静默 13 处（29.5%，纯 pass 2 处）：core/image_io.py:48/75（文档化契约对齐，:75 唯一调用方已检查返回值——缓解）、training/generic_trainer.py:89（warmup 纯 pass 无注释）、serving/serialization.py:82/:179、serving/server.py:57/:68/:80/:162、gui/core/tasks_ui.py:37、theme.py:195、home/page.py:170、predict/page.py:333（纯 pass 有注释）。最严重 5 处：generic_trainer.py:197（已升 P1-3）；server.py:68-69 ListTasks 整体失败返回空列表——客户端把故障当"无任务"；server.py:162-163 Release 失败无服务端日志（与 P1-1 互为盲区）；home/page.py:170-171 历史加载任何异常显示"暂无检测记录"——真实历史被损坏 JSON/权限问题掩盖；generic_trainer.py:89-90。档：44/15,881 = 2.77/千行 → P2 档（1-5/千行）。

**P2-14 单实例互斥完全不存在：双开 GUI 无任何拦截**（未反驳·单源实测）
grep QLockFile|QSharedMemory|QLocalServer|CreateMutex|single_instance 于 gui/core/serving/ivp = 0；main() 从 setup_logging 直进 QApplication。双开后果：两进程同写 user_settings.json、两个 RotatingFileHandler 持有同一 logs/autovision.log（Windows 文件锁下轮转 PermissionError 竞争）、同项目目录并发扫描/计数器写竞争。档：按"可重复启动 → 共享文件双写竞争"后果 → P2。

**P2-15 deploy 导出 worker 在工作线程读取 QWidget（self._task_combo.currentIndex()）——W9 同类违例读侧残留**（双透镜一致·未反驳；v1 P2-10 残留）
deploy/page.py:163 `task_value = _TASK_MAP.get(self._task_combo.currentIndex(), "det")` 在 threading.Thread（:191 启动）内执行——QComboBox 跨线程只读亦违 Qt 契约；对照同函数 :138-140 fmt_idx/precision 已正确在线程启动前主线程读好，:163 属遗漏。其余 10 处 worker 体逐一读过：UI 更新全部经 invoke_main/信号，无触碰。档：W9 修复的同类违例残留 1 处 → P2（一行移动即修）。

**P2-16 thread_bridge 潜伏崩溃面（offscreen 实测复现）：None/tuple/numpy 标量载荷在工作线程抛 TypeError；invokeMethod 返回值被忽略，失败调用静默丢弃**（未反驳·单源实测）
(a) _to_qarg(None)/(1,2)/np.float32(0.5)/np.int64(3) 四种载荷实测全部 RAISE TypeError（thread_bridge.py:32-38 类型表无这些项）；TypeError 发生在工作线程，多数 worker except 元组不含 TypeError（data_manage:363、deploy:188、flaw_gen:207、label:562/645/677）→ 线程裸死、按钮永久禁用；eval_:382-385 是唯一显式收的（W8 教训注释）。现有 30 处调用点逐一核对均只传 str/int/float/dict/list——当前无活跃触发，属潜伏面。(b) offscreen 实测 invokeMethod 对无 @Slot/不存在的方法均返回 False 且静默不执行，而 thread_bridge.py:65/:69 忽略返回值——槽名拼错/漏 @Slot = 运行期无声空操作；当前无失配（deploy:195 引用的 set_progress 槽存在且有 @Slot(int)）。档：实测复现但无生产触发路径 → P2。

**P2-17 认证链无效：0 字节 license.key 即直入离线模式，登录后的用户名/角色被整体丢弃，全 11 页零角色控制；初始密码 print 到 stdout**（双透镜一致·未反驳；v1 P2-11 残留）
wc -c configs/license.key = 0 字节（文件存在即真）；login/page.py:292-301 `_do_offline` 仅 os.path.exists 判断——存在即 login_success.emit("offline", tr("操作员"))，无内容/签名校验（缺文件路径已加确认对话框 = 部分修）；登录成功后 main.py:149-151 `lambda _u, _r: win.select("home")` 用户名角色双丢弃；11 页 grep role/permission 无一处访问控制（命中均为 QSS 装饰）；连带 audit/history 的 user 恒 "system"（P1-4）。:94-95 初始密码 `logger.info(msg); print(msg)` 双通道（msg 含明文初始密码）。档：本地单工位威胁模型缓解 → P2。

**P2-18 gRPC 无鉴权无 TLS：默认 127.0.0.1 是实质缓解，但文档示例与死配置双双示范 0.0.0.0 暴露路径**（双透镜一致·未反驳；v1 P2-11 残留）
server.py:190 add_insecure_port；grep interceptor/TLS/token 于 serving = 0；默认值本身安全（:192/:215 默认 127.0.0.1）；但 :10 模块 docstring 用法示例即 `python -m serving --host 0.0.0.0`，且 core/config.py:146 ServerConfig host="0.0.0.0" 死默认（P1-2 关联）。附带：shm 文件落 %TEMP% 无 ACL 硬化，本机任意进程可读推理载荷（本地威胁，与 localhost 同级）。档：默认回环 + 学习项目 → P2。

**P2-19 GUI 关键操作零操作日志：gui 层 logger 密度 2.11/千行，autovision.log 全生命周期实测仅 3 行**（未反驳·单源实测；修正 v1 C5"三轨齐备"结论）
gui 全层 14 处 logger / 6,638 行；分页实测：label 0/818、data_manage 0/777、train 0/505、project 0/320、settings 0/259、deploy 0/252、flaw_gen 0/254、home 0/188（仅 login 8、eval_ 3、predict 1）。autovision.log 全部内容 3 行（271B：两次初始化 + 一次训练完成），同期 history 写了 342 行——一次含完整训练的 GUI 会话在运行日志里只留初始化行。保存标注（io_labelme.py:153-185 零 logger）、训练启动、登录成功/失败均无操作留痕。档：可观测性缺口 → P2。

**P2-20 serving 独立进程只有 console 日志：无文件 handler、无轮转，脱离 GUI 运行时日志随终端关闭消失**（未反驳·单源实测）
server.py:196-200 basicConfig 仅 console；grep FileHandler serving/*.py = 0；RotatingFileHandler 只在 gui/main.py:62-67 配置，serving 进程不经过该路径；shared_memory.py:33 的 logger 无 handler 时 WARNING 以下丢失。档：独立服务进程可观测性缺失 → P2。

**P2-21 依赖 CVE 面（推断）：setuptools 锁定 70.2.0 处于 CVE-2024-6345 受影响区间；torch 反序列化风险已被代码侧防护**（未反驳·推断单源，未经扫描器验证）
requirements.lock.txt 205 包中 setuptools==70.2.0 落在 CVE-2024-6345（package_index RCE）受影响区间 <70.14（推断，依据：知识库截止 2026-01）；利用场景（恶意源 download）不适用于本离线应用故不升档。torch 2.5.1 的 torch.load 默认风险已被全仓 3 处 weights_only=True 防护（已验证）。其余关键包（numpy 2.4.4/Pillow 12.2.0/requests 2.34.2/urllib3 2.7.0/aiohttp 3.14.1/cryptography 49.0.0/grpcio 1.83.0/protobuf 7.35.1/transformers 5.12.1）知识内无已知未修高危（推断）。附带：lock 经 anomalib 拉入 gradio/fastapi/flask/dash 全栈 web 框架，仅存 venv、spec 打包不纳入。档：P2（推断）。

**P2-22 data_manage 页 docstring 宣称对接不存在的 DataManager；DataManagerExt 生产零调用方**（未反驳·单源实测）
data_manage/page.py:3 宣称"对接 industrial_vision_platform.DataManager 做数据集 CRUD 与划分"——grep `class DataManager\b` 全仓 0 命中；页面实际依赖 dataset.format_export（:582）+ core.constants + thumbnail_loader。industrial_vision_platform/data_manager_ext.py（298 行）DataManagerExt 生产调用方 0，仅 tests/test_data_manager_ext_deep.py 消费——孤儿模块。档：宣称失实 + 孤儿模块 → P2。

**P2-23 登录角色持久层中文字面量与 tr() 默认值混用**（未反驳·单源实测；v1 P2-7 残留）
login/page.py:74 注册写 `"role": "管理员"`（中文字面量）；:181 `record.get("role", tr("操作员"))`（tr() 结果作数据默认值）；:236 直接 emit stored_role——en_US 下历史账户角色显示与比较错乱。同项其余已修：缺译 30→1、语言传播已接线（main.py:155）。档：上轮残留 → P2。

**P2-24 proto 生成码留在门禁分母：78 条 miss（占全仓 857 的 9.1%）是结构性噪声**（未反驳·单源实测）
pb2.py 52 stmts/40 miss（missing 33-72 为 _USE_C_DESCRIPTORS 纯 Python 回退块，C/upb 生效时环境性死代码）；pb2_grpc.py 78 stmts/38 miss（missing 44-74 为 Stub 客户端构造器，测试直调 Servicer 无 channel）。78/857 = 9.1%。档：生成码不可由业务测试自然覆盖 → 结构性 P2。修法：coverage omit serving/proto/*pb2*.py（地板更反映手写码，棘轮可顺势上调）或补 grpc.insecure_channel 进程内往返冒烟。

**P2-25 两处文档与门禁实测漂移：pytest.ini 尾巴清单陈旧 + release-checklist 门槛落后三个 wave**（未反驳·单源实测）
pytest.ini:10 称 path_io 28%、interfaces_supervised 67%，当日 .coverage 实测 93% 与 78%——path_io 已被 W10 中文路径测试填平，清单未同步；release-checklist.md:4/:12"门禁 64%" vs pytest.ini:38 fail-under=89。真实尾巴（miss 数）：config 74、interfaces 35、generative_metrics 52、proto 78、exporter 39。档：误导补覆盖优先级 + 发版可能按 64% 放行 → P2 文档债。

**P2-26 无任何 CI，门禁地板是单机环境敏感值**（未反驳·单源实测）
无 .github/.gitea/.gitlab（ls 实测）；fail-under=89 为本机实测地板——pb2 覆盖依赖 protobuf C 描述符开关、shm/UIA 为 Windows 专用，换机分子分母都漂；叠加 P1-6（lock 不可直接安装）第二台机器装不出环境。档：学习项目单机单人 + 门禁每提交在跑 → P2；转团队即 P1。

**P2-27 QT_QPA_PLATFORM=offscreen 靠 28 个测试文件逐文件自设，无集中兜底**（未反驳·单源实测）
28 个 tests/*.py 各自 setdefault（如 test_gui.py:7），根 conftest.py 未设；新 GUI 测试文件漏写将在门禁机弹真窗、无头环境崩。档：依赖每文件纪律、慢反馈 → P2 弱。修法：conftest.py 一行 setdefault。

### 8.3 18 视角覆盖矩阵（C1-C6 必查 / S1-S12 按适用性）

| 视角 | 状态 | 已查 | 关键发现 |
|---|---|---|---|
| C1 架构合理性 | 必查 | ✓ | 分层无环、契约单源（§3/§4.1）；P0-1 巨石函数、P2-7 绕过分发层、P2-8 零样本死线 |
| C2 可维护性 | 必查 | ✓ | TODO 0、i18n 收敛；P1-2 双配置死区、P2-11 死代码、P2-12 注册表不一致、P2-10 双列表 |
| C3 可靠性 | 必查 | ✓ | 热路径错误处理规范；P1-3 训练假成功、P2-13 静默 except、P2-16 潜伏崩溃面、P2-2/P2-3 退出路径 |
| C4 可测试性 | 必查 | ✓ | 89.35% 棘轮 + 三层金字塔是资产；P1-6 lock 不可装、P1-7 安全路径零覆盖、P2-24 proto 噪声、P2-26 无 CI、P2-27 offscreen |
| C5 可运维性 | 必查 | ✓ | P1-4 审计停摆、P2-19/P2-20 双日志缺口、P2-25 文档漂移、P2-5 版本纪律 |
| C6 安全性 | 必查 | ✓ | PBKDF2/weights_only/CSV 防护达标；P2-17 认证链、P2-18 gRPC 暴露、P2-21 CVE（推断） |
| S1 性能伸缩 | 适用 | ✓ | 无性能型缺陷立案；推理时延/显存峰值/启动时间未实测（§12）；画布 O(N) 重绘属 v1 P2-14 未复核 |
| S2 数据持久化 | 适用 | ✓ | 文件系统存储无 DB；非原子 JSON 写风险在 P2-2；history 逐条落盘健康 |
| S3 并发 | 适用 | ✓ | P1-1 shm 并发泄漏、P2-14 单实例互斥、P2-3 QThread 生命周期；RLock/协作停止为正面 |
| S4 API 契约 | 适用 | ✓ | proto + dtype 契约 + C# 测试齐备；P2-8 ListTasks 广告不可用任务、C# mapper 不保留 shm 句柄（并入 P1-1） |
| S5 依赖健康 | 适用 | ✓ | P1-6 lock 断点、P2-21 CVE 推断；mmedit 停更背景属 v1 已知（本轮生成引擎路径未重审，推断） |
| S6 灾备 | 不适用 | ✓ | 单机学习项目，无生产部署/备份承诺（不适用原因） |
| S7 合规 | 不适用 | ✓ | 无 PII/监管面；无第三方分发（不适用原因） |
| S8 可观测性深化 | 适用 | ✓ | P1-4 审计停摆、P2-19/P2-20 日志缺口、Release 失败无日志（P1-1 内）；无 metrics/tracing（MonitoringConfig 死配置） |
| S9 i18n/a11y | 适用 | ✓ | 缺译 30→1 已修；P2-23 角色持久层残留；中文路径缺陷已由 imread_unicode 根治（W10，生产 cv2.imread 0 处） |
| S10 演进/ADR | 适用 | ✓ | 决策可追溯体系是亮点（§8.1-2）；P2-6 ADR 债务、P2-5 版本纪律 |
| S11 构建链 | 适用 | ✓ | P1-6 lock 断点、P2-25 文档漂移、P2-26 无 CI、P2-10 spec 守卫；spec 质量与 UIA runbook 为正面 |
| S12 资源泄漏/生命周期 | 适用 | ✓ | P1-1 shm 泄漏、P2-4 异常退出兜底、P2-2/P2-3 退出线程；C# 句柄纪律为正面 |

---

## 9. 改进路线（三波 × ROI，动作回引缺点编号）

### 🚑 第一波·止血（低风险，立即，约 3-4 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 1 | FID sqrtm 对称化 | P1-5 | 改恒等式 sqrtm(ΣgΣr)=Σg^{1/2}(Σg^{1/2}ΣrΣg^{1/2})^{1/2}Σg^{−1/2}（两次 eigh 均作用对称阵）或恢复 scipy；加非负断言；补非对称输入用例 |
| 2 | 训练保存失败显性化 | P1-3 | final save 失败让 fit 抛出，或 TrainArtifact 加 status 字段且 UI 校验；至少 :200 前 os.path.exists 校验 |
| 3 | shm 服务端自治回收 | P1-1 | 区域 TTL/上限惰性清扫 + 启动清扫陈旧 ava_*.bin + Release 失败 logger.warning + C# CallDetect 读后自动 release + 接口文档写明结果句柄须回收 + 测试锚定 Detect→release 配对 |
| 4 | 审计即时落盘 | P1-4 | 逐条 append（对齐 detection_history 模式）或 atexit+closeEvent 双兜底；接入会话 user；deploy:222 补日志 |
| 5 | lock 可执行化 | P1-6 | lock 头部补 `--extra-index-url https://download.pytorch.org/whl/cu121`；新建 INSTALL.md 最小复现路径并纳入 release-checklist 前置 |
| 6 | 安全回退补测 | P1-7 | 3 用例：正常 zip 提取成功 / 恶意 pickle 触发 UnpicklingError / 非 zip 旧格式 raise RuntimeError |
| 7 | 一行级真 bug 速修 | P2-9、P2-15 | 混淆矩阵 else 分支改"无混淆矩阵数据"占位；deploy:163 currentIndex 移到线程启动前 |
| 8 | git tag v2.0.0 | P2-5 | 补打到发版提交；checklist 第 5 节改可执行命令 |
| 9 | 拆 3 个业务巨石 | P0-1 | fit 按 epoch 内分段、_run_eval/_work 抽 evaluation 层纯函数（照 workers.py 范式）；_build_ui 巨石后排 |

### 🔧 第二波·可测化解耦（中风险，约 5-8 人日）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 10 | config 双体系收敛 | P1-2 | 二选一：settings 写回 get_config().update(inference.device) 并启动回灌；或删减 config.py 至 logging+inference 两节（约 −300 行，幽灵字段随 P2-8 一并处理） |
| 11 | page_job 统一后台样板 | P2-1 | gui/core/page_job.py：run_job(page, work, on_done, on_fail, on_progress, button)——10 处样板缩为 10 行调用；统一槽命名；三套线程模型归一 |
| 12 | 分发层单入口 | P2-7 | models.supervised 提供 ensure_registered()/acquire(task)，gui 各页与 dispatcher 共用；exporter.export_onnx 改签名 (model, task_value, path) 消灭 _EngineStub |
| 13 | 零样本摘除或实装 | P2-8 | list_all_tasks 按 zero_shot_ready 条件隐藏；docstring 改"预留注入点"；或接 anomalib PatchCore 缺省实现 |
| 14 | 退出生命周期治理 | P2-2、P2-3 | 各页暴露 is_busy() 协议（closeEvent 遍历而非猜属性名）；确认退出后 shutdown 钩子：stop→wait(3000)→_thumb_pool.clear()+waitForDone(2000)；batch_tools 写盘改 tmp+os.replace |
| 15 | 静默 except 补日志 | P2-13 | serving 五处统一 logger.warning(exc_info=True)；home:170 区分"无记录/读取失败"文案 |
| 16 | thread_bridge 加固 | P2-16 | _to_qarg 补 None/tuple/numpy 标量归一；invoke_main 检查 invokeMethod 返回值 False 时告警；worker except 元组统一补 TypeError |
| 17 | 门禁去噪与文档对齐 | P2-24、P2-25 | coverage omit proto 生成码（棘轮顺势上调）；pytest.ini 尾巴注释刷新为真实尾巴；release-checklist 改引 pytest.ini 单一真源 |
| 18 | spec 离线守卫 | P2-10 | ~20 行测试：解析 spec hiddenimports 与 engines/modes 模块列表逐项 diff；canvas.py:220 改静态导入 |
| 19 | conftest 集中兜底 | P2-27 | 根 conftest.py 加一行 os.environ.setdefault('QT_QPA_PLATFORM','offscreen') |
| 20 | 死代码/死宣称清理 | P2-11、P2-22 | 删 4 项死代码及导出；补"公共导出可导入"冒烟测试；改写 data_manage docstring 为真实依赖；DataManagerExt 标注 experimental 或接线 |

### 🚀 第三波·现代化（高风险，充分 PoC 后）

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 21 | CI 落地 | P2-26（P1-6 收尾） | GitHub Actions windows-latest 跑范围版 + 门禁出数暂不加 fail-under；本地 pre-push 自动跑门禁落趋势 |
| 22 | 安全决策落地 | P2-6、P2-17、P2-18 | ADR 固化"默认 127.0.0.1"（--host 非回环时告警）；license.key 改内容校验（机器指纹+HMAC）；login_success 落会话对象 + 按角色 setEnabled；删除初始密码 print |
| 23 | 观测补齐 | P2-19、P2-20、P2-4 | 页级关键操作 info 一行式（操作+路径+用户）；serving 复用 RotatingFileHandler 写 logs/serving.log；signal handler + 启动清扫；C# 补最小 logger、NLog 移除或启用 |
| 24 | 单实例互斥 | P2-14 | 入口 QLockFile（configs/ 下）或 QLocalServer 激活已有窗口 |
| 25 | UI 巨石拆分 | P0-1（后半） | 5 个 _build_ui 按表单区拆子方法；theme _build_qss 按 区块拼装 |
| 26 | 角色枚举化 | P2-23 | 持久层改存 admin/engineer/operator 稳定枚举，展示层再 tr() |

---

## 10. 决策者建议

1. **总体判断：继续投资，不需要重写。** W7-W10 后骨架与质量基建（89.35% 棘轮、三层测试金字塔、决策可追溯、四族反模式清零）已到"改动有安全网"的水位；当前债务集中在"长时运行资源治理"与"结果诚实性"两个主题，第一波 9 项即可消除全部"静默失败"类风险。
2. **若只做三件事：修 FID（P1-5）、给 shm 加 TTL（P1-1）、让 lock 可安装（P1-6）。** 前者是用户可见的错误数字（每次评估都错 2.5 倍），后者决定服务化故事能否成立，第三件决定"第二台机器/未来的你"能否复现环境——三者合计不足两人日。
3. **保持"教训 → 注释 → 回归守卫"的吸收循环。** 对抗复核证实该循环有效（v1 四族反模式零复发、W4 打包事故已固化为 UIA 守卫）；本版新守卫（spec diff 测试、is_busy 协议、Detect→release 配对断言）应沿用同一模式，而非逐点点修。

---

## 11. 完整性批判记录（九问实答）

1. **最关键风险面覆盖了吗？** 已覆盖：长时运行服务资源治理（P1-1，S12 透镜 + 运行时实验）、产物/审计静默丢失（P1-3/P1-4）、环境可复现（P1-6）三条主风险面各有独立透镜且全部对抗复核 confirmed；无"已识别未审查"的最高风险面遗留。
2. **有没有没打开过的子系统？** 有四类：serving/proto 生成码（按生成物跳过，仅纳入覆盖统计）、C# dotnet_client 9 文件（本轮未整体复审，采信 v1 背书 + 行号级抽查）、gui/widgets 3 控件（仅行数与引用计数）、wave2/3/5/6/8/9/10/11 的 state.json（仅清单 wc，未逐字段精读）。
3. **外部边界错误路径看了吗？** 看了主要四类：gRPC 对端崩溃/强杀（P1-1 运行时坐实）、磁盘满/权限拒绝（P1-3 代码路径）、依赖缺失惰性导入（W 系列已治，本轮零新发现）、宿主异常终止（P2-4 静态确证）；未做：真实网络分区、CUDA OOM 路径。
4. **非功能默认成立了吗？** 没有：性能数字（推理时延/显存峰值/启动时间）全部标注未实测；本轮唯一运行时量化是 shm 累积实验与 FID 数值实验。
5. **运行产物异常信号解释了吗？** 解释了：autovision.log 全生命周期 3 行 → 归因 P2-19（GUI 零操作日志）而非日志系统故障；audit 48 天 0 落盘 → 升级 P1-4；history 当日 154 行在写 → 健康；无未解释的异常信号。
6. **只看主路径忽略边界？** 两处反例已抓：thread_bridge 潜伏面（30 调用点当前全安全但 None/tuple/numpy 标量实测必炸，P2-16）、serialization 64KiB 阈值死代码（P1-1 内）；零样本回退路径静态推演必 raise（P2-8）但未实跑 infer() 验证。
7. **文档自相矛盾？** 本轮抓到 3 处：pytest.ini 尾巴清单陈旧、release-checklist 门槛落后三波（P2-25）、v1 :367 宣传的 run_m3_verification 入口断链（P2-11）；本文全部数字以当日实测覆盖 v1 旧值（生产 14,361→15,881、label/page.py 691→818、覆盖 44%→89.35%）。
8. **单一证据源结论？** 8+1 条对抗复核全部 confirmed 才定稿；C4 透镜 7 条与绝大多数 P2 为单源实测，已逐条标注（未反驳·单源实测）；CVE 是本文唯一"零实测"定级（知识推断，未跑扫描器）。
9. **本领域该加的视角？** 已加并用上：工业长时运行服务的资源治理（S12 抓到 P1-1）、训练产物完整性（C3 抓到 P1-3）、评估数学正确性（FID 实验抓到 P1-5）；可再补而未补：数据集版本管理/漂移检测（纯文件系统，学习项目暂可接受）。

---

## 12. 验证范围与局限

**已验证**：§7 全部数字（多数双源或对抗复核复现）；6 视角 coverageNotes 声明的已查项（决策资产清单+两 wave 精读、44 处 except 逐处分类、13 个关键文件全文精读、11+2 线程 spawn 点全定位、shm/FID 运行时小实验、C4 当日 .coverage 离线尾巴分析）。

**未验证/未做**：
1. shm 泄漏未做真实 C# 客户端长时间压测（累积实验为 Python 侧 20 次调用 + fd 上限实测）；"客户端断连但进程存活"场景未单独验证（泄漏机制与崩溃同路，推断同结论）。
2. CVE 全部为知识推断（截止 2026-01），未跑 pip-audit/OSV；protobuf 7.x / transformers 5.x / pandas 3.x 等新版本超出复核代理确信范围。
3. C# 侧 9 文件未整体复审（v1 背书 + 本轮 Client/Mapper/接口行号级实测）；C# 45 测试采信基线。
4. PyInstaller exe 重建确定性未验；dist/ 未执行，exe 层退出码/atexit 实际执行路径未运行验证。
5. QThread destroyed-while-running 崩溃未实机复现（代码路径静态无歧义）；94 处页面内 connect 未逐条验证 receiver 生命周期（依赖"页面永生 + sender 临时"架构论证，未跑对象计数）。
6. 未重跑全量测试/UIA/打包——门禁 659/89.35%/120s、UIA 双连绿、9min/13min 分层时长引用 W 系列记录与 report.md。
7. 圈复杂度未实测（radon 未装），以 AST 行数代理；全仓 import 环检测只覆盖 gui→引擎方向与 labeling 包内，未做 modules 层内部环扫描。
8. 零样本 RuntimeError 路径未实际调用验证（静态 0 调用方证据）；i18n 缺译 30→1 引用工件 _missing_keys.txt，未重跑 check_i18n 脚本（脚本本体未定位）。
9. v1 P2-3（编排内联）与 P2-14（画布性能/撤销栈）未专项复核（P2-3 仅确认编排模式未变 + 818 行实测）。
10. P2 复核基于静态源码 + git log，未 checkout 历史版本逐项 diff，波次归因依赖代码内 W 注释与 commit message。
11. users.json 并发写竞争未深查（单用户桌面场景低风险）；长时间运行的实际句柄/内存增长基准未做（泄漏结论基于代码路径 + 小实验）。

---

## 13. 对抗验证驳回与降级记录（审计轨迹）

对抗复核共 9 条（8 条在 lens-digest + 1 条较晚完成的补充判定），**结论 8 confirmed + 1 confirmed（含下游断言修正）**，无 finding 级驳回；以下为子断言驳回与终裁降级：

1. **「训练权重下游必爆 FileNotFoundError」——驳回（补充判定）**：全仓无 artifact.weights_path 直接消费者、引擎侧 load 均 exists 预检（det_yolo.py:25 等）、deploy:188 有捕获；真实危害修正为"假成功浪费整轮训练、产物静默丢失"。P1-3 定级维持（confirmed），正文已采用修正表述。
2. **「后台任务样板 P1」——终裁降级 P2**：对抗复核证实全部事实（verdict 记 confirmed，52 触点分布精确复现），但计数 11→10 有水分、无对应阈值档、不符合本项目复核基准——主代理终裁降级，按 P2-1 收录并注明"原判 P1 经反驳降级"。流程刻意保留的审计轨迹。
3. **微修正清单（不影响结论，已并入正文）**：巨石函数实为 10 个（初判 9 属少报非夸大，新发现 metrics_supervised.py:34 det_map=112）；gui 50-100 档函数 16→17；"shell.py"系 gui/core/shell.py 路径缩写（行号 55 吻合）；FID 调用点 :96→:101；shared_memory.py 322→321 行（末行无换行符）；EMFILE 的 errno 文本会透出到 DetectResponse.error（"根因不可见"言重，但 shm 未释放本身确无指标/日志）；FID 玩具值 −2278.33 未逐值复现（30-seed 结论与负值现象确证）。

---

## 14. 附录：v1 P2 状态对照表（W5-W10 落地后）

v1 的 4 条 P1（引擎缺口与可达性倒挂 / 生成引擎假回退 / 主线程重活 / 非 git 仓库）已由 W5-W7 根治，本复审零复发（引擎 9/9 真实现、predict 单张推理等重活全部线程化、git 仓库在树 60+ 提交）；v1 P1-2（生成引擎假回退）本轮未重审生成路径，以四族反模式清零与 flaw_gen 页零新 finding 间接佐证（引用 W 系列记录）。14 条 P2 现状：

| v1 编号 | 内容 | 现状 |
|---|---|---|
| P2-1 | 构建环境树外流浪 | ✅ 根治：.venv 归位 + requirements.lock.txt 在树（残余断点转为本版 P1-6） |
| P2-2 | dispatcher 无锁竞态 | ✅ 根治：RLock 三处临界区（W1-T2，vision_dispatcher.py:52/104/130/192） |
| P2-3 | UI 编排逻辑内联页面 | ⏸ 未专项复核（编排模式未变；label/page.py 818 行实测，并入本版 P0-1/P2-1） |
| P2-4 | 门禁未迁移 | ✅ 根治：pytest.ini fail-under=89 棘轮（89.35% 定板） |
| P2-5 | 中文路径 cv2.imread ×5 | ✅ 根治：imread_unicode 统一入口（W10；生产 cv2.imread 0 处） |
| P2-6 | SAM 交互式标注未接线 | ✅ 根治：SamAdapter + 预热 + InteractiveLabeler 注入（W5/W6，commit 55603a4） |
| P2-7 | i18n 失真 | ✅ 大体根治：缺译 30→1、语言切换单点广播；残留角色持久层中文（本版 P2-23） |
| P2-8 | thread_bridge eval + 静默回退 | ✅ 根治：W3-T3 显式类型映射（新潜伏面另行立案为本版 P2-16） |
| P2-9 | 主题 auto 恒等于 night | ✅ 根治：随系统 colorScheme（theme.py:182） |
| P2-10 | 线程杂项 | ◐ 部分残留：predict _results 已收敛到工作线程；deploy:163 currentIndex 残留（本版 P2-15）、closeEvent 守卫失灵扩大（本版 P2-2） |
| P2-11 | 本地安全杂项 | ◐ 残留：初始密码 print / license 存在性校验 / gRPC 无鉴权（本版 P2-17/P2-18/P2-6） |
| P2-12 | 数据诚实性 | ◐ 残留并加重：混淆矩阵编造（本版 P2-9）；审计缓冲由"崩溃丢尾"升级为"常态全丢"（本版 P1-4） |
| P2-13 | 死代码集 | ✅ 大体根治：brush_size/handle_commit 已修；register_into_container 残留（并入本版 P2-11） |
| P2-14 | 标注画布性能/内存 | ⏸ 未专项复核（本轮无证据，撤销栈上限与 O(N) 重绘现状未知） |

---

*本报告由 architecture-review 技能流程产出：6 视角并行透镜 → 9 条独立对抗复核 → 主代理终裁定稿；三处 429 限流重试后完成的判定（补漏透镜全部 7 条、训练权重补充验证）照常收录并逐条标注复核状态。*
