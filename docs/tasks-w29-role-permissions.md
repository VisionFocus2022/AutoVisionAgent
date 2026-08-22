# 任务列表：W29 角色权限最小面（L2 · tasks-lite）

> 版本 1.0 · 2026-08-22 · 上游 PRD：`docs/prd-w29-role-permissions.md`
> 追溯：FR-1..7 ↔ Task 1..4；AC-1..7 ↔ 各任务验证项

## Task 1 · permissions 纯函数面（FR-1/3/4/7）
- RED：`tests/test_w29_permissions.py`（矩阵三角色/登录页恒允许/未知角色最小集/未注册动作全拒/零 Qt AST 守卫）
- GREEN：`gui/core/permissions.py`（角色常量真源 + 页面矩阵 + 空 action 矩阵默认拒绝）
- 验证：新文件单跑全绿（AC-1/2/3/6）

## Task 2 · MainWindow 消费接线（FR-2）
- RED：`set_role` 导航可见性（AC-7）+ 拒绝 select 不切页/状态栏/审计（AC-4）
- GREEN：`gui/core/shell.py` 增 `_active_role`/`set_role`/`_apply_nav_visibility`/select 守卫；`core/audit_logger.py` 增 `log_access_denied`
- 验证：新用例 + 既有 shell/窗口测试全绿

## Task 3 · 登录链路角色语义（FR-5/6）
- RED：offline emit ("offline","admin")；gui/main `_on_login_success` 消费 role（源码守卫）
- GREEN：`gui/pages/login/page.py`（offline 改 admin + 审计一致 + 删装饰下拉/_role_display_map；ROLE_* 改 import 自 permissions 保 re-export）；`gui/main.py` 加 `win.set_role(_role)`
- 迁移：test_gui_pages_more（offline→admin）、test_w18_role_enum（offline→admin；删 role_combo 用例）、test_m2_e2e 注释
- 验证：AC-5 断言绿 + 既有登录面测试迁移后全绿

## Task 4 · 收尾（FR-7 + 全量验证）
- i18n 拒绝词条 zh+en；全量门禁（1042 基线 + 新增严丝合缝）；`--clean` 重打包 + PYZ 含 `gui.core.permissions` + lite 重派生；UIA 抽查（predict/pole 设置流——离线=admin 全可见零破坏）；.workflow 状态留档 + commit（门禁代偿授权下不自动 push）
- 验证：AC 全过 + 总检 11 项

---
- ✅ Tasks 门禁：代偿通过（计划批准 + 用户指令）
