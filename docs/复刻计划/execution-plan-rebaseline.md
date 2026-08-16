# AutoVisionAgent 重定基线执行计划（诚实现状 + 剩余真实工作）

> ⚠️ **2026-07-01 已过时（基于旧快照）**：本文基于 `E:\学习项目\视觉大模型`（代码**旧快照**，无 venv）核查所写，对 R0-1/R0-2/R1/R2-1/R2-3/R2-4「缺失 / 桩 / 已删」的判断**整体错误**——真实树 `E:\计算机视觉\视觉大模型`（带 venv，可运行）里这些均已完成：det/seg/abdet 真引擎 + sseg/sgan/super Option A 真化 + 真训练策略 + 真 load→infer 测试 + enterprise/encryption 已恢复 + 3D/视频超分/OCR/SAM-auto+ONNX 全在。2026-07-01 真实树复核：1713 passed / 1 xfailed / 0 failed / 80.77%。**当前真源 → `E:\计算机视觉\视觉大模型\docs\复刻计划\STATUS.md`**。本文 §3「防假绿验证标准」方法论仍可参考；§1/§2 的具体工作项已不适用（R0 已在真实树完成，仅 R0-3 三条边缘造假 loss 回退于 2026-07-01 收尾）。

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-30 |
| 性质 | **当前真源**——2026-06-30 重定基线核查后发现：既有 `tasks-fix-backlog.md`/`qoder-checklist-mfix.md` 的 DoD（9.5/10、80%、1693p）与代码实际状态整体脱节。本文接管「真正剩余的工作」的单一事实源。 |
| 触发原因 | 用户「完善计划」 → 实读代码核查 9 引擎 / 训练 / GUI / 已删模块，发现计划宣称的完成度大面积失真（详见 §1）。 |
| 项目根 | `E:\学习项目\视觉大模型`（**订正**：旧文档误写 `E:\计算机视觉\视觉大模型\`；skolpha.exe 对标来源在 `E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\`） |
| 约束 | NFR-5 零样本链路零侵入不动；本轮**止于规划**，不进编码（沿用既有「Phase 1–3 文档」约定）。 |
| 关联 | 上游意图存档：`prd-fix-backlog.md` / `design-fix-backlog.md`（era-3，已加订正横幅）；进度订正：`qoder-checklist-mfix.md` / `tasks-fix-backlog.md §9` / `tasks-tech-debt.md`。 |

> 🔴 **一句话结论**：fix-backlog 战役当初要消灭的「假绿」，在更高层面重现了——注册表静默吞 `ImportError`、引擎带 `score=1.0`/`arr.copy()`/`INTER_NEAREST` 假回退、训练带 `math.exp` 假 loss、覆盖率把被测模块放进排除列表。所谓 80% / 1693 passed **测的多是桩与回退路径**。本文给出诚实的现状与剩余工作。

---

## 1. 现状诚实盘点（2026-06-30 实读代码 · file:line 证据）

### 1.1 九任务引擎（声称 9，实态 3 缺 / 3 真 / 3 桩）

`models/supervised/engines/`（7 文件 + 注册表）。`engines/__init__.py:31-35` 对每个引擎 `try: __import__ except ImportError: warn+skip`——**缺引擎不报错，静默从注册表消失**。

| TaskType | 引擎文件 | 实态 | 证据 |
|----------|----------|------|------|
| DET | `det_yolo.py` | 🔴 **缺失** | 文件不存在；`__init__.py:34` 静默 skip → `registry.get(DET)` 抛 `UnsupportedTaskError` |
| SEG | `seg_yolo.py` | 🔴 **缺失** | 同上 |
| ABDET | `abdet_anomalib.py` | 🔴 **缺失** | 同上 |
| CLS | `cls_torchvision.py` | 🟢 真 | `torchvision.transforms` happy path（`:36`），`self._model(tensor)`+softmax（`:60`） |
| POSE | `pose_yolo.py` | 🟢 真 | `from ultralytics import YOLO`（`:28`），`self._model(image)`（`:44`），返 keypoints |
| PSEG | `pseg_yolo.py` | 🟢 真 | ultralytics（`:29`），返 masks（`:56`） |
| SSEG | `sseg_mmseg.py` | 🟡 **桩** | mmseg happy path（`:30-32`），ImportError→`_safe_torch_load`（`:43`）+ torch argmax 退化为直通（`:77`） |
| SGAN | `sgan_mmedit.py` | 🟡 **桩** | mmedit happy path（`:75`），ImportError→`synth_np = arr.copy()`（`:84`）+ 硬编码 `score=1.0`（`:88`） |
| SUPER | `super_mmedit.py` | 🟡 **桩** | mmedit happy path（`:59`），ImportError→`cv2.resize INTER_NEAREST` 4×（`:69`）+ `score=1.0`（`:73`） |

> 全项目 `grep segmentation_models_pytorch|cv2.dnn_superres|cv2.seamlessClone` = **0 命中** → fix-backlog 宣称的「Option A 轻量库真化（1-01/02/03）」**从未落地**。三个桩引擎仍走 mmseg/mmedit（环境里这两个库本身就没装 → 落到假回退是 100% 概率）。

### 1.2 训练（声称已接真引擎，实态全假）

- `training/` 只有 `__init__.py` + `generic_trainer.py`；**`training/strategies/` 不存在**（fix-backlog T-FIX-2-06 宣称的 `yolo/anomalib/smp_train.py` 从未创建）。
- `generic_trainer.py` 本身是真的循环驱动（`fit:92` → `strategy.train_epoch:134`，含 warmup/LR/early-stop/checkpoint），但**依赖一个不存在的 strategy**。
- `_SmokeStrategy` 从生产代码移除 ≠ 消灭——改名 `_SimStrategy` 仍在 `gui/pages/train/page.py:318-336`（`loss = math.exp(-epoch*0.05)` `:326`）；`EngineTrainStrategy.train_epoch:406` 也是 `math.exp` 假兜底。
- **6 个引擎无一实现 `train_epoch`** → 训练页任何路径都打到假 loss。垂直切片「选 det → 训练 → 评估 → 发布」**端到端不通**。

### 1.3 GUI 页面（接线层 ~70% 真，依赖引擎处即崩/即假）

| 页面 | 实态 | 证据 |
|------|------|------|
| login | 🟢 真本地鉴权 / 🔴 **非** LicenseManager | PBKDF2 `core.auth.verify_and_migrate`（`:184`）；读写 `configs/users.json`（`:243,256`）；「离线模式」仅查 `license.key` 文件（`:292`）。**未调任何 LicenseManager**（`enterprise/` 整目录已删，见 §1.4）。 |
| home | 🟢 真 | `project.recent.recent_list`（`:143`）、`core.detection_history` 统计（`:154`） |
| eval_ | 🟡 接真服务 / 缺引擎即假 | 调 `evaluate_supervised`（`:363`）+ `registry.get_engine(...).infer()`（`:316,349`）；**缺引擎时回退「GT 当预测 @ score=0.5」**（`:361`）→ 对 det/seg/abdet 出假指标 |
| deploy | 🟢 真 | `SupervisedExporter.export_onnx`（`:172`）/ `export_tensorrt`（`:179`）；`torch.load(weights_only=True)`（`:152`）；`weights_only=False` 全 gui 树 0 命中 ✅ |
| settings | 🟢 真 | `_save` 写 `configs/user_settings.json`（`:232`）；`retranslate()` 真刷新（`:247`） |
| train | 🔴 假 | 见 §1.2，恒假 loss |

### 1.4 已整个删除的模块（计划仍宣称「沿用/留」）

| 模块 | 计划宣称 | 实态 | 影响 |
|------|----------|------|------|
| `enterprise/license_manager.py`（整 `enterprise/` 目录） | FR-H3「授权走 license_manager 软件授权门控」 | 🔴 **整目录不存在** | 登录门控叙述与代码不符（实际是本地 PBKDF2） |
| `core/encryption.py` | FR-H2「留 Fernet 配置加密」 | 🔴 **已删** | 配置实际明文存（`configs/*.json`）；FR-H2 承诺落空 |
| `run_app.py` | CLAUDE.md / 部分文档称入口 | 🔴 不存在 | 实际入口是 `gui/main.py` |

### 1.5 P2 扩展（声称 4/4 完成，实态 0/4）

`qoder-checklist-mfix.md` 标 `4-01..05 [x]`，代码里**全缺**：无 `labeling/three_d/`、无视频超分（`super_*` 仅单图）、无 `ocr_engine.py`（且 `TaskType` 无 OCR 成员）、`sam_adapter.py` 仅交互预测器（无 `SamAutomaticMaskGenerator`、无 `load_onnx`）。

### 1.6 残余技术债（`tasks-tech-debt.md` 10 条，6 解 / 4 残）

详见 `tasks-tech-debt.md`（本次已补状态列）。关键残留：TD-05 `flaw_gen/page.py:220` 仍 `shutil.copy2` 把 OK 图伪装合成图（**诚信级**）；TD-06 docstring 仍指不存在的 `VisionModelSystem`；TD-08 仅窗口按钮 4 个 tooltip；TD-10 `dist/` 仍在源码树。

---

## 2. 真正剩余的工作（按优先级 · 编号 R0..R3）

> 工作量 S≤1d·M1-3·L3-10·XL>10。每项**必须**满足 §3 防假绿验证才算完成。

### 2.1 R0 — MVP 红线救援（不做则平台不可用）

| ID | 工作 | 估 | 依据 |
|----|------|----|------|
| **R0-1** | **补建 det/seg/abdet 三引擎**：`det_yolo.py`（ultralytics YOLOv8 检测，返 `[N,6]` bbox）、`seg_yolo.py`（YOLOv8-Seg 实例 mask）、`abdet_anomalib.py`（anomalib PatchCore/PaDiM，返 `{score, anomaly_map}`）。每个 `@register_engine(TaskType.X)`，实装 `load/infer/release/info`。 | L | §1.1；上游 FR-A2/A3/A7（P0） |
| **R0-2** | **sseg/sgan/super 真化（Option A 真落地）**：sseg→`segmentation_models_pytorch` DeepLabV3+；sgan→`cv2.seamlessClone` copy-paste blend（产 GT mask）；super→`cv2.dnn_superres`（EDSR/ESPCN）。**删除 `score=1.0`/`arr.copy()`/`INTER_NEAREST` 假回退**；库缺失则 `raise`（不返假数据）。 | L | §1.1；上游 FR-A6/A8/A9 |
| **R0-3** | **训练策略真化 + 彻底杀假 loss**：新建 `training/strategies/{yolo,anomalib,smp}_train.py`，各实装 `ITrainStrategy.train_epoch`（真 backward，复用 `generic_trainer.py:92-` 的 AMP/梯度累积范式）；**删除 `_SimStrategy` 与 `EngineTrainStrategy` 的 `math.exp` 兜底**（`train/page.py:326,406`）；引擎不支训练时显式抛 `UnsupportedTaskError`，不造假 loss。 | L | §1.2；上游 FR-B2/B3 |
| **R0-4** | **注册表不再静默吞缺失**：改 `engines/__init__.py:31-35`——核心任务（det/seg/abdet/cls/pose/pseg/sseg）模块缺失时 `raise SupervisedEngineError`（仅可选任务 sgan/super 允许 skip 并显式标注）。**这是假绿的结构性根因之一，必须先修**。 | S | §1.1 |

### 2.2 R1 — 决策项（需用户拍板：restore vs descope）

| ID | 工作 | 估 | 决策点 |
|----|------|----|--------|
| **R1-1** | **Fernet 配置加密（FR-H2）**：要么①恢复 `core/encryption.py` + 在配置**写入侧**接 `encrypt_file`（TD-03）；要么②正式从 PRD 撤销 FR-H2，文档改为「配置明文本地存储」。 | M | 保留承诺 ① / 撤销承诺 ② |
| **R1-2** | **授权门控（FR-H3）**：要么①恢复 `enterprise/license_manager.py`（软件授权，无加密狗）并接到 login；要么②接受现状「本地 PBKDF2 用户鉴权（`configs/users.json`）」，文档改为不再宣称 LicenseManager。 | M | 恢复 ① / 接受现状 ② |
| **R1-3** | **`run_app.py` 入口**：补一个根入口 thin-wrapper（调 `gui/main.py`），或在文档统一改为「入口 = `python -m gui.main`」。 | S | 补 ① / 改文档 ② |

### 2.3 R2 — 完整对标 P2（对标 skolpha 有、AVA 无；4 项）

> 前置：R2-3 OCR 需先扩 `TaskType` 加 `OCR` 成员（接口层小改，零侵入）。R2-1 3D / R2-4 SAM-ONNX 依赖较重，建议 R0/R1 收口后再切片。

| ID | 工作 | 估 | 风险 |
|----|------|----|------|
| **R2-1** | 3D / 立体标注：`labeling/three_d/{o3d_vis,perspective,stereo}.py` + `canvas_3d.py`（Open3D）。 | XL | 🟡 Open3D 重 |
| **R2-2** | 视频超分 + 插帧：`super_video.py`（帧间 super / 插帧）。 | L | 🟡 |
| **R2-3** | OCR：`ocr_engine.py` + `TaskType.OCR`（paddleocr/easyocr/tesseract 选型评审，注意许可）。 | L | 🟡 许可 |
| **R2-4** | SAM 全自动分割 + ONNX 后端：`sam_adapter.py` 加 `SamAutomaticMaskGenerator` + `load_onnx()`。 | L | 🟡 |

### 2.4 R3 — 残余技术债收口

| ID | 工作 | 估 |
|----|------|----|
| **R3-1** | 删 `flaw_gen/page.py:220` `shutil.copy2` 假回退（引擎不可用→报错，不伪装成功）；`tasks-tech-debt.md` TD-05。 | S |
| **R3-2** | 清 docstring 指向不存在的 `VisionModelSystem`（`vision_dispatcher.py:1`、`registry.py:140`）→ 改指 `VisionModelDispatcher`；TD-06。 | S |
| **R3-3** | 离线帮助：各页关键控件 `setToolTip`/`setWhatsThis` + F1 打开本地手册；TD-08。 | M |
| **R3-4** | `dist/` 移出源码树（已有 `.gitignore`，物理移到 `.build/` 或树外）；TD-10。 | S |

---

## 3. 防假绿验证标准（**本次重定基线的元教训**）

> 上一轮 DoD 失效的结构性原因：①注册表吞缺失；②引擎带伪装成功的回退；③训练带假 loss；④覆盖率排除被测模块。本轮每项任务**必须**满足下列对应条款，否则不算完成。

| 条款 | 要求 | 适用 |
|------|------|------|
| **V-注册** | `register_all_engines()` 后 `registry.has(DET/SEG/ABDET/CLS/POSE/PSEG/SSEG)` 全 True；缺失即 `raise`，不 warn-skip | R0-1/R0-4 |
| **V-无假回退** | 引擎代码不得出现 `score=1.0` 硬编码 / `arr.copy()` 当合成结果 / `INTER_NEAREST` 当超分 / argmax 直通当语义分割。库缺失 `raise`，不返假数据 | R0-2 |
| **V-真打库** | 契约测试 `pytest.importorskip("<lib>")`，**装库时**真 `load→infer` 断言 `DetectionResult` 结构与数值范围；有权重时 `@gpu` 真跑。不得用固定种子/mock 撑过 | R0-1/R0-2/R2-* |
| **V-真训练** | 训练测试断言「loss 来自真 backward」（如注入一个 1-step 真策略，断言梯度非 None / loss 随 epoch 真实下降），**代码里 `grep math.exp` 在 `training/`+`gui/pages/train/` = 0** | R0-3 |
| **V-覆盖率不排除被测模块** | `.coveragerc` 的 `omit` 不得包含本轮真化/补建的引擎与训练策略；`--cov-fail-under` 报告须**包含**这些模块的真实行覆盖 | 全部 |
| **V-端到端** | `tests/test_full_e2e_pipeline.py`：导入图→标注→**真训练 1-epoch**→评估→推理→导出，全链路断言（小数据集 + YOLOv8n），不得用桩策略 | R0-1/R0-3 |
| **V-诚实 skip** | 缺权重/无 GPU 时测试**显式 skip 并注明原因**，不得用桩冒充通过 | 全部 |
| **V-文档一致** | 任务完成后，`qoder-checklist-mfix.md` 的 `[x]` 必须由代码事实支撑；覆盖率排除列表不得与「真化 [x]」自相矛盾 | 全部 |

---

## 4. 建议里程碑与门禁

```
M-REBASE-0  红线救援 (R0-4→R0-1→R0-2→R0-3)   🛑退出：det/seg/abdet 真跑 + 三桩真化 + 真训练 + e2e 绿 + V-条款全过
              ⎇ R1 决策项与 M-REBASE-0 并行（用户拍板 restore/descope）
M-REBASE-1  P2 对标 (R2-1..4 切片)            🛑退出：4 项各 e2e + 零样本回归 0 失败
M-REBASE-2  收口 (R3-1..4)                    🛑退出：TD 残留清零；DoD 真实可达
```

**门禁节奏**：每里程碑结束 → 跑 §3 全部 V-条款 + `pytest -m regression`（零样本前置护栏，红即停）→ 评审后进下一里程碑。

**关键路径**：R0-4（修注册表，先止血）→ R0-1（三引擎）→ R0-3（训练）→ V-端到端。R0-2 可与 R0-1 并行。

---

## 5. 追溯（重定基线 → 上游 FR / 旧任务）

| 重定基线 ID | 上游 FR | 原 fix-backlog 任务（失真） | 说明 |
|-------------|---------|----------------------------|------|
| R0-1 det/seg/abdet | FR-A2/A3/A7（P0） | 原属 M1 T-M1-02/03/04（更早宣称✅） | 三引擎从未落盘 |
| R0-2 sseg/sgan/super | FR-A6/A8/A9 | T-FIX-1-01/02/03（标 [x]） | Option A 未落地 |
| R0-3 训练策略 | FR-B2/B3 | T-FIX-2-06/07（标 [x]） | strategies/ 不存在；假 loss 改名存活 |
| R0-4 注册表止血 | —（结构性） | — | 旧计划未识别此根因 |
| R1-1 Fernet | FR-H2 | T-M0-02（宣称✅） | encryption.py 已删 |
| R1-2 授权 | FR-H3 | T-FIX-2-01 login（标 [x]） | enterprise/ 整删；login 实为本地鉴权 |
| R2-1..4 P2 | FR-C6 / 视频 / OCR / SAM-auto | T-FIX-4-01..04（标 [x]） | 4 项全缺 |
| R3-1..4 技术债 | — | TD-05/06/08/10 | 4 项残留 |

✅ 旧 DoD 的失真项全部被本文 R0..R3 接管。

---

## 6. 完成定义（DoD · 诚实版）

- [ ] R0 全部完成：det/seg/abdet 真引擎 + sseg/sgan/super 真化（无假回退）+ 真训练策略（`grep math.exp` 在训练链 = 0）+ e2e 绿。
- [ ] R1 三项各经用户决策并落实（restore 或 descope 二选一，文档与代码一致）。
- [ ] R2 四项 P2 各 e2e 跑通（或经门禁正式延期并登记）。
- [ ] R3 残留技术债清零。
- [ ] §3 全部 V-条款在 `run_m3_verification.py` 中机制化（依赖就绪 + 真功能冒烟 + 无假回退检查）。
- [ ] 覆盖率报告**包含**本轮真化/补建模块，全包 ≥80% 且不靠排除被测代码达成。
- [ ] 零样本回归 0 失败（NFR-5）。
- [ ] `qoder-checklist-mfix.md` 每个 `[x]` 有代码事实支撑，无自相矛盾。

---

*本文为 2026-06-30 重定基线的诚实执行计划，接管既有 fix-backlog 三件套中失真的「完成度」。本轮止于规划；开工从 R0-4（注册表止血）起步，按 §4 里程碑推进。所有状态断言以代码 file:line 为准。*
