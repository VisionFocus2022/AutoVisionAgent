# SKolpha 能力复刻立项 — 编码任务规划

> 版本: 1.0 | 日期: 2026-09-02 | 关联设计: docs/design-skolpha-replication.md v1.0 | 关联 PRD: docs/prd-skolpha-replication.md v1.0 | 档位: 🔴 L3 | 确定性: 波内高/整体低（D-1..D-4 待裁决） | 影响半径: 大（命中硬触发器②破坏性接口变更——AnnotationMode 扩展联动 io/spec/守卫）
> **门禁 4（最终关口）状态**: ⛔ **停点待用户裁决**——自治会话不自行开工（S3「严格限显式请求范围」边界；多波编码属门禁 4 后行动）。裁决时可同时处理 PRD §11 待裁决项 D-1..D-4。

---

## 概览

- **总任务数**: 13 个（4 波 W56-W59 + 前置/终验）
- **预估工作量**: S×4 + M×7 + L×2
- **关键路径**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 8 → Task 11 → Task 12 → Task 13
- **可并行任务**: 波间**一律串行**（共享 gui/core/i18n.py、autovisionagent.spec、主门禁分母三冲突面）；波内 Task 8 ∥ Task 9（文件域不交：project/store+predict/label vs data_manage/label_tools，i18n 键已分块）
- **验证环境**: `.venv/Scripts/python.exe -m pytest`（主门禁含 coverage fail-under=92）；ruff check；lite 派生 14 用例守卫

> ✅ **2026-09-02 W56 批次完成**（Task 1-4 全过，门禁 4 经用户裁决「确认开工 W56」；D-1/D-2/D-3 按文档默认锁定）：
> 主门禁 **1262 passed / 5 skipped / rc=0**（ruff 全仓 0 error，含 .workflow extend-exclude 卫生化）；
> AC-001 锚点（枚举=7/工具栏=7/快捷键 C/O）+ AC-002（往返）+ AC-003（两模式+取消语义）波内达标；
> 模板初值 9 任务码 203 参数入 `configs/train_templates/_source_dict.json`（Task 5 转正式 YAML 的草值）。
> 偏差 5 条 + 挂死排查留痕见 `.workflow/skolpha-replication/deviations.md`；经验沉淀 EXP-20260902c。

> ✅ **2026-09-02 W57 批次完成**（Task 5-7，用户指令「继续实施待办，按照默认顺序执行」）：
> 11 份明文模板（9 任务码×normal + det small/large，初值取自解密产物换算）+ loader（容错/未知字段告告警/重复后到覆盖）
> + AugmentationConfig 冻结 dataclass + TrainConfig.augmentation 可选段（None=旧行为）+ 训练页模板下拉回填/增强面板/诚实提示。
> 门禁 **1281 passed / rc=0**；草值 _source_dict.json 转正后删除（明细留 .workflow 解密档）。
> 守卫咬合实证：W20 i18n 完整性守卫拦下漏键「模板」→ 即补。

> ✅ **2026-09-02 W58 批次完成**（Task 8-10）：
> project/binding.py（ProjectBinding 四段/原子写/读侧全容错）+ store 创建即写默认 binding（transferType 按任务推导）
> + 预测页「从项目带入/保存绑定」（读改写保留他段）+ label 页 transferType 联动（main.py 一行接线）
> + **假设修正**：S_Tools 首批三件存量已实现（labeling/batch_tools.py，PRD 差距测绘 grep 中文按钮词未命中英文实现名）
> → Task 9 调整为补缺（.bak 备份/删除致空日志警示/统计含面积分布）。
> 门禁 **1298 passed / rc=0**；data_manage 页 800 行压线过守卫。

> ✅ **2026-09-02 W59 批次完成**（Task 11-13）：
> inference/api_client.py（multipart POST→boxes 契约/超时/非 200/缺键四分支/密钥 env>凭据文件且零日志回显）
> + api_actions Mixin（endpoint 输入+API 推理，完成链复用 _single_done）+ .gitignore 凭据防呆（W23 同型）
> + Task 12 守卫终态（FB-016 全集断言：枚举七成员/模板任务码全集；新模块覆盖率 87-100% 总 95%）+ code-reviewer 复核
> + **AC-002 缺口修正**：W55 顶点编辑面扩展至 CUT_LINE（≥2 点）/OPERATION（角点拖拽改尺寸，拒插删点）
> ——立项时 AC-002 假设 EDIT 全形态可用，实测仅多边形。
> code-reviewer 复核（0C/1H/4M/5L）：HIGH+4MEDIUM+3LOW 全修（模板 loader 启动链收口/API 契约收口/模板增强段断链/keypoint 诚实跳过/统计容错/互斥与文案/原子写），2 LOW 记录；
> 门禁终态 **1318 passed / 5 skipped / rc=0**；ruff 0 error；总检 grep 全净（0 调试残留/0 硬编码密钥）。
> **发版窗留项**：exe 重打包+PYZ 守卫/lite 派生实测（零新依赖预期零增量）/UIA 回归（新切割线用例）——环境窗操作标 N/A 待发版；
> AC-010（SKolpha 实机核对三处推断级语义，用户配合项 D-4）保持开放；NFR-001 并行吞吐计时断言未落（完整性+排序已验，记健康度待补）。


> ✅ **2026-09-02 W60 批次完成**（P2 收官：FR-008 实施 + FR-009/010 评估缓办）：
> 裁剪数据集（图像+标注配对瓦片，补 cut_annotations 缺失的图像侧）/ 照片尾缀修改（NTFS 大小写归一同文件豁免）
> / 数据清洗（坏图+孤立标注扫描，确认后移入 _trash 可逆隔离，不硬删）；
> 存量三件（统计/替换/删除）抽至 LabelToolsMixin（页面 800→716 行腾位），W35 门控测试补双模块补丁。
> FR-009 缓办（零引擎实现 train_epoch，子进程隔离无真实负载）；FR-010 缓办（super 推理-only+零依赖约束）——依据见 PRD §3.1 裁决记录与偏差账 D-15/16。
> 门禁 **1324 passed / 5 skipped / rc=0**；ruff 0 error。经验 EXP-20260902e（NTFS 大小写三坑）。

---

## 任务列表

### Task 1 (W56-0): 前置核查与 RED 基线
- **复杂度**: S
- **关联需求**: 全局（FR-001..007 消费方安全网）
- **涉及文件**:
  - `.workflow/skolpha-replication/` (新建留痕目录)
  - `tests/test_w56_consumers_probe.py` (新建)
- **详细步骤**:
  1. 五方消费方核查（FB-005）：AnnotationMode 与 TrainConfig 的 生产代码/单元测试/UIA/脚本/守卫测试 五方清单落 `.workflow/skolpha-replication/consumers-w56.md`
  2. 用 decrypt_skolpha.py（%TEMP%/skolpha-forensics 工具链）解密 TrainConfigs 9 类模板 → 提取参数初值字典（img_scale/split/data_expansion/max_rotate/translate/flip 等 30+ 项）落 `configs/train_templates/_source_dict.json`（草值，Task 5 转正式 YAML）
  3. 写 RED 探针测试（AnnotationMode 新成员尚不存在→collect 必红），确认红灯可见
- **验证方式**:
  - [ ] 语法检查: `ruff check .` 0 error
  - [ ] 功能测试: 探针测试 RED（证明守卫先于实现存在）
  - [ ] 回归确认: 主门禁不跑（无生产改动）
- **依赖关系**: **前置**: 无（首个任务） | **阻塞**: Task 2/3/5
- **风险提示**: 解密产物只读取证（PRD §6.3 授权路径），不修改 SKolpha 安装目录

### Task 2 (W56-A): 切割线 + 操作标注全链路（TDD）
- **复杂度**: L
- **关联需求**: FR-001, FR-002
- **涉及文件**: 见 Design §3 前 8 行（base/modes×2/modes__init__/canvas/io_labelme/label page/spec/i18n）
- **详细步骤**:
  1. RED：tests/test_w56_label_modes_industrial.py（Design §9.2 用例 1-3 + roundtrip + 未知形态兼容）
  2. GREEN：CutLineLabeler/OperationLabeler + 枚举 + 注册 + canvas 虚线渲染 + io_labelme linestrip/operation:true 映射
  3. label 页工具栏 +2 按钮、快捷键 C/O、i18n 双语键
  4. transferType 联动钩子（为 Task 8 预留接口 `set_default_shape_mode(mode)`，本任务仅实现函数不接项目信号）
  5. spec hiddenimports + PYZ 守卫口径同步；动态导入守卫增行
- **验证方式**:
  - [ ] 语法检查: `ruff check` 0 error
  - [ ] 功能测试: AC-001（枚举=7/按钮=7/快捷键）+ AC-002（roundtrip）
  - [ ] 回归确认: 既有 5 形态用例全绿；主门禁 fail-under 92
- **依赖关系**: **前置**: Task 1 | **阻塞**: Task 4
- **风险提示**: 语义为推断级（🔎）——若用户实机核对（AC-010）先行推翻，按新语义改本任务映射再落码

### Task 3 (W56-B): 批量预测模式与并发选项（TDD）
- **复杂度**: M
- **关联需求**: FR-003
- **涉及文件**: `gui/pages/predict/batch_runner.py` (修改)、`gui/pages/predict/batch_actions.py` (新建)、`gui/core/i18n.py` (追加键)
- **详细步骤**:
  1. RED：tests/test_w56_batch_modes.py（用例 4-5：incremental 取消语义/并发一致性集合比较/滚动落盘）
  2. GREEN：run_batch 增 mode/concurrency 参数（引擎前向保持串行，ThreadPool 仅后处理层）；incremental 每 10 张滚动原子落盘
  3. batch_actions Mixin：模式选项组+并发微调（1-4 默认 1）+「从项目带入」按钮位（Task 8 接线）
- **验证方式**:
  - [ ] 语法检查: ruff 0 error
  - [ ] 功能测试: AC-003 两模式；既有 W18 批量取消用例零改动全绿
  - [ ] 回归确认: page.py 行数不增（Mixin 外置——W24 ≤800 守卫）
- **依赖关系**: **前置**: Task 2（i18n.py 排队编辑） | **阻塞**: Task 4
- **风险提示**: 竞态高危（PRD §8.2 🔴）——默认串行不动现有行为；并行路径先写失败注入测试（两线程同时落盘）再实现

### Task 4 (W56-V): W56 波验收
- **复杂度**: S
- **关联需求**: AC-001/002/003/008（波内部分）
- **验证方式**:
  - [ ] 主门禁全量 rc=0（fail-under 92）；规模守卫绿（label/predict 页 ≤800）
  - [ ] `grep -rnE "CUT_LINE|OPERATION" tests/ | wc -l` ≥ 探针数（守卫增量生长 FB-016）
- **依赖关系**: **前置**: Task 2, Task 3 | **阻塞**: Task 5（波门）

### Task 5 (W57-A): 训练模板 loader 与 TrainConfig 扩展（TDD）
- **复杂度**: M
- **关联需求**: FR-004
- **涉及文件**: `training/train_templates.py` (新建)、`configs/train_templates/*.yaml` (新建 ≥9×1)、`core/interfaces_supervised.py` (修改)、`configs/train_templates/_source_dict.json` (转正/删除)
- **详细步骤**:
  1. RED：tests/test_w57_train_templates.py（用例 6：加载/校验/未知字段告警/缺目录回退/AugmentationConfig 默认值）
  2. GREEN：TrainTemplate/load_templates/validate_raw + AugmentationConfig 冻结 dataclass + TrainConfig.augmentation 可选段（Task 1 五方清单逐项核对消费者）
  3. _source_dict.json → 正式 YAML（9 任务码 normal/small/large 变体按 SKolpha 粒度取舍——至少 normal）
- **验证方式**:
  - [ ] AC-004 前半：模板数 ≥9×1、明文（grep -c "gAAAAA" configs/train_templates/ = 0）
  - [ ] TrainConfig 旧行为零变化：既有训练用例全绿
- **依赖关系**: **前置**: Task 4 | **阻塞**: Task 6

### Task 6 (W57-B): 训练页模板 UI（TDD）
- **复杂度**: M
- **关联需求**: FR-004
- **涉及文件**: `gui/pages/train/page.py` (修改，模板下拉)、`gui/pages/train/train_augment_actions.py` (新建 Mixin)、i18n
- **详细步骤**: RED（表单回填断言）→ 模板下拉+回填+状态栏提示 → 增强参数面板（augmentation 字段控件进 Mixin）→ 引擎无增强消费时诚实提示（「当前引擎忽略增强参数」）
- **验证方式**: AC-004 后半（UI 选择→TrainConfig 反映）；train/page.py ≤800 守卫绿
- **依赖关系**: **前置**: Task 5 | **阻塞**: Task 7

### Task 7 (W57-V): W57 波验收
- **复杂度**: S | **验证方式**: AC-004 全过 + 主门禁 rc=0 + 守卫增量行（模板加载测试进 W 守卫）
- **依赖关系**: **前置**: Task 6 | **阻塞**: Task 8/9（波门）

### Task 8 (W58-A): 工程绑定三段（TDD）
- **复杂度**: M
- **关联需求**: FR-005
- **涉及文件**: `project/store.py` (修改)、`gui/pages/predict/batch_actions.py` (接线带入按钮)、`gui/pages/label/page.py` (transferType 联动)、tests
- **详细步骤**: RED（用例 7：旧项目缺段默认/写读一致）→ ProjectBinding + get/set_binding + binding.json 原子写 → predict「从项目带入」接线 → label transferType→set_default_shape_mode 接线（Task 2 预留接口）
- **验证方式**: AC-005 全过（带出/联动/兼容三断言）
- **依赖关系**: **前置**: Task 7 | **阻塞**: Task 10 | **可与 Task 9 并行**（文件域不交）

### Task 9 (W58-B): 数据工具三件（TDD）
- **复杂度**: M
- **关联需求**: FR-006
- **涉及文件**: `project/label_tools.py` (新建)、`gui/pages/data_manage/tools_actions.py` (新建 Mixin)、tests
- **详细步骤**: RED（用例 8）→ 统计/替换/删除纯函数（.bak+原子写+Report）→ Mixin 对话框+run_job 调度+进度/结果摘要
- **验证方式**: AC-006 全过；data_manage/page.py 零增行（守卫验证）
- **依赖关系**: **前置**: Task 7 | **阻塞**: Task 10 | **与 Task 8 并行**

### Task 10 (W58-V): W58 波验收
- **复杂度**: S | **验证方式**: AC-005/006 + 主门禁 rc=0 + data_manage/predict 页 ≤800
- **依赖关系**: **前置**: Task 8, 9 | **阻塞**: Task 11（波门）

### Task 11 (W59-A): HTTP API 推理（TDD）
- **复杂度**: M
- **关联需求**: FR-007
- **涉及文件**: `inference/api_client.py` (新建)、`gui/pages/predict/api_actions.py` (新建 Mixin)、`.gitignore` (+configs/api_key.txt)、tests（含元守卫 pathspec 追加——W23 initial_credentials 同型防呆）
- **详细步骤**: RED（用例 9：mock server 三失败分支+契约解析）→ infer_remote/resolve_api_key → API 源 UI（endpoint 输入+推理按钮，结果与本地同表）→ .gitignore+元守卫
- **验证方式**: AC-007 全过（三分支/入表/`grep -rnE "api[_-]?key\s*=\s*[\"'][^\"']+[\"']"` 生产码命中=0）
- **依赖关系**: **前置**: Task 10 | **阻塞**: Task 12

### Task 12 (N-1): 测试与守卫终态（强制·TDD 收口）
- **复杂度**: M
- **关联需求**: 全部核心 FR
- **详细步骤**:
  1. 核对 Design §9.2 用例 1-9 全部存在且绿；补漏
  2. 守卫全集相等断言（FB-016）：Task 1-11 增量守卫行翻新为全集 Enum 断言（AnnotationMode 七成员全集 / 模板任务码全集 / 模式模块文件清单全集）
  3. 覆盖率核查：新模块 ≥80%（PRD §5.2 质量线）；整体不低于波前基线
  4. code-reviewer 复核无 CRITICAL/HIGH
- **验证方式**（三件套）: 命令 `python -m pytest --cov` / 阈值 rc=0 且 fail-under=92 / 不达标：补测试或申报降级由用户确认
- **依赖关系**: **前置**: Task 11 | **阻塞**: Task 13

### Task 13 (N): 集成验证（强制末位）
- **复杂度**: M
- **关联需求**: 全部 AC
- **详细步骤**:
  1. 启动 GUI（源码态）走用户旅程：切割线标注→保存重开；模板选择→训练配置；项目绑定→预测带出；数据工具三件；API 源 mock
  2. exe 重打包 + PYZ 守卫（labeling 30 处口径）+ lite 派生 14 用例 + <2GiB
  3. UIA 回归：既有 12 用例零改动全绿（窗口期）+ 新增切割线硬断言用例 1 条
  4. AC-001..010 逐项勾验；总检 11 项；经验沉淀（Phase 4.6）
- **验证方式**:
  - [ ] AC-001..009 逐项过；AC-010 若用户未配合实机核对→标注「推断级留档+待回填」不伪造
  - [ ] UIA: 已运行通过 / 记录 N/A 原因（环境窗口）
  - [ ] lite <2GiB 实测
- **依赖关系**: **前置**: Task 12 | **阻塞**: 无

---

## 依赖关系图

```
Task 1 (W56-0 前置)
  └→ Task 2 (W56-A 标注形态·L) ─→ Task 3 (W56-B 批量模式) ─→ Task 4 (W56-V 波验收)
        │（i18n/spec 排队面，故串行）
Task 4 ─→ Task 5 (W57-A 模板loader) ─→ Task 6 (W57-B 训练UI) ─→ Task 7 (W57-V)
Task 7 ─→ Task 8 (W58-A 工程绑定) ∥ Task 9 (W58-B 数据工具) ─→ Task 10 (W58-V)
Task 10 ─→ Task 11 (W59-A API推理) ─→ Task 12 (N-1 测试守卫终态) ─→ Task 13 (N 集成验证)
```

## 关键路径分析

| 路径 | 任务序列 | 总复杂度 | 风险点 |
|------|----------|----------|--------|
| 主路径 | 1→2→3→4→5→6→7→8→10→11→12→13 | S+L+M+S+M+M+S+M+S+M+M+M | Task 2 体量最大；Task 3 竞态面 |
| 副路径 | 7→9→10 | M+S | 低风险（纯函数+Mixin） |

## 风险登记册

| 风险 | 所在任务 | 可能性 | 影响 | 缓解措施 | 负责确认 |
|------|----------|--------|------|----------|----------|
| 形态语义推断与原品不符 | Task 2 | 中 | 中 | AC-010 实机核对尽量前置于 W56；linestrip 原生形态兜底 | Task 4/13 验收 |
| 并行批量竞态 | Task 3 | 中 | 高 | 默认串行；失败注入测试先行；只并行后处理层 | Task 4 |
| TrainConfig 扩展破坏消费方 | Task 5 | 低 | 中 | Task 1 五方清单；None 默认零行为变化 | Task 7 |
| 页面超 800 行守卫 | Task 3/6/9/11 | 高 | 低 | Mixin 外置硬约束（Design §1.1） | 各波验收 |
| lite 体积超线 | Task 13 | 低 | 中 | 零新依赖约束；派生实测 14 用例 | Task 13 |
| UIA 环境窗口不可用 | Task 13 | 中 | 低 | 既有冷知识套路（空闲复跑）；N/A 留痕不伪造 | Task 13 |

## 执行约定

### 编码规范
- 遵循项目现有风格；新函数全类型标注；异常显式（AppError 家族）；常量入配置/命名常量；不可变 dataclass 优先
- **门禁三件套**: `ruff check .`（0 error）+ `python -m pytest`（rc=0，fail-under=92）+ 守卫测试（W24 规模/动态导入/PYZ）

### 验证标准
- 任务验证清单全 ✅ 才 completed；偏差即记 `.workflow/skolpha-replication/deviations.md`；新发现入风险登记册

### 进度汇报（L3 节奏）
- 每 2-3 任务汇报；修复尝试上限 3 次/任务（超限→回滚决策协议）；连续 2 任务失败→逃生通道（诊断三选一）

---

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 1.0 | 2026-09-02 | 初始版本（L3 立项） | Claude |

---

## 自检（7 项）
- [x] **原子性**: 13 任务各自单一目标可独立验证
- [x] **依赖正确**: 依赖图人工拓扑核对无环；并行仅 Task 8∥9（文件域不交已核）
- [x] **验证可行**: 每任务三件套/AC 锚点可判定
- [x] **覆盖完整**: FR-001..007 ↔ Task 2/3/5/6/8/9/11 全覆盖；FR-008..010 明确列后续波次（P2）
- [x] **工作量合理**: 无超 L 任务（Task 2=L 已按全链路上限标注）
- [x] **风险已识别**: 登记册 6 项含缓解
- [x] **执行约定明确**: 门禁三件套+汇报节奏+回滚上限

## ✅ 门禁（Phase 3 · 最终关口）
- [ ] ⛔ **停点**: 用 AskUserQuestion 确认「📝 编码任务规划已生成，确认后开始编码执行」——**本自治会话不自行开工**，交用户裁决（可连同 PRD D-1..D-4 一并拍板；裁决记录回填本节）

## 跨阶段一致性检查

| 检查项 | 方法 | 结果 |
|--------|------|------|
| FR → Tasks 覆盖 | FR-001..007 ↔ Task 2/3/5/6/8/9/11；FR-008..010 标 P2 后续波 | ✅ |
| AC → Tasks 覆盖 | AC-001/002→T2/T4；AC-003→T3/T4；AC-004→T5/T6/T7；AC-005→T8/T10；AC-006→T9/T10；AC-007→T11；AC-008/009→T12/T13；AC-010→T13（留档分支） | ✅ |
| Design 组件 → Tasks | §4.1→T2；§4.2→T3；§4.3→T5；§4.4→T8；§4.5→T9；§4.6→T11 | ✅ |
| 测试策略 → 测试任务 | Design §9.2 用例 1-9 ↔ 各任务 RED + T12 收口全集 | ✅ |
| 文件变更清单 → Tasks | Design §3 23 项 ↔ T2(8)/T3(3)/T5(4)/T6(3)/T8(4)/T9(3)/T11(4)/T12/T13(spec/i18n 终态) | ✅ |
