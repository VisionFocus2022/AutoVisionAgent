"""登录页（FR-D2）— 对标 SKolpha 登录/License 验证。

本地用户认证：用户名+密码 PBKDF2 加盐比对 configs/users.json。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Dict, Optional

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from core.constants import CONFIG_DIR as _CONFIG_DIR

logger = logging.getLogger(__name__)

# 安全参数
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 分钟锁定


class LoginPage(QWidget):
    """登录/许可证激活页。"""

    login_success = Signal(str, str)  # (user, role)
    status_changed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._ensure_default_admin()
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
                    "role": "管理员",
                    "iterations": iters,
                    "must_change": True,  # 首次登录强制改密
                }
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
                # 限制文件权限（仅所有者可读写）
                try:
                    os.chmod(db_path, 0o600)
                except OSError:
                    pass
                # 打印随机密码到控制台 + 日志（不硬编码 admin/admin）
                msg = (
                    "=" * 60 + "\n"
                    "首次启动：已创建默认管理员账户。\n"
                    f"  用户名: admin\n"
                    f"  初始密码: {default_pwd}\n"
                    "  请首次登录后立即修改密码。\n" +
                    "=" * 60
                )
                logger.info(msg)
                print(msg)
        except (OSError, json.JSONDecodeError):
            logger.exception("初始化默认管理员失败")

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
        self._role_combo.addItems([tr("管理员"), tr("工程师"), tr("操作员")])
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
        stored_role = record.get("role", tr("操作员"))

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

        # 首次登录强制改密提示
        must_change = record.get("must_change", False)
        if must_change:
            record["must_change"] = False
            users_db[user] = record
            self._save_users_db(users_db)
            self.status_changed.emit(tr("首次登录，请尽快修改密码"), "warn")
        else:
            users_db[user] = record
            self._save_users_db(users_db)

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
            # 限制文件权限（仅所有者可读写）
            try:
                os.chmod(db_path, 0o600)
            except OSError:
                pass
        except (OSError, TypeError):
            logger.exception("保存用户数据库失败")

    def _do_register(self) -> None:
        """注册许可证：选择并导入 .key 许可证文件（R4-4）。"""
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
        """离线模式：需验证本地 License 文件，而非无条件进入。"""
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
            log_login(user="offline", role=tr("操作员"), mode="offline")
        except (ImportError, OSError):
            logger.exception("离线模式审计写入失败")
        self.login_success.emit("offline", tr("操作员"))
        self.status_changed.emit(tr("已进入离线模式"), "ok")

    def retranslate(self) -> None:
        self._title.setText(tr("AutoVisionAgent 登录"))
        self._user_edit.setPlaceholderText(tr("请输入用户名"))
        self._pass_edit.setPlaceholderText(tr("请输入密码"))
        self._role_combo.setItemText(0, tr("管理员"))
        self._role_combo.setItemText(1, tr("工程师"))
        self._role_combo.setItemText(2, tr("操作员"))
        self._remember.setText(tr("记住登录状态"))
        self._login_btn.setText(tr("登录"))
        self._register_btn.setText(tr("注册许可证"))
        self._offline_btn.setText(tr("离线模式"))
