# W38 发版纠偏波（v6 P1×2 + P2×2 清偿） — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-23 | 档位: 🟡 L2 | 确定性: 高（修法均经 v6 双源验证） | 影响半径: 大（i18n 守卫语义 + 发版元数据 + 批量预标注生产写盘路径；未命中 7 类硬触发器） | 可逆性: 双向门（git 精确回退）
> 前置：docs/AutoVisionAgent-架构解析与优化方案-v6.md §8 第一波（探索门禁已裁决：UIA 推迟空闲窗口 / 版本对齐 2.1.0+补 tag）。

## 1. 背景与目标

- **背景**：v6 深审发现 P1×2（i18n 转义错位键运行时永不生效且守卫归一化假绿；pyproject 停 2.0.0 无版本守卫）与 P2×2（守卫单引号盲区 6 处漏翻；跨盘符批量预标注整批静默失败），均为 v2.1.0 发版宣称与实际的落差。
- **目标**：
  1. 四项修复全部落地且 TDD 先红后绿（守卫类修复=守卫自身口径修正+断言加固）
  2. 受影响回归套件全绿，无范围蔓延（第二波护栏项明确不做）
  3. 版本四方一致 + tag v2.1.0 补打在修复 commit（commit/tag 均经门禁批准）

## 2. 功能需求 (FR)

- **FR-001**: P1-1 i18n 转义错位修复 — ① `gui/core/i18n.py` `_EN_US` 中源文本含双反斜杠（`\\`）的键改为单反斜杠转义（运行时与调用点等价）② 守卫 `_dict_keys()` 删除 `\\→\` 归一化（假绿根源）③ 守卫新增断言：字典键源文本不得含 `\\` ④ 功能断言：en_US 模式 `tr("有正在进行的操作（训练/推理）。\n")` 返回英文。 | P0
- **FR-002**: P2-5 守卫扩单引号口径 — `_tr_literals()` 正则扩至 `tr('...')` 单引号字面量；补 6 词条（`旧`/`新`/`处差异`/`项`/`……其余`/`项略`，英文 Old/New/differences/items/... remaining/omitted）；探针测试同步覆盖单引号样例；口径声明（docstring）更新。 | P0
- **FR-003**: P1-2 版本四方守卫 — `pyproject.toml` 2.0.0→2.1.0；新增 `tests/test_w38_version_consistency.py`：正则提取 README.md / RELEASES.md（最新条目）/ gui/pages/settings/page.py / pyproject.toml 四处版本号断言一致。 | P0
- **FR-004**: P2-2 跨盘回退 — `gui/pages/label/batch_prelabel.py`：`os.path.splitdrive` 判 image_path 与 out_dir 跨盘 → 回退写绝对路径（LabelMe 兼容）；manifest 增 `relpath_fallback` 列表（additive，向后兼容）区分「跨盘回退」与「坏图」；`tests/test_w30_batch_prelabel.py` 增跨盘用例（真盘符 C:/E:，单盘环境 skip）。 | P0
- **FR-005**: P2-1 UIA 12/12 — 显式排期项：用户空闲窗口执行 `pytest tests/uia/`（约 10 分钟），本波不编码不执行。 | P1
- **FR-006**: 收尾补 tag — commit 经门禁批准后，`git tag v2.1.0` 打在修复 commit 上。 | P1

## 3. 验收标准 (AC)

- **AC-001**: FR-001 先红后绿——新增转义断言在修复前命中 ≥1 键（红）、修复后 0（绿）；运行时验证 en_US `tr()` 返回英文（命令对照） [FR-001]
- **AC-002**: 守卫扩口径后 `pytest tests/test_w20_i18n_completeness.py` 全绿且扫描面探针仍 >50、含单引号样例 [FR-002]
- **AC-003**: `pytest tests/test_w38_version_consistency.py` 四方一致（修复前 pyproject 2.0.0 红 → 修复后绿）[FR-003]
- **AC-004**: 跨盘用例：不同盘符图目录 × out_dir → `written=N` 正常、`relpath_fallback` 记录、imagePath 绝对；同盘既有用例（imagepath_is_relative）不破 [FR-004]
- **AC-005**: 回归全绿：w20/w30/w35 + 新测试 + 全量收集 ≥1110；`python -m py_compile` 0 error [FR-001~004]
- **AC-006**: 无范围蔓延：`git status` 改动仅限 gui/core/i18n.py、tests/test_w20_i18n_completeness.py、pyproject.toml、gui/pages/label/batch_prelabel.py、tests/test_w30_batch_prelabel.py、tests/test_w38_version_consistency.py（新增）+ 本波 docs [全]
- **AC-007**: 新增/改写文件歧义词 grep = 0 [全]

## 4. 范围

- ✅ **In Scope**: 上列 6 FR 对应文件；W38 PRD/tasks 文档
- ❌ **Out of Scope**: 第二波护栏项（宽容态反转/离线 admin/data_manage 登记消费/标签语义统一/原子写收敛）；第三波卫生项（P3×16）；RELEASES.md 不动（修复属 2.1.0 纠偏）；单图 save() 路径决策（随二波）；分隔符 posix 归一化（P3 附注，随三波）

## 5. 风险与假设（含探索三栏）

- **已知**: 修法定位精确（v6 五元组）；守卫全文/6 键上下文已读；工作树无并行在途；C:/E: 真盘符可用
- **假设**: 守卫扩口径后缺失集合恰为已测 6 键（若暴露更多 → 全部补齐不做豁免，超 10 处即汇报）；单盘 CI 环境跨盘用例 skip 不算失败
- **未知**: 无残留（2/2 已裁决）
- **风险**: ① i18n 键修改手误（双反斜杠替换 → 用脚本定位+逐一核对 diff）；② tag 打点依赖 commit 顺序（收尾门禁统一执行 commit+tag）；③ UIA 推迟项遗忘（PRD/收尾双处留痕）

## 6. 实现思路

- **拟采用**: 逐任务 TDD（先写红测试→修生产码→绿→回归）；i18n 转义键用脚本扫描 `\\` 定位全部实例再改；版本守卫正则四处提取（RELEASES 取首个 `## v` 即最新）
- **复用**: test_w20 既有结构（_dict_keys/_tr_literals/探针）；test_w30 既有 batch_prelabel 测试模式（fixture 造图+stub 引擎）
- **注意**: manifest 新键 `relpath_fallback` 为 additive——页面消费方只读 total/written/failed/cancelled，不破坏；`_dict_keys()` 删归一化后与运行时键一一对应，需保证正则提取与 Python 解析一致（`\t`/`\\` 等转义统一按源文本比对，两侧同源故一致）

---

## 自检（5 项）

- [x] 完整性: FR-001~006 全编号
- [x] 无歧义: 本文件歧义词 grep = 0
- [x] 可追溯: 每 FR 有 AC
- [x] 范围清晰: In/Out 已列
- [x] 指标可量化: AC 均可执行判定

## ✅ 门禁（3 项）

- [x] 门禁 1 探索门禁：2 问已裁决（2026-08-23：UIA 推迟 / 对齐 2.1.0+tag）
- [x] 门禁 2 PRD：AskUserQuestion 确认 → 进入执行（2026-08-23 用户确认）
- [x] 门禁 3 收尾：AC-001~007 全过 + 全量回归 1106 绿 + commit 全部+tag v2.1.0 批准（2026-08-23 用户裁决）
