# PRD：W29 角色权限最小面（L2 · 精简 PRD）

> 版本 1.0 · 2026-08-22 · 上游：`.claude/plan/skolpha-benchmark-optimization.md` W29 节（用户已批准）
> 档位：🟡L2（高确定 × 大影响——硬触发器 #3 安全关键逻辑〔权限门控〕）
> 门禁代偿：本 harness 无 AskUserQuestion；探索门/PRD 门/收尾门以「计划批准 + 用户指令『继续 W29』」为代偿授权，偏差已记录。

## §1 背景与目标

角色自 W18 起稳定枚举（admin/engineer/operator）且登录审计在案，但**零消费**：
gui/main.py 登录成功处理器字面丢弃 role；登录页角色下拉纯装饰（`_do_login`
从不读取）。本波把角色从「存储+审计」推进到「存储+审计+**消费**」最小闭环：
页面可见性过滤 + 被拒访问审计。

**诚实边界（docstring 级声明）**：本门控是**操作护栏非安全边界**——
users.json 本地可编辑、单工位进程无提权防护；目标是现场职责分离
（操作员不误入系统设置/发布），不防恶意本地用户。

## §2 功能需求（FR）

| # | 需求 |
|---|------|
| FR-1 | 新建 `gui/core/permissions.py` 纯函数（零 Qt）：`page_allowed(role, page_id)` / `action_allowed(role, action)` + 角色常量 + 矩阵；docstring 诚实声明护栏属性 |
| FR-2 | MainWindow `set_role(role)`：登录成功处消费 role → 导航按钮可见性过滤 + `select()` 守卫（拒绝时不切页 + 状态栏提示 + 审计 `access_denied`） |
| FR-3 | 页面矩阵：admin 全 11 页；engineer 除 settings；operator = home/label/data_manage/predict/eval（最小特权：现场操作页，排除 train/deploy/flaw_gen/project/settings） |
| FR-4 | 登录页恒允许；未知页/未知角色 → 最小集（默认拒绝） |
| FR-5 | 离线模式会话角色改为 admin（`_do_offline` emit + 审计一致）：离线=本机单工位完整权限（确认框「受限」指无 License 单工位，非页面裁剪）；否则 12 条 UIA（全走离线路径，导航覆盖 9 页）全崩 |
| FR-6 | 登录页装饰性角色下拉删除（虚假控件——选择从未被消费） |
| FR-7 | 拒绝文案 i18n zh+en 同 commit；action_allowed 动作清单**不冻结**（W30/W33/W34 各波按冻结动作集补矩阵，未注册动作默认全角色拒绝） |

## §3 验收标准（AC）

- AC-1 operator：settings/train/deploy/flaw_gen/project 为 False；home/label/data_manage/predict/eval 为 True
- AC-2 engineer：train/eval/deploy True；settings False
- AC-3 admin：11 页全 True
- AC-4 拒绝访问：不切页 + 状态栏含拒绝文案 + audit 记 `access_denied`（user/role/page）
- AC-5 离线 emit `("offline", "admin")`；UIA 12 用例零破坏
- AC-6 permissions.py 零 Qt import（AST 守卫）；未注册 action 三角色全 False
- AC-7 `set_role` 后导航按钮可见性即时同步

## §4 范围外（Out of Scope）

action 级消费点（W30/W33/W34 逐波）；登出/切换用户；多用户管理 UI；
安全加固（users.json 权限）；服务端鉴权。

## §5 风险与假设（含探索三栏）

【已知】角色枚举/login_success(user,role)/audit log 模式/UIA 走离线路径（9 页导航）
【假设】①operator 矩阵=现场操作页（计划只锁 settings 不可见，其余按最小特权+工业职责设计选择）②离线=admin 语义成立（无认证的旁路模式本就等价本机所有者）
【未知】无
风险：①既有 4 处测试锚定 offline→operator 需随语义迁移；②登录页删下拉影响 retranslate/枚举测试（删除锚定装饰控件的用例）；③未登录态（role=None）保持宽容（全可见）——既有测试与 UIA 在登录前不触导航，且 W29 消费点按计划锚定登录成功处。

## §6 实现思路

`permissions.py`（角色常量真源，login 页 re-export 兼容既有 import 路径）→
`shell.py` 增 `_active_role`/`set_role`/`_apply_nav_visibility` + select 守卫 →
`main.py` `_on_login_success` 加 `win.set_role(role)` → `login/page.py`
offline 改 emit admin + 删装饰下拉 → `audit_logger` 增 `log_access_denied`。

---
- ✅ 探索门禁：代偿通过（计划批准 + 用户指令；三栏已并入 §5）
- ✅ PRD 门禁：代偿通过（同上）
