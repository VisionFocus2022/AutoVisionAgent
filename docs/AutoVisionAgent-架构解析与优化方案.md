# AutoVisionAgent 2.0.0 架构解析与优化方案

> 审查日期：2026-08-16 ｜ 方法：architecture-review v2.2（证据驱动，L2 标准档）
> 审查对象：`E:\学习项目\视觉大模型`（AutoVisionAgent 2.0.0，非 git 仓库）
> 读者：本项目开发者 / 架构师 ｜ 输出语言：中文
> 代码地图：本项目已建 CodeGraph 索引（`.codegraph/`，120 文件 / 2,074 节点 / 4,810 边），使用方式见附录 F。
>
> **标注约定**：全文每条结论标 `（已验证）`（≥2 类证据交叉印证或本人 Read 复核）或 `（推断，依据：…）`。
> **诚实声明**：本文降低误判概率，不保证零遗漏；未验证范围见文末「验证范围与局限」。
> **修订记录**：初稿定 9 P1 + 10 P2；经对抗式复核（1 事实核查员 + 1 对抗工程师，结论均经本人抽样复核）修正为 **4 P1 + 14 P2**——降级理由在各条内注明，这是流程刻意保留的审计轨迹。

---

## 1. 文档摘要

AutoVisionAgent 2.0.0 是一个 **PySide6 桌面工业视觉平台**（标注 → 训练 → 推理 → 评估 → 发布全流程），并带 **gRPC + 共享内存对外服务层**（供 .NET 进程调用）。约 **93 个生产源文件 / 14,361 行**（另有 19 个测试文件 3,914 行）（已验证，find+wc 实测，排除 build/dist/__pycache__ 等）。

一句话总评：**骨架优秀、移植未完成的桌面 AI 平台**——分层干净无环、核心机制（注册表/分发器/训练器/跨语言桥）设计质量高、异常与安全实践好于绝大多数同规模项目；但 v2.0 重建时只移植了部分血肉（引擎 6/9、GUI 只暴露恰好缺失的三个任务、门禁与文档未随迁、venv 流落兄弟树）。**无 P0 级偏态问题，4 条 P1、14 条 P2**；多数 P1 的修复路径是"从兄弟树移植"而非重造。

### 与兄弟树的关系（对抗复核后的关键重定框架，已验证）

本项目在用户机器上有两条已活跃分叉的线：

| 树 | 定位 | 与本审查的关系 |
|---|---|---|
| `E:\计算机视觉\视觉大模型` | v1.x 复刻线（Flask/PyQt5 26 包，STATUS.md 自述 2690 测试/门禁 83.88%） | **资产库**：det_yolo/seg_yolo/abdet_anomalib 真引擎、sgan_blend/super_cv2 真化实现、pytest.ini 覆盖率门禁、README/开发手册/benchmark、**以及本树原用的 .venv**（pyvenv.cfg 明载创建命令为 `-m venv E:\学习项目\视觉大模型\.venv`，系搬家至此）（已验证：本人实测该 venv `import PySide6` = 6.11.1） |
| `E:\学习项目\视觉大模型`（**本文对象**） | v2.0 重写线：PySide6 + gRPC serving + .NET 客户端 + UIA 测试，7 月下旬仍活跃改动（tests/ 07-27、serving/ 07-23、dist/ 07-27） | 审查对象；缺的东西大多在左列有现成实现 |

两树共享 `docs/复刻计划/` 历史文档（era-1~4），但代码完全分叉互不包含（已验证）。旧树 STATUS.md 曾指认本树 docs 为"基于旧快照的计划副本"——45 天后局势反转，本树已是独立演进的主线之一。

---

## 2. 系统概览

### 2.1 定位

对标商业软件 SKolpha 3.3.2（逆向解析见 [SKolpha_架构解析.md](SKolpha_架构解析.md)）的**去 DRM 复刻 + 自研扩展**：9 种有监督视觉任务 + 零样本异常检测双范式、6 种标注模式、项目管理、双语双主题 GUI、ONNX/TensorRT 导出、PyInstaller 打包分发，7 月新增 gRPC 服务化供 .NET（VisionAgent.Shared）跨进程调用（已验证：pyproject 描述、requirements.txt、docs、代码实测一致）。

### 2.2 技术栈（全部实测）

| 层 | 技术 | 证据 |
|---|---|---|
| 语言 | Python ≥3.10（实测运行环境 3.12；兄弟树 .venv 为 3.12.9） | pyproject.toml:5；pyvenv.cfg |
| GUI | PySide6 6.11.1（无边框暗色壳） | .venv 实测 import |
| 深度学习 | torch 2.5.1+cu121 / torchvision 0.20.1 | py312 pip list 实测 |
| 检测引擎 | ultralytics（YOLO，pose/pseg）；mmseg/mmsegmentation、mmedit 为**可选** | engines/*.py 惰性导入；requirements.txt:28-32 |
| 服务 | grpcio 1.78 + protobuf（自定 proto + 生成代码） | serving/proto/ |
| 测试 | pytest 8.3.5 + pytest-cov；uiautomation（UIA 真窗自动化） | pip 实测；tests/uia/conftest.py:35 |
| 打包 | PyInstaller ≥6.0（onedir, console=False） | autovisionagent.spec |
| 工具链 | ruff + mypy 配置存在（未装于 py312 全局环境） | pyproject.toml:7-23 |

### 2.3 规模度量（已验证，排除 build/dist/__pycache__/.benchmarks/.pytest_cache）

| 指标 | 值 | 复核状态 |
|---|---|---|
| 生产源文件 / 行数 | 93 文件 / 14,361 行 | （重验：三次 find+wc 一致） |
| 测试文件 / 行数 | 19 文件 / 3,914 行 | （重验：一致） |
| 最大单文件 | gui/pages/label/page.py **691 行** | （重验：wc 三次一致；无 >1000 行文件） |
| >300 行生产文件 | 11 个 | wc 排序实测 |
| def test_ 总数 | 199（含 e2e/UIA） | grep 实测 |
| CodeGraph 索引 | 120 文件 / 2,074 节点 / 4,810 边 / 5.84MB | codegraph status |

---

## 3. 整体架构

### 3.1 分层图（依赖方向自上而下，实测 import 关系绘制）

```
┌─────────────────────────── 入口层（2 条启动链）───────────────────────────┐
│  python -m gui.main（桌面）            python -m serving（gRPC 服务）      │
├─────────────────────────── 表现层（GUI）──────────────────────────────────┤
│ gui/core: shell(无边框主壳) theme(QSS双主题) i18n(280条字典) thread_bridge │
│ gui/pages ×11: login home label data_manage train predict eval_ deploy    │
│                flaw_gen project settings                                  │
│ gui/widgets ×3: file_dialog loss_chart thumbnail_loader                   │
├─────────────────── 服务层（跨进程 IPC，Python 侧）─────────────────────────┤
│ serving: server(gRPC Servicer) serialization(结果↔proto)                   │
│          shared_memory(临时文件+mmap 零拷贝) proto(pb2 生成代码)            │
│ [跨进程] serving/dotnet_client: C# VisionAgent.Shared（含 3 组单测）        │
├─────────────────── 平台分发层 ────────────────────────────────────────────┤
│ industrial_vision_platform: VisionModelDispatcher(双范式统一入口+LRU显存)  │
│                             data_manager_ext                              │
├─────────────────── 领域层 ────────────────────────────────────────────────┤
│ models/supervised: registry(@register_engine) + engines×6                 │
│ training: GenericTrainer(策略模式训练循环)                                  │
│ labeling: canvas/controller/modes×6/io_labelme/batch_tools/sam_adapter    │
│ inference: tiling_inferencer(滑窗+NMS合并)  evaluation: 指标  exporter:ONNX│
├─────────────────── 数据层 ────────────────────────────────────────────────┤
│ dataset: VisionDataset(LabelMe矩形配对)  project: store/counter/recent     │
├─────────────────── 基础设施层（core，零内部依赖）───────────────────────────┤
│ config dataclass配置树  auth PBKDF2  audit_logger  detection_history       │
│ exceptions 异常层级  constants  interfaces_supervised(任务契约)             │
└───────────────────────────────────────────────────────────────────────────┘
```

### 3.2 分层质量（已验证）

- **core 零内部依赖**，11 个包全部单向依赖 core，**无包级循环依赖**（grep 全量 import 矩阵实测 + codegraph 边印证）。
- gui 是组合根（composition root），直接延迟 import 几乎所有领域层——桌面单体合理形态（定级讨论见 P2-3）。
- serving→industrial_vision_platform→models 方向干净；唯一越层注释：serving/server.py:113 在 UnloadModel 里直取 `models.supervised.registry`（代码注释自认 dispatcher 缺 unload 接口）（已验证）。

---

## 4. 关键机制剖析

### 4.1 引擎注册表 + 双范式分发器（核心骨架，已验证）

- `@register_engine(TaskType.X)` 装饰器自注册到全局 `EngineRegistry`（models/supervised/registry.py:101）；**RLock + 双检锁 + 锁外 GPU unload**（registry.py:49-94）。
- `VisionModelDispatcher`（industrial_vision_platform/vision_dispatcher.py）统一入口 `infer(task, image, mode)`：`zero_shot` 走注入的零样本检测器；有监督走已加载引擎；`auto` 按是否已加载路由（:130-175）。**LRU 显存管理**：`max_loaded=2`，超限驱逐最久未用引擎（:99-111，R5-10 编号可追溯 fix-backlog）。
- `register_all_engines()` 惰性导入 9 个引擎模块，缺失的记 warning 跳过（engines/__init__.py:31-35）——**当前实际注册 6/9**（det_yolo/seg_yolo/abdet_anomalib 文件不存在，见 P1-1）。

### 4.2 策略模式训练器（已验证）

`GenericTrainer.fit()`（training/generic_trainer.py:92-209）驱动任意 `ITrainStrategy`（只需 `train_epoch/save`，可选暴露 optimizer）：进度回调 + 用户中断 + 断点恢复（checkpoint sidecar `.meta.json` 优先、权重内元字典兜底）+ 早停 + LR 调度（cosine/step/plateau）+ 线性预热 + 滚动保留最近 3 个 checkpoint。UI 与算法解耦干净（train 页是唯一规范使用 QThread+Signal 的页面）。

### 4.3 gRPC + 共享内存跨语言桥（7 月新增，已验证）

- 大数组（掩码/关键点/大图）不进 protobuf：`SharedMemoryManager` 写临时文件 + mmap，gRPC 消息只传 `SharedMemoryHandle{file_path,offset,length,dtype,shape}`（serving/shared_memory.py），dtype 契约与 .NET 侧 `SharedMemoryReader` 对齐；`atexit` 兜底 + `ReleaseSharedMemory` RPC 显式回收。
- .NET 侧 `serving/dotnet_client/` 是结构完整的 C# 库（Interfaces/Services/Tests，3 组单测）——**Python serving 侧反而 0 测试覆盖**（覆盖率实测，见 P2-4/P2-13 相关）。

### 4.4 核心三件套（已验证）

- **配置**（core/config.py）：dataclass 配置树 + YAML 模板回退链 + `?` 前缀自文档化键（对标 SKolpha）+ 点分嵌套 + 类型转换 + validate()。注：ModelConfig 节（DINOv3/CLIP）属 v1 零样本遗留，v2.0 GUI 链路未消费（推断，依据：全仓无 gui 文件 import 其键）。
- **认证**（core/auth.py）：PBKDF2-HMAC-SHA256、**600,000 迭代**（OWASP 2023）、常数时间比较、`verify_and_migrate` 旧参数自动升级。角色三档（管理员/工程师/操作员）在 login 页。users.json 无明文密码（实测结构）。
- **审计/历史**（core/audit_logger.py + detection_history.py）：JSONL 按日分文件；审计 100 条内存缓冲满刷盘 + logging 镜像；检测历史 deque(10000) + 实时落盘。**无防篡改**（纯明文 append）。

---

## 5. 启动链与生命周期

### 5.1 GUI 桌面链（已验证，gui/main.py:194-210）

```
python -m gui.main
 → setup_logging()            # RotatingFileHandler(UTF-8) + 控制台，读 core.config.LoggingConfig
 → _load_user_settings()      # configs/user_settings.json（主题/语言持久化）
 → QApplication → ThemeManager.apply(默认 night)
 → build_window()             # 实例化 11 页 + 信号枢纽接线：
      page.status_changed ──────────→ 主壳状态栏
      project.project_opened ───────→ data/predict 页 set_project_dir + home 统计刷新
      login.login_success ─────────→ win.select("home")
      shell.language_changed ──────→ 全页 retranslate()
 → win.select("login")  → app.exec()
```

退出：`MainWindow.closeEvent`（gui/core/shell.py:242-283）检查活动 worker（确认对话框）→ 清空引擎缓存释放显存 → accept。**该检查只识别带 `isRunning` 的对象（QThread 语义），对 predict/eval_/deploy/flaw_gen 四页的裸 `threading.Thread` 无效**（见 P2-10）。

### 5.2 gRPC 服务链（已验证，serving/__main__.py + server.py:194-207）

```
python -m serving [--host 127.0.0.1 --port 50051 --max-workers 8]
 → serve() → create_server()
     → 延迟 get_dispatcher()（避免 torch 未就绪影响模块加载）
     → grpc.server(ThreadPoolExecutor(8)) + add_insecure_port
 → wait_for_termination()     # Ctrl+C 优雅 stop(grace=3)
 RPC: Ping / ListTasks / GetTaskInfo / LoadModel / UnloadModel / Detect / ReleaseSharedMemory
```

---

## 6. 核心组件职责表（证据来源：codegraph + Read 复核）

| 组件 | 层 | 职责 | 规模 | 关键类型 |
|---|---|---|---|---|
| core/interfaces_supervised | 基础 | 任务契约：TaskType×9、DetectionResult(frozen)、TrainConfig(frozen)、引擎 ABC、ITrainStrategy | 323 行 | TaskType, AbstractTaskEngine |
| core/config | 基础 | 配置树+加载器（单例） | 545 行 | BaseConfig, ConfigManager |
| core/auth | 基础 | PBKDF2 哈希/验证/迁移 | 114 行 | verify_and_migrate |
| models/supervised | 领域 | 引擎注册表 + 6 引擎（cls=torchvision；pose/pseg=ultralytics；sseg/sgan/super=mm 系带降级） | 721 行 | EngineRegistry |
| training | 领域 | 通用训练循环 | 312 行 | GenericTrainer |
| labeling | 领域 | 标注子系统：策略模式 6 模式 + 画布 + LabelMe IO + 批量工具 + SAM 适配器（**未接线**） | 1,940 行 | AnnotationCanvas, AnnotationController, make_labeler |
| inference | 领域 | 大图滑窗分块 + 跨瓦片 NMS 合并 | 233 行 | tile_infer |
| evaluation | 领域 | mAP/IoU/AUROC（纯 numpy）+ FID/LPIPS（惰性） | 432 行 | evaluate_supervised |
| exporter | 领域 | ONNX 导出（opset14 动态轴）+ 可选 onnxsim/fp16/int8/TRT | 302 行 | export_onnx |
| dataset | 数据 | 图像×LabelMe(矩形) 配对加载 | 177 行 | VisionDataset |
| project | 数据 | 文件系统项目存储 + 计数器 + 最近列表（~/AutoVisionAgent_Projects） | 443 行 | FileSystemProjectStore |
| industrial_vision_platform | 平台 | 双范式分发 + LRU + 数据管理扩展 | 572 行 | VisionModelDispatcher |
| gui | 表现 | 11 页 + 主壳 + i18n/主题/线程桥 | 6,040 行 | MainWindow |
| serving | 服务 | gRPC + 零拷贝共享内存 + .NET 客户端 | 1,230 行(+C#) | AutoVisionAgentServicer |

---

## 7. 领域专用章节

### 7.1 标注子系统（对标 SKolpha 6 模式，已验证）

策略模式 + 工厂：`make_labeler(mode, ...)` 字典分发（modes/__init__.py:80），controller 对模式无感知。新增模式需改 **3-5 处**（枚举/新模块/工厂两处硬编码/IO 映射/渲染分支）——半注册表，有双处维护摩擦（modes/__init__.py:40-47 vs 62-69）。画布为 QGraphicsScene；**每次鼠标移动触发 O(N) 全量图元重建**（controller.py:122 → canvas.py:166-177）；撤销栈 `deepcopy` 快照**无上限**（canvas.py:75-79）。

### 7.2 引擎族真假与 GUI 可达性（已验证，era-4"假绿"问题的 v2.0 残留+回归）

| 引擎 | 实现 | 缺依赖时行为 | GUI 可达性 |
|---|---|---|---|
| cls_torchvision | torchvision ResNet 真实现（含批量） | 无降级（torch 必装） | **train/predict/eval 下拉不含 cls** |
| pose_yolo / pseg_yolo | ultralytics 真实现 | 惰性导入报错 | 同上，几乎不可达 |
| sseg_mmseg | mmseg 真实现 | 降级路径未逐行核（推断） | 同上 |
| **sgan_mmedit** | mmedit 真实现 | **假结果：原图 arr.copy() + score=1.0**（sgan_mmedit.py:84-88） | flaw_gen 页可达；但真引擎路径 100% 崩（见 P1-2） |
| **super_mmedit** | mmedit 真实现 | **假结果：INTER_NEAREST 4x 放大 + score=1.0**（super_mmedit.py:69-73） | deploy 页可达 |
| det_yolo / seg_yolo / abdet_anomalib | **文件不存在**（兄弟树有真实现） | 注册时 warning 跳过 | **train/predict/eval 三页下拉恰好只暴露这三个**（train/page.py:34-38 `_M1_TASKS`、predict/page.py:80-82、eval_/page.py:309-313） |

**对抗复核发现的加重项**：GUI 呈现与引擎现实**完全倒挂**——用户从界面能选到的任务恰是没实现的，已实现的 6 个反而几乎无法从 GUI 到达；`list_all_tasks()` 无条件对外广告全部 10 种任务（serving ListTasks 同样）；零样本桥 `load_zero_shot` 全树零调用方 → abdet 双死（无引擎且检测器永不注入）。

### 7.3 .NET 互操作（已验证）

C# 侧 VisionAgent.Shared：IAutoVisionAgentClient 接口 + gRPC 客户端 + SharedMemoryReader（按 Python 契约读临时文件）+ DetectionResultMapper + 3 组单测。UIA 端到端测试（tests/uia/）从**外部驱动打包后的 exe**：uiautomation COM 找控件、ctypes 发原始鼠标流画标注、预创建空 license.key 进"离线模式"免登录——工程投入扎实，但**无头环境会失败而非跳过**（无 skipif）。

---

## 8. 配置体系（已验证）

- `configs/default.yaml` 模板（推理/训练/日志/安全/监控五节）+ dataclass 默认值双保险；用户配置 `configs/user_settings.json`；敏感文件已列 .gitignore。
- 安全节有实际消费者：图像尺寸上限、限流配置（core/config.py SecurityConfig）。
- 配置分散度低（configs/ 单目录 + 4 个环境变量）→ 阈值表"配置分散目录数 <10 = 正常"。

## 9. 日志/诊断/可靠性（已验证）

- 全生产代码 `print(` 仅 15 处：14 处在 scripts/ CLI 工具（合理）+ **1 处 login 页把初始 admin 密码打到 stdout**（gui/pages/login/page.py:95，同时 logger.info，R4-4 有意设计但 print 过度）（重验：grep 两次一致）。
- 33 个文件使用 logging（根 logger + RotatingFileHandler UTF-8 10MB×5）；logs/autovision.log 实有 7-27 运行痕迹。
- 审计与检测历史双轨 JSONL；**审计缓冲 100 条，进程崩溃丢尾部；无哈希链防篡改**。
- 异常体系：AppError → 引擎/导出/标注三组带上下文字段——**裸 except = 0**（实测）；except Exception 42 处中纯吞掉 6 处（2 处 scripts、2 处带注释有意为之、真问题约 2 处如 generic_trainer.py:89 预热失败静默）→ 密度 2.9/千行（P2 档 1-5）。

---

## 10. 关键架构特性总结

1. **分层干净无环**：core 零依赖底座 + 11 包单向依赖（实测 import 矩阵）（已验证）。
2. **注册表+策略模式双骨架**：引擎可插拔、训练策略可插拔，R4-x/R5-x 编号保留 fix-backlog 可追溯性（已验证）。
3. **安全实践高于同规模平均**：weights_only=True 禁 RCE 回退（RestrictedUnpickler 兜底）、PBKDF2 600k+迁移、常数时间比较、路径遍历防护（project/page.py:281-287）、CSV 公式注入防护（predict/page.py:37-44）（已验证）。
4. **跨语言服务桥设计成熟**：gRPC 信令 + 共享内存大数据 + 显式回收 RPC + .NET 单测（已验证）。
5. **测试网诚实**：3 个缺失引擎被自家注册矩阵测试**真实地亮红**（7 failed），无假绿——延续 era-4"防假绿"遗产（已验证）。
6. **UIA 真窗端到端测试**是同类项目罕见的投入（已验证）。
7. **弱点集中于"移植未完成"**：引擎 6/9 且 GUI 不可达倒挂、门禁/文档未随迁、venv 流落兄弟树（见 §11.4）。

---

## 11. 量化评估与优化方案

### 11.1 实测指标表（含复核状态）

| 指标 | 实测值 | 测量方式 | 复核状态 | 阈值定级（§7 校准） |
|---|---|---|---|---|
| 单文件最大 LOC | 691（label/page.py） | wc | （重验：三次一致） | P2（300-1000 档）⚠️ |
| >1000 行文件 | 0 | wc | （重验：一致） | 正常 |
| except Exception 密度 | 42 处 / 14,361 行 = 2.9/千行 | Python 脚本精确解析 | （重验：两版脚本一致，第二版修正缩进 bug） | P2（1-5/千行）⚙️ |
| 裸 except | 0 | grep | （重验：一致） | 正常 |
| 吞掉型 except | 6 处（真问题 ~2） | 缩进感知脚本 | （重验：一致） | P2（绝对量小，校准降档）⚙️ |
| TODO/FIXME | 0 | grep | （重验：一致） | 正常 |
| 生产 print | 15（GUI 1 + scripts 14） | grep | （重验：修正初版 awk bug 后重测） | 正常（1 处密码属 P2-11） |
| 测试/生产代码比 | 3,914 / 14,361 = 0.27 | wc | （重验：一致） | P2（0.1-0.3 档）⚠️ |
| 测试实跑（py312 可运行子集） | 182 项：**175 过 / 7 败** + 2 模块跳过 | pytest 三次 | （重验：一致） | 7 败全因引擎缺失（P1-1） |
| e2e + UIA 测试 | 26 + 1 项 | pytest --co | 环境定位经对抗复核修正：**可用 venv 在兄弟树**（本人实测 PySide6 6.11.1），本树内无 | P2-1 |
| 覆盖率（11 包可运行子集） | **44%**（3,668 语句）；serving 0%、trainer 0%、exporter 12%、canvas/controller 0%（其测试随 PySide6 缺失被模块跳过） | pytest-cov | （重验：一致） | P2-4（无门禁；含 gui 加权估算 ~28%，估算依据：gui 6,040 行按未跑计）⚠️ |
| 直接依赖（核心） | 10 | 人工读 | 单源 | 正常（<50） |
| 配置分散目录 | 1 + 4 环境变量 | ls | （重验：一致） | 正常 |
| 循环依赖（包级） | 0 | import 矩阵 | （重验：codegraph 边 + grep 一致） | 正常 |

### 11.2 一句话总评

**一套骨架质量显著高于平均、但血肉移植未完成的桌面 AI 平台**——修复路径以"从兄弟树移植"为主，适合继续投资，不适合推倒重写。

### 11.3 优点（带证据）

1. 分层无环 + core 零依赖（import 矩阵实测）（已验证）
2. 注册表/策略/分发器三骨架设计良好且（除 dispatcher 外，见 P2-2）线程安全（已验证）
3. 安全实践：weights_only 禁 RCE、PBKDF2 600k、注入/遍历防护（已验证）
4. 测试网诚实抓真问题（7 红全对缺引擎）（已验证）
5. 跨语言桥 + UIA e2e 的工程投入（已验证）
6. 不可变数据习惯好：DetectionResult/TrainConfig/SharedMemoryHandle 均 frozen（已验证）

### 11.4 缺点（终版：P1 × 4，P2 × 14；降级轨迹注明）

> 定级依据 §7 阈值表 + 对抗复核裁决（4 维持 / 5 降级 / 0 升 P0）。无命中 P0 阈值。

#### 🔴 P1 级

**P1-1 引擎完整性缺口与 GUI 可达性倒挂**（C1/C2，功能完整性；对抗复核**加重**）
证据：engines/ 仅 6 文件 vs `register_all_engines()` 列 9（engines/__init__.py:18-30）；docstring"9 任务全注册"（:1）；test_m2_matrix **7 项真实红灯**；spec hiddenimports 有意只列 6（autovisionagent.spec:29-35）；**train/predict/eval 三页下拉恰好只暴露缺失的 det/seg/abdet**（train/page.py:34-38 `_M1_TASKS`、predict/page.py:80-82、eval_/page.py:309-313——本人复核属实）；`load_zero_shot` 全树零调用方 → abdet 双死；`list_all_tasks()` 无条件广告 10 任务（serving 对外同样）；train 页在引擎缺失路径用 `math.exp` 造假 loss 且**不触发任何警告**（train/page.py:300-336，警告只在 except 分支）；eval 页把 GT 当预测算假指标（eval_/page.py:361）。era-2 曾标三引擎 ✅（execution-plan-autovisionagent.md §4），v2.0 重建未迁移且无 ADR。
定级：P1 维持（若 serving 已对 .NET 客户端承诺 det/seg/abdet 则升 P0）。修复成本低——**兄弟树有真实现可直接移植**（det_yolo.py/seg_yolo.py/abdet_anomalib.py，本人 ls 确认）。

**P1-2 生成类引擎假回退 + flaw_gen 真路径必崩**（C3；对抗复核**证据增强**）
证据：sgan_mmedit.py:84-88（arr.copy()+score=1.0）、super_mmedit.py:69-73（INTER_NEAREST 4x+score=1.0），DetectionResult 无降级标记且 happy path 也恒 score=1.0（分数无意义）；flaw_gen 页真引擎路径 **100% 崩**：`SganMmeditEngine(TaskType.SGAN)` 构造器不收参数 → TypeError 不在 :204/:227 的任何 except 元组里 → 线程静默死、按钮永久禁用（flaw_gen/page.py:168，本人复核属实）；缺引擎时 `shutil.copy2` 复制占位图充当生成结果（era-4 TD-05 定性"诚信级"）。**旧树已真化**（sgan_blend.py/super_cv2.py，本人 ls 确认）——v2.0 移植的是旧桩代码，相对 era-4"库缺失则 raise"决策属回归。
定级：P1 维持（若 flaw_gen 无"建设中"横幅明示则可 argue P0——假数据喂训练）。

**P1-3 主线程同步执行重活**（S1/C5；对抗复核维持）
证据：data_manage 导入/划分/批量标注工具（data_manage/page.py:249-272, 274-352, 425-533）、label 页 AI 预标注（label/page.py:449-541）、**predict 单张推理（predict/page.py:255-302，对抗复核补充）**均在 UI 线程同步执行；grep 证明 gui 树零 processEvents。缩略图已用 QThreadPool(4)+限 200（R5-5）、批量推理/eval/export/flaw_gen 已线程化——团队明知此模式，恰是四处漏网。数千张工业图导入=分钟级"未响应"，对工业用户等同故障。
定级：P1 维持。

**P1-4 非版本管理**（C2/S11，Phase 0 触发器 5；对抗复核维持）
证据：`.git` 不在项目与父目录（git rev-parse fatal 确认）；`E:\学习项目\视觉大模型.zip`（68MB，7-23 16:15）存在但已陈旧——晚于它的 serving 修改（7-23 19:32）与 tests/configs/dist（7-27）均不在快照内；.gitignore 存在而无 .git（意图与实态脱节）。与 P2-4（无门禁）叠加 = 任何重构无安全网裸奔。
定级：P1 维持。`git init` 五分钟可解，高收益零成本。

#### 🟡 P2 级

**P2-1 构建环境"树外流浪"**（S11；初判 P1，对抗复核部分驳倒后降级）
修正记录：初判"本机所有解释器均无 PySide6"**有误**——漏测了兄弟树 venv（`E:\计算机视觉\视觉大模型\.venv`，本人实测 `import PySide6`=6.11.1；其 pyvenv.cfg 明载创建命令 `-m venv E:\学习项目\视觉大模型\.venv`，系搬家而非销毁）。存活部分：本树内无 venv、requirements.txt 全 range 无 lock、无任何文档指路环境在哪、UIA/e2e 在本树内无法直接运行。`.pytest_cache` lastfailed 含 test_gui 逐条失败 → GUI 测试近期实际运行过（用树外 venv）。
定级：P2（修复=venv 迁回或复制 + `pip freeze` 锁定 + README 写明环境路径）。

**P2-2 VisionModelDispatcher 无锁竞态**（S3；初判 P1，对抗复核降级）
证据：vision_dispatcher.py 全文无锁 + server.py:186 八工作线程共享单例，`move_to_end`/LRU 驱逐确有 TOCTOU。缓解（对抗复核查证）：GIL 保证 OrderedDict 结构不损坏（后果限单次请求失败可重试）；servicer 每方法全 try/except 兜底；驱逐仅发生在第 2 个模型加载时（管理操作非稳态流量）；registry/shared_memory 自身有锁。
定级：P2（后果 fail-request 级；但一把 `threading.Lock` 成本极低，值得第一波顺手修）。

**P2-3 UI 编排逻辑内联页面**（C1/C4；初判 P1，对抗复核降级）
证据：train 策略类（train/page.py:318-336, 386-433）、deploy 的 torch.load+_EngineStub 包装（deploy/page.py:152-172）内联 page.py。反驳有效部分：ITrainStrategy 协议在 core、GenericTrainer/SupervisedExporter/TrainWorker 均已分层，页面只留编排+回退桩——单页桌面工具的组合根内联是常见取舍；其中**真正有害的假 loss 无警告问题已归入 P1-1**。
定级：P2（纯架构整洁问题，第二波抽离）。

**P2-4 工程纪律资产未随 v2.0 迁移**（C4/C2；初判两条 P1/P2，对抗复核合并降级）
证据：本树 pyproject addopts 无 --cov、无 CI、ruff/mypy 未装；README/用户手册/开发文档/benchmark/`gui/_render_preview.py` 均缺（run_m3_verification.py:102 引用必失败）；实测可运行子集覆盖 44%（serving 0%、trainer 0%、exporter 12%）。对抗复核修正：**这些资产未销毁**——pytest.ini（fail-under 80）、README.md、development.md、cov_baseline.py、_render_preview.py 全部存留于兄弟树，属"移植未完成"而非"丢失"（era-2 历史仅存文档无 git 可考，fail-under 15→60 出处为 execution-plan-autovisionagent.md §4 T-AVA-18）。
定级：P2（从兄弟树移植 pytest.ini/文档脚手架即闭环）。

**P2-5 中文路径读图缺陷 ×5 处（潜伏级）**（S9 扩展；初判 P1，对抗复核降级+措辞修正）
证据（对抗复核补全为 5 处）：label/page.py:467,519、predict/page.py:269,362、dataset/vision_dataset.py:64 均直接 `cv2.imread`。修正："必挂"不成立——label 页显示走 `QPixmap(path)`（:398，Qt unicode 安全），cv2 失败处均有 None 检查（优雅报错或跳过）；**真危险**在 vision_dataset.py:64——imread 返回 None 时无 PIL 回退（仅 ImportError 才回退），None 静默流入训练数据——但 VisionDataset 在 v2.0 生产代码零调用方（仅测试用）→ 潜伏而非现役。触发条件真实：本树根路径即中文。
定级：P2（一行 np.fromfile+imdecode 可修；若未来接线 VisionDataset 训练管线则升回 P1）。

**P2-6 SAM 交互式标注未接线**：SamAdapter 生产零调用方，InteractiveLabeler 无适配器时静默 no-op（interactive.py:58-60），GUI 切到该模式点击无效；spec 却打包 sam_adapter+interactive（已验证）。
**P2-7 i18n 失真**：_i18n_report.txt 声称全过但实际 **30 处缺译**（事实核查员按 check_i18n.py 同款正则复算 307 个唯一 tr() 串）；settings 页 set_language 不 emit（双路径行为不一）；login 把 tr() 结果当数据存 role（login/page.py:181,301）——切英文后角色比较失效（已验证，核查员独立复核属实）。
**P2-8 thread_bridge eval+静默回退**：`eval(type_name)` 解析 Qt 元类型，NameError 被吞后全走 QVariant 兜底（thread_bridge.py:36-42），13 处调用参数类型匹配靠隐式转换（已验证 Read）。
**P2-9 主题体系破损**："auto"恒等于 night（settings/page.py:212）；多页硬编码暗色内联样式，daytime 主题视觉破碎（已验证）。
**P2-10 线程杂项**：predict 工作线程 `json.dump(self._results)` 与主线程 invokeMethod append 并发（predict/page.py:374-376，快照不一致风险；append 本身在主线程——比初判轻，经本人复核修正）；deploy:163 工作线程读 Qt 控件 currentIndex；shell closeEvent 的 isRunning 检查对四页裸 threading.Thread 无效（退出丢任务）（已验证）。
**P2-11 本地安全杂项**：gRPC add_insecure_port 无鉴权（默认 127.0.0.1 尚可，--host 0.0.0.0 即暴露未鉴权推理端点，server.py:190）；空 license.key 文件即进"离线模式"（login/page.py:289-302 仅查存在性，无内容/签名校验）；初始密码 print 到 stdout（login/page.py:95）（均已验证）。
**P2-12 数据诚实性杂项**：审计 100 条缓冲崩溃丢尾 + 无防篡改（audit_logger.py:56-82）；eval_ 页无 TP/FP/FN 时 max(tp,1)/max(tn,1) 硬造混淆矩阵示数（eval_/page.py:414-419，无"示例"标识）（已验证）。
**P2-13 死代码集**：register_into_container 引用已删除的 core.dependency_injection（registry.py:138-147，零调用方）；_MANUAL_FACTORIES、tiling _gaussian_weight、controller 双事件入口、canvas API 三胞胎、handle_commit 逻辑反转（controller.py:177-186）、brush_size 存而不用（已验证各 file:line）。
**P2-14 标注画布性能/内存**：撤销栈 deepcopy 无上限（canvas.py:75-79）；鼠标移动 O(N) 全量重绘（controller.py:122→canvas.py:166-177）（已验证）。

### 11.5 改进路线（三波 × ROI；对抗复核后"移植优先"取代"重造"）

**🚑 第一波·止血（低风险，立即，~2-3 人日）**

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 1 | `git init` + 首提交 | P1-4 | .gitignore 已就绪；此后每波独立小步提交 |
| 2 | venv 归位 + 锁定 | P2-1 | 兄弟树 .venv 迁回/复制本树 → 补装 PySide6/ultralytics/uiautomation → `pip freeze > requirements.lock.txt` → README 写明环境；验证 182 项 + e2e/UIA 恢复 |
| 3 | dispatcher 加锁 | P2-2 | 一把 `threading.Lock` 保护 _engines 复合操作（仿 registry.py，unload 移锁外），成本极低 |
| 4 | 中文路径读图统一 | P2-5 | `core/image_io.py: imread_unicode()`（np.fromfile+imdecode）替换 5 处 |
| 5 | 宣称诚实化 | P1-1(第一步) | engines/__init__ docstring 改"6/9"；train/predict/eval 下拉按 `registry.has()` 动态生成（一举消除可达性倒挂）；假 loss 路径加状态栏警告 |

**🔧 第二波·移植与可测化（中风险，环境就绪后，~5-8 人日）**

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 6 | **移植 3 引擎** | P1-1(根治) | 从兄弟树移植 det_yolo/seg_yolo/abdet_anomalib（已确认存在）；过 test_m2_matrix 7 红变绿；serving ListTasks 改按实际注册返回 |
| 7 | 生成引擎真化 | P1-2(根治) | 移植兄弟树 sgan_blend/super_cv2 替换 mmedit 桩；修 flaw_gen TypeError（except 元组加 TypeError 或改构造调用）；降级路径打 extra={"degraded":true} + 页面明示 |
| 8 | 重活移出主线程 | P1-3 | 导入/划分/单张推理/预标注统一 train 页 QThread+Signal 模式（修 P2-8 后可复用 thread_bridge） |
| 9 | 门禁迁移 | P2-4 | 从兄弟树移植 pytest.ini（--cov 棘轮从实测 44% 起）+ cov_baseline.py；serving 补单测（serialization/shared_memory 纯逻辑，0%→60% 优先） |
| 10 | 纪律资产回迁 | P2-4 | README/开发文档/benchmark/_render_preview 从兄弟树取回并按 v2.0 现状改写 |

**🚀 第三波·现代化（高风险，充分 PoC 后）**

| # | 动作 | 解决 | 怎么做 |
|---|---|---|---|
| 11 | 生成质量升级 | P1-2(增强) | 若 blend/cv2 路径不满足需求：评估 diffusers 替代已停更的 mmedit（PoC） |
| 12 | 服务安全决策 | P2-11 | 写 ADR：本机锁定 127.0.0.1，或跨机则 TLS+token；license 离线模式改内容校验 |
| 13 | SAM 接线 | P2-6 | label 页构造 SamAdapter（可选依赖检测+状态栏明示），InteractiveLabeler 注入 |
| 14 | thread_bridge 去 eval | P2-8 | 显式 QMetaType 映射表或改 Signal 方案 |
| 15 | UIA 入常规验证 | P2-1(收尾) | 环境归位后把 UIA e2e 纳入发版检查单；无头环境加 skipif |

### 11.6 决策者建议

1. **不要重写，也不要从零重造**——兄弟树是现成资产库（真引擎/门禁/文档/venv），v2.0 的问题主要是"移植未完成"，按三波推进，每波可独立回滚（git 就绪后）。
2. **若只做一件事：做第 1+2 步（git + venv 归位）**。无版本管理 + 环境流落树外的组合意味着任何改动不可归因、不可复现——这是一切其他风险（包括两树分叉的历史教训）的放大器。
3. **保持测试网的诚实红色**。7 个红测试是资产不是负债——移植引擎（第二波）让其变绿，而不是删测试或改断言（era-3 假绿教训）。GUI 下拉按注册表动态生成后，"可达性倒挂"这类问题将结构性地不再发生。

---

## 12. 附录

### 附录 A：模块速查（按层）

core（契约/配置/认证/审计/历史/异常）→ project + dataset（数据）→ models/supervised + training + labeling + inference + evaluation + exporter（领域）→ industrial_vision_platform（分发）→ gui（桌面）/ serving（gRPC+C#）。入口：`python -m gui.main` / `python -m serving`；验证：`python run_m3_verification.py`（注意其第 4 步引用本树不存在的 gui._render_preview）。

### 附录 B：配置与数据目录

configs/（default.yaml、users.json、user_settings.json）｜logs/（autovision.log、audit/、history/）｜outputs/checkpoints｜~/AutoVisionAgent_Projects｜%TEMP%/autovisionagent_shm

### 附录 C：术语表

| 术语 | 含义 |
|---|---|
| 双范式 | 零样本（检测器注入）与有监督（引擎族）两条推理路径，dispatcher.auto 路由 |
| 引擎 | 实现 ISupervisedTaskEngine 的任务处理器（load/infer/unload） |
| LRU 驱逐 | dispatcher 保持 max_loaded=2 驻留引擎，超限释放最久未用（R5-10） |
| 兄弟树 | `E:\计算机视觉\视觉大模型`（v1.x 线），本树 v2.0 缺失资产的多数据源 |
| era-1~4 | docs/复刻计划/ 的四个文档时代，era-4=重定基线（防假绿） |
| UIA | Windows UI Automation，tests/uia/ 用真窗驱动打包 exe |
| SHM 句柄 | SharedMemoryHandle{file_path,offset,length,dtype,shape}，跨进程零拷贝契约 |

### 附录 D：评估覆盖矩阵（§6.3 交付副本）

| 视角 | 状态 | 已查 ✓ | 关键发现 |
|---|---|---|---|
| C1 架构合理性 | 必查 | ✓ | 分层无环、注册表/策略骨架优（§3、§4）；P1-1 宣称失实+可达性倒挂、P2-3 编排内联 |
| C2 可维护性 | 必查 | ✓ | 无千行文件、TODO=0；P1-4 非 git、P2-13 死代码、P2-4 文档未迁移 |
| C3 可靠性 | 必查 | ✓ | 异常体系好、裸 except=0；P1-2 假回退+TypeError 崩、P2-2 竞态、P2-10 线程杂项 |
| C4 可测试性 | 必查 | ✓ | 199 测试、UIA e2e 罕见投入；P2-4 无门禁+serving 0%、P2-3 页面不可单测 |
| C5 可运维性 | 必查 | ✓ | 日志/审计/历史三轨齐备；P2-12 审计缓冲丢尾 |
| C6 安全性 | 必查 | ✓ | PBKDF2/weights_only/注入防护；P2-11 gRPC 无鉴权+空 license 绕过+密码 print（涉深可触发 security-review 专项） |
| S1 性能伸缩 | 适用 | ✓ | P1-3 主线程阻塞；P2-14 画布 O(N) 重绘；推理时延未实测（未验证范围） |
| S2 数据持久化 | 适用 | ✓ | 文件系统存储无 DB；LabelMe 5.4.3 稳定 |
| S3 并发 | 适用 | ✓ | P2-2 dispatcher 无锁（降级）；registry/shm/auth 锁设计正确 |
| S4 API 契约 | 适用 | ✓ | gRPC proto + .NET 镜像 + dtype 契约有 Tests；proto 无版本字段（小瑕疵，未列缺点——推断影响低） |
| S5 依赖健康 | 适用 | ✓ | torch 2.5.1（本机驱动约束）、mmedit 已停更（P1-2 根因之一）、无 lock（P2-1） |
| S6 灾备 | 不适用 | ✓ | 单机桌面工具，无生产部署承诺（不适用原因） |
| S7 合规 | 不适用 | ✓ | 无 PII/监管面；AGPL 决策归档在兄弟树（era-2 引用） |
| S8 可观测性深化 | 部分适用 | ✓ | 有结构化日志+审计+历史；无 metrics/tracing 实装（MonitoringConfig 预留，消费者未证实——推断） |
| S9 i18n/a11y | 适用 | ✓ | 中英双语+双主题实装；P2-7 缺译 30 处、P2-9 主题破损、P2-5 中文路径 |
| S10 演进/ADR | 适用 | ✓ | era-1~4 文档史完整是优点；但 v2.0 删引擎/未迁门禁**无 ADR**（P1-1/P2-4 证据链） |
| S11 构建链 | 适用 | ✓ | P2-1 venv 树外流浪+无 lock（对抗复核修正定性）；PyInstaller spec 质量好 |
| S12 资源泄漏/生命周期 | 适用 | ✓ | unload/release/atexit/cleanup 链完整；P2-10 退出丢任务、P2-14 撤销栈无上限 |
| E1 扩展：桌面工业软件适配（中文路径/打包/离线授权） | 新增 | ✓ | P2-5 中文路径×5、P2-11 离线授权绕过、spec 只含 6 引擎 |

### 附录 E：完整性批判记录（§6.4 九问 + 本次教训）

1. **最关键风险面？** 移植未完成（引擎/门禁/环境）与无版本管理——已由 C1/C2/S11 覆盖。
2. **有没有子系统没打开过？** 本人 + 3 子代理精读约 40+ 文件（占生产文件 ~43%），其余经 codegraph 索引与依赖矩阵覆盖。未逐行：gui 各页全量、pb2 生成代码。**本次教训：初判漏了"项目外资产"维度**——兄弟树的存在直到对抗复核才纳入，多条定级因此修正；单树视角是本次最大的完整性缺口（已补救）。
3. **外部边界没看？** 已看文件 IO/gRPC/GPU/临时目录；相机采集不适用。
4. **非功能被默认成立？** 性能数字未实测（列入未验证范围）；监控节消费者未证实。
5. **运行产物异常信号解释了吗？** logs 仅 3 行 INFO 无异常信号；audit/history 仅测试条目。
6. **只看主路径忽略错误路径？** 契约测试专测错误路径；本人复核 6 处吞错点与 3 个假回退。
7. **文档自相矛盾？** era-2 计划与磁盘现状矛盾已归因（无 ADR 的重构）；本文数字均经重验，初判错误（PySide6 全无/20+ 缺译/predict 跨线程 append/9P1）已在对抗复核后修正并留痕。
8. **单一证据源？** 关键数字双测以上；子代理重磅结论（venv/下拉倒挂/TypeError/旧树引擎）均经本人独立复核属实后才采信。
9. **领域该加的视角？** 已加 E1；工业实时性/安全联锁不适用（非运动控制）。

### 附录 F：CodeGraph 代码地图（本次已创建）

- 索引：`.codegraph/`（SQLite，5.84MB）——120 文件 / 2,074 节点（759 方法、188 函数、155 类）/ 4,810 边；文件 watcher 自动同步（改动 2s 去抖更新）。
- 用法：MCP `codegraph_explore`（传 projectPath 为本树根）或 CLI `codegraph explore "<符号名/问题>"`；常用：`codegraph status`（健康/过期）、`codegraph callers <符号>`、`codegraph impact <符号>`（改前影响面）。
- 实测示例：`codegraph_explore "VisionModelDispatcher infer load_supervised"` 一次返回调度器全源码 + `get_dispatcher` 的 6 个调用方 + LRU 驱逐的动态分派候选（release/unload）。
- 版本注：服务器跑 v1.4.1，上游已有 v1.5.0（`codegraph upgrade` 可升级，未代跑）。

---

## 验证范围与局限

**已验证**：全部量化数字（§11.1，多数三重验证）；引用 file:line 经 Read/Grep/codegraph 复核；测试实跑三次；1 名事实核查员对 18 条结论逐条复核（17 属实 + 1 基本属实，i18n 缺译由 20+ 修正为精确 30）；1 名对抗工程师对 9 条 P1 对抗反驳（4 维持/5 降级/0 升级），其 4 项重磅修正（兄弟树 venv、GUI 下拉倒挂、flaw_gen TypeError、旧树真引擎）均经本人独立复核属实后采信。

**未验证/未做**：
1. 性能数字（推理时延、显存峰值、启动时间）——未跑基准（benchmark 脚本在本树不存在，兄弟树有）。
2. GUI 全部 11 页逐行审读——经子代理表征 + 本人抽查，非逐行。
3. serving/proto 生成代码按生成物跳过质量评审。
4. .NET 客户端仅静态结构确认，未编译/未跑单测。
5. 圈复杂度/重复块——未装 lizard/jscpd 无法实测（间接判断置信中）。
6. sseg_mmseg 缺依赖降级路径未逐行核（标注推断）。
7. e2e/UIA 未实际运行（环境在兄弟树 venv，归位后应重验——P2-1 修复项）。
8. 兄弟树仅做资产定位性核查（venv/引擎文件/spec 门禁存在性），未审查其内部质量。
9. PyTorch 多线程 unload+forward 是否产生粘性 CUDA 上下文错误（对抗复核提出的开放问题，未验证）。

*本报告由 architecture-review 技能流程产出：Phase 0-7 全过，Gate 4 经双对抗子代理 + 本人重验与抽样复核。*
