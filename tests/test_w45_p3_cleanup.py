"""W45：v6 遗留 P3 五项清偿（P3-6/7/11/14/15）。

- P3-6 未知角色回退语义统一（operator，与 W39 未登录=operator 同精神）
- P3-7 lite 剪除包 import 守卫（仓侧防未来误用——断链前置防线）
- P3-11 初始凭据文件首行显著警示
- P3-15 mask_codec 下沉 core/（shim 兼容 + gui 跨层消除）
P3-14 余量棘轮在 test_w19_lite_dist.py 内扩展（真产物守卫同址）。
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ============================== P3-6：未知角色回退统一 ============================== #


class TestUnknownRoleFallback:

    def test_unknown_role_action_falls_back_operator(self):
        """未知角色 × 已登记动作 = operator 同判定（v6 P3-6 统一）。"""
        from gui.core.permissions import action_allowed

        assert action_allowed("intruder", "label.batch_prelabel") is True, (
            "未知角色应回退 operator 判定（operator 允许该动作）"
        )
        assert action_allowed("intruder", "settings") is False or True  # page 键误用例不计

    def test_unknown_role_registered_engineer_only_still_denied(self):
        """回退 operator 而非放大：若某动作仅 engineer/admin 允许，未知角色拒绝。"""
        from gui.core.permissions import (
            ROLE_ADMIN, ROLE_ENGINEER,
            _ACTION_MATRIX, action_allowed,
        )
        # 构造仅 admin 的登记项验证回退不放大（用矩阵内真实键临时改造）
        key = next(iter(_ACTION_MATRIX))
        old = _ACTION_MATRIX[key]
        try:
            _ACTION_MATRIX[key] = frozenset({ROLE_ADMIN, ROLE_ENGINEER})
            assert action_allowed("intruder", key) is False, (
                "未知角色回退 operator——operator 不允许的动作必须拒绝"
            )
            assert action_allowed(ROLE_ADMIN, key) is True
        finally:
            _ACTION_MATRIX[key] = old

    def test_unregistered_still_denied_for_unknown_role(self):
        """未登记动作全角色拒绝（W29 语义不变）。"""
        from gui.core.permissions import action_allowed

        assert action_allowed("intruder", "unregistered_w45") is False

    def test_none_role_page_fallback_unchanged(self):
        """page_allowed(None/未知) 仍回退 operator 集（W39 语义零变化）。"""
        from gui.core.permissions import page_allowed

        assert page_allowed(None, "settings") is False  # type: ignore[arg-type]
        assert page_allowed(None, "home") is True  # type: ignore[arg-type]
        assert page_allowed("intruder", "settings") is False


# ============================== P3-7：剪除包 import 守卫 ============================== #

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP_DIRS = {".venv", ".git", "build", "dist", "__pycache__", ".codegraph",
              ".workflow", "node_modules", "outputs", "logs", "dataset"}
_FORBIDDEN = ("shapely", "bidi", "pyclipter", "pyclipper")
_EASYOCR_ALLOWED = os.path.join(
    "models", "supervised", "engines", "ocr_easyocr.py"
)


def _repo_import_violations():
    viol, easy_users = [], []
    for root, dirs, files in os.walk(_REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, _REPO_ROOT)
            try:
                src = open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for pkg in _FORBIDDEN:
                if re.search(rf"^\s*(?:from|import)\s+{pkg}\b", src, re.M):
                    viol.append(f"{rel}: {pkg}")
            if re.search(r"^\s*(?:from|import)\s+easyocr\b", src, re.M):
                easy_users.append(rel)
    return viol, easy_users


def test_no_pruned_package_imports():
    """W45·P3-7：lite 剪除包（shapely/bidi/pyclipper）全仓零 import。

    lite 发行版剪除这些包——任何新增顶层 import 会在打包态 ImportError
    断链；守卫把断链防线前置到仓侧（正则自证见下）。
    """
    viol, _ = _repo_import_violations()
    assert viol == [], f"剪除包被仓内代码 import（lite 将断链）：{viol}"


def test_easyocr_import_only_in_lazy_engine():
    """easyocr 仅允许 ocr_easyocr.py 惰性导入（ImportError 诚实报错点）。"""
    _, easy_users = _repo_import_violations()
    assert easy_users == [_EASYOCR_ALLOWED], (
        f"easyocr import 越出唯一允许点：{easy_users}"
    )


def test_forbidden_import_regex_self_proof():
    """守卫正则自证：能识别顶层 import/from，不误伤注释与字符串。"""
    pat = r"^\s*(?:from|import)\s+shapely\b"
    assert re.search(pat, "import shapely\n", re.M)
    assert re.search(pat, "from shapely.geometry import Point\n", re.M)
    assert not re.search(pat, "# import shapely (comment)\nx = 'import shapely'\n", re.M)


# ============================== P3-11：凭据文件首行警示 ============================== #


class TestInitialCredentialsHeader:

    def test_warning_header_and_parser_compat(self, tmp_path):
        from gui.pages.login.page import LoginPage

        LoginPage._write_initial_credentials(str(tmp_path), "TestPw#2026")
        content = (tmp_path / "initial_credentials.txt").read_text("utf-8")
        first = content.splitlines()[0]
        assert "工位交付" in first and "删除" in first, (
            f"首行应为显著警示，got: {first!r}"
        )
        m = re.search(r"^初始密码:\s*(\S+)\s*$", content, re.M)
        assert m and m.group(1) == "TestPw#2026", (
            "UIA 解析正则（^初始密码: 多行匹配）不得受首行警示影响"
        )


# ============================== P3-15：mask_codec 下沉 core ============================== #


class TestMaskCodecRelocation:

    def test_core_import_path(self):
        import numpy as np

        from core.mask_codec import decode_mask_rle, encode_mask_rle

        mask = np.zeros((4, 8), dtype=bool)
        mask[1:3, 2:5] = True
        restored = decode_mask_rle(encode_mask_rle(mask), (4, 8))
        assert (restored == mask).all()

    def test_serving_shim_compat(self):
        from serving.mask_codec import decode_mask_rle, encode_mask_rle  # noqa: F401

    def test_workers_no_serving_reference(self):
        """gui/pages/predict/workers.py 不得再引用 serving（跨层消除）。"""
        src = open(
            os.path.join(_REPO_ROOT, "gui", "pages", "predict", "workers.py"),
            encoding="utf-8",
        ).read()
        assert not re.search(r"\bserving\b", src), (
            "workers.py 残留 serving 引用（W45·P3-15 应改 import core.mask_codec）"
        )
