"""core/auth.py 单元测试（R4-12）。

覆盖：PBKDF2 参数、盐随机性、rehash 迁移、时序安全比较。
"""
import pytest

from core import auth


@pytest.mark.unit
class TestHashPassword:
    """hash_password 基础功能。"""

    def test_returns_three_tuple(self):
        """R4-3: hash_password 返回 (hash_hex, salt_hex, iterations)。"""
        result = auth.hash_password("test123")
        assert len(result) == 3
        h, s, iters = result
        assert isinstance(h, str) and len(h) > 0
        assert isinstance(s, str) and len(s) > 0
        assert iters == auth._PBKDF2_ITERATIONS

    def test_deterministic_with_same_salt(self):
        """相同密码+相同盐 → 相同哈希。"""
        h1, salt, _ = auth.hash_password("test123")
        h2, _, _ = auth.hash_password("test123", salt)
        assert h1 == h2

    def test_different_salts_different_hashes(self):
        """不同盐 → 不同哈希。"""
        h1, s1, _ = auth.hash_password("test123")
        h2, s2, _ = auth.hash_password("test123")
        assert h1 != h2
        assert s1 != s2

    def test_custom_iterations(self):
        """自定义迭代次数。"""
        h, s, iters = auth.hash_password("test", iterations=10000)
        assert iters == 10000

    def test_pbkdf2_iterations_meets_owasp(self):
        """R4-3: 迭代次数 >= 600,000（OWASP 2023）。"""
        assert auth._PBKDF2_ITERATIONS >= 600_000


@pytest.mark.unit
class TestVerifyPassword:
    """verify_password 功能。"""

    def test_correct_password(self):
        """正确密码 → True。"""
        h, s, _ = auth.hash_password("my_secret")
        assert auth.verify_password("my_secret", h, s) is True

    def test_wrong_password(self):
        """错误密码 → False。"""
        h, s, _ = auth.hash_password("my_secret")
        assert auth.verify_password("wrong", h, s) is False

    def test_empty_hash_returns_false(self):
        """空哈希 → False。"""
        assert auth.verify_password("test", "", "salt") is False

    def test_empty_salt_returns_false(self):
        """空盐 → False。"""
        assert auth.verify_password("test", "hash", "") is False

    def test_legacy_iterations_compatible(self):
        """旧版迭代次数兼容。"""
        h, s, old_iters = auth.hash_password("test", iterations=auth._LEGACY_ITERATIONS)
        assert auth.verify_password("test", h, s, old_iters) is True
        # 新迭代次数无法匹配旧哈希
        assert auth.verify_password("test", h, s, auth._PBKDF2_ITERATIONS) is False


@pytest.mark.unit
class TestNeedsRehash:
    """needs_rehash 迁移判断。"""

    def test_legacy_needs_rehash(self):
        """旧迭代次数 → 需要迁移。"""
        assert auth.needs_rehash(auth._LEGACY_ITERATIONS) is True

    def test_current_no_rehash(self):
        """当前迭代次数 → 不需要迁移。"""
        assert auth.needs_rehash(auth._PBKDF2_ITERATIONS) is False


@pytest.mark.unit
class TestVerifyAndMigrate:
    """verify_and_migrate 自动迁移。"""

    def test_correct_password_no_migration(self):
        """当前哈希 + 正确密码 → (True, None)。"""
        h, s, _ = auth.hash_password("test")
        is_valid, rehash = auth.verify_and_migrate("test", h, s)
        assert is_valid is True
        assert rehash is None

    def test_correct_password_with_migration(self):
        """旧哈希 + 正确密码 → (True, rehash_info)。"""
        h, s, old_iters = auth.hash_password("test", iterations=auth._LEGACY_ITERATIONS)
        is_valid, rehash = auth.verify_and_migrate("test", h, s, old_iters)
        assert is_valid is True
        assert rehash is not None
        new_h, new_s, new_iters = rehash
        assert new_iters == auth._PBKDF2_ITERATIONS
        assert new_h != h  # 新哈希不同于旧哈希

    def test_wrong_password_no_migration(self):
        """错误密码 → (False, None)。"""
        h, s, _ = auth.hash_password("test")
        is_valid, rehash = auth.verify_and_migrate("wrong", h, s)
        assert is_valid is False
        assert rehash is None

    def test_migrated_hash_verifies(self):
        """迁移后的新哈希可以通过验证。"""
        h, s, old_iters = auth.hash_password("test", iterations=auth._LEGACY_ITERATIONS)
        _, rehash = auth.verify_and_migrate("test", h, s, old_iters)
        new_h, new_s, new_iters = rehash
        assert auth.verify_password("test", new_h, new_s, new_iters) is True
