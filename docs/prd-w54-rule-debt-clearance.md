# PRD W54 · 规则债务全面清偿（ruff 棘轮 1153→0 + P0 真缺陷修复）

> 版本：v1.0（2026-08-30）｜ 档位：🟡L2 ｜ 状态：执行中
> 触发：用户显式指令「根据 E:\学习项目\视觉大模型\.qoder\rules 制定全面的修复」
> 上游：`.qoder/rules/R00-R05`（2026-08-30 六工序流水线入驻产物，AGENTS.md 索引）

## 0. 定档声明（SDW Step 0）

- 档位：🟡 L2（精简 PRD + tasks，3 门禁；自治会话按 S1 显式指令 + S3 留痕替代 AskUserQuestion）
- 确定性：高——ruff 修复方法逐类已定（安全自动修 + 逐类人工修法），P0 处已逐个读码定修法
- 影响半径：大——涉及 ~160+ 文件、12 包与 serving 对外契约层；双向门（git 干净树起点 0fa797f，逐任务原子可回滚）
- 规模：大（机械 ~919 条 + 人工判断 ~227 条 / ~40 文件）
- 可逆性：双向门
- 覆盖：无（Claude 判断即 L2；依据=高确定×大影响主矩阵）

## 1. 背景与目标

2026-08-30 六工序流水线入驻时首次安装 ruff，实测存量 **1151** 条（基线 `scripts/ruff-baseline.txt`=1153，棘轮合规但为债；AGENTS.md L0 红线③：只降不升，清偿后降基线）。其中埋有**真缺陷**：1 处语法错误（脚本无法运行）、6 处未定义名、2 处函数双定义、4 处循环变量闭包、恒假断言等。同时按 R01-R04 自检清单对架构级规则做了全面 grep 审计（结论见 §5）。

**目标**：按 .qoder/rules 全面清偿——ruff 棘轮降至 0、修复全部 P0 真缺陷、三重门禁全绿、基线文件归零。

## 2. 需求（FR）

| 编号 | 需求 | 规则依据 |
|---|---|---|
| FR-1 | P0 真缺陷修复 24 处：syntax 1（fetch_ocr_weights.py:65 f-string 多余 `}`）、F821 6（serialization.py ×5 + shared_memory.py ×1，numpy 引号注解缺 TYPE_CHECKING 导入）、F811 2（io_labelme.py 双定义、test_gui_predict_flawgen.py 函数内重复导入）、B023 4（exp_sam3_inference_params.py / exp_sam3_region_caliber.py 闭包用默认参数绑定 cx/cy）、F632 2（test_w44 `is` 比较字面量→`==`）、W605 3（两测试 docstring Windows 路径加 r 前缀）、失效 noqa 6（`# noqa: X（中文）`格式坏→修正格式保留抑制意图） | R02 §4、R04 §1 |
| FR-2 | 机械安全修复 ~919 条：UP006/UP045/UP035/UP037/UP007/UP015/UP009/I001/SIM300/B009（`ruff --fix` 安全子集，等价性由 1216 用例 + 覆盖棘轮守卫） | AGENTS.md L0③ |
| FR-3 | 判断类清偿 209 处：F401 98（tests 死导入删除 / `__init__` re-export 改 `import x as x` 形态 / 有意 side-effect 加有效 noqa+理由）、E402 31（sys.path 前置导入场景逐条 noqa+理由，R02 §4.2「注明原因」）、SIM105 29（try/except:pass→contextlib.suppress 等价改写）、F841 17（死赋值删除）、B905 7（zip 补 strict= 按语义判 True/False）、E701 6 / E702 2（拆行）、SIM115 6（测试文件句柄场景逐个判断）、E741 4（`l`→改名）、B007 5（循环变量→`_`前缀）、SIM117 2（合并 with）、SIM108 1（三元）、UP028 1（yield from） | R02 §4、R04 §1.5 |
| FR-4 | 收口：`scripts/ruff-baseline.txt` 降为 0；`bash scripts/check-gate.sh` 三段全绿（命名 PASS / ruff 0≤0 / pytest rc=0 覆盖≥92 不降） | R01 §4、R04 §1.1 |
| FR-5 | 架构审计结论留档（§5），不新增 .qoder 资产 | R00 |

## 3. 验收标准（AC）

- AC-1 `ruff check .` 0 errors（rc=0）
- AC-2 `scripts/ruff-baseline.txt` 内容 = 0
- AC-3 主门禁 `.venv/Scripts/python.exe -m pytest` rc=0，passed ≥1216，覆盖率 ≥92.82 不降（棘轮）
- AC-4 `bash scripts/check-naming.sh` PASS
- AC-5 P0 逐处验证：fetch_ocr_weights.py `py_compile` 通过；serving 两文件可导入且 ruff F821 清零；相关测试快跑绿
- AC-6 测试断言语义不变（F632 只改比较运算符；不删测试、不放宽断言——R04 §1.2）

## 4. 范围外（Out of Scope）

- 不动 `autovisionagent.spec` hiddenimports（无新模块/无依赖变化；动 spec 才触发 R01 §3.2 重打包+UIA）
- 不跑 UIA 真窗（本波仅注解/导入序/死代码级改动，不动 GUI 装配链；R04 §1.4 场景不命中）
- 不动他人未提交资产（docs/prd-sam3-region-cliff-fix.md、docs/prd-dotnet-decompile-python.md、scripts/exp_sam3_region_prompt_sweep.py 等——提交时 pathspec 精确圈定）
- 不做 PEP 604 之外的类型系统重构；不改 .qoder 规则文件本身

## 5. 架构级规则审计结论（Phase 0 取证，全部实跑证据）

| 规则项 | 结论 | 证据 |
|---|---|---|
| R01 §1.1 依赖方向 L0 | ✅ 零反向 | core/ 无 `from\|import (gui\|labeling\|...)`；领域五包无 `import gui`；serving 无跨层（Grep 三查均 No matches） |
| R03 §1.3 页面规模 ≤800 | ✅ 全合规（贴线） | label=799 / data_manage=797 / predict=782（find+wc 实测，label 距守卫 1 行） |
| R02 §2.3 无裸 except | ✅ | `except\s*:` 全仓 Grep = 0 |
| R02 §1.1 异常唯一字典 | ✅ | 自定义异常类仅 core/exceptions.py（6 个）；tests 有 1 个局部桩类（允许） |
| R03 §3.2 AVA_ 前缀 | ✅ | 非 AVA 环境变量仅 QT_QPA_PLATFORM（Qt 官方变量，非自有命名，测试态） |
| R00 命名 | ✅ | `bash scripts/check-naming.sh` PASS（rc=0） |
| ruff 棘轮 | ⚠️ 1151 ≤ 1153（合规但为债）| `ruff check . --statistics` 实跑：UP006=384/UP045=203/I001=131/UP035=128/F401=98/UP037=40/E402=30/SIM105=29/…共 1151；919 条安全可自动修 |

**结论：架构级规则全绿，债务集中在 ruff 棘轮；本波主体 = FR-2/FR-3 清偿 + FR-1 真缺陷修复。**

## 6. 风险与假设（含 D4 三栏账）

**【已知】** 见 §5；P0 24 处已逐个读码定修法；919 条安全自动修；三重门禁今日 onboarding 实测全绿（1216 passed / 92.82% / 116.70s）。
**【假设】** ①「全面的修复」= 清偿至 0 基线而非仅修 P0（棘轮条款「清偿后降基线」的自然延伸）；② 有意为之的 E402/F401（conftest sys.path、re-export、side-effect import）以有效 noqa / `as` 形态保留并注明理由；③ 双 serving 文件 F821 运行时无害（`from __future__ import annotations` 实证，serialization.py:16 / shared_memory.py:39）。
**【未知】** 无阻塞项——io_labelme 双定义两版本行为等价（读码证实，删 142-150 保留 96 版含 W1 出处）；测试断言改动语义不变（F632 处 `is` 因驻留恰好通过，`==` 同样通过）。自治会话：门禁以 S1（用户显式指令）+ S3（本档留痕）替代，回滚走协议默认分支（git 起点干净，逐任务可 revert）。

## ✅ 门禁记录（自治 S1/S3 留痕）

- 探索门禁：S1 用户显式指令「制定全面的修复」= 授权按规则全面清偿；三栏账见 §6，未知栏空。2026-08-30 过。
- PRD 门禁：S2 上游预裁决（.qoder/rules R04 §3.1 重决策落 docs/ + AGENTS.md 工作流约定「提交前必跑门禁」）→ 本 PRD 即裁决载体。2026-08-30 过。
- 收尾门禁：**过**（2026-08-30）。`bash scripts/check-gate.sh` 实跑三段全绿 rc=0：
  - [PASS] check-naming: .qoder 资产命名合规（R00）
  - [PASS] ruff 0 <= 基线 0（scripts/ruff-baseline.txt 已从 1153 降为 0）
  - pytest **1220 passed, 5 skipped, 4 warnings in 86.96s**，**Total coverage: 92.93%**（≥92 棘轮，较波前 92.82 不降反升）
  - AC-1~AC-6 全过：ruff=0 ✓ / 基线=0 ✓ / pytest 1220≥1216 且覆盖 92.93≥92.82 ✓ / naming PASS ✓ / fetch_ocr_weights py_compile 通过 + F821 清零 ✓ / 断言仅改比较运算符、测试零删零放宽 ✓
  - 附带产出：check-gate.sh ruff 段零基线假红缺陷修复（sys 记录 20260830_script_check-gate-zero-ratchet）；共享工作区并发流处置与混流文件排除清单见 tasks v1.1 偏差②。
