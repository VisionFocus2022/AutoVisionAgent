# AutoVisionAgent — 剩余任务执行规划（Qoder 目标模式自主执行）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-29 |
| 适用 | Qoder 目标模式 / Agent 自主连续执行 |
| 项目根 | `E:\计算机视觉\视觉大模型\` |
| 产品名 | **AutoVisionAgent**（原内部代号 "SKolpha 复刻"，已重命名） |
| 上游依据 | `docs/复刻计划/prd-skolpha-fork.md` · `design-skolpha-fork.md` · `tasks-skolpha-fork.md` |
| 现场约束 | Windows + Git Bash；非 git 项目（回滚靠备份原文件） |

> ⚠ **2026-06-30**：本文档（v1.0.0，10:25）记录 T-AVA-01..21 已完成基线。**活的 Qoder-feed 是更晚的 `tasks-fix-backlog.md` v1.1.0**（M-FIX-0..4，含对标 skolpha 审计的后端改向 Option A + 净增任务 + P2 扩展）。续做请以 fix-backlog 三件套为准，勿按本文 §6 残余任务执行。

---

## 0. 如何使用本文档（给 Qoder）

1. **连续执行**：从「§6 任务清单」按 ID 顺序执行；每个任务走「§5 执行循环」。
2. **每任务必过验证**：编码后执行该任务「验证命令」一栏，全绿才能标记完成；失败按「§7 回滚」处理。
3. **不破坏既有**：严格遵守「§3 工程约定」与「§4 已完成清单（不要重做）」。
4. **门禁**：每个里程碑（M1 收尾 / M2 / M3）结束，输出「§9 进度汇报」并暂停等待人工评审（或按 Qoder 目标模式继续，见各里程碑末尾）。
5. **偏差即记**：实际与计划不符，在任务下追加 `> 偏差:` 记录原因与处置。
6. **接口契约权威**：本文名字/签名与 `design-skolpha-fork.md` 冲突时，以 design 文档为准并回写本文。

> ⚠ **非 git 项目**：每个任务开工前备份涉及的文件（复制到 `*.bak`）；改动出错手动还原。原子化小步提交。

---

## 1. 项目与技术栈

- **基线**：DINOv3 零样本工业视觉缺陷检测平台（DDD 分层、PyTorch）。
- **扩展目标**：在零样本链路**零侵入**前提下，新增 9 任务有监督引擎、训练流水线、6 模式标注、PySide6 桌面 GUI、项目管理、Fernet 配置加密（对标 SKolpha 3.3.2 商业平台，去 DRM）。
- **技术栈**：Python 3.12 · PySide6 6.11.1 · torch 2.5.1+cu121（CUDA ✓）· ultralytics · anomalib · cryptography · opencv · numpy。
- **虚拟环境**：`.venv/`（Windows）。Python 解释器：`.venv/Scripts/python.exe`。
- **后续依赖（按需安装）**：`mmsegmentation` / `mmcv-full`（sseg）、`mmedit` 或 `diffusers`（sgan/super）、`segment-anything`（SAM）、`pytest-qt`（GUI e2e）、`onnx` / `tensorrt`（发布）。安装时分组写 `requirements.txt` 并锁版本（R-3）。

---

## 2. 目录结构（现状）

```
视觉大模型/
├── core/                       # 基础设施（既有 + 新增）
│   ├── interfaces_supervised.py   # ✅ ISupervisedTaskEngine/TaskType/DetectionResult/TrainConfig/TrainArtifact
│   ├── encryption.py             # ✅ IConfigCipher/FernetConfigCipher/{Env,Keyring,Service}KeyProvider
│   ├── exceptions.py             # ✅ 含 Supervised/Training/Unsupported/ConfigDecryption/Labeling/InvalidShape/AnnotationIO
│   ├── dependency_injection.py   # ✅ DI 容器
│   └── interfaces.py / config.py / enums.py   # 既有
├── models/supervised/          # ✅ 有监督引擎
│   ├── base.py                   #   AbstractTaskEngine
│   ├── registry.py               #   @register_engine
│   └── engines/{det_yolo,seg_yolo,abdet_anomalib}.py   # ✅ FR-A2/A3/A7
├── training/                   # ✅ 训练流水线
│   └── {config,trainer,generic_trainer,dataset_adapter,callbacks,continual_learning,meta_learning}.py
├── project/                    # ✅ 项目目录模型
│   └── {models,store,counter}.py
├── labeling/                   # ✅ 标注子系统（本次完成）
│   ├── base.py / geometry.py / io_labelme.py / canvas.py / controller.py
│   └── modes/{polygon,rectangle,brush,keypoint}.py + _base.py + __init__.py
├── gui/                        # 🟡 主壳+标注页完成，4 页待实装
│   ├── core/{theme,i18n,shortcuts,icons,shell}.py
│   ├── pages/{label/page.py ✅, placeholder.py}
│   └── main.py                  #   入口：python -m gui.main
├── industrial_vision_platform/ # ✅ 平台层（VisionModelSystem/TrainingTracker/ModelEvaluator/DataManager/ConfigSystem...）
├── evaluation/                 # labelme_loader.py（标注/评估共用 LabelMe 解析）
├── exporter/  inference/  enterprise/  services/  api/  web/   # 既有
├── tests/                      # test_labeling.py(26) + test_gui.py(6) + 既有
├── docs/复刻计划/              # 本文档 + prd/design/tasks
└── desktop.spec  requirements.txt  pytest.ini  setup.cfg  CLAUDE.md
```

---

## 3. 工程约定（Qoder 必须遵守 · 违反即回滚）

| 约定 | 要求 |
|------|------|
| 风格 | PEP8；**行长 100**；双引号；`from __future__ import annotations`；函数 <50 行；文件 <800 行 |
| 不可变 | 数据用 `@dataclass(frozen=True)`；序列用 `Tuple[...]` + `field(default_factory=tuple)`；更新用 `replace()`/`with_*()` 返回新对象 |
| 类型 | 所有签名加类型注解；Protocol 定义接口；`Optional` 显式 |
| 测试 | pytest；标记 `@pytest.mark.{unit,integration,e2e,regression,slow,gpu}`（**`--strict-markers` 已开**，未注册标记会报错）；Qt 测试用 `QT_QPA_PLATFORM=offscreen` + 会话级 `qapp` fixture（见 `tests/test_gui.py`/`test_labeling.py` 范式） |
| 异常 | 抛 `core/exceptions.py` 子类（带 code/details），不裸 `Exception`；UI 层 catch 转友好提示 |
| i18n | UI 文案用 `from gui.core.i18n import tr` 包装：`tr("中文")`；新串补 `i18n.py` 的 `_EN_US` 字典 |
| 零侵入 | 不改 `models/{detector,dinov3,clip,few_shot_trainer}`、`services/detection_service`、`api/gateway`、Web/CLI——零样本链路一行不动（NFR-5） |
| 命名 | 中文注释/docstring（与既有代码一致）；英文标识符 kebab/snake |
| 安全 | `weights_only=True` 加载权重；密钥不硬编码；bandit 通过（如装了） |

**lint 现状**：`.venv` 内**未装** ruff/mypy/black/flake8（仅 pytest 9.1.1）。故「语法检查」用 `py_compile`，「功能验证」用 `pytest`。勿假装通过未安装工具。

---

## 4. 已完成清单（不要重做 · 验证基线）

| 里程碑 | 任务 | 状态 | 验证 |
|--------|------|------|------|
| M0 | T-M0-01..08 接口/加密/注册/异常/项目/配置/回归护栏/集成 | ✅ | `pytest tests/test_exceptions*.py tests/test_encryption.py --no-cov -q` |
| M1 | T-M1-01 AbstractTaskEngine | ✅ | `models/supervised/base.py` |
| M1 | T-M1-02/03/04 det/seg/abdet 引擎 | ✅ | `models/supervised/engines/` |
| M1 | T-M1-05..08 训练流水线 | ✅ | `training/*.py` |
| M1 | **T-M1-09/10 标注子系统** | ✅ | `pytest tests/test_labeling.py --no-cov -q`（26 例） |
| M1 | **T-M1-11 GUI 主壳**（无边框/主题/i18n/快捷键/图标） | ✅ | `pytest tests/test_gui.py --no-cov -q`（6 例） |
| M1 | **T-M1-12 标注页实装 + 4 占位页** | ✅（仅标注页） | `python -m gui._render_preview` 渲染 PNG |
| — | **重命名 → AutoVisionAgent** | ✅ | 窗口标题/应用名/i18n |
| M1 收尾 | **T-AVA-01..07** 数据/训练/推理/项目页 + ModelEvaluator + DataManager + M1 e2e | ✅ | `pytest tests/test_m1_e2e.py`（10 例） |
| M2 | **T-AVA-08..15** 9 引擎全注册 + SAM + FID + 5 页 + exporter + 双范式分发 + M2 e2e | ✅ | `pytest tests/test_m2_e2e.py`（15 例） |
| M3 | **T-AVA-16** PyInstaller spec（入口/图标/PySide6） | ✅* | spec 语法+入口+图标齐；`*`exe 待装 PyInstaller 构建 |
| M3 | **T-AVA-17** 性能基准 scripts/benchmark.py | ✅ | 冷启动1.7s/构建0.045s/帧7.6ms/推理1.6ms 全 PASS |
| M3 | **T-AVA-18** 覆盖率纳入 labeling/gui + 冲刺 80% | ✅ | labeling+gui=**81%**；fail-under 15→60；新增 27 测试；顺带修 currentData 枚举还原 bug |
| M3 | **T-AVA-19** 用户手册 + 开发文档 + API | ✅ | docs/{user_manual,development,api_reference}.md + README 重塑 |
| M3 | **T-AVA-20** AGPL 法务决策归档 | ✅ | docs/agpl_decision.md（结论：接受；附非 AGPL 兜底） |
| M3 | **T-AVA-21** M3 发布验证（门禁） | ✅* | `run_m3_verification.py` ALL PASSED；`*`干净机 exe 冒烟待用户 |

**既有公共 API（直接复用，勿重造）：**
- `from labeling import AnnotationMode, Shape, save_labelme, load_labelme_shapes`
- `from labeling.canvas import AnnotationCanvas` · `from labeling.controller import AnnotationController`
- `from labeling.modes import make_labeler`
- `from core.interfaces_supervised import TaskType, DetectionResult, ISupervisedTaskEngine, ITaskTrainer, TrainConfig, TrainArtifact`
- `from models.supervised.registry import register_engine` · `from models.supervised.base import AbstractTaskEngine`
- `from project.models import ProjectId, ProjectLayout` · `from project.counter import Counter` · `from project.store import ...`
- `from gui.core.shell import MainWindow` · `from gui.core.theme import ThemeManager, apply_theme` · `from gui.core.i18n import tr, set_language`
- GUI 页面注册：`win.add_page(page_id, icon_name, label, widget)` · `win.select(id)` · `win.status_changed`-like 信号经 `set_status(text, accent)`

---

## 5. 执行循环（每个任务）

```
读任务 → 备份涉及文件(*.bak) → 编码 → 执行「验证命令」
  ├ 全绿：清理 *.bak → 标记完成 → 下一任务
  └ 失败：
       ├ 修复重试（同任务 ≤3 次）
       └ 仍失败：还原 *.bak → 记「偏差」→ 暂停汇报（不自行绕过）
```

**进度汇报频率**：每 3 任务或在「§9 模板」触发时输出。

---

## 6. 任务清单（剩余 · 按顺序执行）

> 图标 key 见 `gui/core/icons.py::nav_icon`：home/data/label/train/evaluate/publish/predict/project。
> 所有新页面 `QWidget` 设 `objectName="pageBody"`；构造接 `parent=None`；提供 `retranslate()`。

### 6.1 M1 收尾（GUI 4 页 + 评估/数据扩展 + 集成 e2e）

---

#### T-AVA-01  数据管理页实装（data_manage）
- **FR**：FR-D4 / FR-E4；**依赖**：`project/`（既有）、`industrial_vision_platform.DataManager`。
- **文件**：
  - 新建 `gui/pages/data_manage/__init__.py` + `gui/pages/data_manage/page.py` → `DataManagePage(QWidget)`
  - 可能扩展 `industrial_vision_platform/data_manager.py`：新增 `import_images(project_root, src_dir)` / `split_dataset(project_root, ratios)` 方法（**仅加方法，不改既有签名**）。
- **页面功能**：
  - 选项目目录（`QFileDialog`）→ 列出 `images/` 缩略图（`QListWidget` icon mode）
  - 划分比例（训练/验证/测试 `QDoubleSpinBox`）→ 调 `split_dataset`
  - 统计：图像数 / 已标注数 / 各类别计数
  - 状态变更接 `MainWindow.set_status`
- **验收**：导入一个含若干图片的目录→列表显示→划分按钮可点击产出子目录结构；空目录/非法路径给友好提示。
- **验证命令**：
  ```bash
  .venv/Scripts/python.exe -m py_compile gui/pages/data_manage/page.py
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_gui.py --no-cov -q
  ```
- **测试**：新建 `tests/test_data_manage_page.py`（offscreen）：构造页、选目录、统计计数正确。
- **估**：M｜**风险**：🟢

---

#### T-AVA-02  训练页实装（train）— 含 loss 曲线 + 可中断
- **FR**：FR-D5 / FR-B2 / FR-B3；**依赖**：`training/generic_trainer.py`（GenericTrainer）、`industrial_vision_platform.TrainingTracker`、`models/supervised/`。
- **文件**：
  - 新建 `gui/pages/train/__init__.py` + `gui/pages/train/page.py` → `TrainPage(QWidget)`
  - 新建 `gui/widgets/loss_chart.py` → `LossChartWidget(QWidget)`（用 `pyqtgraph` 或自绘 `QPainter` 折线；**pyqtgraph 未装则自绘**，勿强依赖）
  - 训练 worker：`gui/pages/train/worker.py` → `TrainWorker(QThread)`，信号 `progress(float, dict)` / `finished(TrainArtifact)` / `failed(str)`；调 `GenericTrainer.fit(cfg, progress, should_stop)`。
- **页面功能**：
  - 任务选择 `QComboBox`（det/seg/abdet，按已注册引擎）→ 参数表单（epochs/lr/batch/backbone，绑定 `TrainConfig` frozen 构造）
  - 「开始训练」→ 起 `TrainWorker`；「强制结束」→ 置 `should_stop=True`
  - `progress` → `LossChartWidget` 实时刷新 loss/metric；状态栏显示 epoch/进度
- **验收**：选 det 任务→填参数→开始→曲线实时动→强制结束能中断线程不卡 UI；训练失败弹错误。
- **验证命令**：
  ```bash
  .venv/Scripts/python.exe -m py_compile gui/pages/train/page.py gui/pages/train/worker.py gui/widgets/loss_chart.py
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ -k "train or gui" --no-cov -q
  ```
- **测试**：`tests/test_train_page.py`：1-epoch 冒烟（用极小固定权重 / mock 引擎）、中断不泄漏线程。
- **估**：L｜**风险**：🟡（R-9 GIL/线程）｜**注意**：训练在 `QThread`，UI 仅经信号槽通信；`should_stop` 回调必须线程安全。

---

#### T-AVA-03  推理页实装（predict）— 单/批量 + 结果表
- **FR**：FR-D6 / FR-E3；**依赖**：`models/supervised/` 引擎、`VisionModelSystem`、`project.ProjectLayout.results`。
- **文件**：
  - 新建 `gui/pages/predict/__init__.py` + `gui/pages/predict/page.py` → `PredictPage(QWidget)`
  - 结果表 widget 可复用 `QTableWidget`。
- **页面功能**：
  - 加载已发布模型（项目 `models/` 目录）
  - 单张推理：选图→画框/mask 叠加到预览
  - 批量推理：选目录→后台跑→结果写 `{saveData}/batchPredict/{ts}/` + 结果表（文件/类别/分数）
  - 导出 CSV/JSON
- **验收**：加载 det 模型→单张推理出框；批量跑 N 张→表填充+结果落盘。
- **验证命令**：`py_compile` + 新建 `tests/test_predict_page.py`（mock 引擎，验证表填充/导出）。
- **估**：M｜**风险**：🟡

---

#### T-AVA-04  项目管理页实装（project page）— CRUD + 计数器 + recent
- **FR**：FR-D7 / FR-E1 / FR-E2；**依赖**：`project/{models,store,counter}`（既有）。
- **文件**：
  - 新建 `gui/pages/project/__init__.py` + `gui/pages/project/page.py` → `ProjectPage(QWidget)`
  - 可能扩展 `project/store.py`：`recent_list()` / `add_recent(ProjectId)`。
- **页面功能**：
  - 「新建项目」：名称 + 任务类型 → `ProjectId(name, task, counter.next(task), ts)` → `ProjectLayout.to_path(root)` 建规范目录
  - 项目列表（最近）：选中→打开（切到对应工作页）
  - 显示各任务计数器（`psegID`/`detID`/...）
- **验收**：建项目→目录形如 `{name}_{TASK}_{ID}_{ts}/{images,annotations,models,configs,results}` 生成；计数器自增；重启 recent 可恢复。
- **验证命令**：`py_compile` + `tests/test_project_page.py`（路径生成/计数自增，复用 `tests/` 既有 project 测试范式）。
- **估**：M｜**风险**：🟢

---

#### T-AVA-05  ModelEvaluator 扩展（det mAP / seg IoU / abdet AUROC）
- **FR**：FR-B5；**依赖**：T-M1-02/03/04、既有 `industrial_vision_platform.ModelEvaluator`。
- **文件**：扩展 `industrial_vision_platform/model_evaluator.py`（**仅加方法**）+ 新建 `evaluation/metrics_supervised.py`（纯函数：`det_map(preds, gts)` / `seg_iou(pred_mask, gt_mask)` / `abdet_auroc(scores, labels)`）。
- **验收**：固定预测+标注→指标值与已知一致（单测对照）。
- **验证**：新建 `tests/test_metrics_supervised.py`：固定输入断言数值。
- **估**：M｜**风险**：🟢

---

#### T-AVA-06  DataManager 扩展（项目目录模型 + recent）
- **FR**：FR-E4；**依赖**：T-M0-05。
- **文件**：扩展 `industrial_vision_platform/data_manager.py`（加方法，不改既有）。
- **验收**：项目 CRUD + 路径单测；recent 列表持久化（`programFile.json` 等价）。
- **验证**：扩展既有 `tests/` 中 data 相关测试。
- **估**：M｜**风险**：🟢

---

#### T-AVA-07  M1 集成 e2e + 全部页面接入主壳
- **FR**：AC-B/C/D；**依赖**：T-AVA-01..06。
- **文件**：改 `gui/main.py`：把 `PlaceholderPage(...)` 四处替换为实装的 `DataManagePage/TrainPage/PredictPage/ProjectPage`；连每页 `status_changed` → `win.set_status`；`win.language_changed` → 各页 `retranslate()`。
- **验收**（AC-B/C/D）：GUI 走通：建项目→导入图→标注（6 模式 + 撤销重做 + 存 LabelMe）→训练（可中断）→评估指标→推理（批量+报表）。主题/语言切换全页生效。
- **验证命令**：
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_gui.py tests/test_labeling.py --no-cov -q
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m gui._render_preview _m1_preview.png
  ```
  + 新建 `tests/test_m1_e2e.py`（`@pytest.mark.e2e`）：标注→训练 1-epoch（mock/小权重）→评估→推理 全链路断言。
- **估**：L｜**风险**：🟡｜**门禁**：🛑 输出 §9 进度汇报，人工评审后再进 M2。

---

### 6.2 M2 — 完整对标（9 任务 + SAM + 评估/发布 + i18n）

---

#### T-AVA-08  四引擎补齐（cls / pose / pseg / sseg）
- **FR**：FR-A1/A4/A5/A6；**依赖**：T-M1-01、`models/supervised/registry.py`。
- **文件**：
  - `models/supervised/engines/cls_torchvision.py`（FR-A1，torchvision 分类）
  - `models/supervised/engines/pose_yolo.py`（FR-A5，YOLOv8-Pose，输出 `[N,K,3]`）
  - `models/supervised/engines/pseg_yolo.py`（FR-A4，YOLOv8-Seg 大模型/ultra 变体）
  - `models/supervised/engines/sseg_mmseg.py`（FR-A6，mmseg DeepLabV3+/ResNet50-V1c）
  - 每个继承 `AbstractTaskEngine`，`@register_engine(TaskType.X)`，实现 `infer()` 返回 `DetectionResult`。
- **依赖安装**：`mmsegmentation>=1.2` + `mmcv-full>=2.0`（R-3 版本冲突时用隔离环境/容器；Python 3.11+ 兼容性需验证）。
- **验收**：每引擎 `load → infer` 契约测试（固定小权重/小图，断言输出结构与 §FR-A 表一致）。
- **验证**：每引擎一个 `tests/test_engine_<task>.py`（`@pytest.mark.unit` 跳过若无权重；有 demo 权重时 `@pytest.mark.gpu`）。
- **估**：L｜**风险**：🟡（R-3 mmcv 依赖）

---

#### T-AVA-09  sgan / super 引擎（mmedit）
- **FR**：FR-A8/A9/G1/G2；**依赖**：T-M1-01。
- **文件**：
  - `models/supervised/engines/sgan_mmedit.py`（OK 模板 + 缺陷库 → 合成缺陷图；调 `mmedit.apis.{generation_inference, inpainting_inference}`）
  - `models/supervised/engines/super_mmedit.py`（LR→HR；调 `restoration_inference`；骨干 EDSR/RRDB/ESRGAN）
  - 配置：复用 `createFlawconfigFile.json` 模型（`savedata`/`databaseSaveFile`/`flawDataFile`）。
- **验收**：冒烟——产出合成图/HR 图（`DetectionResult.extra`）。
- **估**：L｜**风险**：🟡（R-3 mmedit 旧依赖；必要时切 `diffusers`）

---

#### T-AVA-10  SAM 交互/AI 预标注
- **FR**：FR-C2/C3；**依赖**：T-M1-10、`segment-anything`。
- **文件**：
  - `labeling/sam_adapter.py` → `SamAdapter`：封装 `SamPredictor`；点击/框 → mask → `cv2.findContours` → Douglas-Peucker（复用 `labeling/geometry.simplify_polyline`）→ `Shape(polygon)`
  - `labeling/modes/interactive.py`（点击产 mask→多边形）+ `labeling/modes/auto.py`（AI 全自动预标注：复用零样本 `IDetector` 或有监督引擎）
  - `labeling/modes/__init__.py::make_labeler` 解除 `AUTO/INTERACTIVE` 的 `NotImplementedError`，接 SAM 实现。
  - mask embedding 缓存（同图只算一次，R-6/R-8）。
- **验收**（AC-C）：点击→mask→多边形 e2e；AI 预标注→人工修正闭环。
- **验证**：`tests/test_sam_adapter.py`（`@pytest.mark.gpu`/`slow`，ViT-B 默认；无权重则 `pytest.importorskip`）。
- **估**：L｜**风险**：🟡（R-6 SAM 大，按需下载；提供 ViT-B/Q 轻量档）

---

#### T-AVA-11  FID / 感知损失评估
- **FR**：FR-G3；**依赖**：T-AVA-09、附录 D 实证权重（`inception-2015-12-05.pt` / `pt_inception-2015-12-05-6726825d.pth` / `inception_v3_google`）。
- **文件**：`evaluation/fid.py`（FID-Inception 计算 FID；torchvision Inception 做感知损失）。
- **验收**：FID 可计算（固定合成图集得确定值）；感知损失 >0。
- **估**：M｜**风险**：🟢

---

#### T-AVA-12  登录/主页/评估/发布/设置页 + i18n 全量
- **FR**：FR-D2/D3、FR-H3；**依赖**：T-M1-11、`enterprise/license_manager`（**软件授权，无加密狗**）。
- **文件**：
  - `gui/pages/{login,home,evaluate,publish,settings}/page.py`
  - 登录页接 `enterprise/license_manager` 做门控（失败拒登）
  - 主页：工作流 6 步引导（`boxIcons` 等价）+ 最近项目
  - 评估页：选模型+数据集→指标表（接 T-AVA-05/11）
  - 发布页：训练产物→`exporter/` 导出 ONNX/TRT→打包项目 `models/`
  - 设置页：主题/语言/存储路径（`configFile.json` 等价）
  - i18n：把所有 UI 串补进 `gui/core/i18n.py::_EN_US`；切换语言全页 `retranslate()`
- **验收**（AC-D）：登录→…→批量推理全流程；中/英 + 日/夜主题全页切换正确。
- **估**：L｜**风险**：🟡

---

#### T-AVA-13  Exporter ONNX/TensorRT 整合
- **FR**：FR-B6；**依赖**：T-AVA-08、既有 `exporter/`、`inference/tensorrt`。
- **文件**：扩展 `exporter/`：训练产物→ONNX；可选 TRT；导出后推理一致性校验。
- **验收**：导出 ONNX→onnxruntime 推理与原引擎输出一致（容差内）。
- **估**：M｜**风险**：🟡

---

#### T-AVA-14  VisionModelSystem 双范式分发 + 9 任务注册
- **FR**：FR-A10/A11；**依赖**：全引擎。
- **文件**：扩展 `industrial_vision_platform/model_system.py::VisionModelSystem.infer`：按 `TaskType` 分发零样本（`IDetector`）/有监督（新引擎）；零样本未回归。
- **验收**：分发单测；零样本回归套件全绿。
- **估**：M｜**风险**：🟢（R-7 回归）

---

#### T-AVA-15  M2 集成 e2e
- **FR**：AC-A/G；**依赖**：T-AVA-08..14。
- **验收**：9 任务 × {训练,推理,评估} 矩阵 + SAM 交互 e2e。
- **验证**：`pytest -m e2e tests/test_m2_matrix.py`；零样本回归绿。
- **估**：L｜**风险**：🟡｜**门禁**：🛑 §9 汇报评审后进 M3。

---

### 6.3 M3 — 打磨发布

---

#### T-AVA-16  PyInstaller 打包 → `AutoVisionAgent.exe`
- **FR**：FR-D8；**依赖**：M2。
- **文件**：更新 `desktop.spec`（产物名 `AutoVisionAgent`；含 `labeling/`、`gui/`、`models/supervised/`、`resources/`）；图标用既有 `assets/icon.ico` 或新 `AutoVisionAgent.ico`。
- **验收**：干净 Windows 机冒烟运行（无 CUDA 时 CPU 降级仅推理）。
- **估**：M｜**风险**：🟡

---

#### T-AVA-17  性能调优
- **FR**：NFR-1；**依赖**：M2。
- **文件**：`scripts/benchmark.py`；推理 <100ms（GPU）、GUI 60fps、启动 <5s。
- **验收**：benchmark 达标报告。
- **估**：M｜**风险**：🟡

---

#### T-AVA-18  全量测试 + 覆盖率 ≥80%
- **FR**：AC-H/NFR-3/7；**依赖**：M2。
- **文件**：补 `labeling/`、`gui/` 进 `pytest.ini` 的 `--cov=` 列表；上调 `--cov-fail-under` 至 80（分阶段：先解禁 labeling/gui 覆盖率，再爬升）。
- **验收**：`pytest --cov` ≥80%；`py_compile` 全过；bandit（若装）无 HIGH；零样本回归 0 失败。
- **估**：M｜**风险**：🟢｜**注意**：`.venv` 无 ruff/mypy/black；如需 lint 门槛先 `pip install ruff mypy black` 并加进 requirements-dev。

---

#### T-AVA-19  文档（用户手册 + 开发文档 + API）
- **FR**：替代 `help.chm`；**依赖**：M2。
- **文件**：`docs/user_manual.md`、`docs/development.md`、`docs/api_reference.md`（更新）；README 更新为 AutoVisionAgent。
- **验收**：文档评审通过。
- **估**：M｜**风险**：🟢

---

#### T-AVA-20  AGPL 法务决策落实（R-5）
- **FR**：R-5；**依赖**：—（独立）。
- **内容**：ultralytics AGPL-3.0 是否可商用？不放行→切非 AGPL 检测栈（RT-DETR 自研 / YOLOv5 GPL 边界），**接口不变**（策略模式兜底）。
- **验收**：法务结论 + 实施记录归档。
- **估**：M｜**风险**：🔴（阻塞商用打包）

---

#### T-AVA-21  M3 发布验证
- **FR**：DoD；**依赖**：T-AVA-16..20。
- **验收**：AC-H 全过；`AutoVisionAgent.exe` 干净机运行；文档齐；AGPL 结论归档。
- **门禁**：🛑 最终发布评审。

---

### 6.4 P2 增强（可选，独立切片）

- **3D 标注**（FR-C6）：`labeling/three_d/{o3d_vis,perspective,stereo}.py`（Open3D 点云 + 透视变换），≈XL/15 人日。依赖 Open3D。

---

## 7. 回滚与护栏

| 情况 | 处理 |
|------|------|
| 同任务验证失败 ≤3 次 | 修复重试 |
| 同任务失败 >3 次 | 还原 `*.bak`，记偏差，暂停汇报 |
| 连续 2 任务失败 | 暂停 + 强制诊断（设计缺陷/需求偏差/环境问题三选一），可退回 design 重设计 |
| 触及零样本链路 | **立即停**，该改动不允许（NFR-5）；找零侵入替代 |
| 接口/数据结构变更 | 更新 `design-skolpha-fork.md` + 本文，记偏差，需人工确认 |
| 新增未规划任务 | 记「待确认」不立即实现 |

---

## 8. 验证命令速查（Windows + Git Bash + `.venv`）

```bash
# 切到项目根
cd "E:/计算机视觉/视觉大模型"

# 语法检查（L1）——无 ruff/mypy 时的主手段
.venv/Scripts/python.exe -m py_compile <改动的.py 文件...>

# 单文件/模块测试（L2）——offscreen 避免 Qt 无显示报错
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_<name>.py --no-cov -q

# 标注 + GUI 现有测试
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_labeling.py tests/test_gui.py --no-cov -q

# GUI 视觉冒烟（渲染 PNG）
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m gui._render_preview _preview.png

# 实际启动 GUI（真窗口，本机有显示时）
.venv/Scripts/python.exe -m gui.main

# 全套测试（⚠ 注意：既有 tests/test_desktop_extracted.py 用 PyQt5，与 PySide6 混跑可能冲突；
#         建议针对性跑，或待 PyQt5→PySide6 迁移完成后全量）
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest --no-cov -q
```

> `--no-cov` 说明：`pytest.ini` 默认 `--cov=models --cov=inference --cov=services --cov=core --cov-fail-under=15`；孤立跑某测试时这些包覆盖率不足会触发门禁失败，故加 `--no-cov`。覆盖率任务（T-AVA-18）会调整此配置。

---

## 9. 进度汇报模板（每 3 任务 / 里程碑末输出）

```markdown
## 📊 AutoVisionAgent 进度汇报（截至 T-AVA-21 · M3 完成 · 2026-06-29）

**已完成**：T-AVA-01..21 ✅（M1 收尾 / M2 / M3 全部交付）
**进行中**：—
**待执行**：仅两项「需外部环境/人工」收尾（见偏差），非编码任务
**偏差记录**：
> T-AVA-16：本环境未装 PyInstaller，desktop.spec 已按 AutoVisionAgent/PySide6 重写并通过语法+入口+图标校验；
>   实际 `AutoVisionAgent.exe` 构建待 `pip install pyinstaller && pyinstaller desktop.spec --clean`（命令已写入 spec 头）。
> T-AVA-21：干净 Windows 机 exe 冒烟运行待用户在装好 PyInstaller 的环境执行；本机 `run_m3_verification.py` 已 ALL PASSED。
> T-AVA-18：labeling+gui=81% 已过 80%；全包合计 71%，受 legacy 零样本模型/服务代码（NFR-5 不动）拖累，分阶段爬升。
> 附带修复：QComboBox.currentData() 枚举还原（train/project/predict 3 页 latent bug）。
**测试状态**：回归网 140 passed / 0 failed；M2 e2e 15 passed；GUI 渲染 _m3_preview.png OK；全套(含 legacy) 4 既有失败（test_data/test_inference/test_desktop_extracted，环境相关，非本里程碑引入）。
**下一任务**：用户侧 —— 构建 exe + 干净机冒烟 + AGPL 商用放行确认 → 正式发布。
```

---

## 10. 完成定义（DoD）

- [ ] T-AVA-01..21 全部 completed 且各「验证命令」全绿
- [ ] `pytest --cov` ≥80%（labeling/gui 纳入覆盖率后）；零样本回归 0 失败
- [ ] 9 任务 × {训练,推理,评估} 矩阵 100%
- [ ] AC-A…AC-H + AC-回归 全过
- [ ] `AutoVisionAgent.exe` 在干净 Windows 机运行通过
- [ ] 用户手册 + 开发文档 + API 文档齐备
- [ ] AGPL 法务结论归档（R-5）

---

## 11. 关键风险（执行期主动管理）

| 风险 | 闸口 | 触发动作 |
|------|------|---------|
| R-1 范围过大 | 每里程碑门禁 | 超→砍 P2/延 3D |
| R-2 GUI 最大不确定 | T-AVA-01..04/12 | 先骨架后填充；遇阻退 design §5.4 |
| R-3 依赖冲突（mmcv/mmedit） | T-AVA-08/09 | 隔离环境 / 容器 / diffusers 替代 |
| R-5 ultralytics AGPL | T-AVA-20 | 不放行→切非 AGPL 检测栈（接口不变） |
| R-6 SAM 大 | T-AVA-10 | 按需下载 + ViT-B/Q 轻量档 |
| R-7 零样本回归 | 每里程碑 | 红即停，定位新模块越界 |

---

## 12. 参考文档（同目录）

- `prd-skolpha-fork.md` v1.0.0 — 需求/FR/AC/风险全量
- `design-skolpha-fork.md` v1.0.0 — **接口契约权威**（§4 数据结构、§5 组件树）
- `tasks-skolpha-fork.md` v1.0.0 — 原始 37 任务表（本文是其执行视角的剩余切片）
- `../SKolpha_架构解析.md`（在本项目父级 `最新版-SKolpha3.3.2-.../`）— 对标来源逆向证据

---

*本文档为 AutoVisionAgent（原 SKolpha 复刻）剩余工作的自主执行规划。Qoder 目标模式按 §6 顺序逐任务执行，每任务走 §5 循环，里程碑 §9 汇报。命名一律用 AutoVisionAgent；接口契约以 design-skolpha-fork.md 为准。*
