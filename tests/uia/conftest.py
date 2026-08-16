"""UIA 全流程测试 pytest 配置。

fixtures：
- ``ava_app``：启动 AutoVisionAgent 桌面应用（默认打包 exe，环境变量
  ``AVA_UIA_SOURCE=python`` 改用 ``python -m gui.main``），返回主窗口控件，
  测试结束自动关闭进程。
- ``sample_images_dir``：临时目录，含 3 张 PIL 生成的测试图片（PNG/JPG/BMP）。
- ``workspace_dir``：临时工作目录，作为数据管理目标目录 / 标注 / 部署输出。
- ``fake_model_path``：一个伪造 .pt 文件路径，供部署页"浏览"选择（流程触发用）。

运行前提：见 tests/uia/README 末尾说明（桌面会话、exe 已构建、无同名单实例运行）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# 确保仓库根目录在 sys.path 中，便于 `from tests.uia...` 导入
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 同时把 tests/uia 目录加入 sys.path，兼容 pytest 将 conftest 当作顶层
# 模块加载的场景（此时 `tests.uia` 包不可用，需直接导入 uia_helpers）
_TESTS_UIA_DIR = Path(__file__).resolve().parent
if str(_TESTS_UIA_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_UIA_DIR))

import pytest


def _has_desktop_session() -> bool:
    """是否存在交互桌面会话（无头 CI/纯 SSH 控制台下 GetSystemMetrics 返回 0）。"""
    try:
        import ctypes

        return ctypes.windll.user32.GetSystemMetrics(0) > 0
    except Exception:
        return False


if not _has_desktop_session():
    # W4-T4：无头环境跳过而非报错（架构审查 P2-1 收尾；
    # 默认门禁已 --ignore=tests/uia，此处兜底手动误跑场景）
    pytest.skip("UIA 测试需要交互桌面会话（无头环境自动跳过）",
                allow_module_level=True)

import uiautomation as ua

try:
    from tests.uia.uia_helpers import find_main_window
except ImportError:  # pytest 顶层模式加载 conftest 时
    from uia_helpers import find_main_window  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# 仓库根（tests/uia/conftest.py 上三级）
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = REPO_ROOT / "dist" / "AutoVisionAgent" / "AutoVisionAgent.exe"
CONFIG_DIR = REPO_ROOT / "configs"
LICENSE_KEY = CONFIG_DIR / "license.key"


# ================================ 启动应用 ================================ #

@pytest.fixture(scope="session")
def ava_app():
    """启动 AutoVisionAgent 并返回主窗口控件，会话结束后关闭进程。

    启动方式：
      - 默认：dist\\AutoVisionAgent\\AutoVisionAgent.exe
      - AVA_UIA_SOURCE=python：python -m gui.main（需 PySide6 已安装）
      - AVA_UIA_EXE：自定义 exe 路径

    为支持"离线模式"免确认登录（避免 QMessageBox 阻塞自动化），启动前
    会确保 configs/license.key 存在（空文件即可，登录页仅检查存在性）。
    若文件原本不存在，会话结束会清理掉，避免污染仓库。

    注意：exe 模式下 CONFIG_DIR 解析到 ``dist/AutoVisionAgent/_internal/configs/``，
    python 模式下解析到仓库根的 ``configs/``，两处都会创建。
    """
    license_created = _ensure_license_key()

    source = os.environ.get("AVA_UIA_SOURCE", "exe").lower()
    proc = _launch_app(source)

    # python 源码模式下，启动后台线程持续读取子进程 stdout/stderr 输出到测试日志
    stop_reader = {"stop": False}
    if source == "python" and proc.stdout is not None:
        import threading

        def _reader():
            try:
                for line in proc.stdout:
                    if stop_reader["stop"]:
                        break
                    line = line.rstrip()
                    if line:
                        logger.info("[APP] %s", line)
            except Exception:  # noqa: BLE001
                pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

    # 等待主窗口（含重试）
    try:
        win = find_main_window(timeout=float(os.environ.get("AVA_UIA_LAUNCH_TIMEOUT", "40")))
    except Exception:
        # 启动失败时输出进程日志辅助诊断
        _dump_process(proc)
        try:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise

    # 额外等待 UI 渲染稳定
    time.sleep(1.5)
    yield win

    # 清理：关闭应用
    stop_reader["stop"] = True
    try:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:  # noqa: BLE001
        pass
    # 兜底：杀残留同名进程（避免下次测试启动被单实例挡住）
    _kill_residual("AutoVisionAgent")
    # 清理：若 license.key 是本次创建的，移除避免污染仓库
    if license_created:
        for p in [
            LICENSE_KEY,
            DEFAULT_EXE.parent / "_internal" / "configs" / "license.key",
        ]:
            try:
                p.unlink()
            except OSError:
                pass


def _launch_app(source: str) -> subprocess.Popen:
    """按 source 启动应用进程。"""
    if source == "python":
        # 支持自定义 python 解释器（AVA_UIA_PYTHON），便于在带 PySide6 的 venv 中启动
        python_exe = os.environ.get("AVA_UIA_PYTHON", sys.executable)
        cmd = [python_exe, "-m", "gui.main"]
        cwd = str(REPO_ROOT)
        logger.info("启动（python 源码）: %s (cwd=%s)", " ".join(cmd), cwd)
        # 捕获 stdout/stderr 以便诊断启动失败与应用日志
        return subprocess.Popen(
            cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    # exe
    exe = os.environ.get("AVA_UIA_EXE", str(DEFAULT_EXE))
    if not os.path.exists(exe):
        raise FileNotFoundError(
            f"AutoVisionAgent.exe 不存在: {exe}。"
            f"请先 pyinstaller autovisionagent.spec --noconfirm，"
            f"或设置 AVA_UIA_SOURCE=python 用源码运行。"
        )
    logger.info("启动（exe）: %s", exe)
    return subprocess.Popen([exe], cwd=os.path.dirname(exe))


def _dump_process(proc: subprocess.Popen) -> None:
    """输出进程 stdout/stderr（若有）辅助诊断启动失败。"""
    if proc is None:
        return
    logger.error("进程返回码: %s", proc.poll())


def _ensure_license_key() -> bool:
    """确保 configs/license.key 存在（登录页"离线模式"仅检查文件存在性）。

    覆盖两种运行模式下的 CONFIG_DIR：
      - python 源码模式：``<repo_root>/configs/license.key``
      - exe 模式：``dist/AutoVisionAgent/_internal/configs/license.key``
        （core/constants.py 的 _PROJECT_ROOT 在 frozen exe 中指向 _internal/）

    若文件已存在则不动；否则创建空文件。返回是否本次新建（任一处新建即 True）。
    """
    candidates = [
        LICENSE_KEY,  # <repo_root>/configs/license.key
        DEFAULT_EXE.parent / "_internal" / "configs" / "license.key",
    ]
    created_any = False
    for p in candidates:
        if p.exists():
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"")
            logger.info("已创建空 license.key 以支持离线模式: %s", p)
            created_any = True
        except OSError as e:
            logger.warning("创建 license.key 失败 (%s): %s", p, e)
    return created_any


def _kill_residual(name: str) -> None:
    """杀掉残留同名进程（Windows）。"""
    try:
        subprocess.run(
            ["taskkill", "/IM", f"{name}.exe", "/F"],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass


# ================================ 测试数据 ================================ #

@pytest.fixture(scope="session")
def sample_images_dir(tmp_path_factory) -> Path:
    """生成 3 张测试图片（不同格式/尺寸）到临时目录。"""
    d = tmp_path_factory.mktemp("sample_images")
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        pytest.skip(f"PIL 未安装，无法生成测试图片: {e}")

    specs = [
        ("img_001.png", (640, 480), "PNG"),
        ("img_002.jpg", (800, 600), "JPEG"),
        ("img_003.bmp", (320, 240), "BMP"),
    ]
    for name, size, fmt in specs:
        img = Image.new("RGB", size, color=(80, 120, 200))
        draw = ImageDraw.Draw(img)
        # 画一个矩形目标，便于标注
        draw.rectangle([size[0]//4, size[1]//4, size[0]*3//4, size[1]*3//4],
                       outline=(220, 60, 60), width=4)
        img.save(d / name, format=fmt)
    logger.info("生成测试图片: %s (%d 张)", d, len(specs))
    return d


@pytest.fixture()
def workspace_dir(tmp_path) -> Path:
    """每个测试用的工作目录（数据管理目标目录 / 标注输出 / 部署输出）。"""
    d = tmp_path / "workspace"
    d.mkdir()
    (d / "data").mkdir()      # 数据管理目标目录
    (d / "models").mkdir()    # 部署输出目录
    (d / "labels").mkdir()    # 标注输出目录
    return d


@pytest.fixture()
def fake_model_path(workspace_dir) -> Path:
    """伪造 .pt 模型文件（部署页"浏览"选择用，仅供流程触发）。

    部署页内部 ``torch.load`` 会因无 torch 或格式不符而失败 —— 这不影响
    "部署流程被触发"的验证（状态变"导出进行中..."）。若环境有 torch + 真实
    模型，可设置 AVA_UIA_MODEL 指向真实 .pt。
    """
    real = os.environ.get("AVA_UIA_MODEL")
    if real and os.path.exists(real):
        return Path(real)
    p = workspace_dir / "models" / "fake_model.pt"
    # 写入占位字节（非真实 torch 序列化格式）
    p.write_bytes(b"FAKE_PT_FOR_UIA_TEST")
    return p
