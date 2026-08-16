# Design — SKolpha 完整对标扩展（DINOv3 平台架构设计）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-28 |
| 阶段 | L3 / Phase 2 — Design |
| 上游 | `prd-skolpha-fork.md` v1.0.0（已门禁通过；3D = P2） |
| 下游 | `tasks-skolpha-fork.md`（Phase 3） |
| 设计基线 | DINOv3 现有 DDD 分层（`ARCHITECTURE.md`）+ `core/interfaces.py` 既有契约 + SKolpha 逆向（`SKolpha_架构解析.md`） |

---

## 1. 设计目标与原则

1. **零侵入扩展**：新增能力放**新模块 + 新接口**，不改动既有 `IDetector`/零样本链路；旧回归零失败（NFR-5）。
2. **接口先行**：所有新能力定义为 `Protocol`，DI 注册，可替换可测试（呼应 `core/dependency_injection.py`）。
3. **双范式共存**：零样本（`IDetector`）与有监督（`ISupervisedTaskEngine`）在 `VisionModelSystem` 下并存，按项目任务类型分发。
4. **不可变 + 类型化**：frozen dataclass + 类型注解（CLAUDE.md 规范）。
5. **对标而非照抄**：复刻 SKolpha 的**公开行为与页面结构**，用现代化栈原创实现；不复制专有源码。

---

## 2. 备选方案对比与选型

| 维度 | 方案 A：新协议+DI 扩展 ✅选定 | 方案 B：统一 ITaskEngine 吸收 IDetector | 方案 C：有监督微服务 sidecar |
|------|------------------------------|----------------------------------------|------------------------------|
| 零样本侵入 | 无（新接口并存） | 高（需重构 `IDetector` 全部实现） | 无 |
| 回归风险 | 🟢 低 | 🔴 高（动既有 detector） | 🟡 中（集成层） |
| 桌面 GUI 契合 | 好（进程内） | 好 | 差（IPC/网络） |
| 长期一致性 | 中（两套接口） | 高（一套接口） | 中 |
| 落地速度 | 快 | 慢 | 中（运维开销） |
| 部署复杂度 | 低（单体） | 低 | 高（多进程） |

**选型理由（A）**：用户要求"扩展既有 DINOv3 + 零样本不退化 + 桌面平台"。A 满足全部且风险最低；B 的统一性优势不抵回归风险；C 与桌面分发冲突。长期可在 A 稳定后，渐进把 `IDetector` 适配为 `ISupervisedTaskEngine` 的一个实现（向后收敛），纳入路线图 P2+。

---

## 3. 总体架构（分层 + 新增模块标注）

```
┌──────────────────────────────────────────────────────────────────┐
│  表现层                                                            │
│ ├─ Web/Gradio (既有)   ├─ REST/WebSocket/CLI (既有)                │
│ └─ 【新】gui/  PySide6 桌面 (登录→主页→数据→标注→训练→评估→发布→推理→项目) │
├──────────────────────────────────────────────────────────────────┤
│  应用服务层                                                        │
│  industrial_vision_platform/ (既有，扩展)                          │
│   VisionModelSystem ── 任务分发(零样本⇄有监督)                     │
│   TrainingTracker ◂── 【新】training/ 通用训练追踪                  │
│   ModelEvaluator ◂── 9 任务指标扩展                                │
│   DataManager / ConfigSystem ◂── 项目目录模型 + Fernet              │
├──────────────────────────────────────────────────────────────────┤
│  领域层                                                            │
│ ├─ models/ (既有：dinov3/clip/few_shot/detector…) 零样本，零改动     │
│ ├─ 【新】models/supervised/  9 任务引擎 (实现 ISupervisedTaskEngine) │
│ ├─ 【新】training/           训练流水线 (trainer/dataset/callback)  │
│ ├─ 【新】labeling/           6 模式标注 + SAM 适配器                │
│ └─ 【新】project/            项目目录/任务计数/元数据                │
├──────────────────────────────────────────────────────────────────┤
│  数据访问层  repositories/ (既有) + 【新】project/ 存储实现           │
├──────────────────────────────────────────────────────────────────┤
│  基础设施层                                                        │
│ core/ (既有) + 【新】core/encryption.py (Fernet) + core/interfaces_supervised.py │
│ config/ logging/ monitoring/ caching/ (既有，沿用)                  │
└──────────────────────────────────────────────────────────────────┘
```

**数据流（有监督闭环）**：
```
导入图像 → labeling/(6模式+SAM) 生成 LabelMe JSON
   → training/dataset_adapter 按任务转 Dataset
   → training/trainer (子线程, 可中断) 加载 models/supervised/{task} 引擎训练
   → TrainingTracker 上报 loss/metric → ModelEvaluator 评估
   → 打包到 project/{...}/models + exporter/ 导出 ONNX
   → gui/predict_page 加载 → 批量推理 → results 存储 + 报表
```

---

## 4. 接口与契约（核心，PEP8 / Protocol / frozen dataclass）

### 4.1 任务引擎接口 `core/interfaces_supervised.py`【新】

```python
from __future__ import annotations
from enum import Enum
from typing import Protocol, Optional, Callable, Any
from dataclasses import dataclass
from torch import Tensor

class TaskType(str, Enum):
    CLS = "cls"; DET = "det"; SEG = "seg"; PSEG = "pseg"
    POSE = "pose"; SSEG = "sseg"; ABDET = "abdet"
    SGAN = "sgan"; SUPER = "super"

@dataclass(frozen=True)
class DetectionResult:           # 通用结果容器（不可变）
    task: TaskType
    boxes: Optional[tuple[tuple[float, float, float, float], ...]] = None   # (x1,y1,x2,y2)...
    scores: Optional[tuple[float, ...]] = None
    labels: Optional[tuple[str, ...]] = None
    masks: Optional[Tensor] = None          # [N,H,W] 二值
    keypoints: Optional[Tensor] = None      # [N,K,3]
    anomaly_map: Optional[Tensor] = None    # [H,W]
    score: Optional[float] = None           # 全局异常分
    extra: tuple[tuple[str, Any], ...] = () # 任务专属（如合成图、HR 图）

class ISupervisedTaskEngine(Protocol):
    """有监督任务引擎：加载预训练/微调权重并推理。"""
    task: TaskType
    def load(self, weights_path: str, device: str = "cuda") -> None: ...
    def infer(self, image: Tensor, threshold: float = 0.5,
              labels: Optional[list[str]] = None) -> DetectionResult: ...
    def release(self) -> None: ...
    def info(self) -> dict[str, Any]: ...

class ITaskTrainer(Protocol):
    """任务训练器：消费数据集产出权重。"""
    task: TaskType
    def fit(self, cfg: "TrainConfig",
            progress: Optional[Callable[[float, dict], None]] = None,
            should_stop: Optional[Callable[[], bool]] = None) -> "TrainArtifact": ...
    def resume(self, ckpt: str) -> None: ...
```

> 说明：`should_stop` 回调实现 GUI"强制结束"（FR-B2）；`progress` 回调喂 `TrainingTracker`（FR-B3）。

### 4.2 训练配置 `training/config.py`【新，支持 Fernet】

```python
@dataclass(frozen=True)
class TrainConfig:
    task: TaskType
    epochs: int = 100
    lr: float = 1e-3
    batch_size: int = 8
    optimizer: str = "adamw"
    backbone: str = "yolov8n"        # 任务默认
    augment: tuple[str, ...] = ()
    early_stop_patience: int = 20
    device: str = "cuda"
    # 序列化：to_yaml() 明文内存 ↔ to_encrypted(bytes) Fernet 落盘
```

### 4.3 标注接口 `labeling/base.py`【新】

```python
class AnnotationMode(str, Enum):
    POLYGON="polygon"; RECTANGLE="rectangle"; BRUSH="brush"
    KEYPOINT="keypoint"; AUTO="auto"; INTERACTIVE="interactive"

class ILabeler(Protocol):
    mode: AnnotationMode
    def on_press(self, pt: tuple[float,float]) -> None: ...
    def on_move(self, pt: tuple[float,float]) -> None: ...
    def on_release(self, pt: tuple[float,float]) -> Optional["Shape"]: ...
    def to_shape(self) -> Optional["Shape"]: ...

@dataclass(frozen=True)
class Shape:
    mode: AnnotationMode
    points: tuple[tuple[float, float], ...]
    label: str
    color: tuple[int,int,int,int]
```

### 4.4 项目模型 `project/models.py`【新】

```python
@dataclass(frozen=True)
class ProjectId:
    name: str; task: TaskType; seq: int; ts: int   # {name}_{TASK}_{seq}_{ts}
    def to_path(self, root: str) -> str: ...

@dataclass(frozen=True)
class ProjectLayout:   # 规范目录（FR-E1）
    images: str; annotations: str; models: str; configs: str; results: str
```

### 4.5 加密接口 `core/encryption.py`【新】

```python
class IConfigCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, token: bytes) -> bytes: ...
    def encrypt_file(self, src: str, dst: str) -> None: ...
    def decrypt_file(self, src: str) -> bytes: ...

class FernetConfigCipher:        # 默认实现：cryptography.fernet
    def __init__(self, key_provider: "IKeyProvider"): ...
```

> **密钥策略（缓解 R-4）**：`IKeyProvider` 三实现可选——`EnvKeyProvider`(开发) / `KeyringKeyProvider`(本机 OS 钥匙串) / `ServiceKeyProvider`(企业服务端下发+机器绑定)。密钥**不入仓库**、不嵌明文。

### 4.6 GUI 任务分发的统一门面（扩展 `VisionModelSystem`）

```python
class VisionModelSystem:                # 既有，扩展分发
    def infer(self, project_task: TaskType, image, **kw) -> DetectionResult | dict:
        if project_task in _ZERO_SHOT_TASKS:
            return self._zero_shot_detector.detect(image, ...)   # 既有 IDetector
        return self._engines[project_task].infer(image, **kw)    # 新引擎
```

### 4.7 错误契约（复用 `core/exceptions.py`，新增子类）

```
ModelError (既有)
 ├── SupervisedEngineError    (新)  引擎加载/推理失败
 ├── TrainingError            (新)  训练崩溃/中断异常
 ├── ConfigDecryptionError    (新)  Fernet 解密失败
 └── UnsupportedTaskError     (新)  任务类型未注册
```

---

## 5. 组件设计（按域）

### 5.1 有监督引擎 `models/supervised/`
```
models/supervised/
├── base.py              # AbstractTaskEngine（ISupervisedTaskEngine 骨架）
├── registry.py          # @register_engine(TaskType.DET) 装饰器 + DI 注册
├── cls_torchvision.py   # FR-A1  torchvision 分类
├── det_yolo.py          # FR-A2  ultralytics YOLOv8 检测
├── seg_yolo.py          # FR-A3  YOLOv8-Seg
├── pseg_yolo.py         # FR-A4  YOLOv8-Seg 大模型
├── pose_yolo.py         # FR-A5  YOLOv8-Pose
├── sseg_mmseg.py        # FR-A6  mmseg DeepLabV3+
├── abdet_anomalib.py    # FR-A7  anomalib PatchCore/PaDiM
├── sgan_mmedit.py       # FR-A8  mmedit 生成
└── super_mmedit.py      # FR-A9  mmedit SR
```
每个引擎：`load/infer/release/info`；通过 `registry` 注册到 DI；`VisionModelSystem` 按枚举分发。

### 5.2 训练流水线 `training/`
```
training/
├── trainer.py           # GenericTrainer（线程化 + should_stop 中断 + resume）
├── dataset_adapter.py   # LabelMe JSON → 各任务 Dataset
├── callbacks.py         # LossCallback/MetricCallback/EarlyStop/Checkpoint
├── config.py            # TrainConfig（frozen）+ 序列化（含加密）
├── artifact.py          # TrainArtifact（权重+指标+配置指纹）
└── runner.py            # 对接 industrial_vision_platform.TrainingTracker
```
- **线程模型**：`QThread`（GUI）/ `ThreadPoolExecutor`（API）跑 `ITaskTrainer.fit`；通过 `progress`/`should_stop` 回调与主线程通信，避免 GIL 阻塞 UI（R-9）。

### 5.3 标注子系统 `labeling/`
```
labeling/
├── base.py              # ILabeler + Shape + AnnotationMode
├── modes/
│   ├── polygon.py rectangle.py brush.py keypoint.py   # 4 手动模式
│   ├── auto.py          # AI 预标注（复用零样本/有监督引擎）
│   └── interactive.py   # SAM 交互
├── sam_adapter.py       # segment-anything 封装（点击/框→mask→多边形 Douglas-Peucker）
├── canvas.py            # QGraphicsScene 画布 + 撤销/重做栈（frozen shape 拷贝）
├── io_labelme.py        # LabelMe JSON 读写（对齐 evaluation/labelme_loader.py）
└── controller.py        # 模式调度 + 快捷键
```
- **撤销/重做**：栈存 `tuple[Shape,...]`（不可变快照），对应 FR-C4。
- **SAM**：`SamPredictor`，`interactive` 模式产出 mask→`cv2.findContours`→Douglas-Peucker 简化→`Shape(polygon)`。

### 5.4 桌面 GUI `gui/`（最大模块，对标 SKolpha 页面树）
```
gui/
├── main.py              # 入口 + 无边框主壳（PySide6）
├── core/
│   ├── shell.py         # 自定义标题栏 + 侧边导航 + 页面栈（FR-D1）
│   ├── theme.py         # QSS 加载器（night/daytime）（FR-D1）
│   ├── i18n.py          # gettext + self._() 包装（FR-D3）
│   └── shortcuts.py     # 快捷键注册
├── pages/               # 一页一目录，对标 frontend.ui_*
│   ├── login/  home/  data_manage/  label/  train/
│   ├── evaluate/  publish/  predict/  project/   settings/
├── controllers/         # 页面业务逻辑（对标 frontend.ui_function_*）
├── widgets/             # loss 曲线(pychart)、参数表、结果表、自定义控件
└── resources/           # qss / icons(CoreUI) / locale
```
- **MVVM 轻**：`pages/`（View）↔ `controllers/`（ViewModel，调 `industrial_vision_platform` 服务）↔ 领域层（Model）。
- **训练页**：`QThread` 跑 `GenericTrainer`，`progress` 信号 → loss 曲线 widget 实时刷新（FR-D5）。

### 5.5 项目管理 `project/`
```
project/
├── models.py            # ProjectId / ProjectLayout（frozen）
├── store.py             # IProjectStore（文件系统实现）
├── counter.py           # 任务 ID 计数器（psegID/...，原子自增）
└── metadata.py          # 项目元数据 + recent 列表（saveProgrameList 等价）
```

### 5.6 配置与加密
- `ConfigSystem`（既有）扩展：识别 Fernet token（`gAAAAA` 头）→ `FernetConfigCipher.decrypt_file` → 再 YAML/JSON 解析。
- `core/encryption.py`：`IConfigCipher` + `FernetConfigCipher` + 三种 `IKeyProvider`。

### 5.7 GAN/SR 与质量评估（域 G）
- `sgan_mmedit.py` 调 `mmedit.apis.generation_inference`/`inpainting_inference`；质量用 `evaluation/fid.py`（新，基于 FID-Inception 权重，附录 D 证实）。
- `super_mmedit.py` 调 `restoration_inference`；质量用 PSNR/SSIM。

---

## 6. 数据模型汇总

| 实体 | 类型 | 说明 |
|------|------|------|
| `TaskType` | Enum | 9 任务 |
| `DetectionResult` | frozen dataclass | 引擎统一输出 |
| `TrainConfig` | frozen dataclass | 训练超参（可序列化/加密） |
| `TrainArtifact` | frozen dataclass | 训练产物（权重路径+指标+配置哈希） |
| `Shape` / `Annotation` | frozen dataclass | 标注（LabelMe 兼容） |
| `ProjectId` / `ProjectLayout` | frozen dataclass | 项目目录模型 |
| 项目磁盘结构 | 目录 | `{root}/{name}_{TASK}_{ID}_{ts}/{images,annotations,models,configs,results}` |
| 训练配置文件 | 加密 YAML | 运行时 `gAAAAA…`（Fernet），内存明文 |

**模型权重不入库**（R-6/仓库膨胀）：注册表记录下载 URL + 校验哈希，首次使用按需下载到 `~/.cache/...`（对标 SKolpha 1.28GB 不入库）。

---

## 7. 影响分析（文件变更 / 兼容 / 迁移）

### 7.1 新增（零侵入）
- `core/interfaces_supervised.py`、`core/encryption.py`
- `models/supervised/`（11 文件）、`training/`（6）、`labeling/`（10+）、`project/`（4）、`gui/`（大）
- `evaluation/fid.py`

### 7.2 扩展（向后兼容，仅"加方法/加分发"，不改既有签名）
- `industrial_vision_platform/{model_system, training_tracker, model_evaluator, data_manager, config_system}.py`：**新增方法**，不改既有。
- `core/exceptions.py`：**新增子类**。
- `configs/`：**新增**任务默认配置模板。

### 7.3 不改动（零回归保护）
- `models/{detector, dinov3, clip, few_shot_trainer, ...}`、`services/detection_service`、`api/gateway`、Web/CLI——**一行不动**。

### 7.4 依赖新增（`requirements.txt` 分组）
```
# supervised
ultralytics>=8.1          # ⚠ AGPL-3.0，待法务(R-5)
anomalib>=1.1
mmsegmentation>=1.2 ; mmcv-full>=2.0
mmedit>=0.10              # 或迁移 diffusers
segment-anything @ git+...
open3d>=0.17              # P2 (3D)
# gui
PySide6>=6.6 ; pyqtgraph>=0.13
# encryption
cryptography>=42
```
- **版本隔离(R-3/R-10)**：mmcv/mmedit 旧链可能与 3.11 冲突 → 用 `extras_require` 分组 + CI 矩阵；必要时 mmedit 用容器隔离。

### 7.5 迁移路径
1. M0：新接口 + DI 接入点 + 加密模块（零功能，可单独合入）。
2. M1：det/seg/abdet + 训练 + GUI 5 页（MVP 闭环，可演示）。
3. M2：补齐 9 任务 + SAM + 评估/发布。
4. M3：打包/文档/调优。
每里程碑结束跑**零样本回归套件**（前置护栏）。

---

## 8. 性能设计

| 点 | 策略 |
|----|------|
| 推理 | `weights_only` 加载 + 懒缓存（沿用）；TensorRT 导出（复用 `tensorrt_accel`）；批量 |
| 训练 | AMP（FR-A 的 ultralytics 自带；mmedit 支持）；梯度检查点；子线程不阻塞 UI |
| GUI | 训练在 `QThread`；图像缩略图缓存；结果表虚拟化（`QAbstractItemView`） |
| SAM | 掩码缓存 image_embedding；提供 ViT-B/Q 轻量档（R-6） |
| 启动 | 模型按需加载；GUI 骨架先起 |

---

## 9. 安全设计（呼应 PRD 域 H）

- 模型加载 `weights_only=True`（FR-H1，沿用）。
- Fernet 配置加密 + 密钥三策略（§4.5），密钥不入库（FR-H2，R-4）。
- 授权走 `enterprise/license_manager`（软件授权，**无加密狗**，FR-H3）。
- 输入校验/路径遍历/速率限制沿用 `core/security`（FR-H4）。
- **AGPL 风险(R-5)**：Design 标注为"待法务放行前不得进入商用打包"；若不放行，`det_yolo/seg_yolo/pose_yolo` 切换为非 AGPL 备选（RT-DETR 自研 / 闭源检测头），接口不变（策略模式兜底）。

---

## 10. 测试策略

| 层 | 方法 | 工具 |
|----|------|------|
| 引擎 | 每任务 `infer` 契约测试（固定输入→期望结构） | pytest `@unit` + 小权重 |
| 训练 | 1-epoch 冒烟 + 中断/续训 | pytest `@integration` |
| 标注 | 各模式 shape 生成 + 撤销/重做 + LabelMe 往返 | pytest `@unit` |
| GUI | 关键页面 snapshot + 流程 e2e | pytest-qt `@e2e`（CLAUDE.md `/e2e`） |
| 加密 | 加解密往返 + 错误密钥失败 | pytest `@unit` |
| 回归 | 既有零样本套件 | pytest（前置护栏） |
| 覆盖 | ≥80% | pytest-cov |

---

## 11. 开放问题（待 Phase 3 / 后续决策）

- Q1：ultralytics AGPL 是否可接受？（R-5，阻塞商用）→ 建议 Phase 3 前法务确认。
- Q2：mmseg/mmedit 旧依赖与 Python 3.11 兼容是否需容器隔离？（R-3/R-10）
- Q3：Fernet 密钥策略默认选哪个（开发=Env，生产=Keyring/Service）？
- Q4：模型权重分发渠道（项目内 URL 注册表 vs 内部模型仓库）？

---

*本 Design 基于 PRD v1.0.0 与 DINOv3 现状。接口契约为 Phase 3 Tasks 的实现依据。下一阶段：Tasks（`tasks-skolpha-fork.md`）。*
