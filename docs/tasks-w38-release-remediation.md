# W38 发版纠偏 — 任务列表 (L2)

> 关联: prd-w38-release-remediation.md v1.0（门禁 2 已过，2026-08-23）
> RED 基线：守卫归一化在（删后转义键应红）；单引号不在口径；pyproject 2.0.0；跨盘场景整批 failed；test_w38_version_consistency 不存在。

## 任务列表

### Task 1: P1-1 i18n 转义键修复 + 守卫去归一化（TDD）
- **步骤**: 1. RED：test_w20 删 `_dict_keys()` 归一化 + 新增「键源文本禁含 `\\`」断言 + 「运行时命中转义键」功能测试 → 跑红 2. GREEN：i18n.py 含 `\\` 的键行改单反斜杠 → 绿 3. docstring 口径更新
- **涉及文件**: `gui/core/i18n.py`、`tests/test_w20_i18n_completeness.py`
- **验证**: `pytest tests/test_w20_i18n_completeness.py -q` 全绿；运行时 `tr()` 返回英文 → AC-001

### Task 2: P2-5 守卫扩单引号口径 + 6 词条（TDD）
- **步骤**: 1. RED：`_tr_literals()` 正则扩单引号 → 跑红（6 键缺失）2. GREEN：i18n.py 补 6 词条（Old/New/differences/items/... remaining/omitted）3. 探针补单引号样例断言
- **涉及文件**: `tests/test_w20_i18n_completeness.py`、`gui/core/i18n.py`
- **验证**: w20 全绿 + 扫描面探针含单引号样例 → AC-002

### Task 3: P1-2 版本四方守卫（TDD）
- **步骤**: 1. RED：新建 tests/test_w38_version_consistency.py（README/RELEASES/settings/pyproject 四方正则提取比对）→ pyproject 2.0.0 红 2. GREEN：pyproject → 2.1.0
- **涉及文件**: `tests/test_w38_version_consistency.py`（新）、`pyproject.toml`
- **验证**: 新测试绿 + 四方均 2.1.0 → AC-003

### Task 4: P2-2 跨盘回退 + manifest 区分（TDD）
- **步骤**: 1. RED：test_w30_batch_prelabel.py 增跨盘用例（C:/E: 真盘符、单盘 skip）：断言 written 正常 + `relpath_fallback` 记录 + imagePath 绝对 2. GREEN：batch_prelabel.py `splitdrive` 判跨盘 → 绝对路径回退 + manifest 增 `relpath_fallback` 3. 同盘既有用例复跑
- **涉及文件**: `gui/pages/label/batch_prelabel.py`、`tests/test_w30_batch_prelabel.py`
- **验证**: 跨盘用例绿 + 既有相对化用例绿 → AC-004

### Task 5: 回归 + 收尾（强制末位任务）
- **步骤**: 1. 全量收集 + 受影响套件（w20/w30/w35/w38）+ py_compile 2. 歧义词/残留 grep 3. git diff 范围核对（AC-006）4. 门禁 3 AskUserQuestion（含 commit + tag v2.1.0 批准）5. 沉淀 EXP + learning 文档
- **验证**: AC-005/006/007 全过 → 收尾

## 执行约定

- 修复尝试上限 3 次；每 3 任务汇报；UIA 12/12 为排期项（用户空闲窗口，非本波）。
