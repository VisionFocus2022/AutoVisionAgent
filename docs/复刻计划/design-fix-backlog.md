# Design — 🔴 未完成项补齐战役（关键架构决策）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.1.0（2026-06-30 正文同步重写为 Option A） |
| 创建日期 | 2026-06-29 |
| 阶段 | L3 / Phase 2 — Design |
| 上游 | `prd-fix-backlog.md` v1.1.0（探索门禁已过：全9项/Option A 轻量库/不切栈/全包80%） |
| 下游 | `tasks-fix-backlog.md`（Phase 3） |
| 设计基线 | `design-skolpha-fork.md` v1.0.0（接口契约权威）+ 既有代码实证接口（license_manager/metrics_supervised/supervised_exporter/generic_trainer） |

> 🔧 **v1.1.0 决策记录（2026-06-30 · 对标 skolpha.exe 审计后正文同步重写）**：原 §3.1 选定 A(mmcv 隔离 venv)+D(diffusers 兜底)，审计后判定 mmcv 预编译轮子对 Python 3.12 + torch 2.5.1 覆盖薄、隔离环境复杂度过高，**改采 Option A 轻量库**——sseg→`segmentation_models_pytorch`(DeepLabV3+)、super→`cv2.dnn_superres`、sgan→copy-paste blend(`cv2.seamlessClone`)。正文 §3.1 / §3.3 / §4 / §6.1 / §6.2 / §9 已同步重写为 Option A，本节仅保留决策脉络（不再作"覆盖正文矛盾"的偏差器）。训练侧连带：sseg 用 smp train；sgan 转数据增强（运行时 blend，无训练）；super 仅推理（预训练 EDSR/ESPCN，无训练）。**接口 `ISupervisedTaskEngine` 不变**（零侵入原则保持）。执行细节以 `tasks-fix-backlog.md` v1.1.0 为准。

---

> 🚨 **2026-06-30 重定基线订正**：本文（era-3 设计意图存档）的「Option A 轻量库真化 sseg/sgan/super」「训练策略接线」「5 页业务接线」等关键决策**经核查未落地或失真**（详见 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §1）：① 三引擎仍走 mmseg/mmedit 假回退（`sseg_mmseg.py:30-32,77` / `sgan_mmedit.py:75,84,88` / `super_mmedit.py:59,69,73`，含 `score=1.0`/`arr.copy()`/`INTER_NEAREST`；0 处轻量库 import）；② **det/seg/abdet 引擎根本不在磁盘**（`engines/__init__.py:31-35` 静默吞 ImportError）；③ `training/strategies/` 不存在、`_SmokeStrategy` 改名 `_SimStrategy` 仍 `math.exp` 假 loss（`train/page.py:326,406`）；④ `enterprise/` + `core/encryption.py` 已整个删除 → FR-H2/H3 落空。**本文接口契约（`ISupervisedTaskEngine` 不变等）仍有效；执行以 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) 为准**，其 §3「防假绿验证标准」是对本文「测试真实化」策略的强化落地。

---

## 1. 设计目标与原则

1. **零侵入补齐**：补的是「实现 + 测试」，不改既有公开接口签名（`ISupervisedTaskEngine`/`ITaskTrainer`/`DetectionResult` 等冻结）；新依赖隔离不污染主 venv（NFR-5）。
2. **接口契约权威**：本设计与 `design-skolpha-fork.md` 冲突时以上游为准并回写本文。
3. **消除假绿**：补的测试必须真打库/真跑功能；降级路径必须显式标注「未支持」，不得伪装成已完成。
4. **既有实现优先复用**：`LicenseManager`/`evaluate_supervised`/`SupervisedExporter`/`GenericTrainer+ITrainStrategy` 均已存在，GUI 页面/训练页只需**接线调用**，不重造。

---

## 2. 既有可复用契约（实证接口，已 grep 确认）

| 模块 | 实证签名 | 用途 |
|------|---------|------|
| `enterprise/license_manager.py:480` | `LicenseManager`（`verify_license`/`check_feature`/`get_license_info`，`:535/552/622`）+ `create_license_manager()`（`:642`） | FR-FIX-03 login 门控 |
| `evaluation/metrics_supervised.py` | `det_map`/`seg_iou`/`abdet_auroc`/`evaluate_supervised`（`:34/149/186/227`） | FR-FIX-03 eval_ 接线 + FR-FIX-06 测试 |
| `exporter/supervised_exporter.py:18` | `SupervisedExporter(opset=14,simplify=True).export_onnx(...)`/`export_tensorrt(...)`（`:31/95`） | FR-FIX-03 deploy 接线 |
| `training/generic_trainer.py:32/46` | `ITrainStrategy.train_epoch(epoch,cfg)->Dict[str,float]` + `GenericTrainer(strategy).fit(cfg,progress,should_stop)->artifact` | FR-FIX-04 训练页接线 |
| `models/supervised/registry.py` | `register_engine(TaskType)` + `get_engine(task)` | FR-FIX-05 引擎测试 |
| `core/interfaces_supervised.py` | `TaskType`/`DetectionResult`/`ISupervisedTaskEngine`/`TrainConfig`/`TrainArtifact` | 全局契约 |
| `industrial_vision_platform/vision_dispatcher.py` | `VisionModelDispatcher`（真分发器，双范式路由） | FR-FIX-03/04 间接依赖 |

> ⚠️ **命名陷阱**：`industrial_vision_platform/model_system.py::VisionModelSystem` 与 registry 引擎脱钩（走自带 toy nn.Module），**真分发器是 `vision_dispatcher.py::VisionModelDispatcher`**。GUI/训练接线用后者，勿用前者。本次不改二者（NFR-5），仅文档澄清。

---

## 3. 关键决策（6 项，含选型对比）

### 3.1 后端选型方案（FR-FIX-01/02/07）✅核心

| 方案 | 描述 | 零样本风险 | 落地速度 | 选定 |
|------|------|-----------|---------|------|
| **A：轻量库直装主 venv**（Option A） | sseg→`segmentation_models_pytorch`(DeepLabV3+)、super→`cv2.dnn_superres`(EDSR/ESPCN)、sgan→copy-paste blend(`cv2.seamlessClone`)；均纯 Python 或轻 C 扩展 | 🟢 无（无 mmcv 重依赖） | 快 | **✅ 选定** |
| ~~B：mmcv 隔离 venv~~（作废） | 新建 `.venv-mm/` 装 mmcv-full/mmedit/mmsegmentation | 🟢 无但复杂 | 慢 | ❌ 审计后否决（mmcv 轮子薄） |
| C：Docker 容器 | 用既有 `Dockerfile` 装 mm 链 | 🟢 无 | 慢（桌面分发冲突） | 备选（CI 用） |
| ~~D：diffusers 兜底~~（作废） | super/sgan 切 diffusers、sseg 切 torchvision deeplabv3 | 🟢 无 | 中 | ❌ Option A 已覆盖，不再需要 |

**选定 Option A（轻量库直装主 venv）**：三引擎全部走轻量库，主 venv 直装，**无隔离环境、无 mmcv 依赖**。M-FIX-0 仅需验证 `segmentation_models_pytorch` + `cv2.dnn_superres` 可装可跑（Python 3.12 + torch 2.5.1，预期无障碍）。`ISupervisedTaskEngine` 接口不变。SAM（segment_anything）与 pyinstaller 风险低，可直装主 venv。

### 3.2 登录门控接线（FR-FIX-03 login）

```
login._do_login(username, license_key?)
  → LicenseManager.verify_license(license_key)   # 既有 :535
     ├─ True  → emit login_success(LicenseInfo)   # main.py lambda 切 home
     └─ False/异常 → 状态栏友好提示 + 留在 login（不 emit）
```
- **LicenseManager 实例来源**：经 DI 容器解析（`create_license_manager()`），或 login 页构造时注入。**不硬编码密钥**（R-FIX 安全省 §5）。
- **降级**：开发态可设「离线模式」跳过（沿用既有 `_offline` 按钮逻辑），但生产态必须门控。

### 3.3 训练页接真引擎（FR-FIX-04）

```
TrainPage._make_trainer(task, cfg) -> GenericTrainer
  strategy = {
    DET/SEG/POSE/PSEG: YoloTrainStrategy(engine),   # 封装 ultralytics model.train() 成 ITrainStrategy
    ABDET: AnomalibTrainStrategy(engine),            # 封装 anomalib PatchCore.fit
    SSEG: SmpTrainStrategy(engine),                  # 封装 segmentation_models_pytorch train（轻量）
    SGAN: 无训练（copy-paste blend 是运行时数据增强，不建模），
    SUPER: 无训练（cv2.dnn_superres 仅推理，用预训练 EDSR/ESPCN 权重），
  }[task]
  return GenericTrainer(strategy)
```
- **新增文件** `training/strategies/{yolo,anomalib,smp}_train.py`，各实现 `ITrainStrategy.train_epoch`（真 backward，复用 `training/trainer.py:290-355` 的 AMP/梯度累积范式）。sgan/super 无训练策略（前者运行时 blend，后者纯推理）。
- **`_SmokeStrategy` 处置**：移入 `tests/` 仅作测试夹具（冒烟假策略在测试里合法），**从生产 page.py 删除**。
- **线程模型不变**：`TrainWorker(QThread)` + `threading.Event` stop_flag（既有 `worker.py:39-57` 真实）。

### 3.4 5 空壳页面业务接线（FR-FIX-03）

| 页面 | 接线（调既有） | 关键控件 |
|------|--------------|---------|
| login | `LicenseManager.verify_license`（§3.2） | 用户名 + license 输入 |
| home | `DataManager` 项目计数 → `update_stats()`；`project.recent.recent_list()` → 最近项目 QList | 4 StatCard + 最近列表 |
| eval_ | 选模型+数据集 → `evaluate_supervised(preds,gts,task)` → 填 QTableWidget | 模型/数据选择 + 指标表 |
| deploy | 选训练产物 → `SupervisedExporter.export_onnx(path)`（+可选 TRT）→ 进度 + `torch.allclose` 一致性校验 | 产物选择 + 导出按钮 |
| settings | 主题 combo→`ThemeManager.apply`；语言 combo→`i18n.set_language`；路径→写 `configFile.json` | 3 combo + 保存 |

- **`retranslate()` 补全**：5 页当前是 `pass`（审查实证），必须实装刷新按钮文本（i18n 全页生效）。

### 3.5 覆盖率门禁机制（FR-FIX-09）

- **分阶段爬升**：`pytest.ini` `--cov-fail-under` 60 → 70 → 80（每里程碑上调，红即停）。
- **per-package 防回退**：新增 `.coveragerc` 或 `setup.cfg [coverage:report]` 的 `fail_under` 分包阈值——新模块（models/supervised、training、labeling、gui、evaluation）各 ≥80%，legacy（models/detector 等零样本）分阶段。
- **解决配置冲突**：`setup.cfg [tool:pytest]` 段与 `pytest.ini` 重复——删除 `setup.cfg` 的 pytest/coverage 死配置段，统一到 `pytest.ini`（审查清单 §三-25，本战役顺手收，因直接影响覆盖率机制）。
- **legacy 补测原则**：**只加测试不改 legacy 源码**（NFR-5）；优先补 `models/`、`services/`、`inference/` 的纯函数/分支测试。

### 3.6 测试真实化策略（FR-FIX-05/06，消除假绿）

- **引擎契约测试**：每引擎 `tests/test_engine_<task>.py`，`pytest.importorskip` 对应库；有 demo 权重时 `@gpu` 真跑 `load→infer`，断言 `DetectionResult` 字段；无权重时**显式 skip 并注明原因**，不用固定种子造假。
- **`test_m2_e2e.py` 的 `hasattr` 检查**：保留为「注册完整性」测试（合法用途），但**降级命名**（如 `test_all_engines_registered`），不再是引擎功能验证的唯一手段——引擎功能由 `test_engine_*.py` 承担。
- **真 e2e 链路**：`tests/test_m1_e2e.py` 现是断片（训练用 `_SmokeStrategy`）→ 新增串行用例「导入图→标注→真训练 1-epoch→评估→推理→导出」全链路断言（用小数据集 + ViT-B/YOLOv8n）。
- **`run_m3_verification.py` 强化**：从「py_compile + pytest + 渲染 PNG + 注册名检查」升级为含「依赖就绪检查 + 关键功能冒烟（至少 1 引擎真 infer + SAM 真 mask + 1 页真业务）」。

---

## 4. 组件设计（新增/改动清单）

### 4.1 新增
```
training/strategies/
├── yolo_train.py          # YoloTrainStrategy(ITrainStrategy) — det/seg/pose/pseg
├── anomalib_train.py      # AnomalibTrainStrategy — abdet
└── smp_train.py           # SmpTrainStrategy — sseg（segmentation_models_pytorch）
                          # 注：sgan(copy-paste blend)/super(dnn_superres 推理) 无训练策略
tests/
├── test_engine_cls.py test_engine_pose.py test_engine_pseg.py
├── test_engine_sseg.py test_engine_sgan.py test_engine_super.py   # 6 引擎契约测试
├── test_metrics_supervised.py   # FR-FIX-06
├── test_sam_adapter.py          # FR-FIX-06（importorskip segment_anything）
├── test_train_page.py           # FR-FIX-06
└── test_full_e2e_pipeline.py    # 真 e2e 链路（替代断片冒烟）
（无 .venv-mm/ —— Option A 直装主 venv，无需隔离环境）
```

### 4.2 改动（向后兼容，仅接线/补实现，不改签名）
- `gui/pages/{login,home,eval_,deploy,settings}/page.py`：补业务方法 + `retranslate()`。
- `gui/pages/train/page.py`：`_make_trainer` 换真策略；`worker.py` 不变。
- `models/supervised/engines/{sseg_mmseg,sgan_mmedit,super_mmedit}.py`：改走 Option A 轻量库真分支（sseg→smp DeepLabV3+ / sgan→seamlessClone blend / super→dnn_superres），移除伪装成功的假回退。**文件名保留 `_*_mmedit/mmseg` 历史命名**（避免改 import 路径扩大 diff、断注册表）；如需正名（如 `sseg_smp.py`）另登记为低优清理。
- `run_m3_verification.py`：强化功能冒烟。
- `pytest.ini` + `setup.cfg`：覆盖率门禁分阶段 + 删冲突段。
- `desktop.spec`：合并去重 + `collect_all` PySide6/torch。

### 4.3 不改动（零回归保护）
零样本链路（`models/{detector,dinov3,clip,few_shot_trainer}`、`services/detection_service`、`api/gateway`、Web/CLI、`VisionModelSystem`）——一行不动。

---

## 5. 安全设计（呼应 PRD 域 H）

- LicenseManager 密钥不硬编码（R-FIX），经 DI 或环境变量注入。
- 引擎加载 `weights_only=True` 沿用（FR-H1）。
- SAM/mmseg 权重按需下载，校验哈希，不入库（R-6）。
- **AGPL 风险**（R-5，用户已定接受）：Design 标注「含 AGPL 组件，闭源商用前需法务确认」，README 明示，不切栈。

---

## 6. 影响分析与迁移路径

### 6.1 依赖新增（`requirements.txt` 分组）
```
# supervised 轻量后端（Option A，主 venv 直装）
segmentation_models_pytorch>=0.3 ; opencv-contrib-python（含 dnn_superres）
# sam
segment-anything @ git+...
# export/build
onnx>=1.16 ; onnxruntime>=1.18 ; pyinstaller>=6.0
# 测试（.venv）
pytest-qt>=4.4  # 可选——当前测试用 offscreen 不强依赖
```

### 6.2 迁移路径（里程碑）
1. **M-FIX-0**：主 venv 装轻量库验证（`segmentation_models_pytorch` + `cv2.dnn_superres` 可装可跑）+ 回归护栏基线快照。
2. **M-FIX-1**：3 引擎真化 + SAM 真化 + 6 引擎契约测试。
3. **M-FIX-2**：5 页面接业务 + 训练接真引擎 + 真 e2e。
4. **M-FIX-3**：覆盖率 80 + 3 缺失测试 + exe 构建 + AGPL 归档。

每里程碑结束跑**零样本回归套件**（前置护栏，红即停）。

---

## 7. 测试策略（强化真实化）

| 层 | 方法 | 工具 | 真实化要求 |
|----|------|------|-----------|
| 引擎 | 每任务 `load→infer` 契约 | pytest `@unit`/`@gpu` + importorskip | 有权重真跑，无权重显式 skip 注明 |
| SAM | mask→多边形 e2e + 缓存命中 | pytest `@gpu` + importorskip | ViT-B 真跑，不用 FakeSamAdapter 冒充 |
| 训练 | 1-epoch 真策略 + 中断/续训 | pytest `@integration` | 真 backward（非 _SmokeStrategy） |
| GUI | 5 页业务行为 + 真 e2e | pytest offscreen + 直接调方法 | 断言业务输出（指标/导出/持久化），非仅构造不崩 |
| 覆盖 | 全包 ≥80% + per-package 防回退 | pytest-cov | 分阶段爬升，红即停 |
| 回归 | 零样本套件 | pytest `@regression` | 前置护栏，0 失败 |

---

## 8. 性能设计

| 点 | 策略 |
|----|------|
| 引擎真测 | 小权重/小图固定输入，避免大模型拖慢 CI；`@gpu`/`@slow` 分离 |
| SAM | ViT-B 默认（非 ViT-H 2.5GB）；mask embedding 缓存（同图一次） |
| 训练 e2e | 1-epoch + 极小数据集（imagenette 子集）冒烟 |
| exe | onedir 先于 onefile；torch/PySide6 `collect_all` 防隐藏导入漏 |

---

## 9. 开放问题（执行期决策）

- ~~Q1：mmcv-full 在 Python 3.12.9 + torch 2.5.1 是否有预编译轮子？若无，源码编译成本可接受否？~~ → **作废**（Option A 弃 mmcv）。**新 Q1**：`segmentation_models_pytorch` + `cv2.dnn_superres` 在 Python 3.12 + torch 2.5.1 是否可直装？预期无障碍（M-FIX-0 验证）。
- Q2：LicenseManager 实例经 DI 还是 login 页构造注入？（M-FIX-2 决策）
- Q3：exe 打包 onedir 还是 onefile？（M-FIX-3 决策，体积 vs 启动速度）

---

*本 Design 基于 `prd-fix-backlog.md` v1.1.0 与既有代码实证接口。关键决策 §3（后端选型 Option A 轻量库 / 登录门控 / 训练策略接线 / 5 页业务 / 覆盖率门禁 / 测试真实化）为 Phase 3 Tasks 实现依据。按用户要求止于 Phase 3。*
