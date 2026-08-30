"""密码哈希与验证 — 不依赖 PySide6，可独立测试。

PBKDF2-HMAC-SHA256 加盐方案，满足 FR-D2 安全要求。
R4-3: 迭代次数提升至 600,000（OWASP 2023 建议），支持渐进迁移。
"""
from __future__ import annotations

import hashlib
import secrets

# PBKDF2 参数（R4-3: OWASP 2023 建议 600,000）
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_DK_LEN = 32
# 旧版迭代次数，用于兼容和迁移判断
_LEGACY_ITERATIONS = 100_000


def hash_password(
    password: str,
    salt_hex: str = "",
    iterations: int = _PBKDF2_ITERATIONS,
) -> tuple[str, str, int]:
    """PBKDF2-HMAC-SHA256 加盐哈希。

    Args:
        password: 明文密码。
        salt_hex: 盐的十六进制字符串，为空则生成随机盐。
        iterations: PBKDF2 迭代次数（默认 600,000）。

    Returns:
        (hash_hex, salt_hex, iterations)。
    """
    if not salt_hex:
        salt_hex = secrets.token_hex(16)
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, _PBKDF2_DK_LEN
    )
    return dk.hex(), salt_hex, iterations


def verify_password(
    password: str,
    stored_hash: str,
    salt_hex: str,
    stored_iterations: int = _PBKDF2_ITERATIONS,
) -> bool:
    """验证密码是否匹配存储的哈希值。

    Args:
        password: 待验证的明文密码。
        stored_hash: 存储的哈希十六进制字符串。
        salt_hex: 存储的盐。
        stored_iterations: 存储时的迭代次数（支持旧版兼容）。

    Returns:
        True 如果密码匹配。
    """
    if not stored_hash or not salt_hex:
        return False
    calc_hash, _, _ = hash_password(password, salt_hex, stored_iterations)
    return secrets.compare_digest(calc_hash, stored_hash)


def needs_rehash(stored_iterations: int) -> bool:
    """判断存储的哈希是否需要用新迭代次数重新计算。

    Args:
        stored_iterations: 存储记录中的迭代次数。

    Returns:
        True 如果迭代次数低于当前推荐值。
    """
    return stored_iterations < _PBKDF2_ITERATIONS


def verify_and_migrate(
    password: str,
    stored_hash: str,
    salt_hex: str,
    stored_iterations: int = _PBKDF2_ITERATIONS,
) -> tuple[bool, tuple[str, str, int] | None]:
    """验证密码并在需要时自动返回迁移哈希。

    如果密码正确但迭代次数低于当前推荐值，返回新哈希供调用方持久化。

    Args:
        password: 待验证的明文密码。
        stored_hash: 存储的哈希。
        salt_hex: 存储的盐。
        stored_iterations: 存储时的迭代次数。

    Returns:
        (is_valid, rehash_info):
        - is_valid: 密码是否正确。
        - rehash_info: 若需迁移则为 (new_hash, new_salt, new_iterations)，否则 None。
    """
    if not verify_password(password, stored_hash, salt_hex, stored_iterations):
        return False, None

    if needs_rehash(stored_iterations):
        new_hash, new_salt, new_iter = hash_password(password)
        return True, (new_hash, new_salt, new_iter)

    return True, None


__all__ = [
    "hash_password",
    "verify_password",
    "needs_rehash",
    "verify_and_migrate",
]
