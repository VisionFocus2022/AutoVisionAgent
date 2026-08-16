# PRD — SKolpha 完整对标扩展（DINOv3 工业视觉平台）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-28 |
| 阶段 | L3 / Phase 1 — PRD（结构化开发工作流） |
| 目标项目 | `E:\计算机视觉\视觉大模型\`（DINOv3 零样本缺陷检测平台） |
| 对标来源 | `E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\`（逆向分析见 `SKolpha_架构解析.md`） |
| 上一阶段引用 | 需求探索结论（完整对标 / 去DRM留Fernet / PySide6 现代化 / 扩展现有 DINOv3） |
| 关联 | Design → `design-skolpha-fork.md`；Tasks → `tasks-skolpha-fork.md` |

---

## 1. 背景与目标

### 1.1 现状

DINOv3 项目（`视觉大模型/`）已是一个**成熟的、DDD 分层的零样本工业视觉缺陷检测平台**：
- **核心范式**：DINOv3 ViT + CLIP 零样本检测 + 少样本训练（`few_shot_trainer.py`、`annotated_trainer.py`、`meta_grpo_trainer.py`）。
- **基础设施完备**：`core/{config, dependency_injection, exceptions, interfaces, enums}`、`api/gateway`、`cloud/`、`enterprise/{license_manager, multi_tenant}`、`commercial/pricing_engine`、`deployment/edge_optimizer`、`inference/tensorrt`、`evaluation/`、`exporter/`、监控/缓存/仓储。
- **平台层**：`industrial_vision_platform/{VisionModelSystem, AnnotationSystem, ConfigSystem, APIServer, DataManager, TrainingTracker, BatchOperationsManager, ModelEvaluator, PerformanceOptimizer, FeedbackSystem, MonitoringSystem}`。
- **SKolpha 客户端**：`integrations/skolpha/`（4 个类，调用 SKolpha 能力，非复刻）。
- **界面**：Web(Gradio) + REST API + WebSocket + CLI；**无桌面 GUI**。
- `CLAUDE.md` **声称**"支持 9 种视觉任务、6 种标注模式、模型训练与导出"，但实装以零样本为核心。

### 1.2 对标目标（SKolpha 3.3.2，证据见 `SKolpha_架构解析.md`）

SKolpha 是 **Nuitka + PyQt5 + Python3.9** 打包的商业桌面平台，**有监督范式**，覆盖：

| 能力域 | SKolpha 实装 | DINOv3 现状 | 差距 |
|--------|-------------|-------------|------|
| 检测范式 | 有监督（标注→训练→部署） | 零样本 + 少样本 | 缺**有监督全训练** |
| 9 任务引擎 | YOLOv8/anomalib/mmedit/mmseg/torchvision/SAM | 仅零样本异常 + 少样本 | 缺 **8/9 有监督引擎**（det/seg/pseg/pose/sseg/abdet-sup/sgan/super/cls） |
| 标注子系统 | 3 套标注器 + SAM 交互 + 3D/Open3D | `AnnotationSystem`（基础） | 缺 **6 模式 + SAM + 3D** |
| 桌面 GUI | PyQt5 全页面（登录→…→项目管理）+ 双主题 + i18n | **无桌面 GUI** | **全缺**（最大工作流） |
| 项目管理 | `{name}_{TASK}_{ID}_{ts}` + 任务ID计数 | `DataManager`（基础） | 缺**规范目录+计数器** |
| 训练配置 | **Fernet 加密** | YAML 明文 | 缺**加密**（用户选择保留） |
| 模型发布/导出 | 内置 | `exporter/`、`tensorrt_accel/` | 部分，需整合 |
| 授权 | **USB 加密狗 DRM** | `enterprise/license_manager`（自有） | **不复刻**（用户选择去 DRM） |

### 1.3 项目目标（Goals）

> **G1** 在 DINOv3 平台基础上**扩展**出 SKolpha 同等能力的**有监督工业视觉平台**，新增 9 任务有监督训练/推理引擎、完整桌面 GUI、6 模式标注（含 SAM/3D）、规范化项目管理、训练配置 Fernet 加密，并保持零样本/少样本既有能力，二者在统一接口下共存。
>
> **G2** 现代化技术栈：**PySide6**（LGPL）+ ultralytics + anomalib + mmsegmentation + mmedit + segment-anything + Open3D，与既有 `core/` 契约对齐。
>
> **G3** 不破坏既有零样本链路；新增能力通过**新接口 + DI 注册**接入，符合 DDD 分层与既有 PEP8/不可变/TDD 规范。
>
> **G4** 去 DRM、留 Fernet 配置加密；授权沿用项目既有 `enterprise/license_manager`。

### 1.4 非目标（Non-Goals）

- ❌ 复刻 SamsunLock USB 加密狗 DRM（用户已决定去除）。
- ❌ 复刻 Nuitka 打包（沿用项目既有 PyInstaller `desktop.spec`）。
- ❌ 复刻 `help.chm`（434MB 帮助集）——用项目自有 `docs/` 替代。
- ❌ 反编译/复制 SKolpha 专有源码——仅复刻**公开行为与架构**，写原创实现。
- ❌ 本阶段（Phase 1–3）**不写可执行项目代码**，只产规划文档（用户明确要求）。

---

## 2. 角色与使用场景

| 角色 | 场景 | 关键诉求 |
|------|------|---------|
| **标注员** | 用 6 模式标注缺陷；SAM 交互式分割；AI 预标注后修正 | 标注高效、撤销/重做、快捷键、批量 |
| **算法工程师** | 选任务→配训练参数→训练→评估→发布 | 多任务训练、可中断、指标、模型导出 |
| **产线操作员** | 加载已发布模型→批量推理→导出报表 | 批量、稳定、可视化结果、统计 |
| **项目管理员** | 建项目、分配任务ID、数据集管理 | 项目隔离、目录规范、计数器 |
| **零样本用户**（既有） | 提示词驱动检测（不被本次扩展影响） | 既有能力不退化 |
| **开发者** | 扩展新任务/新标注模式 | 清晰接口、DI、可测试 |

---

## 3. 功能需求（FR）

> 编号规则：`FR-{域}-{序号}`。每条标注【新增】/【扩展】/【沿用】。验收标准见 §5。

### 3.1 域 A：有监督任务引擎（A1–A9）【新增】

新增统一接口 `ISupervisedTaskEngine`（见 Design），按任务加载不同后端。**完整对标 9 任务**：

| FR | 任务 | 后端库 | 输入→输出 | 对应 SKolpha |
|----|------|--------|----------|-------------|
| FR-A1 | 图像分类 `cls` | torchvision | 图→类别概率 | `preptrain_cls.pt` |
| FR-A2 | 目标检测 `det` | ultralytics YOLOv8 | 图→[N,6] bbox | `preptrain_det.pt` |
| FR-A3 | 实例分割 `seg` | ultralytics YOLOv8-Seg | 图→实例 mask | `preptrain_seg.pt` |
| FR-A4 | 实例分割-Pro `pseg` | ultralytics YOLOv8-Seg（大模型） | 图→高精度 mask | `pretrain_pseg.pth`/`ultra` |
| FR-A5 | 关键点 `pose` | ultralytics YOLOv8-Pose | 图→[N,K,3] | `preptrain_pose.pt` |
| FR-A6 | 语义分割 `sseg` | mmsegmentation（DeepLabV3+/ResNet50-V1c） | 图→H×W 语义图 | `pretrain_sseg.pth` |
| FR-A7 | 异常检测 `abdet`（有监督/特征库） | anomalib（PatchCore/PaDiM） | 图→{score, map} | `abdet_r50.pth` |
| FR-A8 | 缺陷生成 `sgan` | mmedit（GAN+inpainting） | OK图+缺陷→合成图 | `pretrain_sgan.pth` |
| FR-A9 | 超分辨率 `super` | mmedit SR（EDSR/RRDB/ESRGAN） | LR→HR | `pretrain_super.pth` |

- **FR-A10** 模型注册表：统一管理 9 任务模型（加载/卸载/缓存/信息查询），与既有 `model_factory`、`VisionModelSystem` 对齐；沿用 `weights_only=True` 安全加载。
- **FR-A11** 零样本-有监督统一调度：`IDetector`（既有，零样本）与 `ISupervisedTaskEngine`（新）在 `VisionModelSystem` 下共存，按项目任务类型分发。

### 3.2 域 B：有监督训练流水线【新增/扩展】

- **FR-B1** 训练配置 Schema：覆盖 9 任务的 epochs/lr/batch/optimizer/augment/backbone/early-stop 等；**支持 Fernet 加密落盘**（FR-H2）。
- **FR-B2** 训练引擎：线程化训练、**可强制中断**（对应 SKolpha `强制结束线程`）、断点续训、checkpoint。
- **FR-B3** 训练回调：loss/metric 实时上报 → `TrainingTracker`（既有）扩展为通用训练追踪器。
- **FR-B4** 数据集构建：从标注 JSON（LabelMe 兼容）→ 各任务 Dataset（det/seg/pose/cls/sseg）自动转换。
- **FR-B5** 评估：混淆矩阵、mAP、IoU、FID(sgan)、PSNR/SSIM(super)——扩展 `ModelEvaluator`。
- **FR-B6** 模型发布/导出：训练产物 → 打包到项目 `models/`；支持 ONNX/TensorRT 导出（复用 `exporter/`、`tensorrt_accel/`）。

### 3.3 域 C：标注子系统【扩展】

- **FR-C1** 六模式标注：多边形(Q)、矩形(R)、画笔(P)、关键点(K)、AI 自动(W)、交互式(I)，快捷键与 SKolpha 对齐。
- **FR-C2** SAM 交互式分割：集成 `segment-anything`，点击/框 → mask → 多边形（Douglas-Peucker 简化）。
- **FR-C3** AI 预标注闭环：零样本检测器（既有 DINOv3）或有监督模型 → 生成初始标注 → 人工修正。
- **FR-C4** 撤销/重做、复制/粘贴、显示切换（标签/预测）。
- **FR-C5** 标注格式：LabelMe 兼容 JSON（与 `evaluation/labelme_loader.py` 对齐）。
- **FR-C6**（完整对标可选）**3D/立体标注**：Open3D 点云可视化 + 透视变换（`utils_3d`/`o3d_vis` 等价）。

### 3.4 域 D：桌面 GUI【新增 — 最大工作流】

- **FR-D1** PySide6 自定义无边框主壳（标题栏最小/最大/关闭/菜单/设置 + 侧边导航 + 页面栈），双主题（night/daytime）QSS。
- **FR-D2** 页面树：登录/注册（接 `enterprise/license_manager`，**无加密狗**）→ 主页 → 数据管理 → 标注 → 训练（含 loss 曲线）→ 评估 → 发布 → 推理 → 项目管理。
- **FR-D3** i18n：`locale/{ch_CH,en_US}` gettext，运行时切换；沿用 `selected_language` 配置。
- **FR-D4** 数据管理页：导入图像（jpg/png/bmp/tif/...）、数据集划分、统计。
- **FR-D5** 训练页：任务选择、参数表单、开始/强制结束、实时 loss/metric 曲线（pyqtgraph）。
- **FR-D6** 推理页：单张/批量推理、结果可视化、结果表、导出 CSV/JSON。
- **FR-D7** 项目管理页：项目 CRUD、最近项目列表（`saveProgrameList` 等价）、任务计数器显示。
- **FR-D8** 桌面打包：沿用 `desktop.spec`（PyInstaller）；产出 `skolpha-fork.exe`（暂名）。

### 3.5 域 E：项目管理与数据【扩展】

- **FR-E1** 规范化项目目录：`{root}/{name}_{TASK}_{ID}_{unixts}/{images,annotations,models,configs,results}`（对齐 SKolpha 日志实证）。
- **FR-E2** 任务 ID 计数器：每任务独立计数（`psegID/segID/detID/...`），建项目自增。
- **FR-E3** 批量推理结果存储：`{saveData}/batchPredict/{ts}/`。
- **FR-E4** 数据管理器扩展：`DataManager` 支持上述目录模型与项目元数据。

### 3.6 域 F：配置系统【扩展】

- **FR-F1** 三层配置：运行时 / 模板（含 `?字段` 自文档化注释）/ 硬编码回退。
- **FR-F2** 多语言/主题/存储路径配置（`configFile.json` 等价）。
- **FR-F3** 配置加载与既有 `core/config.py` 统一（YAML/JSON + 环境变量覆盖 + 校验）。

### 3.7 域 G：GAN 缺陷生成与超分【新增】

- **FR-G1** 缺陷生成：OK 模板 + 真实缺陷库 → mmedit GAN 合成缺陷图（扩充训练集）。
- **FR-G2** 超分辨率：LR→HR（单图/视频），提升低清相机检测精度。
- **FR-G3** 质量评估：感知损失（torchvision Inception）+ FID（FID-Inception）——对应附录 D 证实的权重用途。

### 3.8 域 H：安全与加密【新增/沿用】

- **FR-H1** 模型安全加载：`weights_only=True` 优先（既有 `integrations/skolpha/model_manager.py` 已实现，沿用）。
- **FR-H2** **训练配置 Fernet 加密**（用户选择保留）：`core/encryption.py` 新模块，密钥管理策略（见 Design §风险）。
- **FR-H3** 授权：沿用 `enterprise/license_manager`（**无 USB 加密狗**）；登录门控用软件授权。
- **FR-H4** 输入校验/路径遍历/速率限制（既有 `core/security` 设计，沿用）。

---

## 4. 非功能需求（NFR）

| 编号 | 维度 | 要求 |
|------|------|------|
| NFR-1 | 性能 | 单图推理 GPU < 100ms（det/seg），批量吞吐随 GPU 线性扩展；GUI 不阻塞（训练在子线程） |
| NFR-2 | 可维护性 | PEP8、frozen dataclass、文件 < 800 行、函数 < 50 行、嵌套 ≤ 4；模块按域划分（呼应 CLAUDE.md） |
| NFR-3 | 可测试性 | pytest 覆盖率 ≥ 80%；`@pytest.mark.{unit,integration,e2e}`；TDD（CLAUDE.md `/tdd`） |
| NFR-4 | 可扩展性 | 新任务 = 新 `ISupervisedTaskEngine` 实现 + DI 注册（OCP）；策略模式 |
| NFR-5 | 兼容性 | **不破坏既有零样本链路**；新接口与 `IDetector/IInferenceEngine` 并存 |
| NFR-6 | 跨平台 | Windows 主（对标），Linux 可构建（Docker 既有） |
| NFR-7 | 安全 | bandit 通过；无硬编码密钥；Fernet 密钥不落明文 |
| NFR-8 | 国际化 | 中/英双语；UI 文案走 `self._(...)` 抽取（对齐 `read_chinese.py` 思路） |
| NFR-9 | 打包 | PyInstaller 单文件/目录；模型按需下载，不全部内置 |
| NFR-10 | 许可 | PySide6(LGPL)、ultralytics(AGPL-3.0⚠️)、anomalib(MIT)、mmseg/mmedit(Apache-2.0)、SAM(Apache-2.0)——**AGPL 风险需法务确认**（见风险） |

---

## 5. 验收标准（AC，关键项）

- **AC-A**：9 任务引擎各自能 `load → infer`，输出结构与 FR-A 表一致；零样本链路回归测试全绿。
- **AC-B**：任选 det/seg 任务，标注数据集 → 训练（可中断/续训）→ 产出权重 → 评估指标达标 → 导出 ONNX。
- **AC-C**：GUI 6 模式标注可用；SAM 交互分割能生成多边形；AI 预标注→修正闭环跑通。
- **AC-D**：从登录到批量推理全页面流程跑通；中/英 + 日/夜主题切换正确。
- **AC-E**：项目按 `{name}_{TASK}_{ID}_{ts}` 创建；任务计数器自增；最近项目列表可恢复。
- **AC-F**：训练配置能加密落盘、运行时解密加载；密钥不在仓库明文。
- **AC-G**：sgan 能合成缺陷图（FID 可计算）；super 能 2×/4× 超分（PSNR 报告）。
- **AC-H**：`bandit -r .` 无 HIGH；`pytest --cov` ≥ 80%；`ruff`/`mypy`/`black --check` 通过。
- **AC-回归**：既有零样本 `services/detection_service`、`models/detector`、Web/CLI/API 行为不变（回归套件全绿）。

---

## 6. 约束与假设

**约束**：
- 必须扩展现有 DINOv3 项目（`视觉大模型/`），不得另起独立仓库。
- 技术栈固定：PySide6 + ultralytics + anomalib + mmseg + mmedit + segment-anything + Open3D。
- 沿用既有 `core/` 契约（`IDetector/IInferenceEngine`）、DI 容器、配置/异常体系。
- 沿用 PEP8/frozen dataclass/pytest/TDD/black/isort/ruff/mypy/bandit 规范。
- 去 DRM、留 Fernet；授权走 `enterprise/license_manager`。
- Phase 1–3 只产文档，不写可执行代码。

**假设**：
- 目标机具备 CUDA GPU（训练/超分/GAN 必要）；CPU 降级仅推理。
- 模型权重按需下载（不全部内置，避免仓库膨胀；对标 SKolpha 的 1.28GB 模型不入库）。
- 用户拥有各任务 demo 数据集（或用 imagenette 等公开集做冒烟）。
- ultralytics AGPL-3.0 许可能被项目接受（**待确认**，见风险 R-5）。

---

## 7. 范围（In / Out of Scope）

### 7.1 In Scope（本次扩展交付）
- 域 A（9 任务有监督引擎）、域 B（训练流水线）、域 C（6 模式标注 + SAM；3D 标注列**可选 P1**）、域 D（桌面 GUI 全页面）、域 E（项目管理）、域 F（配置 + Fernet）、域 G（sgan/super）、域 H（安全/授权）。

### 7.2 Out of Scope（明确不做）
- USB 加密狗 DRM、Nuitka 打包、`help.chm`、复刻专有源码、skolpha 客户端 `integrations/skolpha/` 的替代（保留，作为对标参考）。
- 联邦学习、AutoML（既有 ARCHITECTURE.md "长期目标"，不在本次）。

### 7.3 优先级分级（指导 Tasks 排期）
- **P0（MVP 内核）**：FR-A2/A3/A7（det/seg/abdet）、FR-B1/B2/B4/B5、FR-C1/C5、FR-D1/D2/D4/D5/D6（核心页面）、FR-E1/E2、FR-F1、FR-H1/H2。
- **P1（完整对标主力）**：FR-A1/A4/A5/A6、FR-A8/A9、FR-B3/B6、FR-C2/C3/C4、FR-D3/D7/D8、FR-G1/G2/G3、FR-H3。
- **P2（增强/可选）**：FR-C6（3D 标注）、视频流推理、多机分布式训练。

---

## 8. 风险与依赖

| 编号 | 风险/依赖 | 等级 | 缓解 |
|------|----------|------|------|
| R-1 | **范围过大**（GUI + 9 引擎 + 训练 = 人月级） | 🔴 高 | 严格 P0/P1/P2 分期；P0 先出可用闭环；阶段门禁控范围 |
| R-2 | **桌面 GUI 是最大不确定项**（DINOv3 现无 Qt 源码） | 🔴 高 | 用成熟无边框模板（PyDracula 风格）+ CoreUI 图标；先骨架后填充 |
| R-3 | ultralytics/anomalib/mmedit/mmseg 版本冲突（重依赖） | 🟡 中 | 锁版本 + `requirements.txt` 分组；CI 矩阵；mmedit 较老考虑替代（diffusers） |
| R-4 | Fernet 密钥管理：嵌入二进制仍可被提取（SKolpha 同病） | 🟡 中 | 密钥拆分 + 机器绑定 + 服务端下发（设计期决策） |
| R-5 | **ultralytics AGPL-3.0** 传染性许可 | 🔴 高 | 法务确认；若商用闭源则改用非 AGPL 检测栈（如 RT-DETR 自研/YOLOv5 GPL 边界） |
| R-6 | SAM 模型大（ViT-H ~2.5GB），打包/下载成本 | 🟡 中 | 按需下载；提供 ViT-B/Q 轻量档 |
| R-7 | 零样本链路回归（既有大量代码） | 🟡 中 | 回归套件前置；新功能放新模块，零侵入 |
| R-8 | 9 任务各自的训练超参/数据格式差异大 | 🟡 中 | 统一 Dataset 适配层 + 每任务默认配置模板 |
| R-9 | PySide6 + Python GIL 与训练线程 | 🟢 低 | QThread + 信号槽；不阻塞主线程 |
| R-10 | 依赖：Python ≥3.9（DINOv3 用 3.11/3.12 venv） | 🟢 低 | 确认 ultralytics/anomalib/mmedit 对 3.11 兼容（mmedit 可能需 3.8/3.9 隔离环境） |

---

## 9. 里程碑（高层，详细分解见 Tasks）

| 里程碑 | 内容 | 退出标准 |
|--------|------|---------|
| **M0 基线** | 接口契约 + DI 接入点 + 项目目录模型 + Fernet 加密模块 | `ISupervisedTaskEngine` 等接口评审通过；零样本回归绿 |
| **M1 MVP 闭环** | det/seg/abdet 引擎 + 训练流水线 + 6 模式标注 + GUI 核心 5 页面 | AC-B/C/D(E1/E2) 跑通 |
| **M2 完整对标** | 9 任务全引擎 + sgan/super + SAM 交互 + 评估/发布 + i18n/主题 | AC-A/G 跑通 |
| **M3 打磨发布** | 桌面打包 + 文档 + 全量测试 + 性能调优 | AC-H + NFR 全过；`skolpha-fork.exe` 可分发 |

---

## 10. 度量与成功标准

- 功能完成度：9 任务 × {训练, 推理, 评估} 矩阵覆盖率 100%（P1 末）。
- 质量：pytest 覆盖率 ≥ 80%、bandit/ruff/mypy 全过、零样本回归 0 失败。
- 性能：det/seg GPU 推理 < 100ms；GUI 训练页 60fps 不卡顿。
- 对标度：SKolpha 13 项能力域（§1.2 表）覆盖 ≥ 11 项（3D 标注 P2 可延后）。

---

*本 PRD 基于对 SKolpha 3.3.2 的真实逆向分析（`SKolpha_架构解析.md`）与 DINOv3 项目现状（`ARCHITECTURE.md`/`CLAUDE.md`/源码盘点）生成。下一阶段：Design（`design-skolpha-fork.md`）。*
