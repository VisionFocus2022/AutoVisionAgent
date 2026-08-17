"""M2 集成 e2e 测试 — 9 引擎注册 + 双范式分发 + 新页面构建 + 生成指标。

运行：pytest tests/test_m2_e2e.py -m e2e --no-cov -q
"""
from __future__ import annotations

import os
import numpy as np
import pytest

# offscreen Qt（无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def qapp():
    """Qt 应用级 fixture（与 test_gui.py / test_labeling.py 同范式）。"""
    return QApplication.instance() or QApplication([])


# ---- 1. 9 引擎全部注册 ----


class TestEngineRegistration:
    """T-AVA-08/09: 全部 9 种引擎可注册。"""

    def test_register_all(self) -> None:
        from models.supervised.engines import register_all_engines
        from models.supervised.registry import get_default_registry

        register_all_engines()
        reg = get_default_registry()

        expected = {
            "cls", "det", "seg", "pseg", "pose",
            "sseg", "abdet", "sgan", "super",
        }
        # reg.list() 返回 TaskType 枚举成员，取 .value 后再与字符串集合比较
        registered = {t.value for t in reg.list()}
        missing = expected - registered
        assert not missing, f"缺失引擎: {missing}"

    def test_each_engine_has_correct_task(self) -> None:
        from core.interfaces_supervised import TaskType
        from models.supervised.engines import register_all_engines
        from models.supervised.registry import get_default_registry

        register_all_engines()
        reg = get_default_registry()

        for tt in TaskType:
            assert reg.has(tt), f"注册表缺少 {tt.value}"

    def test_engines_are_protocols(self) -> None:
        """引擎实例满足 ISupervisedTaskEngine 接口。"""
        from core.interfaces_supervised import (
            ISupervisedTaskEngine,
            TaskType,
        )
        from models.supervised.engines import register_all_engines
        from models.supervised.registry import get_default_registry

        register_all_engines()
        reg = get_default_registry()

        for tt in TaskType:
            engine = reg.get(tt)
            assert hasattr(engine, "load"), f"{tt.value} 缺少 load"
            assert hasattr(engine, "infer"), f"{tt.value} 缺少 infer"
            assert hasattr(engine, "release"), f"{tt.value} 缺少 release"
            assert hasattr(engine, "info"), f"{tt.value} 缺少 info"


# ---- 2. 双范式分发 ----


class TestVisionDispatcher:
    """T-AVA-14: 双范式分发器。"""

    def test_dispatcher_singleton(self) -> None:
        from industrial_vision_platform.vision_dispatcher import (
            get_dispatcher,
        )
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        assert d1 is d2

    def test_list_all_tasks(self) -> None:
        from industrial_vision_platform.vision_dispatcher import (
            get_dispatcher,
        )
        d = get_dispatcher()
        tasks = d.list_all_tasks()
        # 9 有监督；zero_shot 为预留注入点已摘除（W14 P2-8）
        assert len(tasks) == 9
        task_names = {t["task"] for t in tasks}
        assert "zero_shot" not in task_names
        assert "cls" in task_names
        assert "sgan" in task_names
        assert "super" in task_names

    def test_task_info(self) -> None:
        from industrial_vision_platform.vision_dispatcher import (
            get_dispatcher,
        )
        d = get_dispatcher()
        info = d.get_task_info("cls")
        assert info["paradigm"] == "supervised"
        assert info["requires_training"] is True

        zs_info = d.get_task_info("zero_shot")
        assert zs_info["paradigm"] == "zero-shot"
        assert zs_info["requires_training"] is False

    def test_infer_without_load_raises(self) -> None:
        from industrial_vision_platform.vision_dispatcher import (
            get_dispatcher,
        )
        d = get_dispatcher()
        with pytest.raises(RuntimeError):
            d.infer("det", np.zeros((100, 100, 3), dtype=np.uint8))


# ---- 3. 生成指标 ----


class TestGenerativeMetrics:
    """T-AVA-11: FID / LPIPS。"""

    def test_perceptual_loss_fallback(self) -> None:
        """LPIPS 回退到 L2 像素损失。"""
        from evaluation.generative_metrics import perceptual_loss
        img1 = [np.zeros((64, 64, 3), dtype=np.uint8)]
        img2 = [np.zeros((64, 64, 3), dtype=np.uint8)]
        loss = perceptual_loss(img1, img2)
        assert loss == pytest.approx(0.0, abs=1e-6)


# ---- 4. 新页面构建 ----


class TestM2Pages:
    """T-AVA-12: 5 个新页面可构建。"""

    def test_login_page(self, qapp) -> None:
        from gui.pages.login import LoginPage
        page = LoginPage()
        assert page is not None

    def test_home_page(self, qapp) -> None:
        from gui.pages.home import HomePage
        page = HomePage()
        page.update_stats(projects=5, images=100, models=3, gpu="RTX 4090")
        assert page is not None

    def test_eval_page(self, qapp) -> None:
        from gui.pages.eval_ import EvalPage
        page = EvalPage()
        page.set_results([("mAP", 0.85, "Detection")])
        assert page is not None

    def test_deploy_page(self, qapp) -> None:
        from gui.pages.deploy import DeployPage
        page = DeployPage()
        page.set_progress(75)
        assert page is not None

    def test_settings_page(self, qapp) -> None:
        from gui.pages.settings import SettingsPage
        page = SettingsPage()
        assert page is not None


# ---- 5. 主窗口 10 页全注册 ----


class TestM2MainWindow:
    """T-AVA-15: 主窗口构建全部 10 页。"""

    def test_build_window(self, qapp) -> None:
        from gui.main import build_window
        win = build_window()
        # W1: 11 pages（flaw_gen 为 era-2 后新增）
        assert win._stack.count() == 11

    def test_login_to_home_navigation(self, qapp) -> None:
        from gui.main import build_window
        win = build_window()
        # W1: 离线模式登录（license.key 存在即直通，同 UIA conftest 手法）
        from core.constants import CONFIG_DIR
        license_path = CONFIG_DIR / "license.key"
        created = not license_path.exists()
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_bytes(b"")
        try:
            login_page = win._pages["login"]
            login_page._do_offline()
        finally:
            if created:
                license_path.unlink(missing_ok=True)
        # login_success → build_window 接线 win.select("home")
        assert win._stack.currentWidget() is win._pages["home"]
