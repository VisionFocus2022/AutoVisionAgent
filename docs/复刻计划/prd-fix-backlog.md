# PRD-Lite — 🔴 未完成项补齐战役（AutoVisionAgent 达 DoD）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.1.0（2026-06-30 正文同步重写为 Option A） |
| 创建日期 | 2026-06-29 |
| 阶段 | L3 / Phase 1 — PRD（结构化开发工作流） |
| 目标项目 | `E:\计算机视觉\视觉大模型\`（AutoVisionAgent） |
| 上游依据 | `prd-skolpha-fork.md` v1.0.0 · `design-skolpha-fork.md` v1.0.0 · `tasks-skolpha-fork.md` v1.0.0 · `execution-plan-autovisionagent.md` v1.0.0 |
| 触发原因 | 2026-06-29 完成度审查发现 9 项「计划标 ✅ 但实际未兑现」（见审查清单 §一） |
| 探索门禁结论 | 范围=全 9 项 ｜ 依赖路线=Option A 轻量库（smp/cv2.dnn_superres/copy-paste blend） ｜ AGPL=接受不切栈 ｜ 覆盖口径=全包硬性 80% |
| 关联 | Design → `design-fix-backlog.md`；Tasks → `tasks-fix-backlog.md` |
| 本轮范围 | **止于 Phase 3 规划，不进 Phase 4 编码**（用户明确要求） |

> 🔧 **v1.1.0 决策记录（2026-06-30 · 对标 skolpha.exe 审计后正文同步重写）**：本轮原定后端 Option B（mmcv/mmedit 隔离环境），审计后判定 mmcv 预编译轮子对 Python 3.12 + torch 2.5.1 覆盖薄、隔离环境复杂度过高，**改采 Option A 轻量库**（sseg→`segmentation_models_pytorch` / super→`cv2.dnn_superres` / sgan→copy-paste blend），`ISupervisedTaskEngine` 接口不变。正文 §1.2 G2 / §1.3 / §3.1 FR-FIX-01 / §5.2-5.3 已同步改为 Option A，本节仅保留决策脉络（不再作"覆盖正文矛盾"的偏差器）。**范围扩展**：3D / 视频超分+插帧 / OCR / SAM 全自动+ONNX 由原 Non-Goal 改入 M-FIX-4（见 tasks §5.1）。**技术债另立**：本次审计的 10 条工程债（pseg 同构 / 计数器持久化 / Fernet 落盘 / 裸 except / flaw_gen 假生成 / ivp 平行层 / 死文件 / 离线帮助 / skolpha 旁路 / 产物污染）已建 `tasks-tech-debt.md` v1.0.0，不并入本战役。执行以 `tasks-fix-backlog.md` v1.1.0 为准。

---

> 🚨 **2026-06-30 重定基线订正**：本文（era-3 设计意图存档）的「Option A 真化 sseg/sgan/super」「5 页接业务」「训练接真引擎」等核心条款**经核查未落地或失真**（详见 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §1）：① sseg/sgan/super 仍走 mmseg/mmedit 假回退（全项目 0 处 `segmentation_models_pytorch/cv2.dnn_superres/cv2.seamlessClone`）；② **det/seg/abdet 引擎根本不在磁盘**（`engines/__init__.py` 静默吞缺失）；③ `training/strategies/` 不存在、训练仍 `math.exp` 假 loss；④ `enterprise/`（LicenseManager）+ `core/encryption.py`（Fernet）已整个删除 → **FR-H2「留 Fernet」/ FR-H3「授权走 license_manager」承诺落空**。本文保留为设计意图参考；**执行以 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) 为准**（R0..R3 接管未完成项；R1-1/R1-2 待用户决策恢复 or 撤销承诺）。

---

## 1. 背景与目标

### 1.1 现状（审查实证）

AutoVisionAgent 的 `execution-plan-autovisionagent.md` §4/§9 把 T-AVA-01..21 几乎全标 ✅，但 2026-06-29 完成度审查（静态读码 + `.venv` 依赖探测 + 测试真实性核查）发现 **9 项「代码已落、门面齐全、底层未兑现」**：

| # | 缺口 | 实证（file:line） |
|---|------|------------------|
| 1 | sseg/sgan/super 三引擎依赖缺失，运行时 100% 走假分支 | `mmseg/mmcv/mmedit` 全 MISSING；`sseg_mmseg.py:41-43`、`sgan_mmedit.py:48-50,82-84`、`super_mmedit.py:34-35,65-69` `except ImportError` 回退 torch/拷贝/最近邻 |
| 2 | SAM 从未真跑，无测试 | `segment_anything` MISSING；`sam_adapter.py:29` 延迟 import；`tests/test_sam_adapter.py` 不存在 |
| 3 | 5 个 GUI 页面是空壳 | login(98行)/home(107)/eval_(131)/deploy(122)/settings(144) 核心业务空；login 零 license 调用（grep 0） |
| 4 | 训练页未接真引擎 | `gui/pages/train/page.py:217-230` `_make_trainer` 仍用 `_SmokeStrategy`（`math.exp` 假 loss） |
| 5 | 6/9 引擎零推理测试 | `test_m2_e2e.py:57-74` 只 `hasattr` 反射检查 |
| 6 | 3 个点名测试文件缺失 | `test_metrics_supervised.py`/`test_sam_adapter.py`/`test_train_page.py` 不存在 |
| 7 | PyInstaller exe 从未构建 | `pyinstaller` MISSING；两份重复 spec |
| 8 | AGPL 决策仅文档 | `docs/agpl_decision.md` 有结论但备选切栈未落地 |
| 9 | 覆盖率未达 80% | `pytest.ini` `--cov-fail-under=60`（实测声称 71%） |

### 1.2 目标（Goals）

> **G1** 把 9 项从「代码已落/门面齐全」补到「**真实功能跑通 + 测试真覆盖**」，达成 `tasks-skolpha-fork.md` 的 DoD。
>
> **G2** 全程 **NFR-5 零样本链路零侵入**——装轻量库（smp/cv2.dnn_superres，均纯 Python 或轻 C 扩展）+ SAM 不得搞崩既有 venv；Option A 已无 mmcv 重依赖，主 venv 直装即可，无需隔离环境。
>
> **G3** 消除「假绿测试」——补的测试必须真打库/真跑功能，不用固定随机种子/mock 撑过；`run_m3_verification.py` 要校验真实功能而非仅 `py_compile`。
>
> **G4** 测试覆盖率达 PRD NFR-3 口径（**全包 ≥80%**，用户选定），`pytest.ini` 门禁机制化。

### 1.3 非目标（Non-Goals）

- ❌ Phase 4 编码执行（本轮只产规划文档）。
- ❌ 修改既有零样本链路（`models/{detector,dinov3,clip,few_shot_trainer}`、`services/detection_service`、`api/gateway`、Web/CLI）——NFR-5。
- ❌ 切非 AGPL 检测栈（用户选定「接受 AGPL 不切栈」）。
- ~~❌ 3D 标注（FR-C6，P2，仍延后）~~ → **已撤销**：3D / 视频超分+插帧 / OCR / SAM 全自动+ONNX 改入 M-FIX-4（见 tasks §5.1），不再是非目标。
- ❌ 技术债清理（10 条工程债已另立 `tasks-tech-debt.md` v1.0.0，不并入本战役）。

---

## 2. 角色与使用场景（沿用上游，聚焦补齐影响）

| 角色 | 补齐前痛点 | 补齐后 |
|------|-----------|--------|
| 算法工程师 | 训练页是假冒烟、6 引擎没测过推理 | 真训练可跑、9 引擎各有 load→infer 契约测试 |
| 操作员 | 评估/发布/设置页是空壳 | 评估出指标、发布导 ONNX、设置真持久化 |
| 项目管理员 | 登录无门控 | 登录接 LicenseManager 软件授权 |
| 发布者 | 无 exe、覆盖率 60% | exe 可构建、覆盖率 ≥80% |

---

## 3. 功能需求（FR-FIX）

> 编号 `FR-FIX-{序号}`，与上游 FR 双向追溯（见 §6）。每条对应审查清单一项。

### 3.1 引擎与依赖域

- **FR-FIX-01**【真化】sseg/sgan/super 三引擎走 **Option A 轻量库**真分支：sseg→`segmentation_models_pytorch`(DeepLabV3+)、super→`cv2.dnn_superres`(EDSR/ESPCN/LapSRN)、sgan→copy-paste blend(`cv2.seamlessClone`)。验证真实 `load→infer`，**移除/标注 `except ImportError` 假回退**（sgan 不得把输入图当合成结果返 score=1.0；super 不得退化为最近邻 resize；sseg 不得在 state_dict 时裸崩）。接口 `ISupervisedTaskEngine` 不变。（上游 FR-A6/A8/A9）
- **FR-FIX-02**【真化】SAM 端到端：`segment_anything` 装库后 `SamAdapter.load→set_image→predict_point/box→mask→轮廓→简化→Shape` 真跑通；mask embedding 缓存（`sam_adapter.py:43-47`）真验证。（上游 FR-C2/C3）

### 3.2 GUI 业务接线域

- **FR-FIX-03**【补全】5 个空壳页面接真实业务：
  - **login** → `enterprise/license_manager.LicenseManager.verify_license`（既有，`license_manager.py:535`），失败拒登（FR-H3 软件授权门控）
  - **home** → 接项目数据源刷新统计 + 最近项目列表（非永远显示 0）
  - **eval_** → 调 `evaluation.metrics_supervised.evaluate_supervised`（既有，`metrics_supervised.py:227`）填指标表
  - **deploy** → 调 `exporter.supervised_exporter.SupervisedExporter.export_onnx/export_tensorrt`（既有，`supervised_exporter.py:31/95`）真导出
  - **settings** → 主题/语言/存储路径真持久化（写 `configFile.json` 等价），combo 联动 `ThemeManager`/`i18n.set_language`
- **FR-FIX-04**【补全】训练页接真引擎：`gui/pages/train/page.py` 的 `_make_trainer` 移除 `_SmokeStrategy`，按 `TaskType` 造真实 `ITrainStrategy` 实现（det/seg 封装 ultralytics train API；abdet 封装 anomalib fit），注入 `GenericTrainer`。（上游 FR-B2/B3）

### 3.3 测试真实化域

- **FR-FIX-05**【补测】6 个零推理测试引擎（cls/pose/pseg/sseg/sgan/super + abdet 真拟合路径）各补 `load→infer` 契约测试（固定小权重/小图，断言 `DetectionResult` 结构与 §FR-A 表一致）；`test_m2_e2e.py` 的 `hasattr` 反射检查保留但降级为「注册完整性」测试，不再是引擎验证的唯一手段。
- **FR-FIX-06**【补建】3 个点名缺失测试文件：
  - `tests/test_metrics_supervised.py`（det_map/seg_iou/abdet_auroc/evaluate_supervised 全函数覆盖，固定输入断言数值）
  - `tests/test_sam_adapter.py`（SamAdapter 真测：importorskip segment_anything；装库时 `@gpu` 真跑 mask→多边形；mask 缓存命中）
  - `tests/test_train_page.py`（TrainPage 表单绑定 TrainConfig、TrainWorker 信号、1-epoch 真策略冒烟、中断不泄漏线程）

### 3.4 发布与质量域

- **FR-FIX-07**【构建】PyInstaller exe：装 `pyinstaller`；合并两份重复 spec（删 `autovisionagent.spec`，留 `desktop.spec` 或反之二选一）；构建 `AutoVisionAgent.exe`；干净 Windows 机冒烟（无 CUDA 时 CPU 降级仅推理）。（上游 FR-D8）
- **FR-FIX-08**【归档】AGPL 决策落实：`docs/agpl_decision.md` 结论=接受；在 README/开发文档明示「含 AGPL 组件，闭源商用前需法务确认」；不切栈。（上游 R-5）
- **FR-FIX-09**【门禁】覆盖率全包 ≥80%：`pytest.ini` `--cov-fail-under` 从 60 分阶段爬升至 80；补 legacy 零样本模块测试（**只加测试不改 legacy 源码**，NFR-5）；新增 per-package 覆盖阈值机制防回退。（上游 AC-H/NFR-3）

---

## 4. 验收标准（AC-FIX）

- **AC-FIX-1**：sseg/sgan/super 走 Option A 轻量库跑 `load→infer`，输出真实语义图/合成图/HR 图（非拷贝/非最近邻/非 score=1.0 假返），有契约测试证据。
- **AC-FIX-2**：SAM 点击/框 → mask → 多边形 e2e 真跑（ViT-B 默认），`tests/test_sam_adapter.py` 绿。
- **AC-FIX-3**：login 接 LicenseManager（无 license 拒登）；eval 出指标；deploy 导出 ONNX（数值一致性校验）；settings 持久化；home 显示真实统计——5 页 e2e 可见业务行为。
- **AC-FIX-4**：训练页选 det/seg → 真训练 1-epoch（真 backward，非 `_SmokeStrategy`）→ loss 曲线动 → 可中断不泄漏线程。
- **AC-FIX-5**：9 引擎各有 `load→infer` 契约测试（abdet 含真拟合路径）；`tests/test_metrics_supervised.py` 全函数覆盖。
- **AC-FIX-6**：`AutoVisionAgent.exe` 在干净 Windows 机运行通过（无 CUDA 时 CPU 降级）。
- **AC-FIX-7**：`pytest --cov` 全包 ≥80%（`--cov-fail-under=80` 生效）；零样本回归 0 失败；AGPL 文档归档完成。
- **AC-回归**：既有零样本套件 + 既有 M0-M2 测试全绿，零样本链路行为不变。

---

## 5. 范围、风险与假设

### 5.1 In Scope（本轮规划交付）
FR-FIX-01..09 全部（用户选定全 9 项）。

### 5.2 约束与假设
- **约束**：扩展现有项目不得另起仓库；沿用 `core/` 契约/DI/异常体系；PEP8/frozen dataclass/pytest；零样本零侵入；去 DRM 留 Fernet。
- **关键假设**：
  - 目标机 CUDA 可用（torch 2.5.1+cu121，CUDA True 已确认）。
  - 用户拥有各任务 demo 权重/数据（或用 imagenette/COCO 子集冒烟）。
  - **Option A 轻量库（segmentation_models_pytorch / cv2.dnn_superres）在 Python 3.12 + torch 2.5.1 可直装**——纯 Python 或轻 C 扩展，无 mmcv 预编译轮子问题；DeepLab/EDSR 预训练权重官方可获取或按需下载（R-FIX-6）。

### 5.3 风险登记（Top 5）
| 编号 | 风险 | 等级 | 缓解 |
|------|------|------|------|
| ~~R-FIX-1~~（作废） | ~~mmcv/mmedit 装库搞崩 Python 3.12 venv~~ → Option A 已弃 mmcv/mmedit，本风险消除 | ⚪ 已消除 | 改记 R-FIX-6 |
| R-FIX-6 | Option A 轻量库预训练权重（DeepLabV3+/EDSR/ESPCN）下载源不稳或 license 受限 | 🟡 中 | 权重走官方 release + 哈希校验；不可获取时该引擎测试显式 skip 注明，不伪装通过 |
| R-FIX-2 | 全包 80% 需补大量 legacy 零样本测试 | 🟡 中 | 分阶段爬升（60→70→80）；只加测试不改 legacy 源码；用 `.coveragerc` per-package 阈值 |
| R-FIX-3 | SAM/引擎真测缺 demo 权重 → 测试永远 skip，又是假绿 | 🟡 中 | 权重按需下载脚本 + ViT-B 轻量档；`@gpu` 标记，CI 报告 skip 原因不假装通过 |
| R-FIX-4 | PyInstaller 打包 PySide6 + torch 体积大/隐藏导入漏 | 🟡 中 | spec 用 `collect_all`/`collect_submodules`；分阶段先 onedir 再 onefile |
| R-FIX-5 | 范围大（≈5-8 周）拖成烂尾 | 🟡 中 | 严格里程碑门禁；M-FIX-0 装库验证先行（失败即拉绳升级） |

---

## 6. 追溯（FR-FIX ↔ 上游 FR/AC ↔ 审查项）

| FR-FIX | 上游 FR | 上游 AC | 审查清单项 | Tasks 里程碑 |
|--------|--------|--------|-----------|-------------|
| 01 引擎真化 | A6/A8/A9 | AC-A/G | §一-1 | M-FIX-1 |
| 02 SAM 真化 | C2/C3 | AC-C | §一-2 | M-FIX-1 |
| 03 GUI 接业务 | D2/D5eval/D8/F3/H3 | AC-D | §一-3 | M-FIX-2 |
| 04 训练接真引擎 | B2/B3 | AC-B | §一-4 | M-FIX-2 |
| 05 引擎契约测试 | A 系列 | AC-A | §一-5 | M-FIX-1 |
| 06 缺失测试 | — | AC-C/质量 | §一-6 | M-FIX-2/3 |
| 07 exe 构建 | D8 | DoD | §一-7 | M-FIX-3 |
| 08 AGPL 归档 | R-5 | DoD | §一-8 | M-FIX-3 |
| 09 覆盖率 80% | AC-H/NFR-3 | AC-H | §一-9 | M-FIX-3 |

✅ 9 项审查缺口全部映射到 FR-FIX，无遗漏。

---

*本 PRD 基于 2026-06-29 完成度审查实证 + 探索门禁 4 决策。下一阶段：Design（`design-fix-backlog.md`）。按用户要求，本轮止于 Phase 3 Tasks，不进 Phase 4 编码。*
