"""角色权限面（W29）：页面可见性 + 动作允许的纯函数矩阵。

诚实声明：本模块是【操作护栏非安全边界】——users.json 本地可编辑、
单工位进程内的角色状态可被本地调试工具改写。目标是现场职责分离
（操作员不误入系统设置/发布等工程域），不防恶意本地用户。

消费方：MainWindow 导航可见性过滤与 select 守卫（gui/core/shell.py），
登录成功处注入角色（gui/main.py）。角色常量为全仓真源——登录页
（gui/pages/login/page.py）自此 import 并 re-export 兼容既有路径。

action_allowed 动作清单**有意不冻结**（W26 计划批判修正）：W30/W33/W34
各波冻结自身动作集后逐波登记到 _ACTION_MATRIX；未注册动作默认全角色
拒绝（漏登记=显式拒绝而非静默放行）。
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ---- 角色稳定枚举（W18 语义延续；login 页 re-export 兼容） ----
ROLE_ADMIN = "admin"
ROLE_ENGINEER = "engineer"
ROLE_OPERATOR = "operator"

ROLES: Tuple[str, str, str] = (ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR)

# 登录页恒允许（认证入口；登出/回登录不受门控）
LOGIN_PAGE = "login"

# 全部受门控页面（与 gui.main build_window 注册的 11 页一致）
ALL_PAGES: FrozenSet[str] = frozenset({
    "home", "label", "data_manage", "train", "predict",
    "eval", "deploy", "flaw_gen", "project", "settings",
}) | {LOGIN_PAGE}

# ---- 页面矩阵（W29 最小面；operator=现场操作页最小特权） ----
_PAGE_MATRIX: Dict[str, FrozenSet[str]] = {
    ROLE_ADMIN: ALL_PAGES,
    # 工程师：全部业务页；settings（系统级配置）归管理员
    ROLE_ENGINEER: ALL_PAGES - {"settings"},
    # 操作员：标注/数据管理/推理/评估/主页；train/deploy/flaw_gen/project/settings 不可见
    ROLE_OPERATOR: frozenset({
        "home", "label", "data_manage", "predict", "eval", LOGIN_PAGE,
    }),
}

# ---- 动作矩阵（W29 空集起步；各波冻结动作集后逐波登记） ----
# W30：批量预标注（标注页 operator 可见，动作不收紧——三角色全允许）
_ACTION_MATRIX: Dict[str, FrozenSet[str]] = {
    "label.batch_prelabel": frozenset({ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR}),
}


def page_allowed(role: str, page_id: str) -> bool:
    """角色是否可访问页面。

    - 登录页恒允许；
    - 未知/异常角色 → operator 最小集（默认最小特权，不放大）；
    - 未知页 id → 拒绝。
    """
    if page_id == LOGIN_PAGE:
        return True
    pages = _PAGE_MATRIX.get(role, _PAGE_MATRIX[ROLE_OPERATOR])
    return page_id in pages


def action_allowed(role: str, action: str) -> bool:
    """角色是否允许动作（W29 最小面：未注册动作全角色拒绝）。

    后续波次（W30 批量预标注 / W33 批量产物 / W34 视频）冻结各自动作
    集后在此登记：_ACTION_MATRIX[action] = frozenset({ROLE_...})。
    """
    allowed = _ACTION_MATRIX.get(action)
    return allowed is not None and role in allowed


__all__ = [
    "ROLE_ADMIN",
    "ROLE_ENGINEER",
    "ROLE_OPERATOR",
    "ROLES",
    "LOGIN_PAGE",
    "ALL_PAGES",
    "page_allowed",
    "action_allowed",
]
