# W39 护栏收口+卫生 — 任务列表 (L2)

> 关联: prd-w39-guardrail-hygiene.md v1.0（门禁 2 已过，2026-08-23）
> RED 基线：未登录=全放行（旧语义）；data_manage 三工具零门控；单张预标注 labels[0]；原子写 3 处定义；门控顺序 2 处违约定；审计 page 字段混载；16 死键在；FakeThread 多副本。

## 任务列表

### Task 1: FR-001/002 宽容态反转 + 离线降级（语义组·先建新测试基线）
- **步骤**: 1. 新增新语义测试（未登录→operator 集：锁页导航隐藏+select 拒绝+审计；check_action 未登录走 operator 矩阵；离线→operator）→ RED 2. 改 shell.py 两处 None 特赦 + check_action + login/page.py:543 + docstring 3. 更新旧语义断言（test_w29/test_w35/test_gui_login_page）4. 受影响套件绿
- **涉及文件**: `gui/core/shell.py`、`gui/core/permissions.py`、`gui/pages/login/page.py`、tests/test_w29_permissions.py、tests/test_w35_action_gate.py、tests/test_gui_login_page.py
- **验证**: 新语义测试绿 + AC-001/002

### Task 2: FR-003 data_manage 批量工具入控
- **步骤**: 1. RED：页面级门控测试（哨兵模式仿 test_w35）2. `_ACTION_MATRIX` 登记 `data_manage.batch_label_edit` 3. 三按钮入口 `check_action` 消费
- **涉及文件**: `gui/core/permissions.py`、`gui/pages/data_manage/page.py`、tests/test_w35_action_gate.py（扩）
- **验证**: AC-003

### Task 3: FR-004 标签语义统一（逐框）
- **步骤**: 1. RED：多类 DET 单张预标注逐框标签测试 2. `label/workers.py` `labels[0]`→`labels[i]` 3. 既有套件绿
- **涉及文件**: `gui/pages/label/workers.py`、tests（test_w30 或新用例）
- **验证**: AC-004

### Task 4: FR-005 原子写收敛单源
- **步骤**: 1. `labeling/batch_tools.py` 强版公开为 `atomic_write_json`（保旧名别名）2. predict/workers.py、label/batch_prelabel.py 删本地版改 import 3. grep 定义=1 + 套件绿
- **涉及文件**: `labeling/batch_tools.py`、`gui/pages/predict/workers.py`、`gui/pages/label/batch_prelabel.py`
- **验证**: AC-005

### Task 5: FR-006 门控顺序统一
- **步骤**: predict/page.py `_batch_infer`、video_super_actions.py 的 check_action 移至入口首行；test_w35 页面测试适配
- **验证**: AC-006（grep 顺序证据）

### Task 6: FR-007 审计一致性
- **步骤**: 1. check_action 审计 `page=f"action:{action}"` 2. predict/page.py 裸 pass→logger.warning 3. audit_logger mkdir 入 try + buffer 上限 1000 + 测试
- **涉及文件**: `gui/core/permissions.py`、`gui/pages/predict/page.py`、`core/audit_logger.py`
- **验证**: AC-007

### Task 7: FR-008 卫生四件
- **步骤**: 1. permissions 模块头补声明 2. 16 死键主会话 grep 双源复核后删除 3. 死控件 grep 测试引用→删 4. `rmdir unused/`
- **涉及文件**: `gui/core/permissions.py`、`gui/core/i18n.py`、`gui/pages/login/page.py`
- **验证**: AC-008

### Task 8: FR-009 测试卫生
- **步骤**: 1. test_w35 接线断言行为化 + 删死 FakeThread + docstring 4→3 2. FakeThread/fake_threads 上移 tests/conftest.py，grep 清单驱动删本地副本
- **涉及文件**: tests/conftest.py、test_w35_action_gate.py、~6-8 个测试文件
- **验证**: AC-009（全仓定义=1）

### Task 9: 集成验证 + 收尾（强制末位）
- **步骤**: 1. 全量回归 + py_compile + 歧义词/残留 grep 2. git status 范围核对 3. 门禁 3（commit 批准）4. 沉淀 EXP+learning（将达 5/5 → 综合学习提案随收尾门禁出示）5. RELEASES 不动
- **验证**: AC-010 + 总检 11 项

## 执行约定

- 修复尝试上限 3 次；每 3 任务汇报；反转影响面超预期 → 升档协议。
