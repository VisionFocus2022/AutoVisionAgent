"""登录页（FR-D2）— 对标 SKolpha 登录/License 验证。

本地用户认证：用户名+密码 PBKDF2 加盐比对 configs/users.json。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from core.auth import hash_password as _hash_password
from core.auth import verify_and_migrate as _verify_and_migrate
from core.auth import verify_password as _verify_password
from core.constants import CONFIG_DIR as _CONFIG_DIR

logger = logging.getLogger(__name__)

# 安全参数
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 分钟锁定

# W19（v3 第三波 FR-5.1）：初始凭据一次性文件——替代日志明文通道；
# 改密成功后由 _remove_initial_credentials 删除（FR-5.2）
_INITIAL_CREDENTIALS_FILENAME = "initial_credentials.txt"

# ---- W18 / P2-8: 角色稳定枚举 ----
# 持久层（users.json）与 login_success 信号只落枚举值，与界面语言解耦；
# 显示名经 _role_display_map() 按当前语言渲染（展示层再 tr()）。
ROLE_ADMIN = "admin"
ROLE_ENGINEER = "engineer"
ROLE_OPERATOR = "operator"

_ROLE_ORDER = (ROLE_ADMIN, ROLE_ENGINEER, ROLE_OPERATOR)

# 中文旧值迁移映射（W18 前历史库落的是 tr() 显示名）
_LEGACY_ROLE_MAP = {
    "管理员": ROLE_ADMIN,
    "工程师": ROLE_ENGINEER,
    "操作员": ROLE_OPERATOR,
}


def _role_display_map() -> Dict[str, str]:
    """枚举 → 当前语言显示名。

    tr() 依赖运行期语言状态，映射须函数内构造（模块导入期语言未定）。
    """
    return {
        ROLE_ADMIN: tr("管理员"),
        ROLE_ENGINEER: tr("工程师"),
        ROLE_OPERATOR: tr("操作员"),
    }


def _migrate_role(value: object) -> str:
    """归一历史/新式角色值为稳定枚举。

    - 已是枚举 → 直通；
    - 中文旧值（"管理员"/"工程师"/"操作员"）→ 迁移到枚举；
    - 缺失/未知值 → 回退 operator（默认角色缺省）。
    """
    if not isinstance(value, str):
        return ROLE_OPERATOR
    if value in _ROLE_ORDER:
        return value
    return _LEGACY_ROLE_MAP.get(value, ROLE_OPERATOR)


def sweep_residual_initial_credentials(config_dir: Optional[str] = None) -> str:
    """W24（v4 P3-7）：启动时补删残留首启凭据文件。

    缺口：改密成功即删 initial_credentials.txt
    （_remove_initial_credentials），但 os.remove 失败（Windows 文件
    占用）仅记日志、无重试路径 → 明文文件可长存。登录页构造时补扫：

    - 文件不存在 → "absent"（含 exists→remove 间被外部删除的竞态）；
    - admin 已改密（users.json must_change=False；记录缺失/非字典亦然
      ——无待改标志即无挂起改密）→ 补删，成功 "deleted"；
    - os.remove 失败（占用）→ 告警保留 "remove_failed"（下次启动再试）；
    - 尚未改密（must_change=True）、users.json 不可读**或非字典形态**
      （合法 JSON 的 list/str/int——W24 对抗验证员 MEDIUM：形状损坏曾
      以 AttributeError 逃出致启动崩溃）→ "kept_pending_change"
      （登录流程仍强制改密并删除，文件内容自附删除提示）。
    """
    cfg = config_dir if config_dir is not None else str(_CONFIG_DIR)
    cred_path = os.path.join(cfg, _INITIAL_CREDENTIALS_FILENAME)
    if not os.path.exists(cred_path):
        return "absent"
    try:
        with open(os.path.join(cfg, "users.json"), "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("补扫初始凭据：users.json 不可读，保守保留 %s", cred_path)
        return "kept_pending_change"
    if not isinstance(db, dict):
        logger.warning(
            "补扫初始凭据：users.json 非字典形态（%s），保守保留 %s",
            type(db).__name__, cred_path,
        )
        return "kept_pending_change"
    record = db.get("admin")
    if not isinstance(record, dict):
        record = {}
    if record.get("must_change", False):
        logger.info("补扫初始凭据：admin 尚未改密，保留 %s", cred_path)
        return "kept_pending_change"
    try:
        os.remove(cred_path)
        logger.warning("补扫初始凭据：admin 已改密，补删残留文件 %s", cred_path)
        return "deleted"
    except FileNotFoundError:
        return "absent"
    except OSError:
        logger.exception("补扫初始凭据：补删失败（可能被占用），下次启动再试: %s", cred_path)
        return "remove_failed"


class _ChangePasswordDialog(QDialog):
    """首登强制改密对话框（W19/FR-5.3）。

    三重校验：旧密须匹配 record 哈希、新密 >= 8 字符、两次输入一致；
    错误经 QLabel 就地提示（不关框）。全过 → new_hash_record 落新哈希
    三元组并 accept()；取消/失败 → new_hash_record 保持 None。
    """

    _MIN_NEW_PASSWORD_LEN = 8

    def __init__(self, record: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("首次登录——请修改密码"))
        self._record = record
        self.new_hash_record: Optional[Tuple[str, str, int]] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self._old_edit = QLineEdit()
        self._old_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("旧密码"), self._old_edit)
        self._new_edit = QLineEdit()
        self._new_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("新密码"), self._new_edit)
        self._confirm_edit = QLineEdit()
        self._confirm_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("确认新密码"), self._confirm_edit)
        root.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #FF6B6B;")
        root.addWidget(self._error)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton(tr("确认修改"))
        cancel_btn = QPushButton(tr("取消"))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _on_accept(self) -> None:
        """三重校验；全过才落新哈希三元组并关闭。"""
        old_ok = _verify_password(
            self._old_edit.text(),
            self._record.get("password_hash", ""),
            self._record.get("salt", ""),
            self._record.get("iterations", 100_000),
        )
        if not old_ok:
            self._error.setText(tr("旧密码错误"))
            return
        new = self._new_edit.text()
        if len(new) < self._MIN_NEW_PASSWORD_LEN:
            self._error.setText(tr("新密码至少 8 个字符"))
            return
        if new != self._confirm_edit.text():
            self._error.setText(tr("两次输入不一致"))
            return
        self.new_hash_record = _hash_password(new)
        self.accept()


class LoginPage(QWidget):
    """登录/许可证激活页。"""

    login_success = Signal(str, str)  # (user, role)——role 为稳定枚举值（W18/P2-8）
    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._ensure_default_admin()
        # W24（v4 P3-7）：补扫残留首启凭据（此前删除失败的场景），
        # 首启场景 _ensure_default_admin 刚建文件时 must_change=True
        # 会保守保留——见 sweep_residual_initial_credentials 文档。
        sweep_residual_initial_credentials()
        self._build_ui()
        self._wire()

    @staticmethod
    def _ensure_default_admin() -> None:
        """确保 configs/users.json 中有默认 admin 账户（R4-4: 随机密码）。"""
        try:
            config_dir = str(_CONFIG_DIR)
            os.makedirs(config_dir, exist_ok=True)
            db_path = os.path.join(config_dir, "users.json")
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            else:
                db = {}
            # 只有当库为空时才创建默认 admin（R4-4: 随机密码）
            if not db:
                # 生成随机初始密码（R4-4）
                default_pwd = secrets.token_urlsafe(12)
                h, s, iters = _hash_password(default_pwd)
                db["admin"] = {
                    "password_hash": h,
                    "salt": s,
                    "role": ROLE_ADMIN,
                    "iterations": iters,
                    "must_change": True,  # 首次登录强制改密
                }
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
                # chmod(0o600) 为 POSIX 语义；Windows/NTFS 下仅映射只读位，
                # 不构成访问控制——凭据保护实际依赖文件系统 ACL/目录权限。
                try:
                    os.chmod(db_path, 0o600)
                except OSError:
                    pass
                # W19（v3 第三波 FR-5.1）：初始密码改落一次性文件，
                # 日志只记提示不含明文（W14-C3 的日志通道明文就此关闭）
                LoginPage._write_initial_credentials(config_dir, default_pwd)
        except (OSError, json.JSONDecodeError):
            logger.exception("初始化默认管理员失败")

    @staticmethod
    def _write_initial_credentials(config_dir: str, default_pwd: str) -> None:
        """初始密码写 configs/initial_credentials.txt（W19/FR-5.1）。

        内容：用户名/初始密码/首次登录后修改提示；attempt chmod 0o600
        （与 users.json 同法）。改密成功后自动删除（FR-5.2）。
        """
        cred_path = os.path.join(config_dir, _INITIAL_CREDENTIALS_FILENAME)
        content = (
            "AutoVisionAgent 首次启动——默认管理员账户\n"
            "用户名: admin\n"
            f"初始密码: {default_pwd}\n"
            "请首次登录后立即修改密码，并删除本文件。\n"
        )
        with open(cred_path, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            os.chmod(cred_path, 0o600)
        except OSError:
            pass
        logger.info(
            "初始密码已写入 configs/%s，首次登录后请修改并删除该文件",
            _INITIAL_CREDENTIALS_FILENAME,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 48, 48, 48)
        root.setSpacing(16)

        self._title = QLabel(tr("AutoVisionAgent 登录"))
        self._title.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF;")
        root.addWidget(self._title)

        form_box = QFrame()
        form_box.setMaximumWidth(400)
        form = QFormLayout(form_box)
        form.setSpacing(12)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText(tr("请输入用户名"))
        form.addRow(tr("用户名"), self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setPlaceholderText(tr("请输入密码"))
        self._pass_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("密码"), self._pass_edit)

        self._role_combo = QComboBox()
        # userData=稳定枚举：currentData() 取值，显示文本仅作渲染（语言切换不落库）
        for _role in _ROLE_ORDER:
            self._role_combo.addItem(_role_display_map()[_role], userData=_role)
        form.addRow(tr("角色"), self._role_combo)

        self._remember = QCheckBox(tr("记住登录状态"))
        form.addRow(self._remember)

        root.addWidget(form_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self._login_btn = QPushButton(tr("登录"))
        self._login_btn.setObjectName("accentButton")
        self._register_btn = QPushButton(tr("注册许可证"))
        self._offline_btn = QPushButton(tr("离线模式"))
        btn_row.addWidget(self._login_btn)
        btn_row.addWidget(self._register_btn)
        btn_row.addWidget(self._offline_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

    def _wire(self) -> None:
        self._login_btn.clicked.connect(self._do_login)
        self._register_btn.clicked.connect(self._do_register)
        self._offline_btn.clicked.connect(self._do_offline)

    def _do_login(self) -> None:
        """本地用户认证：PBKDF2 加盐验证用户名+密码 + 失败锁定。"""
        user = self._user_edit.text().strip()
        password = self._pass_edit.text()
        if not user:
            self.status_changed.emit(tr("请输入用户名"), "warn")
            return
        if not password:
            self.status_changed.emit(tr("请输入密码"), "warn")
            return

        # 加载用户数据库（R4-5: 从持久化读取锁定状态）
        users_db = self._load_users_db()

        if user not in users_db:
            self.status_changed.emit(tr("用户不存在"), "warn")
            return

        record = users_db[user]

        # R4-5: 从用户记录读取持久化锁定状态
        lock_until = record.get("lockout_until", 0)
        if lock_until > time.time():
            remaining = int(lock_until - time.time())
            self.status_changed.emit(
                tr("账户已锁定") + f" ({remaining}s)", "error"
            )
            return

        stored_hash = record.get("password_hash", "")
        salt_hex = record.get("salt", "")
        stored_iterations = record.get("iterations", 100_000)  # 旧记录默认 100K
        stored_role = _migrate_role(record.get("role"))

        # R4-3: 使用 verify_and_migrate 验证密码
        is_valid, rehash_info = _verify_and_migrate(
            password, stored_hash, salt_hex, stored_iterations
        )

        if not is_valid:
            # 登录失败计数（R4-5: 持久化 fail_count）
            fail_count = record.get("fail_count", 0) + 1
            record["fail_count"] = fail_count
            remaining = _MAX_LOGIN_ATTEMPTS - fail_count
            if remaining <= 0:
                # R4-5: 锁定状态持久化到 users.json
                lock_time = time.time() + _LOCKOUT_SECONDS
                record["lockout_until"] = lock_time
                record["fail_count"] = 0
                users_db[user] = record
                self._save_users_db(users_db)
                self.status_changed.emit(
                    tr("登录失败次数过多，账户已锁定") + f" ({_LOCKOUT_SECONDS}s)",
                    "error",
                )
                logger.warning("用户 %s 因连续登录失败被锁定", user)
            else:
                users_db[user] = record
                self._save_users_db(users_db)
                self.status_changed.emit(
                    tr("密码错误") + f" ({remaining} {tr('次剩余')})", "warn"
                )
            return

        # 登录成功：重置锁定状态（R4-5: 持久化重置）
        record["fail_count"] = 0
        record.pop("lockout_until", None)

        # R4-3: 如果需要迁移哈希，自动更新
        if rehash_info:
            new_hash, new_salt, new_iters = rehash_info
            record["password_hash"] = new_hash
            record["salt"] = new_salt
            record["iterations"] = new_iters
            logger.info("用户 %s 密码哈希已迁移到新迭代次数", user)

        # W19（v3 第三波 FR-5.3）：must_change 强制拦截——改密成功才放行
        if not self._handle_must_change(user, record, users_db):
            return

        # W13-C3: 会话用户 + 登录审计（docstring 宣称记录登录，此前 0 条）
        try:
            from core.audit_logger import log_login
            from core.session import set_current_user

            set_current_user(user)
            log_login(user=user, role=stored_role, mode="local")
        except (ImportError, OSError):
            logger.exception("登录审计写入失败")

        self.login_success.emit(user, stored_role)
        self.status_changed.emit(tr("登录成功"), user)

    def _handle_must_change(self, user: str, record: dict, users_db: dict) -> bool:
        """must_change 强制改密拦截（W19/FR-5.3）。

        - must_change=False：记录落库直通（既有路径零影响），返回 True；
        - must_change=True：弹改密框——成功 → 新哈希/清标志落库 + 删初始
          凭据文件（FR-5.2），返回 True；取消/失败 → 不动库、提示后
          返回 False（调用方不发 login_success、标志保留）。
        """
        if not record.get("must_change", False):
            users_db[user] = record
            self._save_users_db(users_db)
            return True
        new_hash_record = self._run_change_password_dialog(record)
        if new_hash_record is None:
            self.status_changed.emit(tr("未修改密码，暂不登录"), "warn")
            return False
        new_hash, new_salt, new_iters = new_hash_record
        record["password_hash"] = new_hash
        record["salt"] = new_salt
        record["iterations"] = new_iters
        record["must_change"] = False
        users_db[user] = record
        self._save_users_db(users_db)
        self._remove_initial_credentials()
        return True

    def _run_change_password_dialog(
        self, record: dict
    ) -> Optional[Tuple[str, str, int]]:
        """弹出改密对话框（阻塞），返回新哈希三元组；取消/失败为 None。"""
        dlg = _ChangePasswordDialog(record, parent=self)
        dlg.exec()
        return dlg.new_hash_record

    def _remove_initial_credentials(self) -> None:
        """删除初始凭据文件（W19/FR-5.2：存在才删，幂等）。"""
        cred_path = os.path.join(str(_CONFIG_DIR), _INITIAL_CREDENTIALS_FILENAME)
        try:
            if os.path.exists(cred_path):
                os.remove(cred_path)
        except OSError:
            logger.exception("删除初始凭据文件失败")

    def _load_users_db(self) -> dict:
        """加载 configs/users.json 用户数据库。"""
        try:
            config_dir = str(_CONFIG_DIR)
            db_path = os.path.join(config_dir, "users.json")
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.exception("加载用户数据库失败")
        return {}

    def _save_users_db(self, db: dict) -> None:
        """保存用户数据库（并限制文件权限）。"""
        try:
            config_dir = str(_CONFIG_DIR)
            os.makedirs(config_dir, exist_ok=True)
            db_path = os.path.join(config_dir, "users.json")
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            # chmod(0o600) 为 POSIX 语义；Windows/NTFS 下仅映射只读位，
            # 不构成访问控制——凭据保护实际依赖文件系统 ACL/目录权限。
            try:
                os.chmod(db_path, 0o600)
            except OSError:
                pass
        except (OSError, TypeError):
            logger.exception("保存用户数据库失败")

    def _do_register(self) -> None:
        """导入 .key 许可证文件到 configs/（仅复制，无内容校验）。

        实际语义：把用户选择的文件复制为 configs/license.key，不校验
        签名/格式/有效期（去 DRM 复刻决策，非许可证验证）——文件仅被
        _do_offline 用作存在性提示。
        """
        from gui.widgets.file_dialog import pick_open_file

        config_dir = str(_CONFIG_DIR)
        license_path = pick_open_file(
            self, "选择许可证文件", "License (*.key *.lic)"
        )
        if not license_path:
            return
        try:
            import shutil
            dest = os.path.join(config_dir, "license.key")
            shutil.copy2(license_path, dest)
            self.status_changed.emit(
                tr("许可证导入成功"), os.path.basename(license_path)
            )
            logger.info("许可证已导入: %s -> %s", license_path, dest)
        except (OSError, shutil.Error):
            logger.exception("许可证导入失败")
            self.status_changed.emit(tr("许可证导入失败"), "error")

    def _do_offline(self) -> None:
        """离线模式：license.key 存在性检查 + 缺失时确认框，单工位模式。

        实际语义：仅检查 configs/license.key 是否存在（无签名/内容校验——
        去 DRM 复刻决策，非许可证验证）；文件缺失时弹确认框，用户确认
        即以受限离线模式进入。角色固定枚举 operator。
        """
        config_dir = str(_CONFIG_DIR)
        license_path = os.path.join(config_dir, "license.key")
        if not os.path.exists(license_path):
            reply = QMessageBox.warning(
                self, tr("离线模式"),
                tr("未检测到本地 License 文件。\n是否仍要以受限离线模式进入？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        # W13-C3: 离线会话用户 + 审计（与登录成功同一审计通道）
        try:
            from core.audit_logger import log_login
            from core.session import set_current_user

            set_current_user("offline")
            log_login(user="offline", role=ROLE_OPERATOR, mode="offline")
        except (ImportError, OSError):
            logger.exception("离线模式审计写入失败")
        self.login_success.emit("offline", ROLE_OPERATOR)
        self.status_changed.emit(tr("已进入离线模式"), "ok")

    def retranslate(self) -> None:
        self._title.setText(tr("AutoVisionAgent 登录"))
        self._user_edit.setPlaceholderText(tr("请输入用户名"))
        self._pass_edit.setPlaceholderText(tr("请输入密码"))
        display = _role_display_map()
        for _i, _role in enumerate(_ROLE_ORDER):
            # 仅刷新显示文本；userData（稳定枚举）不动——显示/持久解耦
            self._role_combo.setItemText(_i, display[_role])
        self._remember.setText(tr("记住登录状态"))
        self._login_btn.setText(tr("登录"))
        self._register_btn.setText(tr("注册许可证"))
        self._offline_btn.setText(tr("离线模式"))
