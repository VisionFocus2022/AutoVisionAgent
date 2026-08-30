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

import contextlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# 确保仓库根目录在 sys.path 中，便于 `from tests.uia...` 导入
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 同时把 tests/uia 目录加入 sys.path，兼容 pytest 将 conftest 当作顶层
# 模块加载的场景（此时 `tests.uia` 包不可用，需直接导入 uia_helpers）
_TESTS_UIA_DIR = Path(__file__).resolve().parent
if str(_TESTS_UIA_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_UIA_DIR))


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

@pytest.fixture()
def ava_app():
    """启动 AutoVisionAgent 并返回主窗口控件，测试结束后关闭进程。

    W11 起 function 级（每用例独立启动被测应用——uia-autofix-loop plan-phase
    生命周期纪律）：会话级复用在 6 用例下出现 UIA 树随页面内容膨胀导致的
    渐进性查找失稳（W11 基线实测 5/6 → 1/6 随机翻车）。代价 ~20s/次启动。

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
            with contextlib.suppress(OSError):
                p.unlink()


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
    # W23（v4 P2-1c）：exe 模式剥掉 AVA_LOG_DIR——保持 exe 日志/审计落
    # dist\AutoVisionAgent\logs（cwd 相对）供 UIA 失败排查，不被 pytest
    # 会话临时目录劫走（python 源码分支继承 env 正是隔离所需，不动）。
    exe_env = {k: v for k, v in os.environ.items() if k != "AVA_LOG_DIR"}
    return subprocess.Popen([exe], cwd=os.path.dirname(exe), env=exe_env)


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
    with contextlib.suppress(Exception):
        subprocess.run(
            ["taskkill", "/IM", f"{name}.exe", "/F"],
            capture_output=True, timeout=10,
        )


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


# ================================ 极柱真实数据 ================================ #

# 极柱外观检数据集（用户指定测试图片源，可经 AVA_UIA_POLE_DIR 覆写）
POLE_SOURCE_DIR = Path(os.environ.get(
    "AVA_UIA_POLE_DIR", r"E:\学习项目\极柱外观检标注图"
))


@pytest.fixture(scope="session")
def pole_subset_dir(tmp_path_factory) -> Path:
    """从极柱数据集抽 8 张真实 bmp 到临时目录（4 正常 + 4 缺陷）。

    - 正常图：文件名 "(N)" 前缀；缺陷图：纯数字前缀（数据集约定）。
    - 括号文件名 + 1600x1600 真图：中文/特殊字符读图路径的天然探针
      （历史坑：cv2.imread 对 "(N)" 与非 ASCII 路径解析失败）。
    - 源目录不存在时 skip（fail-honest，不造假图冒充）。
    """
    if not POLE_SOURCE_DIR.is_dir():
        pytest.skip(f"极柱数据集不存在: {POLE_SOURCE_DIR}")

    import shutil

    d = tmp_path_factory.mktemp("pole_subset")
    normals = sorted(POLE_SOURCE_DIR.glob("(N)*.bmp"))
    defects = sorted(
        (p for p in POLE_SOURCE_DIR.glob("*.bmp") if p.name[:1].isdigit()),
        key=lambda p: p.name,
    )
    picked = normals[:4] + defects[:4]
    if len(picked) < 8:
        pytest.skip(
            f"极柱数据集样本不足（正常 {len(normals)} / 缺陷 {len(defects)}）: {POLE_SOURCE_DIR}"
        )
    for src in picked:
        shutil.copy2(src, d / src.name)
    logger.info("极柱子集: %s（%d 张）", d, len(picked))
    return d


# ================================ W25 扩面 fixtures ================================ #

@pytest.fixture(scope="session")
def tiny_det_model_path(tmp_path_factory) -> Path:
    """W25（FR-002/003）：离线构造的可加载 det 权重。

    T2a 调查实证：full_workflow 训练步为 _SimStrategy 模拟训练、零 .pt
    落盘——复用链上产物不可行；本 fixture 用 ultralytics YAML 构造
    yolov8n + torch.save 标准 ckpt 字典（约 12.8MB / 0.1s，零网络），
    exe 内 ultralytics 8.4.81 与 .venv 同版，跨环境反序列化已实测通过
    （DetYoloEngine.load→infer→run_eval_task 全链路绿）。AVA_UIA_MODEL
    指向真权重时优先复用（与 fake_model_path 同约定）。
    """
    real = os.environ.get("AVA_UIA_MODEL")
    if real and os.path.exists(real):
        return Path(real)
    try:
        import time as _time

        import torch
        from ultralytics import YOLO
    except ImportError as e:
        pytest.skip(f"ultralytics/torch 不可用，无法构造测试权重: {e}")

    d = tmp_path_factory.mktemp("tiny_model")
    pt = d / "ava_tiny_det.pt"
    m = YOLO("yolov8n.yaml")
    torch.save(
        {
            "model": m.model,
            "train_args": {},
            "train_metrics": {},
            "epoch": -1,
            "date": _time.time(),
            "version": "8.4.81",
        },
        pt,
    )
    logger.info("构造测试权重: %s (%d B)", pt, pt.stat().st_size)
    return pt


@pytest.fixture()
def eval_gt_dir(tmp_path) -> Path:
    """W25（FR-003）：LabelMe 真值目录（1 图 + 1 JSON，单矩形 shape）。"""
    import json

    from PIL import Image, ImageDraw

    d = tmp_path / "eval_gt"
    d.mkdir()
    im = Image.new("RGB", (640, 480), (80, 120, 200))
    ImageDraw.Draw(im).rectangle(
        [160, 120, 480, 360], outline=(220, 60, 60), width=4
    )
    im.save(d / "gt_probe.png")
    (d / "gt_probe.json").write_text(
        json.dumps(
            {
                "version": "5.2.1",
                "flags": {},
                "shapes": [
                    {
                        "label": "defect",
                        "points": [[160.0, 120.0], [480.0, 360.0]],
                        "group_id": None,
                        "shape_type": "rectangle",
                        "flags": {},
                    }
                ],
                "imagePath": "gt_probe.png",
                "imageData": None,
                "imageHeight": 480,
                "imageWidth": 640,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return d


# ============================== W40：真实 admin 登录预置（自 test_full_workflow 共享化） ============================== #

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UIA_ADMIN_PWD_LOCAL = "UiaFlow#2026"  # 与 uia_helpers.UIA_ADMIN_PWD 同源


def _uia_config_dirs() -> list:
    """UIA 可用的应用 config 目录（python 源码模式 + exe 模式双覆盖）。"""
    return [
        _REPO_ROOT / "configs",
        _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal" / "configs",
    ]


@pytest.fixture()
def ready_admin_cfg():
    """预置免改密 admin（users.json 直写，备份还原）——W39 离线降 operator
    后，锁页（train/deploy/settings/project）UIA 流程需真实 admin 登录。

    双模式 config 目录均覆盖；已有 users.json 先备份（.uia-bak），teardown
    还原；无则删除预置件。参数顺序上须先于 ava_app（应用启动前就位）。
    """
    import json

    from core.auth import hash_password

    h, s, iters = hash_password(_UIA_ADMIN_PWD_LOCAL)
    db = {"admin": {
        "password_hash": h, "salt": s, "role": "admin",
        "iterations": iters, "must_change": False,
    }}
    touched: list = []
    try:
        for cfg in _uia_config_dirs():
            if not cfg.exists():
                continue
            users = cfg / "users.json"
            if users.exists():
                bak = cfg / (users.name + ".uia-bak")
                users.replace(bak)
                touched.append((bak, users))
            users.write_text(
                json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            touched.append((users, None))
        yield
    finally:
        for path, restore_to in reversed(touched):
            try:
                if restore_to is None:
                    path.unlink(missing_ok=True)
                else:
                    path.replace(restore_to)
            except OSError:
                logger.warning("还原 %s 失败", path, exc_info=True)


# ================================ W49 环境治理 ================================ #


@pytest.fixture(scope="session", autouse=True)
def _uia_memory_preflight():
    """提交内存预检（W48 教训制度化：并行 AI 代理的僵尸 pytest 可耗尽
    提交内存杀死 UIA 跑批）。低于阈值整组诚实 skip；AVA_UIA_SKIP_ON_LOW_MEM=0 关闭。"""
    import ctypes

    if os.environ.get("AVA_UIA_SKIP_ON_LOW_MEM", "1") == "0":
        return

    class _MEMSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    stat = _MEMSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    avail_gb = stat.ullAvailPageFile / (1024 ** 3)
    if avail_gb < 6.0:
        pytest.skip(
            f"提交内存 {avail_gb:.1f}GB < 6GB（并行代理/僵尸进程挤占）——"
            "UIA 诚实跳过（AVA_UIA_SKIP_ON_LOW_MEM=0 可强制跑）"
        )
