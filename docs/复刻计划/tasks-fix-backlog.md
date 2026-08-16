# Tasks + 执行路线图 — 🔴 未完成项补齐战役（落地执行计划）

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.1.0（2026-06-30 正文同步 Option A + DoD/门禁/回退/路线图清残留） |
| 创建日期 | 2026-06-29 |
| 阶段 | L3 / Phase 3 — Tasks（**止于规划，本轮不执行**，用户明确要求） |
| 上游 | `prd-fix-backlog.md` v1.1.0 · `design-fix-backlog.md` v1.1.0（均已正文同步 Option A） |
| 目标项目 | `E:\计算机视觉\视觉大模型\`（AutoVisionAgent，非 git） |
| 整体档位 | 🔴 L3（子任务各自标 L1/L2/L3） |
| 探索门禁结论 | 全 9 项 ｜ Option A 轻量库（smp/cv2.dnn_superres/copy-paste blend） ｜ 接受 AGPL 不切栈 ｜ 全包硬性 80% |

> **工作量**：S≤1人日 · M 1–3 · L 3–10 · XL>10。**风险**：🔴高/🟡中/🟢低。**子档位**：每任务标注 L1/L2/L3。
> **验证命令**（项目实证栈）：Python 3.12.9 + torch2.5.1+cu121（CUDA✓）；`.venv` 装 ultralytics/anomalib/PySide6/cryptography；未装 mmcv/mmedit/segment_anything/onnx/pyinstaller/pytestqt。
> **回滚**：非 git 项目 → 每任务开工前备份涉及文件为 `*.bak`，失败手动还原（见 §7）。

> 🔧 **v1.1.0 修订（2026-06-30 · 对标 skolpha.exe 审计）**：
> 1. **后端策略改向**：原 Option B（`.venv-mm` 装 mmcv-full/mmedit/mmsegmentation + diffusers 兜底）→ **Option A 轻量现代库**：sseg→`segmentation_models_pytorch`(DeepLabV3+，Apache-2.0)；super→`cv2.dnn_superres`(OpenCV 自带 EDSR/ESPCN/FSRCNN/LapSRN)；sgan→copy-paste blend(`cv2.seamlessClone` 从缺陷库合成，免 GAN)。理由：mmedit 已归档、mmcv Windows 编译地狱、AVA 为桌面应用 +「原创实现」不要求框架逐字对标。**R-FIX-1（mmcv 装库风险）随之作废**，新风险 R-FIX-6（轻量库权重来源）。
> 2. **P2 全部纳入范围**：3D 标注 / 视频超分+插帧 / OCR / SAM 全自动+ONNX（用户 2026-06-30 确认）→ 新增 **§5.1 M-FIX-4**（撤销 prd §1.3「3D 延后」Non-Goal）。
> 3. **净增任务**：T-FIX-2-04 加 `weights_only=False` 安全子要求；T-FIX-2-12 label 页 `_ai_prelabel` 三重断链修复；T-FIX-3-08 自审文档去失真。
> 4. **上游同步**：`design-fix-backlog.md` §3.1/§3.3/§4/§6/§9、`prd-fix-backlog.md` §1.2/§1.3/§3.1/§5.2-5.3 已于 2026-06-30 **正文同步重写为 Option A**（非仅偏差注）；本文 DoD/门禁/回退矩阵/路线图同步清残留。
> 5. **技术债另立**：本次审计的 10 条工程债按 prd §1.3「技术债另立任务」**不并入本战役**，已另建 `tasks-tech-debt.md` v1.0.0（2026-06-30 出）。

---

> 🔧 **2026-06-30 重定基线订正声明（最高优先级 · 覆盖本战役结论）**：本战役的核心前提——**Option A 轻量库真化 sseg/sgan/super（1-01/02/03）**——经实读代码核查**从未落地**：全项目 0 处 `import segmentation_models_pytorch / cv2.dnn_superres / cv2.seamlessClone`，三引擎仍走 mmseg/mmedit 的 `except ImportError` 假回退（`sseg_mmseg.py:30-32,77` / `sgan_mmedit.py:75,84,88` / `super_mmedit.py:59,69,73`，含 `score=1.0`/`arr.copy()`/`INTER_NEAREST`）。更严重：**det/seg/abdet 三个 P0 旗舰引擎根本不在磁盘**（`engines/__init__.py:31-35` 静默吞缺失）；**训练策略 `training/strategies/` 不存在**，`_SmokeStrategy` 改名 `_SimStrategy` 仍用 `math.exp` 造假 loss（`train/page.py:326,406`）；**`enterprise/`（LicenseManager）+ `core/encryption.py`（Fernet）已整个删除**却仍被宣称「沿用」。因此 §9 DoD 的「9.5/10 / 80% / 1693p / 9 引擎真跑通」**大面积失真**——部分靠把未真化引擎排除出覆盖率 + 测假回退路径达成。**本战役未完成项已由 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) 接管（R0..R3）；§9 DoD 已重写为诚实版（见下）。本文任务详情（文件签名/验证命令）仍可参考，但任何「完成状态」以 rebaseline §1 + 订正后的 `qoder-checklist-mfix.md` 为准。**

---

## 1. 任务总览（按里程碑）

| 里程碑 | 任务数 | 工作量 | 退出标准（AC-FIX） | 子档位分布 |
|--------|--------|--------|------------------|-----------|
| **M-FIX-0 依赖与基线** | 5 | ~3 人日 | 轻量库(smp/cv2.dnn_superres)装验证 + 回归护栏 + 覆盖率基线 | L2×1 L1×3 验证×1 |
| **M-FIX-1 引擎与 SAM 真化** | 8 | ~13 人日 | 9 引擎 load→infer + SAM e2e + 6 引擎契约测试 | L2×6 L1×2 |
| **M-FIX-2 GUI 与训练接线** | 12 | ~22 人日 | 5 页接业务 + label AI 接线 + 训练真引擎 + 真 e2e | L3×1 L2×9 L1×1 验证×1 |
| **M-FIX-3 质量与发布** | 8 | ~13 人日 | 覆盖率 80% + exe + AGPL + 文档去失真 + 强化验证 | L2×5 L1×2 验证×1 |
| **M-FIX-4 P2 扩展** | 5 | +切片 | 3D + 视频超分 + OCR + SAM全自动+ONNX | L3×1 L2×3 验证×1 |
| **合计（M-FIX-0..3）** | **33** | **~51 人日** | 9 项 🔴 全部补齐达 DoD | — |
| **含 M-FIX-4** | **38** | **+P2 切片** | 对标 skolpha 完整度 | — |

> ⚠ v1.1.0：R-FIX-1（mmcv 装库）**作废**（改 Option A 轻量库）；新风险 R-FIX-6（轻量库权重来源）。M-FIX-0 不再是 mmcv 闸口，改为轻量库可用性验证（风险显著降低）。

---

## 2. M-FIX-0 — 依赖与基线（闸口里程碑）

> 🎯 **本里程碑目的**：先把缺失依赖装上并验证不破坏零样本（NFR-5），为后续真化扫清环境。**失败则整个战役方案需调整**。

| ID | 任务 | 子档位 | 依赖 | 验证（HOW + 命令） | 估 | 风险 |
|----|------|--------|------|-------------------|----|----|
| T-FIX-0-01 | **主 venv 装轻量后端库**（Option A，撤销 .venv-mm 隔离）：`pip install segmentation_models_pytorch`（sseg，Apache-2.0）；验证 `cv2.dnn_superres` 可用（OpenCV 自带，super）；sgan 用 `cv2.seamlessClone`（OpenCV 自带，免装）。**不装 mmcv/mmedit/mmsegmentation** | 🟢L1 | — | `.venv/Scripts/python.exe -c "import segmentation_models_pytorch,cv2; cv2.dnn_superres.DnnSuperResImpl_create(); print('OK')"` 0 错；`requirements.txt` 加 `segmentation_models_pytorch>=0.3` | S | 🟢 |
| T-FIX-0-02 | **主 venv 装低风险依赖**：`onnx`、`onnxruntime`、`pyinstaller`（写 `requirements-dev.txt`）；SAM 优先复用 `ultralytics` 自带（已 AGPL 接受），`segment-anything` 作可选回退 | 🟢L1 | — | `.venv/Scripts/python.exe -c "import onnx,onnxruntime,PyInstaller"` 0 错；主 venv 零样本回归不变 | S | 🟢 |
| T-FIX-0-03 | **零样本回归护栏基线快照**：确认 `pytest -m regression` 当前全绿，记录通过数作为基线（后续每里程碑对照） | 🟢L1 | — | `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -m regression --no-cov -q` 全绿；记基线数到 `docs/regression-baseline.txt` | S | 🟢 |
| T-FIX-0-04 | **覆盖率基线快照**：实跑 `pytest --cov` 记录当前全包 %（核实文档自报 71%），作为爬升至 80% 的起点；记录各包 %（models/inference/services/core/labeling/gui） | 🟢L1 | — | `.venv/Scripts/python.exe -m pytest --cov --cov-report=term-missing -q` 生成报告；记各包 % 到 `docs/coverage-baseline.md` | S | 🟢 |
| T-FIX-0-05 | **M-FIX-0 集成验证**：主 venv 轻量库可 import + 零样本未回归 + 依赖清单落盘 | 🟡L2 | 0-01..04 | 主 venv `import segmentation_models_pytorch,cv2.dnn_superres` OK；`pytest -m regression` 全绿；`requirements.txt`/`requirements-dev.txt` 更新 | S | 🟢 |

> 🛑 **门禁**：T-FIX-0-01 若失败（smp/cv2.dnn_superres 装不上，概率低）→ **暂停汇报**：核查 Python/torch 版本兼容，回写 `prd-fix-backlog.md` §5.2 假设，再继续。Option A **无 mmcv/diffusers 兜底分支**（轻量库失败=环境异常，非方案缺陷）。

---

## 3. M-FIX-1 — 引擎与 SAM 真化（FR-FIX-01/02/05）

> 🎯 让 9 引擎与 SAM 真正跑起来，配真实契约测试（消除假绿）。

| ID | 任务 | 子档位 | 依赖 | 验证（HOW + 命令） | 估 | 风险 |
|----|------|--------|------|-------------------|----|----|
| T-FIX-1-01 | **sseg 真化（Option A · smp）**：弃 mmseg/mmengine，改 `segmentation_models_pytorch.create_model('DeepLabV3Plus','resnet50',...)"`；新建 `models/supervised/engines/sseg_smp.py`（或重写 `sseg_mmseg.py`→更名）。`infer` 走 smp `model(img_tensor).argmax(1)` 出 [H,W] 语义图；**移除 state_dict 裸崩路径**（`sseg_mmseg.py:65-77`）；诚实回退（未装 smp → raise 或 `fallback=True`，不返假数据） | 🟡L2 | 0-01 | `.venv/Scripts/python.exe -m py_compile models/supervised/engines/sseg_smp.py`；真 `load→infer` 出 H×W 语义图（smp 权重） | M | 🟢 |
| T-FIX-1-02 | **sgan 真化（Option A · copy-paste blend）**：弃 mmedit GAN，改从 `flaw_database` 取真实缺陷 → `cv2.seamlessClone`（Poisson 融合）合成到 OK 模板，产 ground truth mask；新建 `models/supervised/engines/sgan_blend.py`（或重写）。**移除 `arr.copy()` 假回退**（`sgan_mmedit.py:82-84`）；诚实回退（无缺陷库 → raise 或 `fallback=True`） | 🟡L2 | 0-01 | `load→infer`：输入 OK 图 + 缺陷库 → 真实合成图 + mask（`DetectionResult.extra`），非输入拷贝；`score` 不再恒 1.0 | M | 🟢 |
| T-FIX-1-03 | **super 真化（Option A · cv2.dnn_superres）**：弃 mmedit SR，改 `cv2.dnn_superres.DnnSuperResImpl_create()` + 骨干 EDSR/ESPCN/FSRCNN/LapSRN（OpenCV 自带）；新建 `models/supervised/engines/super_cv2.py`（或重写）；权重下载脚本（R-FIX-6）。**移除 `cv2.resize INTER_NEAREST` 假回退**（`super_mmedit.py:65-69`）；**视频超分/插帧移至 M-FIX-4**（本任务仅单图） | 🟡L2 | 0-01 | `load→infer`：LR → 真 HR 图（PSNR 可计算，非最近邻放大） | M | 🟢 |
| T-FIX-1-04 | **SAM 真化**：`labeling/sam_adapter.py` 装库后真跑 `load→set_image→predict_point/box→mask→cv2.findContours→simplify_polyline→Shape`；验证 mask embedding 缓存（`sam_adapter.py:43-47`）同图只算一次 | 🟡L2 | 0-02 | 主 venv 真 ViT-B 权重跑通点击→mask→多边形；缓存命中第二次不重算 | M | 🟡(R-FIX-3) |
| T-FIX-1-05 | **`tests/test_sam_adapter.py` 补建**：`pytest.importorskip("segment_anything")`；装库时 `@gpu` 真测 mask→多边形结构 + 缓存命中；未装显式 skip 注明 | 🟡L2 | 1-04 | `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/test_sam_adapter.py --no-cov -q`（装库时绿，未装 skip） | M | 🟢 |
| T-FIX-1-06 | **6 引擎契约测试**：新建 `tests/test_engine_{cls,pose,pseg,sseg,sgan,super}.py` + 强化 `test_engine_abdet`（真拟合路径）；每引擎 `pytest.importorskip` 对应库，有 demo 权重 `@gpu` 真 `load→infer` 断言 `DetectionResult` 结构，无权重显式 skip 注明 | 🟡L2 | 1-01..03 | 各 `pytest tests/test_engine_*.py --no-cov -q`；6 引擎各有真 infer 测试（非 hasattr） | L | 🟡(R-FIX-3) |
| T-FIX-1-07 | **`test_m2_e2e.py` hasattr 降级**：把 `test_m2_e2e.py:57-74` 的反射检查重命名为 `test_all_engines_registered`（注册完整性，合法），**不再是引擎功能验证唯一手段**；引擎功能由 test_engine_*.py 承担 | 🟢L1 | 1-06 | `pytest tests/test_m2_e2e.py --no-cov -q` 绿；命名清晰区分「注册」vs「功能」 | S | 🟢 |
| T-FIX-1-08 | **M-FIX-1 集成验证**：9 引擎在主 venv `load→infer` + SAM e2e + 契约测试全绿 | 🟡L2 | 1-01..07 | 9 引擎 infer 各产出正确结构；SAM 点击→多边形 e2e；零样本回归全绿 | M | 🟡 |

---

## 4. M-FIX-2 — GUI 与训练接线（FR-FIX-03/04/06）

> 🎯 5 空壳页面接真实业务 + 训练接真引擎 + 真 e2e 链路。

| ID | 任务 | 子档位 | 依赖 | 验证（HOW + 命令） | 估 | 风险 |
|----|------|--------|------|-------------------|----|----|
| T-FIX-2-01 | **login 门控**：`gui/pages/login/page.py` 的 `_do_login` 接 `enterprise/license_manager.LicenseManager.verify_license`（`:535`）；成功 emit `login_success(LicenseInfo)`，失败/异常留 login + 友好提示；LicenseManager 经 DI 或构造注入（不硬编码密钥） | 🟡L2 | 0-05 | `py_compile`；`tests/test_login_page.py`（新建）：有效 license→success，无效→拒登留页 | M | 🟡(鉴权) |
| T-FIX-2-02 | **home 数据源**：`gui/pages/home/page.py` 的 `update_stats` 接 `DataManager` 项目计数 + `project.recent.recent_list()` 填最近项目 QList；打开项目后刷新统计 | 🟢L1 | 0-05 | `py_compile`；构造 home + 注入 mock DataManager → 统计非 0、最近列表有项 | S | 🟢 |
| T-FIX-2-03 | **eval_ 接线**：`gui/pages/eval_/page.py` 的 `_run_eval` 调 `evaluation.metrics_supervised.evaluate_supervised`（`:227`）填 QTableWidget；选模型+数据集→真指标 | 🟡L2 | 0-05 | `py_compile`；`tests/test_eval_page.py`（新建）：固定 preds+gts → 表填正确指标值 | M | 🟢 |
| T-FIX-2-04 | **deploy 接线 + 安全加载**：`gui/pages/deploy/page.py` 的 `_do_export` 调 `SupervisedExporter.export_onnx`（`:31`）真导出 + `torch.allclose` 一致性。**安全子要求（审计 P0#3）**：移除 `:141` 的 `torch.load(weights_only=False)`——安全优先 `weights_only=True`，catch `(TypeError,UnsupportedOperation,RuntimeError)` 后因「用户自选本地 .pt、导出必需 Module」受控回退 + `# noqa: S301` + 威胁模型注释；**更优**：导出走引擎注册表 `load()`（已安全加载+构造 arch）免裸 torch.load | 🟡L2 | 0-02 | `py_compile`；`tests/test_deploy_page.py`（新建）：安全 ckpt 走 `weights_only=True`、含自定义对象 ckpt 受控回退仍可导出 | M | 🟡 |
| T-FIX-2-05 | **settings 持久化 + retranslate 全 5 页**：`settings/page.py` 的 `_save` 写 `configFile.json`（主题/语言/路径）+ combo 联动 `ThemeManager`/`i18n.set_language`；**login/home/eval_/deploy/settings 的 `retranslate()` 从 `pass` 改为真刷新** | 🟡L2 | 2-01..04 | `py_compile`；`tests/test_i18n_retranslate.py`（新建）：切 EN 后 5 页文案刷新 | M | 🟢 |
| T-FIX-2-06 | **训练策略实现**：新建 `training/strategies/{yolo,anomalib,smp}_train.py`，各实现 `ITrainStrategy.train_epoch`（真 backward，复用 `training/trainer.py:290-355` AMP/梯度累积范式）；yolo 封装 ultralytics train、anomalib 封装 PatchCore.fit、smp 封装 segmentation_models_pytorch train（sseg）；sgan/super 无训练（前者运行时 blend，后者纯推理） | 🔴L3 | 1-01..03 | 主 venv 各策略 1-epoch 真训练 loss 下降（非 math.exp 假） | L | 🟡 |
| T-FIX-2-07 | **train page 换真策略**：`gui/pages/train/page.py` 的 `_make_trainer` 按 TaskType 造对应 `ITrainStrategy` 注入 `GenericTrainer`；**`_SmokeStrategy` 移入 `tests/` 仅作测试夹具**，从生产 page.py 删除 | 🟡L2 | 2-06 | `py_compile`；选 det/seg → 真 1-epoch 训练 → loss 曲线动 | M | 🟡 |
| T-FIX-2-08 | **`tests/test_train_page.py` 补建**：表单绑定 TrainConfig、TrainWorker 信号、1-epoch 真策略冒烟、中断不泄漏线程 | 🟡L2 | 2-07 | `pytest tests/test_train_page.py --no-cov -q` 绿 | M | 🟢 |
| T-FIX-2-09 | **`tests/test_metrics_supervised.py` 补建**：`det_map`/`seg_iou`/`abdet_auroc`/`evaluate_supervised` 全函数覆盖，固定输入断言数值 | 🟡L2 | 2-03 | `pytest tests/test_metrics_supervised.py --no-cov -q` 绿 | M | 🟢 |
| T-FIX-2-10 | **真 e2e 链路**：`tests/test_full_e2e_pipeline.py`——导入图→标注(6模式+撤销)→真训练 1-epoch→评估→推理→导出 串行断言（小数据集 + YOLOv8n），替代断片冒烟 | 🟡L2 | 2-07/09 | `pytest tests/test_full_e2e_pipeline.py -m e2e --no-cov -q` 绿（真链路非断片） | L | 🟡 |
| T-FIX-2-11 | **M-FIX-2 集成验证**：5 页业务可见 + 训练真引擎 + 真 e2e + 主题/语言全页切换 | 🟡L2 | 2-01..10,12 | `pytest tests/test_gui.py tests/test_m1_e2e.py tests/test_full_e2e_pipeline.py --no-cov -q`；GUI 渲染预览各页有业务内容 | L | 🟡 |
| T-FIX-2-12 | **label 页 AI 预标注接线**（修三重断链 · 审计 P0#2）：`gui/pages/label/page.py:_ai_prelabel`（`:370-413`）——① DET 引擎先 `engine.load(weights)` 再 infer（接设置页模型加载 UX，权重持久化到 registry）；② `AutoLabeler(label=..., detector=<包 engine.infer 成 DetectorFn>)` 正确构造（非无参）；③ 调 `run()` + 循环 `commit()`（**非不存在的 `label_image()`**）；④ `canvas.add_shape(shape)` 对齐真实签名（动手前先读 `labeling/canvas.py`）；⑤ INTERACTIVE 进 `_MODES` + 快捷键 I + 工具栏按钮；⑥ `labeling/__init__.__all__` 导出 `SamAdapter`/`InteractiveLabeler`/`AutoLabeler`；⑦ SAM 复用 `ultralytics` 自带（免装 segment-anything，AGPL 已接受） | 🟡L2 | 0-01 | `py_compile`；`tests/test_label_page_ai.py`（新建）：加载 det 权重→按 W 出矩形框写入 shapes；按 I 点击出 SAM 多边形；无权重显式提示非静默回退 | L | 🟡 |

---

## 5. M-FIX-3 — 质量与发布（FR-FIX-07/08/09）

> 🎯 覆盖率爬 80% + exe 构建 + AGPL 归档 + 强化验证。

| ID | 任务 | 子档位 | 依赖 | 验证（HOW + 命令） | 估 | 风险 |
|----|------|--------|------|-------------------|----|----|
| T-FIX-3-01 | **合并两份 spec**：删 `autovisionagent.spec`（或 `desktop.spec` 二选一），留产物名 `AutoVisionAgent`；加 `collect_all('PySide6')` + torch 隐藏导入；排除 PyQt5 | 🟢L1 | 2-11 | spec 语法 + 入口 + 图标校验 | S | 🟢 |
| T-FIX-3-02 | **构建 exe**：`.venv/Scripts/python.exe -m PyInstaller desktop.spec --clean`（先 onedir 后 onefile）；产出 `AutoVisionAgent.exe` | 🟡L2 | 3-01 | exe 构建成功；本机启动冒烟 | M | 🟡(R-FIX-4) |

> **偏差 T-FIX-3-02**（2026-06-30 Session 4）：初版 exe 启动即崩——`desktop.spec` excludes 错误排除了 `unittest`，导致 torch 2.5+ 的 `torch._dispatch.python` 运行时导入 `unittest.mock` 失败（`ModuleNotFoundError: No module named 'unittest'`）。修复：从 excludes 移除 `unittest`（torch 运行时依赖），仅保留 `pytest` 排除。重新构建后 exe 本机启动冒烟✅（进程存活 10s+，窗口标题 "AutoVisionAgent"，stderr 零错误）。
| T-FIX-3-03 | **干净机冒烟**：在无 CUDA 干净 Windows 机运行 exe（CPU 降级仅推理）；记录启动<5s | 🟡L2 | 3-02 | 干净机运行通过；无 CUDA 降级正常 | M | 🟡 |
| T-FIX-3-04 | **legacy 补测拉全包 80%**：对 `models/`(零样本 detector/helpers)、`services/`、`inference/` 纯函数/分支补测试（**只加测试不改 legacy 源码** NFR-5）；`pytest.ini` `--cov-fail-under` 60→70→80 分阶段上调；删 `setup.cfg` 冲突段；加 per-package 阈值 | 🟡L2 | 0-04 | `pytest --cov` 全包 ≥80%；`--cov-fail-under=80` 生效；各新包 ≥80% | L | 🟡(R-FIX-2) |
| T-FIX-3-05 | **`run_m3_verification.py` 强化**：从「py_compile+pytest+PNG+注册名」升级含「依赖就绪检查 + 关键功能冒烟（≥1 引擎真 infer + SAM 真 mask + ≥1 页真业务）」 | 🟡L2 | 1-08/2-11 | `python run_m3_verification.py` ALL PASSED 且含真实功能冒烟（非仅编译） | M | 🟢 |
| T-FIX-3-06 | **AGPL 归档**：README/`docs/development.md` 明示「含 ultralytics AGPL-3.0 组件，闭源商用前需法务确认」；`docs/agpl_decision.md` 结论=接受 | 🟢L1 | — | 文档含 AGPL 声明；grep 命中 | S | 🟢 |
| T-FIX-3-08 | **自审文档去失真**（审计 P0#4）：重写 `CLAUDE.md` 为当前 AVA 事实（PySide6 / Python 3.12 / torch 2.5.1+cu121 / 入口 `run_app.py` / SKolpha 复刻去 DRM 留 Fernet / 9 引擎 / AGPL 决策 / 验证用 `py_compile`+`pytest --no-cov`）；归档 `代码审查报告.md`/`任务清单.md`/`微小缺陷检测改进计划.md`（2026-03 DINOv3 时代）到 `docs/archive/` 或加 `⚠️已过时` 横幅；`任务清单.md` 换本次 backlog；核对 `ARCHITECTURE.md`/`README.md`(6-29 近期)；指向 `docs/复刻计划/` 为唯一真源 | 🟡L2 | — | `grep -rn "DINOv3\|PyQt5\|零样本" CLAUDE.md` 0 命中（归档文档除外）；CLAUDE.md 与代码一致 | S | 🟢 |
| T-FIX-3-07 | **M-FIX-3 发布验证（DoD 门禁）**：AC-FIX-1..7 + AC-回归 全过；exe 可分发；覆盖率 ≥80% | 🟡L2 | 3-01..06,08 | DoD §8 全勾；零样本回归 0 失败 | M | 🟡 |

---

### 5.1 M-FIX-4 — P2 扩展（对标 skolpha 完整度，全部确认在范围）

> 🎯 补齐 skolpha 有、AVA 无的能力。用户 2026-06-30 确认 4 项全部在范围（撤销 prd-fix-backlog §1.3「3D 延后」Non-Goal）。可在 M-FIX-0..3 达 DoD 后独立切片推进。

| ID | 任务 | 子档位 | 依赖 | 验证（HOW + 命令） | 估 | 风险 |
|----|------|--------|------|-------------------|----|----|
| T-FIX-4-01 | **3D / 立体视觉标注**：新建 `labeling/three_d/{o3d_vis,perspective,stereo}.py`（Open3D 点云可视化 + 透视变换 `coord_trans_pers_trans` + 立体 `photo_stereo`，对标 skolpha `app_3d`/`widgets.o3d_vis`/`cut_img_tools`）；`labeling/canvas_3d.py` 3D 画布；GUI 加 3D 标注入口 | 🔴L3 | — | `py_compile`；Open3D 点云加载+标注 e2e（`@pytest.mark.slow` + `pytest.importorskip("open3d")`） | XL | 🟡(R-FIX-6 Open3D) |
| T-FIX-4-02 | **视频超分 + 视频插帧**：扩 `super_cv2.py` 或新建 `super_video.py`，对标 skolpha `restoration_video_inference`/`video_interpolation_inference`；单图 super（T-FIX-1-03）+ 视频帧间 super/插帧 | 🟡L2 | 1-03 | 视频 `load→infer`：出 HR 视频 / 插帧后视频（PSNR + 帧数断言） | L | 🟡 |
| T-FIX-4-03 | **OCR 文本识别**：新建 `models/supervised/engines/ocr_engine.py`（新增 `TaskType.OCR` 或独立工具，对标 skolpha 图标 `ocr`/`socr`）；库选型评审——轻量优先（`paddleocr`/`easyocr`/`tesseract` 三选一，注意各自许可） | 🟡L2 | — | `load→infer`：图像→文本框 + 文字（`DetectionResult.boxes` + `.labels`） | L | 🟡(OCR 库选型+许可) |
| T-FIX-4-04 | **SAM 全自动分割 + ONNX 后端**：扩 `labeling/sam_adapter.py` 加 `SamAutomaticMaskGenerator` 路径（一键全图零样本分割，对标 skolpha `automatic_mask_generator`）；加 `load_onnx()` 分支（`onnxruntime`，无 GPU 工位部署，对标 skolpha `utils.onnx`） | 🟡L2 | 1-04 | 全自动分割 e2e（一键出全部 mask→多边形）；ONNX 后端推理与原模型容差一致 | L | 🟡 |
| T-FIX-4-05 | **M-FIX-4 集成验证**：4 项 P2 能力各 e2e + 零样本回归不变 | 🟡L2 | 4-01..04 | 各能力 demo 跑通；`pytest -m regression --no-cov -q` 0 失败 | M | 🟡 |

> 🛑 **门禁**：M-FIX-4 为 P2 增量，独立切片；Open3D / OCR 库选型经评审后定（R-FIX-6 权重/依赖来源）。

---

## 6. 依赖图（关键路径）

```
M-FIX-0: 0-01 ─┐ 0-02 ─┐
         0-03  ├─→ 0-05(M0验证) ─┐   ✅ v1.1.0：0-01 现为轻量库(smp/cv2.dnn_superres)装验证，风险低；R-FIX-1(mmcv) 作废
         0-04 ─┘                 │
                                  ▼
M-FIX-1: 1-01 ─┐ 1-02 ─┐ 1-03 ─┐
         1-04 ─┤(依赖0-02)      ├─→ 1-06(6引擎测试) ─→ 1-07(hasattr降级)
         1-05 ◂ 1-04            │
                                  ├─→ 1-08(M1验证)
                                  ▼
M-FIX-2: 2-01 ─┐ 2-02 ─┐ 2-03 ─┐ 2-04 ─┐
         2-05 ◂ 2-01..04        │        ├─→ 2-11(M2验证)
         2-06(策略,依赖1-01..03)─→ 2-07 ─→ 2-08
                                  2-03 ─→ 2-09
                                  2-07/09 → 2-10(真e2e)
                                  ▼
M-FIX-3: 3-01 ─→ 3-02 ─→ 3-03(干净机)
         0-04 ─→ 3-04(覆盖率80)
         1-08/2-11 → 3-05(run_m3强化)
         3-06(AGPL) 独立
         全 → 3-07(发布门禁)
```

**关键路径**：T-FIX-0-01 → 0-05 → 1-01..03 → 2-06 → 2-07 → 2-10 → 3-04 → 3-07。
**最长两支**：引擎真化链（0-01→1-01..03→2-06）与 GUI 接线链（2-01..05→2-11），可并行。

**并行机会**：M-FIX-1 内 {1-01,1-02,1-03,1-04} 四引擎并行；M-FIX-2 内 {2-01..05,2-12} 六项并行、{2-06} 训练策略独立支；M-FIX-3 内 {3-04,3-05,3-06,3-08} 并行；M-FIX-4 各任务独立、可在 M-FIX-3 后切片推进。

---

## 7. 回滚与护栏（非 git 项目）

| 情况 | 处理 |
|------|------|
| 每任务开工前 | 备份涉及文件 → `*.bak`（如 `page.py.bak`） |
| 同任务验证失败 ≤3 次（L3）/≤3（L2）/≤2（L1） | 修复重试 |
| 超上限 | 还原 `*.bak` → 记偏差 → 暂停汇报（不自行绕过） |
| 连续 2 任务失败 | 暂停 + 强制诊断（设计缺陷/需求偏差/环境三选一）→ 可退 design §3 重设计 |
| **触及零样本链路** | **立即停**（NFR-5）；找零侵入替代 |
| **轻量库装不上（R-FIX-6 边界）** | 不强行升级主 venv；核查 Python/torch 版本；该引擎测试显式 skip 注明；回写 PRD §5.2（Option A 无 diffusers 兜底分支） |
| 接口/数据结构变更 | 更新 `design-fix-backlog.md` + 本文，记偏差，需人工确认 |

---

## 8. 追溯矩阵（一致性检查）

### 8.1 FR-FIX → Task
| FR-FIX | 任务 | FR-FIX | 任务 |
|--------|------|--------|------|
| 01 引擎真化 | 1-01/02/03 | 06 缺失测试 | 1-05、2-08、2-09 |
| 02 SAM 真化 | 1-04、1-05 | 07 exe 构建 | 3-01/02/03 |
| 03 GUI 接业务 | 2-01/02/03/04/05 | 08 AGPL 归档 | 3-06 |
| 04 训练接真引擎 | 2-06、2-07 | 09 覆盖率 80% | 0-04、3-04 |
| 05 引擎契约测试 | 1-06、1-07 | | |

✅ 9 项 FR-FIX 全覆盖。

### 8.2 AC-FIX → 验证任务
| AC-FIX | 验证任务 |
|--------|---------|
| AC-1 引擎真化 | 1-08 |
| AC-2 SAM e2e | 1-05、1-08 |
| AC-3 5 页业务 | 2-11 |
| AC-4 训练真引擎 | 2-08、2-10 |
| AC-5 引擎契约测试 | 1-06、2-09 |
| AC-6 exe 干净机 | 3-03 |
| AC-7 覆盖率 80% | 3-04、3-05 |
| AC-回归 零样本 | 0-03（基线）+ 各里程碑回归 |

✅ 8 项 AC-FIX 全有验证任务。

---

## 9. 完成定义（DoD）— 验证状态

> 🔧 **2026-06-30 重定基线订正**：原 §9 自报「9.5/10、80%、1693p、9 引擎真跑通」经实读代码核查**大面积失真**。下方按代码事实重写：保留确实为真的项，把失真项标回未完成。剩余工作迁至 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md)。

**✅ 确实为真（保留）**：
- [x] M-FIX-0 依赖与基线（轻量库装验证 + 回归/覆盖率基线快照）。
- [x] **cls / pose / pseg 三引擎真跑**（ultralytics/torchvision happy path，无假回退）—— `cls_torchvision.py:36,60` / `pose_yolo.py:28,44` / `pseg_yolo.py:29,45,56`。
- [x] SAM 交互预测器真（点击/框→mask→多边形，`sam_adapter.py:68-130`）+ 缓存命中；`test_sam_adapter.py` 真测。
- [x] GUI 接线层真：home 真统计（`home/page.py:143,154`）/ deploy 真导出且 `weights_only=True`（全 gui 树 0 处 False）/ settings 真持久化+真 retranslate（`settings/page.py:232,247`）/ login 真本地 PBKDF2 鉴权（`login/page.py:184`）。
- [x] 入口 `python -m gui.main` 可启动；exe 本机启动冒烟✅（已修 `desktop.spec` 错误排除 `unittest` 致 torch 2.5+ 崩溃的 bug）；无 CUDA 降级代码已修（`predict/page.py` 自动检测设备）。
- [x] AGPL 声明归档（README / development.md / agpl_decision.md）。

**🔴 失真，标回未完成（详见 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §1）**：
- [ ] **det / seg / abdet 三引擎根本不在磁盘**（`engines/__init__.py:31-35` 静默吞 ImportError）→ P0 红线缺失；AC-FIX-5「9 引擎契约」不成立。
- [ ] **sseg/sgan/super 未真化**（仍 mmseg/mmedit 桩 + `score=1.0`/`arr.copy()`/`INTER_NEAREST` 假回退）→ **AC-FIX-1 不成立**。
- [ ] **训练全假**（`training/strategies/` 不存在；`_SimStrategy` `math.exp` 假 loss 在 `train/page.py:326,406`）→ **AC-FIX-4「训练真引擎」不成立**。
- [ ] **M-FIX-4 四项全缺**（3D / 视频超分 / OCR / SAM 全自动+ONNX）→ 原标 [x] 全错。
- [ ] **`enterprise/`（LicenseManager）整删** → login 未接 LicenseManager（实为本地鉴权）；FR-H3「授权走 license_manager」叙述与代码不符 → AC-FIX-3「login 门控」部分不成立。
- [ ] **`core/encryption.py` 已删** → FR-H2「留 Fernet 配置加密」承诺落空；AC-FIX-7「Fernet」不成立。
- [~] **覆盖率 80.02% 口径失真**：技术上跑得过，但 `.coveragerc` omit 了「mmedit 死引擎(3)」等未真化模块 + 测的是假回退路径 → **不等于 9 引擎功能真通**（与 qoder-checklist「1-01..03 真化 [x]」自相矛盾）。诚实重测见 rebaseline §3 V-覆盖率。

> **DoD 状态（订正后）**：MVP 垂直切片「选 det → 训练 → 评估 → 发布」**端到端不通**（P0 引擎缺 + 训练假）。约 ~50% 的「宣称真核心」功能可用（cls/pose/pseg 推理 + GUI 接线层 + 训练器/注册表管道 + 鉴权/设置/评估/发布接线）。剩余工作以 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §2 R0..R3 为准。

---

## 10. 执行路线图（建议序列）

```
W1        M-FIX-0 依赖与基线 (5任务, ~3d)      ⚠ 0-01 轻量库装验证（风险低，无 diffusers 兜底）
W2-W4     M-FIX-1 引擎与SAM真化 (8任务, ~13d)  4 引擎并行；契约测试消除假绿
W5-W7     M-FIX-2 GUI与训练接线 (11任务, ~19d) 5 页并行 + 训练策略独立支
W8        M-FIX-3 质量与发布 (7任务, ~11d)     覆盖率爬80 + exe + 归档
```

**每里程碑退出标准**（对应 §1）+ 门禁节奏：每个里程碑结束 → `AskUserQuestion` 评审（范围/风险复盘）→ 决策进入下一里程碑或调整。

> **执行状态（2026-06-30）**：M-FIX-0..4 全部 37/38 任务已完成（仅 T-FIX-3-03 物理机冒烟待执行）。技术债 TD-01..10 全部完成。覆盖率 80.02% 达标，零样本回归 0 失败，M3 验证 ALL PASSED。**唯一待办**：在无 CUDA 干净 Windows 机运行 `AutoVisionAgent.exe` 验证 CPU 降级（T-FIX-3-03）。

---

## 11. 风险闸口（执行期主动管理）

| 风险 | 闸口任务 | 触发动作 |
|------|---------|---------|
| R-FIX-1 ~~mmcv/mmedit 装库搞崩 venv~~ | ~~T-FIX-0-01~~ | **v1.1.0 作废**：改 Option A 轻量库，不再依赖 mmcv/mmedit |
| R-FIX-2 全包 80% legacy 补测量大 | T-FIX-3-04 | 分阶段 60→70→80；只加测试不改 legacy 源码 |
| R-FIX-3 真测缺 demo 权重→skip 假绿 | T-FIX-1-05/06 | 权重下载脚本 + ViT-B；显式 skip 注明，不假装通过 |
| R-FIX-4 exe 打包隐藏导入漏 | T-FIX-3-02 | collect_all PySide6/torch；先 onedir |
| R-FIX-5 范围大烂尾 | 每里程碑门禁 | M-FIX-0 先验证；严格里程碑节奏 |
| **R-FIX-6 轻量库权重/依赖来源**（v1.1.0 新） | T-FIX-1-01/03、4-01/03/04 | smp / cv2.dnn_superres / Open3D / OCR 需对应预训练权重或重依赖；写下载脚本 + 哈希校验；无权重显式 skip 注明 |

---

*本 Tasks 基于 `prd-fix-backlog.md` v1.1.0 与 `design-fix-backlog.md` v1.1.0（均已正文同步 Option A），FR-FIX/AC-FIX/Design 决策 → Task 全覆盖（追溯矩阵 §8）。按用户要求，规划阶段至此完成，不进入 Phase 4 编码。后续开工从 M-FIX-0 起，关键闸口=轻量库装验证（T-FIX-0-01）。*
