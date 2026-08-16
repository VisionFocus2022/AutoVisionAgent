# Tasks + 执行路线图 — SKolpha 完整对标扩展

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-28 |
| 阶段 | L3 / Phase 3 — Tasks（**止于规划，不执行**，按用户要求） |
| 上游 | `prd-skolpha-fork.md` v1.0.0 · `design-skolpha-fork.md` v1.0.0 |
| 目标项目 | `E:\计算机视觉\视觉大模型\` |

> **工作量标记**：S ≤1 人日 · M 1–3 · L 3–10 · XL >10。**风险**：🔴高/🟡中/🟢低。**验证**栏给可执行命令（项目栈：pytest/ruff/mypy/bandit/black）。每个里程碑强制含集成验证任务与测试任务。

---

## 1. 任务总览（按里程碑）

| 里程碑 | 任务数 | 工作量估算 | 退出标准（AC） |
|--------|--------|-----------|----------------|
| **M0 基线** | 8 | ~12 人日 | 接口契约 + 加密 + 项目模型 + 零样本回归护栏就绪 |
| **M1 MVP 闭环** | 15 | ~50 人日 | det/seg/abdet + 训练 + 6模式标注 + GUI 5 页 e2e |
| **M2 完整对标** | 8 | ~45 人日 | 9 任务全引擎 + SAM + 评估/发布 + i18n |
| **M3 打磨发布** | 6 | ~18 人日 | 打包 + 性能 + 全测 + 文档；`skolpha-fork.exe` 可分发 |
| **合计** | **37** | **~125 人日（≈2.5 人月）** | 完整对标 SKolpha（3D 标注 P2 另计 ~15 人日） |

> ⚠ 真实周期受 R-1(范围)/R-2(GUI)/R-5(AGPL) 影响显著；上表为乐观估算。建议 2–3 人并行，墙钟 3–4 月。

---

## 2. M0 — 基线（接口 / 接入点 / 加密 / 护栏）

| ID | 任务 | 依赖 | 验证（HOW） | 估 | 风险 |
|----|------|------|------------|----|----|
| T-M0-01 | `core/interfaces_supervised.py`：`TaskType`枚举 + `ISupervisedTaskEngine`/`ITaskTrainer` Protocol + `DetectionResult`/`TrainConfig`/`Shape` 等 frozen dataclass | — | `mypy core/interfaces_supervised.py` 0 error；契约单测（结构字段） | S | 🟢 |
| T-M0-02 | `core/encryption.py`：`IConfigCipher` + `FernetConfigCipher` + `{Env,Keyring,Service}KeyProvider` | — | 加解密往返单测；错误密钥→`ConfigDecryptionError` | S | 🟡(R-4) |
| T-M0-03 | `models/supervised/registry.py`：`@register_engine` 装饰器 + DI 容器注册接入点 | T-M0-01 | 单测：注册后可按 `TaskType` 解析到占位引擎 | S | 🟢 |
| T-M0-04 | `core/exceptions.py` 新增 `SupervisedEngineError`/`TrainingError`/`ConfigDecryptionError`/`UnsupportedTaskError` | — | `mypy`；异常层次单测 | S | 🟢 |
| T-M0-05 | `project/`：`ProjectId`/`ProjectLayout`(frozen) + `IProjectStore`(文件系统) + `Counter`(任务ID原子自增) | T-M0-01 | 单测：`{name}_{TASK}_{ID}_{ts}` 路径生成 + 计数并发安全 | M | 🟢 |
| T-M0-06 | `ConfigSystem` 扩展：识别 `gAAAAA` 头 → `FernetConfigCipher.decrypt_file` → 解析 YAML/JSON（仅加方法） | T-M0-02 | 单测：加密配置往返；明文配置兼容 | S | 🟡 |
| T-M0-07 | **零样本回归护栏**：把既有零样本套件标记为 `regression`，CI 前置门 | — | `pytest -m regression` 全绿（基线快照） | M | 🟢 |
| T-M0-08 | **M0 集成验证**：接口编译 + 加密往返 + 注册解析 + 项目目录 + 零样本未回归 | T-M0-01..07 | `pytest tests/m0 -m integration` 全绿；`ruff/mypy/bandit` 过 | M | 🟢 |

---

## 3. M1 — MVP 闭环（det/seg/abdet + 训练 + 标注 + GUI 核心）

| ID | 任务 | 依赖 | 验证（HOW） | 估 | 风险 |
|----|------|------|------------|----|----|
| T-M1-01 | `models/supervised/base.py`：`AbstractTaskEngine` 骨架（load/infer/release/info + weights_only） | M0 | 抽象类单测 | S | 🟢 |
| T-M1-02 | `det_yolo.py`：ultralytics YOLOv8 检测引擎（FR-A2） | T-M1-01 | 固定小权重→`infer` 返回 `[N,6]` 结构契约测试 | M | 🔴(R-5 AGPL) |
| T-M1-03 | `seg_yolo.py`：YOLOv8-Seg 实例分割引擎（FR-A3） | T-M1-01 | 契约测试：`masks` 形状 | M | 🔴(R-5) |
| T-M1-04 | `abdet_anomalib.py`：anomalib PatchCore/PaDiM 异常检测引擎（FR-A7） | T-M1-01 | 契约测试：`{score, anomaly_map}` | M | 🟡 |
| T-M1-05 | `training/config.py`：`TrainConfig`(frozen) + 序列化 + Fernet 加密落盘 | M0 | 配置加密往返；版本兼容 | S | 🟡 |
| T-M1-06 | `training/trainer.py`：`GenericTrainer`（QThread/线程池 + `should_stop` 中断 + resume + checkpoint） | T-M1-05 | 1-epoch 冒烟；中断/续训单测 | L | 🟡(R-9) |
| T-M1-07 | `training/dataset_adapter.py`：LabelMe JSON → det/seg/abdet Dataset | M0 | 样例标注→Dataset 长度/字段单测 | M | 🟢 |
| T-M1-08 | `training/callbacks.py`：Loss/Metric/EarlyStop/Checkpoint + 对接 `TrainingTracker` | T-M1-06 | 回调触发单测 | M | 🟢 |
| T-M1-09 | `labeling/base.py` + `modes/{polygon,rectangle,brush,keypoint}.py`（FR-C1 四手动模式） | M0 | 各模式 `to_shape()` 单测 | M | 🟢 |
| T-M1-10 | `labeling/canvas.py` + `io_labelme.py`：QGraphicsScene 画布 + 撤销/重做栈 + LabelMe 读写（FR-C4/C5） | T-M1-09 | 撤销/重做往返；LabelMe 往返 | L | 🟢 |
| T-M1-11 | `gui/core/{shell,theme,i18n,shortcuts}.py`：无边框主壳 + QSS 双主题 + gettext + 快捷键（FR-D1/D3） | — | 手测：主题切换/i18n 切换/快捷键；snapshot 测试 | L | 🟡(R-2) |
| T-M1-12 | `gui/pages/{data_manage,label,train,predict,project}/` + controllers（FR-D4/D5/D6/D7、E1/E2） | T-M1-06/10/11 | pytest-qt：导入→标注→训练→推理 e2e | XL | 🔴(R-2) |
| T-M1-13 | `ModelEvaluator` 扩展：det mAP / seg IoU / abdet AUROC（FR-B5） | T-M1-02..04 | 指标计算单测（固定预测+标注） | M | 🟢 |
| T-M1-14 | `DataManager` 扩展：项目目录模型 + 最近列表（FR-E1/E3/E4） | T-M0-05 | 项目 CRUD + 路径单测 | M | 🟢 |
| T-M1-15 | **M1 集成验证**：det/seg 全闭环 e2e（标注→训练可中断→评估→推理→报表） | 全 M1 | `pytest -m e2e tests/m1`；AC-B/C/D(E1/E2) | L | 🟡 |

---

## 4. M2 — 完整对标（补齐 9 任务 + SAM + 评估/发布 + i18n）

| ID | 任务 | 依赖 | 验证（HOW） | 估 | 风险 |
|----|------|------|------------|----|----|
| T-M2-01 | `cls_torchvision.py` / `pose_yolo.py` / `pseg_yolo.py` / `sseg_mmseg.py` 四引擎（FR-A1/A4/A5/A6） | T-M1-01 | 各契约测试；mmseg 配置加载 | L | 🟡(R-3) |
| T-M2-02 | `sgan_mmedit.py` + `super_mmedit.py`：缺陷生成 + 超分（FR-A8/A9、G1/G2） | T-M1-01 | 冒烟：合成图/HR 图产出 | L | 🟡(R-3) |
| T-M2-03 | `labeling/sam_adapter.py` + `modes/{interactive,auto}.py`：SAM 交互/AI预标注（FR-C2/C3） | T-M1-10 | 点击→mask→多边形 e2e；mask 缓存 | L | 🟡(R-6) |
| T-M2-04 | `evaluation/fid.py`（FID-Inception）+ 感知损失（torchvision Inception）（FR-G3） | T-M2-02 | FID 可计算；对标附录 D 权重 | M | 🟢 |
| T-M2-05 | `gui/pages/{login,home,evaluate,publish,settings}/` 完整 + i18n 全量（FR-D2/D3、H3） | T-M1-11 | 页面 e2e；登录门控（软件授权） | L | 🟡 |
| T-M2-06 | `exporter/` 整合：训练产物→ONNX/TensorRT 导出（FR-B6，复用 `tensorrt_accel`） | T-M2-01 | 导出 + 推理一致性 | M | 🟡 |
| T-M2-07 | `VisionModelSystem` 双范式分发完善 + 9 任务注册（FR-A10/A11） | M1+T-M2-01/02 | 分发单测；零样本未回归 | M | 🟢 |
| T-M2-08 | **M2 集成验证**：9 任务 × {训练,推理,评估} 矩阵 + SAM 交互 e2e（AC-A/G） | 全 M2 | `pytest -m e2e tests/m2`；回归绿 | L | 🟡 |

---

## 5. M3 — 打磨发布

| ID | 任务 | 依赖 | 验证（HOW） | 估 | 风险 |
|----|------|------|------------|----|----|
| T-M3-01 | PyInstaller 桌面打包（`desktop.spec`）→ `skolpha-fork.exe`（FR-D8） | M2 | 干净机冒烟运行 | M | 🟡 |
| T-M3-02 | 性能调优：推理 <100ms、GUI 60fps、启动 <5s（NFR-1） | M2 | benchmark 脚本达标 | M | 🟡 |
| T-M3-03 | 全量测试 + 覆盖率 ≥80% + `ruff/mypy/bandit/black --check`（NFR-3/7、AC-H） | M2 | `pytest --cov`；lint 全过 | M | 🟢 |
| T-M3-04 | 文档：用户手册 + 开发文档（替代 `help.chm`）+ API 文档 | M2 | 文档评审 | M | 🟢 |
| T-M3-05 | **AGPL 法务决策落实**(R-5)：放行 或 切非 AGPL 检测栈（接口不变） | — | 法务结论 + 实施记录 | M | 🔴(R-5) |
| T-M3-06 | **M3 发布验证**：AC-H 全过；可分发制品 | 全 | 发布检查清单 | S | 🟢 |

> **P2 增强包（3D 标注 FR-C6，按门禁结论延后）**：`labeling/three_d/{o3d_vis, perspective, stereo}.py` ≈ XL/15 人日，依赖 Open3D，独立可切片。

---

## 6. 依赖图（关键路径）

```
M0: T01─T03─┐
    T02─T06─┤
    T04     ├─→ T08(M0验证) ─┐
    T05─────┘                │
                             ▼
M1: T-M1-01 ─→ {02,03,04} ──┐
    T-M1-05 ─→ 06 ─→ 08 ────┤
    T-M1-09 ─→ 10 ──────────┤
    T-M1-11 ─→ 12 ◂──────────┤  (12 依赖 06/10/11)
                 13 ◂ 02/03/04│
                 14 ◂ M0-05   │
                 15(M1验证)◂ all
                             ▼
M2: 01,02 并行 ──→ 04,06,07 ─→ 08(M2验证)
    03 并行 ─────→ 05(i18n/login/eval/publish)
                             ▼
M3: 01,02,03,04 并行；05(AGPL) 独立；06(M3验证)◂all
```

**关键路径**：T-M0-01 → T-M1-01 → T-M1-02/03 → T-M1-06 → T-M1-12 → T-M1-15 → T-M2-01/02 → T-M2-08 → T-M3-01 → T-M3-06（GUI M1-12 与训练 M1-06 是最长两支）。

**并行机会**：M0 内 01/02/04/05 可四人并行；M1 内 {02,03,04}、{05,09,11}、{13,14} 多组并行；M2 内 01/02/03/05 并行。

---

## 7. 追溯矩阵（一致性检查）

### 7.1 FR → Task

| FR | 任务 | FR | 任务 |
|----|------|----|------|
| FR-A1 cls | T-M2-01 | FR-C1 六模式 | T-M1-09/10 |
| FR-A2 det | T-M1-02 | FR-C2/C3 SAM/AI | T-M2-03 |
| FR-A3 seg | T-M1-03 | FR-C4/C5 撤销/LabelMe | T-M1-10 |
| FR-A4 pseg | T-M2-01 | FR-C6 3D | P2 包 |
| FR-A5 pose | T-M2-01 | FR-D1/D3 主壳/i18n | T-M1-11 |
| FR-A6 sseg | T-M2-01 | FR-D2/D4-D7 页面 | T-M1-12、T-M2-05 |
| FR-A7 abdet | T-M1-04 | FR-D8 打包 | T-M3-01 |
| FR-A8 sgan | T-M2-02 | FR-E1/E2 项目 | T-M0-05、T-M1-14 |
| FR-A9 super | T-M2-02 | FR-F1-F3 配置 | T-M0-06、T-M1-05 |
| FR-A10/A11 注册/分发 | T-M0-03、T-M2-07 | FR-G1/G2 sgan/super | T-M2-02 |
| FR-B1 配置 | T-M1-05 | FR-G3 FID/感知 | T-M2-04 |
| FR-B2 训练 | T-M1-06 | FR-H1 weights_only | T-M1-01 |
| FR-B3 回调 | T-M1-08 | FR-H2 Fernet | T-M0-02/06 |
| FR-B4 Dataset | T-M1-07 | FR-H3 授权 | T-M2-05 |
| FR-B5 评估 | T-M1-13 | FR-H4 安全 | 沿用 core/security |
| FR-B6 发布 | T-M2-06 | | |

✅ **所有 FR 均有任务覆盖，无遗漏。**

### 7.2 AC → 验证任务

| AC | 验证任务 |
|----|---------|
| AC-A 9 引擎 | T-M2-08 |
| AC-B det/seg 闭环 | T-M1-15 |
| AC-C 标注/SAM | T-M1-15、T-M2-03 |
| AC-D GUI 全流程 | T-M1-12、T-M2-05 |
| AC-E 项目目录/计数 | T-M0-05、T-M1-14 |
| AC-F Fernet | T-M0-08、T-M1-05 |
| AC-G sgan/super | T-M2-02/04 |
| AC-H 质量/lint | T-M3-03/06 |
| AC-回归 零样本 | T-M0-07（前置）、各里程碑回归 |

### 7.3 Design 组件 → Task（抽样）

| Design 组件 | Task |
|------------|------|
| `core/interfaces_supervised.py` | T-M0-01 |
| `core/encryption.py` | T-M0-02 |
| `models/supervised/*` | T-M1-01..04、T-M2-01/02 |
| `training/*` | T-M1-05..08 |
| `labeling/*` | T-M1-09/10、T-M2-03 |
| `gui/*` | T-M1-11/12、T-M2-05 |
| `project/*` | T-M0-05、T-M1-14 |
| `evaluation/fid.py` | T-M2-04 |
| 异常子类 | T-M0-04 |

✅ **Design 所有组件均落到任务。**

---

## 8. 执行路线图（建议序列）

```
W1-W2   M0 基线 (8 任务, ~12d)         ← 并行 4 人；产出可合入的接口层
W3-W7   M1 MVP 闭环 (15 任务, ~50d)    ← GUI(12) 与 训练(06) 两支并行；M1 末可演示
        ⎇ 法务 AGPL(R-5) 启动评估      ← 不阻塞 M1，但 M3 前必须有结论
W8-W12  M2 完整对标 (8 任务, ~45d)     ← 4 任务引擎 + SAM + 发布 并行
W13-W14 M3 打磨发布 (6 任务, ~18d)     ← 打包/调优/全测/文档
W15+    P2 增强 (3D 标注, ~15d, 可选)  ← 独立切片
```

**每里程碑退出标准**（对应 §1）：
- M0：接口/加密/项目模型评审通过；`pytest -m regression` 绿。
- M1：det/seg e2e 闭环；GUI 5 页可用；AC-B/C/D(E1/E2)。
- M2：9 任务矩阵；SAM 交互；AC-A/G；i18n。
- M3：AC-H；`skolpha-fork.exe` 干净机运行；文档齐。

**门禁节奏**：每个里程碑结束 → `AskUserQuestion` 评审（范围/优先级/风险复盘）→ 决策进入下一里程碑或调整。**按用户要求，本规划到此为止，不进入 Phase 4 编码执行。**

---

## 9. 风险闸口（执行期需主动管理）

| 风险 | 闸口任务 | 触发动作 |
|------|---------|---------|
| R-1 范围 | 每里程碑门禁 | 范围超 → 砍 P2、延 3D |
| R-2 GUI | T-M1-11/12 | 先骨架后填充；遇阻退回 Design §5.4 |
| R-5 AGPL | T-M3-05（M1 启动法务） | 不放行 → 切非 AGPL 检测栈（接口不变） |
| R-3 依赖冲突 | T-M2-01/02 | mmseg/mmedit 隔离环境或替代(diffusers) |
| R-7 零样本回归 | T-M0-07 + 每里程碑 | 红即停，定位是新模块越界 |

---

## 10. 完成定义（DoD）

- [ ] 所有 P0/P1 任务 completed 且其验证栏命令全绿
- [ ] `pytest --cov` ≥ 80%；`ruff`/`mypy`/`bandit`/`black --check` 全过
- [ ] 零样本回归套件 0 失败
- [ ] 9 任务 × {训练,推理,评估} 矩阵 100%
- [ ] AC-A…AC-H + AC-回归 全过
- [ ] `skolpha-fork.exe` 在干净 Windows 机运行通过
- [ ] 用户手册 + 开发文档 + API 文档齐备
- [ ] AGPL 法务结论归档（R-5 收尾）

---

*本 Tasks 基于 PRD v1.0.0 与 Design v1.0.0，FR/AC/Design 组件 → Task 全覆盖（追溯矩阵 §7）。按用户要求，规划阶段至此完成，不进入 Phase 4 编码执行。后续如需开工，从 M0 起按路线图逐里程碑推进，每里程碑经门禁评审。*
