# 工程债清单（Tech Debt）— AutoVisionAgent

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0.0 |
| 创建日期 | 2026-06-30 |
| 性质 | **独立切片**——与 M-FIX-0..4 战役（`tasks-fix-backlog.md`）解耦。本清单只收录 fix-backlog **未覆盖**的工程债；可在任何里程碑穿插、或 DoD 后集中清理。 |
| 核验方式 | 每条均经 2026-06-30 实读源码 + grep 交叉验证，附 `文件:行` 证据（非推断）。 |
| 优先级 | P1=诚信/正确性（建议尽早）· P2=结构性（影响维护）· P3=卫生/清理（低风险）。 |
| 与 fix-backlog 关系 | **不重复**：sgan/super/sseg 桩（=T-FIX-1-01..03）、label `_ai_prelabel`（=T-FIX-2-12）、deploy `weights_only`（=T-FIX-2-04）、训练策略（=T-FIX-2-06）均不在本清单。 |
| 红线遵守 | NFR-5：legacy 零样本链路（`models/{detector,dinov3,clip,few_shot_trainer}`、`services/detection_service`、`api/gateway`、`web/`、`run_flask.py`）一行不改——本清单涉及的旁路代码若与 legacy 重叠，仅"标注/隔离"不"改逻辑"。 |

---

## 0. 总览（10 条）

> 🔧 **2026-06-30 重定基线核查状态**：本表「状态」列为实读代码后的最终结论；下方明细 §1 描述的是**原始发现**（部分项其后已修，凡矛盾以本表为准）。**结论：6 解 / 4 残**。残留项（TD-05/06/08/10）已并入 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §2.4 R3 收口。

| ID | 工程债 | 状态 | P | 一句话（含 file:line 证据） |
|----|--------|------|---|------|
| TD-01 | pseg/seg 引擎同构重复 | ✅ 解（前提不成立） | P2 | `seg_yolo.py` 根本不存在（只有 `pseg_yolo.py`）；dedup 前提失效 |
| TD-02 | TaskCounter 无持久化 | ✅ 解 | P1 | `project/counter.py:56-64` `_save` 写 `task_counter.json`；`next_id:79` 自增即存盘，重启不归零 |
| TD-03 | Fernet 加密落盘是死能力 | ✅ 解（但 FR-H2 落空） | P2 | `core/encryption.py` 已**整个删除** → 配置明文存；PRD「留 Fernet」(FR-H2) 承诺落空 → 见 rebaseline R1-1 决策 |
| TD-04 | 裸 except 系统性吞异常 | ✅ 解 | P2 | 源码无裸 `except:`；残留 handler 均类型化（`OSError`/`ImportError`/`Exception`）+ 多数走 `_logger` |
| TD-05 | flaw_gen 游离页假生成 | 🟡 部分（**诚信级残留**） | P1 | `gui/pages/flaw_gen/page.py:220` 仍 `shutil.copy2` 把 OK 图伪装成合成图；`retranslate()` 已修（`:256-267`） → rebaseline R3-1 |
| TD-06 | ivp 平行层 + 双分发器 | 🟡 部分 | P2 | `VisionModelSystem` 类已删；残留 docstring 仍指它（`vision_dispatcher.py:1`、`registry.py:140`） → R3-2 |
| TD-07 | label/page_clean.py 死文件 | ✅ 解 | P3 | 文件已删，仅本文档引用 |
| TD-08 | 离线帮助/手册缺失 | 🟡 部分 | P3 | 仅窗口按钮 4 个 tooltip（`gui/core/shell.py:87,93,100,123`）；无 F1 / QHelpEvent / QWhatsThis → R3-3 |
| TD-09 | integrations/skolpha 旁路 | ✅ 解 | P3 | 整目录 + `services/skolpha_service.py`（+ `services/`）已删；源码 0 引用 |
| TD-10 | 构建产物污染源码树 | 🟡 部分 | P3 | `dist/AutoVisionAgent/` 仍在树内；`.gitignore:8-9` 已忽略（物理未移出） → R3-4 |

> **建议批次（更新）**：P1 仅剩 TD-05（诚信级，rebaseline R3-1 优先）；P2 的 TD-06 随 R3-2 顺手清；P3 的 TD-08/10 在发布前一批扫净（R3-3/R3-4）。TD-02/03/04/07/09 已结案（TD-03 需在 R1-1 决策恢复 Fernet 或撤销 FR-H2）。

---

## 1. 明细

### TD-02 · TaskCounter 无持久化 〖P1〗

- **现状/证据**：`project/counter.py:14` `TaskCounter` 仅 `self._counts: Dict[TaskType,int]` + `threading.Lock`。提供了 `set()`（docstring 写"用于从持久化恢复"，line 35-38）与 `snapshot_by_name()`（"对标 SKolpha psegID/... 的 JSON 字段"，line 45-48），但全项目 grep：`.set(` 零调用、`snapshot()`/`snapshot_by_name()` 只被**读**（`industrial_vision_platform/data_manager_ext.py:256`、`gui/pages/project/page.py:241`），**从不落盘**。
- **影响**：应用重启 → 所有任务计数归零 → 新建项目拿到已用过的 ID → 目录规范 `{name}_{TASK}_{ID}_{ts}` 撞号、历史项目被覆盖风险。对标 SKolpha 恰恰把各任务 ID 持久化在配置 JSON，AVA 这层是漏的。
- **修复思路**：`ProjectStore` 构造/销毁时 `load/save` 一个 `counts.json`（走 `core/encryption.py::load_config_file` 可顺带接 TD-03 的加密落盘）；`next()` 自增后写盘，`set()` 用于启动恢复。不可变快照 + 原子写（tmp→rename）。
- **估时/风险**：S（半天）· 🟡（触及项目目录模型，需回归 `test_project_models.py`）。

### TD-05 · flaw_gen 游离页假生成 〖P1〗

- **现状/证据**：`gui/pages/flaw_gen/page.py` 有完整 UI + `_start_generate` worker（line 137-243），但：
  1. line 163-209 尝试 `SganMmeditEngine`，调 `engine.load_template/load_defect/infer(None)`——这些方法是否存在于引擎**未核实**（很可能不存在或签名不符）；
  2. line 208-209 `except Exception: pass` 吞掉所有失败；
  3. line 211-233 **回退到 `shutil.copy2`：把 OK 模板图复制成 `synthetic_NNNN.png`**，对外报"生成完成 N 张"——**静默产出假数据**；
  4. line 271-272 `retranslate()` 是 `pass`（i18n 切换不刷新）。
- **影响**：用户以为得到了 GAN 合成缺陷图，实际是输入图的副本 rename。这是**诚信级缺陷**，比"功能未实装"更糟（误导下游训练）。且与 fix-backlog T-FIX-1-02（sgan 真化）耦合：即便引擎真化，本页的假回退 + 方法签名错仍会让它走 copy 旁路。
- **修复思路**：① 等依赖 T-FIX-1-02 真化 sgan 后，重写 worker 走真 blend；② **删除 `shutil.copy2` 假回退**，引擎不可用时直接 `_failed_slot` 报错（不伪装成功）；③ 核实并修正 `load_template/load_defect/infer` 调用签名；④ 补 `retranslate()`。
- **估时/风险**：M · 🟡（依赖 T-FIX-1-02；建议排在 M-FIX-1 之后）。

### TD-01 · pseg/seg 引擎同构重复 〖P2〗

- **现状/证据**：`models/supervised/engines/seg_yolo.py`（68 行）与 `pseg_yolo.py`（70 行）逐行比对——`load()` 完全相同；`infer()` 仅两处差异：① `TaskType.SEG` vs `TaskType.PSEG`；② pseg 在 `boxes is None` 时**早返不带 mask**（line 46-47），seg 先取 mask 再判 boxes。pseg docstring 自称"YOLOv8-Seg **Pro 大模型变体** yolov8x-seg"（line 1-3），但代码与 seg 完全同构，**无任何模型尺寸/后处理差异**。
- **影响**：维护双份代码（改一处忘另一处）；docstring 暗示 pseg 是"大模型升级版"但实际是复制粘贴，误导对标评估。
- **修复思路**：抽 `_YoloSegBase`（共享 load/infer），seg/pseg 子类只覆写 `task` 与 mask 处理顺序；或 pseg 真做"Pro"（更大 backbone / 更精 mask 后处理如 `crop+paste` 边缘优化）以名副其实。前者是去重，后者是补真——按对标需求选。
- **估时/风险**：S · 🟢（纯重构，有 `test_m2_e2e.py` 注册测试兜底）。

### TD-03 · Fernet 加密落盘是死能力 〖P2〗

- **现状/证据**：`core/encryption.py` 设计完整——`FernetConfigCipher.encrypt_file/decrypt_file`（line 182-192）、`load_config_file` 自动识别 token（line 196-230）。但全项目 grep `FernetConfigCipher|encrypt_file`：**唯一生产调用方是 `industrial_vision_platform/config_system.py:279` 的 `load_config_file`（解密读）**；`encrypt_file` / `FernetConfigCipher(` 仅出现在 `tests/`。即：**没有任何生产路径把配置加密后写入磁盘**。
- **影响**：PRD/对外宣称"留 Fernet 配置加密"（FR-H2），但实际训练配方/项目配置以**明文 JSON** 落盘，加密能力是死的。对标 SKolpha 恰恰在配置静态存储时加密——AVA 这层通电一半。
- **修复思路**：在配置/配方的**写入侧**（training config 持久化、project store）接 `FernetConfigCipher.encrypt_file`，密钥走 `EnvKeyProvider`/`KeyringKeyProvider`（已具备）。可与 TD-02 的 `counts.json` 持久化合并做。
- **估时/风险**：S · 🟢（能力已具备，只缺接线；注意密钥丢失=配置不可恢复，需配套密钥管理说明）。

### TD-04 · 裸 except 系统性吞异常 〖P2〗

- **现状/证据**：grep `except...:\n pass` 在**项目源码**（排除 `.venv`/`dist`）命中 ~18 文件，GUI 主链尤甚：`gui/pages/settings/page.py`×3、`gui/pages/login/page.py`×2、`gui/pages/label/page.py`×2、`deploy/page.py`×1、`flaw_gen/page.py`×1、`predict/page.py`×1、`train/page.py`×1，加 `project/recent.py`×2、`services/vision_platform_service.py`×6、`utils/config_manager.py`×3 等。另：纯裸 `except:`（无异常类）在 `edge/optimizer.py`、`repositories/model_repository.py`×3、`industrial_vision_platform/{model_system,annotation_system,monitoring_system,feedback_system}.py`、`web/flask_app/blueprints/*.py` 等处。
- **影响**：静默吞异常→故障不可观测、调试黑箱。fix-backlog 仅修了 label `_ai_prelabel`（T-FIX-2-12）与 deploy（T-FIX-2-04）两点，**其余 ~16 处仍裸**。
- **修复思路**：分两批——① GUI 主链（settings/login/predict/train/recent）的 `except: pass` 改为 `except <具体异常> as e: logger.warning(...)` + 友好 UI 提示；② legacy/平台层（edge/web/repositories）按 NFR-5 原则**仅标注不强制改**（加 `# noqa: TD-04 待清理` 注释 + 登记即可）。
- **估时/风险**：M · 🟡（量大但单点简单；注意不要在清理中改变既有"容错行为"——有些 pass 是有意的降级，需逐处判）。

### TD-06 · industrial_vision_platform 平行未通电层 + 双分发器 〖P2〗

- **现状/证据**：
  1. **双分发器**：`industrial_vision_platform/model_system.py:386` 定义 `class VisionModelSystem`（被 `services/vision_platform_service.py:23` 实例化），而**真分发器**是 `industrial_vision_platform/vision_dispatcher.py::VisionModelDispatcher`（GUI 实际使用，见 CLAUDE.md 关键概念）。`core/interfaces_supervised.py:8` docstring 仍写"由 VisionModelSystem 分发"——**文档指向 toy**。
  2. `industrial_vision_platform/__init__.py` 导出 11 个子系统 + 6 个模块级单例（`training_tracker`/`batch_operations_manager`/`model_evaluator`/`performance_optimizer`/`feedback_system`/`metrics_collector`/`alert_manager`/`system_monitor`），其中 `api_server`、`monitoring_system`、`feedback_system`、`performance_optimizer`、`batch_operations` 等被 `services/vision_platform_service.py` 一并 import，但 GUI 走的是 `vision_dispatcher` + 各 page 自己的 store/engine——**整层 ivp + services/vision_platform_service 很可能是一套未接线的平行平台栈**。
- **影响**：认知陷阱（agent 读到 `VisionModelSystem` 以为它是真分发器，已在 `core/interfaces_supervised.py` docstring 误导过一次）；死代码膨胀维护面；`vision_platform_service.py` 的 6 处 `except: pass`（见 TD-04）全部坐落在这层未用代码里。
- **修复思路**：① 先做**接线审计**（grep 每个 ivp 模块是否被 `gui/` 或 `run_app.py` 间接引用），确认死活；② 死的整层移入 `legacy/` 或删除（`api_server`/`monitoring`/`feedback`/`performance`/`batch` 疑似全死）；③ 修正 `core/interfaces_supervised.py:8` docstring 指向 `VisionModelDispatcher`；④ `vision_platform_service.py` 若无用一并清。
- **估时/风险**：M · 🟡（需先审计再动刀；误删真被引用模块会断 GUI——必须 grep 验证调用链）。

### TD-07 · label/page_clean.py 死文件 〖P3〗

- **现状/证据**：`gui/pages/label/` 下 `page.py` 与 `page_clean.py` 并存。grep `page_clean` 在 `gui/**/*.py` **零命中**——无任何导入。
- **影响**：标注页有两份实现并存，agent/维护者不知哪个是活的；`page_clean.py` 疑似某次重构的遗留。
- **修复思路**：diff 两份，确认 `page.py` 是活的后删除 `page_clean.py`（非 git → 先备份 `.bak`）。
- **估时/风险**：S · 🟢（删除前确认无导入即可）。

### TD-08 · 离线帮助/手册完全缺失 〖P3〗

- **现状/证据**：grep `QHelpEvent|helpEvent|QWhatsThis|帮助|manual` 在 `gui/**/*.py` **零命中**。GUI 无 F1 帮助、无 What's This、无内置手册入口（虽有 `docs/user_manual.md` 文档，但桌面端无集成）。
- **影响**：对标 SKolpha 桌面端的内嵌帮助/工具提示体系，AVA 纯靠外部 md；新用户上手成本高。
- **修复思路**：① 轻量——各页关键控件补 `setToolTip` + `setWhatsThis`（i18n 包装）；② 中量——加 F1 快捷键打开本地 `docs/user_manual.html`（或打包进资源）；③ 接 `gui/core/shortcuts.py` 已有的快捷键体系。
- **估时/风险**：M · 🟢（纯增量，不动现有逻辑）。

### TD-09 · integrations/skolpha + skolpha_service 旁路 〖P3〗

- **现状/证据**：`integrations/skolpha/{config_manager,annotation_tool,api_client}.py` + `services/skolpha_service.py` 存在，是一套"**对接商业 SKolpha**"的集成旁路（api_client 调外部 SKolpha）。
- **影响**：AVA 定位是"复刻/去 DRM 的独立平台"，对接商业 SKolpha 的旁路与产品定位冲突，且增加维护/安全面（外部 api_client）。
- **修复思路**：确认无 GUI/入口引用后整目录移入 `legacy/integrations-skolpha/` 或删除。注意 NFR-5 边界——若与 legacy 零样本链路无交集可放心清。
- **估时/风险**：S · 🟢（grep 确认无引用后移走）。

### TD-10 · 构建产物/缓存污染源码树 〖P3〗

- **现状/证据**：本次核验每次 grep/glob 都被 `dist/AutoVisionAgent/_internal/...`（PyInstaller 构建产物，含完整 torch/ultralytics 副本）与 `utils/__pycache__/*.pyc`、`models/**/__pycache__/*.pyc` 淹没（`except:` grep 458 命中里绝大多数来自 `dist/` 与 `.venv/`）。
- **影响**：搜索/审计效率骤降、交接包膨胀、IDE 索引慢；非 git 项目无 `.gitignore` 兜底，构建产物与源码混存。
- **修复思路**：① 加项目根 `.gitignore`（即便非 git，也利于未来初始化 + IDE 忽略）：`dist/`、`**/__pycache__/`、`*.pyc`、`build/`、`.pytest_cache/`；② 把 `dist/` 移出源码树到 `E:\计算机视觉\视觉大模型-build\` 或 `.build/`；③ 清理既存 `__pycache__`。
- **估时/风险**：S · 🟢（纯卫生，无逻辑改动）。

---

## 2. 与 M-FIX 战役的关系（不冲突说明）

- **可并行**：TD-01/03/07/09/10 与 fix-backlog 任意里程碑并行（互不触及相同文件的核心逻辑）。
- **有依赖**：TD-05（flaw_gen 真化）依赖 T-FIX-1-02（sgan 真化）→ 排在 M-FIX-1 之后；TD-02（counter 持久化）若接 TD-03（Fernet 落盘）→ 合并做更省。
- **有重叠边界（不重复）**：TD-04（裸 except）与 T-FIX-2-12/2-04 处理同一类问题的**不同实例**——fix-backlog 修 label/deploy 两点，TD-04 收口其余 ~16 处。
- **建议插入点**：P1（TD-02、TD-05）在 M-FIX-2 期间插入；P2 在 M-FIX-3 发布前清理；P3 集中在 M-FIX-3 Wave 3a（与 3-01 合并 spec、3-06 AGPL 归档等文档/卫生任务一批做）。

---

## 3. 验证命令（通用）

```bash
# 任一条改动后跑（非 git → 先备份 .bak）
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m py_compile <改动的.py>
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ --no-cov -q
```

- TD-02 回归：`pytest tests/test_project_models.py --no-cov -q`
- TD-01 回归：`pytest tests/test_m2_e2e.py --no-cov -q`（注册完整性）
- TD-05/08（GUI）：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m gui._render_preview _preview.png`

---

*v1.0.0 初版。每条均附 2026-06-30 实读证据。后续清理逐条把状态记入下表；与 `tasks-fix-backlog.md` 冲突时以本清单为准（本清单只收 fix-backlog 未覆盖项，理论无冲突）。*
