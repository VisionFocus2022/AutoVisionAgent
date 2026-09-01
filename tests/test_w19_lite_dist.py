"""W19（v3 第三波 FR-3.2/3.3）dist-lite 派生脚本测试。

PRD docs/prd-wave19-v3-wave3.md FR-3.2/3.3：
- ``select_cuda_dlls``：allowlist 前缀匹配纯函数（与文件系统遍历解耦可单测），
  前缀白名单 torch_cuda / c10_cuda / caffe2_nvrtc / nvToolsExt / cudnn / cublas /
  cusparse / cufft / cusolver / curand / nvrtc / nvJitLink / cupti / cudart，
  大小写不敏感、精确 startswith 语义；
- **CPU 轮子替换（W19 主审蒸馏冒烟实证后的方案 v2）**：CUDA 构建 torch 的
  torch_python.dll/shm.dll/torch.dll/torchvision._C.pyd PE 导入表硬链
  torch_cuda.dll/c10_cuda/cudart/cudnn64_9——仅裁 DLL 后 import torch 必崩
  （WinError 126）。故派生 = 复制 → 裁剪（留档）→ 用 CPU 轮子整目录替换
  _internal/torch 与 _internal/torchvision → marker v2 记 replaced_packages；
- ``derive_lite``：tmp 假树集成（纯裁剪模式 cpu_wheels_dir=None 与替换模式
  分别覆盖）——marker（清单+字节+总量+时间戳+替换清单）→ 超限 exit(1)；
- 真产物 ``dist/AutoVisionAgent-lite`` 存在时的守卫（无 CUDA DLL + <2GiB +
  marker 与目录一致 + replaced_packages 非空）；不存在则 skip。
"""
from __future__ import annotations

import importlib.util
import json
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = REPO_ROOT / "scripts" / "make_lite_dist.py"
_LITE_DIST = REPO_ROOT / "dist" / "AutoVisionAgent-lite"
_TWO_GIB = 2 * 1024**3


def _load_module():
    """scripts/ 非包：按文件路径加载 make_lite_dist（避免 sys.path 污染）。

    RED 阶段脚本缺失 → 收集期 FileNotFoundError，即"缺失行为"式失败。
    """
    spec = importlib.util.spec_from_file_location("make_lite_dist", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mld = _load_module()


def _tree_bytes(root: Path) -> int:
    """递归统计目录内全部文件字节（与实现同口径，供一致性断言）。"""
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


# ============================== select_cuda_dlls 纯函数 ============================== #

# 命中集：背景实测 dist/_internal/torch/lib CUDA 栈清单（含大小写不敏感样例；
# c10_cuda/caffe2_nvrtc/nvToolsExt 为蒸馏冒烟实证的残余 CUDA 链 W19 主审补录）
_POSITIVE = (
    "torch_cuda.dll",
    "c10_cuda.dll",
    "caffe2_nvrtc.dll",
    "nvToolsExt64_1.dll",
    "cudnn_adv64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_ops64_9.dll",
    "cublasLt64_12.dll",
    "cublas64_12.dll",
    "cusparse64_10.dll",
    "cufft64_11.dll",
    "cusolver64_11.dll",
    "cusolverMg64_11.dll",
    "curand64_10.dll",
    "nvrtc64_120_0.dll",
    "nvrtc-builtins64_121.dll",
    "nvJitLink64_0.dll",
    "cupti64_2023.1.1.dll",
    "cudart64_12.dll",
    "TORCH_CUDA.DLL",
    "Cudart64_12.dll",
)

# 负例：纯 CPU 栈 + 非 torch/lib 语义白名单陷阱（子串不算命中，前缀必须开头）
_NEGATIVE = (
    "torch_cpu.dll",
    "torch_python.dll",
    "torch_global_deps.dll",
    "fbgemm.dll",
    "c10.dll",
    "shm.dll",
    "libiomp5md.dll",
    "vcruntime140.dll",
    "mycudnn.dll",
    "torchcudart.dll",
    "caffe2.dll",
)


def test_select_cuda_dlls_hits_cuda_stack():
    assert mld.select_cuda_dlls(_POSITIVE) == set(_POSITIVE)


def test_select_cuda_dlls_keeps_cpu_stack():
    assert mld.select_cuda_dlls(_NEGATIVE) == set()


def test_select_cuda_dlls_mixed():
    mixed = list(_POSITIVE[:3]) + list(_NEGATIVE)
    assert mld.select_cuda_dlls(mixed) == set(_POSITIVE[:3])


# ============================== derive_lite 假树集成 ============================== #

# 假 torch/lib 树：CUDA 栈（应删）+ 纯 CPU 栈（应保留）
_FAKE_LIB_FILES: dict[str, int] = {
    "torch_cuda.dll": 1000,
    "cudnn_adv64_9.dll": 500,
    "cublasLt64_12.dll": 300,
    "torch_cpu.dll": 700,
    "torch_python.dll": 200,
    "fbgemm.dll": 50,
    "c10.dll": 20,
    "libiomp5md.dll": 10,
    "vcruntime140.dll": 5,
}


def _make_fake_dist(root: Path, with_versions: bool = False) -> Path:
    """构造假发行版：exe + _internal/torch/lib 正负例 + lib 外同名守卫文件。

    with_versions=True 时补 torch/version.py（2.5.1+cu121）与
    torchvision/__init__.py（0.20.1+cu121）——CPU 轮子替换模式的探测点。
    """
    src = root / "AutoVisionAgent"
    lib = src / "_internal" / "torch" / "lib"
    lib.mkdir(parents=True)
    (src / "AutoVisionAgent.exe").write_bytes(b"MZ" * 8)  # 16 字节
    for name, size in _FAKE_LIB_FILES.items():
        (lib / name).write_bytes(b"\0" * size)
    # torch/lib 之外的同名文件不得被裁剪（FR-3.2：仅匹配 torch/lib 下）
    outside = src / "_internal" / "other"
    outside.mkdir(parents=True)
    (outside / "torch_cuda.dll").write_bytes(b"\0" * 400)
    if with_versions:
        (src / "_internal" / "torch" / "version.py").write_text(
            "__version__ = '2.5.1+cu121'\n", encoding="utf-8"
        )
        tv = src / "_internal" / "torchvision"
        tv.mkdir(parents=True, exist_ok=True)
        (tv / "__init__.py").write_text(
            '__version__ = "0.20.1+cu121"\n', encoding="utf-8"
        )
    return src


def _make_cpu_wheel(
    wheels_dir: Path, pkg: str, version: str, sentinel: str
) -> str:
    """伪造 CPU 轮子（zip：{pkg}/version.py + {pkg}/__init__.py + 哨兵文件）。

    真轮子由主审经 pip download 取得（torch 2.5.1+cpu / torchvision 0.20.1+cpu，
    FR-3.5 证据）；单测不触网，用同构 zip 覆盖替换逻辑。
    """
    wheels_dir.mkdir(parents=True, exist_ok=True)
    name = f"{pkg}-{version}+cpu-cp312-cp312-win_amd64.whl"
    with zipfile.ZipFile(wheels_dir / name, "w") as z:
        z.writestr(f"{pkg}/version.py", f"__version__ = '{version}+cpu'\n")
        z.writestr(f"{pkg}/__init__.py", f"__version__ = '{version}+cpu'\n")
        z.writestr(f"{pkg}/{sentinel}", "cpu-wheel-content")
    return name


_PRUNED_NAMES = ["cublasLt64_12.dll", "cudnn_adv64_9.dll", "torch_cuda.dll"]


def test_derive_lite_prunes_only_within_torch_lib(tmp_path):
    """裁剪只发生在 dst/_internal/torch/lib，源目录与 lib 外文件不动。"""
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite"

    out = mld.derive_lite(src, dst, max_bytes=10 * 1024**3)
    assert out == Path(dst)

    lib = dst / "_internal" / "torch" / "lib"
    for name in _PRUNED_NAMES:
        assert not (lib / name).exists(), f"{name} 应被裁剪"
    for name in _FAKE_LIB_FILES:
        if name not in _PRUNED_NAMES:
            assert (lib / name).exists(), f"{name} 属纯 CPU 栈应保留"
    assert (dst / "AutoVisionAgent.exe").exists()
    # 仅 torch/lib：lib 外同名不动；派生不动源
    assert (dst / "_internal" / "other" / "torch_cuda.dll").exists()
    assert (src / "_internal" / "torch" / "lib" / "torch_cuda.dll").exists()


def test_derive_lite_cpu_wheel_replacement(tmp_path):
    """CPU 轮子替换模式：torch/torchvision 整目录换成轮子内容并留档。

    W19 主审蒸馏冒烟实证：CUDA 构建 torch 仅裁 DLL 必崩（硬链），替换为
    CPU 轮子是 lite 可用的唯一路径。
    """
    src = _make_fake_dist(tmp_path, with_versions=True)
    wheels = tmp_path / "cpu_wheels"
    torch_whl = _make_cpu_wheel(wheels, "torch", "2.5.1", "CPU_WHEEL_SENTINEL")
    tv_whl = _make_cpu_wheel(wheels, "torchvision", "0.20.1", "TV_CPU_SENTINEL")
    dst = tmp_path / "lite"

    mld.derive_lite(src, dst, max_bytes=10 * 1024**3, cpu_wheels_dir=wheels)

    # torch/torchvision 已整目录替换：轮子哨兵在、+cpu 版本在、旧内容不复存在
    assert (dst / "_internal" / "torch" / "CPU_WHEEL_SENTINEL").is_file()
    assert (dst / "_internal" / "torchvision" / "TV_CPU_SENTINEL").is_file()
    ver = (dst / "_internal" / "torch" / "version.py").read_text(encoding="utf-8")
    assert "2.5.1+cpu" in ver
    # 裁剪仍先于替换发生（marker 留档 cu 构建真实裁剪量）
    lib = dst / "_internal" / "torch" / "lib"
    assert not lib.exists() or not (lib / "torch_cuda.dll").exists()

    marker = json.loads(
        (dst / "LITE_MARKER.json").read_text(encoding="utf-8")
    )
    assert marker["replaced_packages"] == {
        "torch": torch_whl, "torchvision": tv_whl,
    }


def test_derive_lite_wheel_version_mismatch_fails(tmp_path, capsys):
    """轮子版本与源不符（2.4.0 vs 2.5.1）→ exit(3) 拒绝派生。"""
    src = _make_fake_dist(tmp_path, with_versions=True)
    wheels = tmp_path / "cpu_wheels"
    _make_cpu_wheel(wheels, "torch", "2.4.0", "S")  # 版本不符
    with pytest.raises(SystemExit) as excinfo:
        mld.derive_lite(
            src, tmp_path / "lite", max_bytes=10 * 1024**3,
            cpu_wheels_dir=wheels, allow_download=False,
        )
    assert excinfo.value.code == 3
    assert "版本" in capsys.readouterr().err


def test_derive_lite_wheel_missing_offline_fails(tmp_path, capsys):
    """离线且轮子缺失 → exit(3)（不触网、不静默跳过替换）。"""
    src = _make_fake_dist(tmp_path, with_versions=True)
    wheels = tmp_path / "cpu_wheels"
    wheels.mkdir()
    with pytest.raises(SystemExit) as excinfo:
        mld.derive_lite(
            src, tmp_path / "lite", max_bytes=10 * 1024**3,
            cpu_wheels_dir=wheels, allow_download=False,
        )
    assert excinfo.value.code == 3


def test_derive_lite_marker_content(tmp_path):
    """LITE_MARKER.json：裁剪清单/逐项字节/总量/时间戳齐全且与目录一致。"""
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite"
    mld.derive_lite(src, dst, max_bytes=10 * 1024**3)

    marker_path = dst / "LITE_MARKER.json"
    assert marker_path.is_file()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["pruned_dlls"] == _PRUNED_NAMES
    assert marker["pruned_bytes"] == {
        "cublasLt64_12.dll": 300,
        "cudnn_adv64_9.dll": 500,
        "torch_cuda.dll": 1000,
    }
    assert marker["pruned_total_bytes"] == 1800
    assert marker["derived_at"]  # 时间戳留档
    assert marker.get("replaced_packages") in (None, {})  # 纯裁剪模式未替换
    # total_bytes 与目录现状一致：裁剪后总量 + marker 自身开销
    assert _tree_bytes(dst) - marker["total_bytes"] == marker_path.stat().st_size


def test_derive_lite_over_limit_exits_nonzero(tmp_path, capsys):
    """假 max_bytes 触发超限：stderr 报体积并 exit(1)，marker 仍先落盘。"""
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite"
    # 裁剪后剩余 exe16 + lib985 + other400 = 1401 字节，加 marker 后仍 >1024
    with pytest.raises(SystemExit) as excinfo:
        mld.derive_lite(src, dst, max_bytes=1024)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "make_lite_dist" in err
    assert (dst / "LITE_MARKER.json").is_file()  # 先写 marker 再门禁


def test_derive_lite_refuses_overwrite_existing_dst(tmp_path):
    """dst 已存在时拒绝覆盖（防误删已有 lite 产物）。"""
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite"
    mld.derive_lite(src, dst, max_bytes=10 * 1024**3)
    with pytest.raises(SystemExit) as excinfo:
        mld.derive_lite(src, dst, max_bytes=10 * 1024**3)
    assert excinfo.value.code != 0


def test_derive_lite_missing_source_exits_nonzero(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        mld.derive_lite(tmp_path / "nope", tmp_path / "lite")
    assert excinfo.value.code != 0
    assert "不存在" in capsys.readouterr().err


# ============================== argparse 入口 ============================== #


def test_cli_main_roundtrip(tmp_path):
    """CLI 显式参数成功路径 rc=0（测试绝不以默认参数触碰真 dist）。"""
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite_cli"
    argv: list[str] = [
        "--source", str(src),
        "--dest", str(dst),
        "--max-gb", "10",
        "--offline",  # 无版本文件 → 跳过替换（stderr 告警），纯裁剪路径
    ]
    assert mld.main(argv) == 0
    assert (dst / "LITE_MARKER.json").is_file()
    assert not (dst / "_internal" / "torch" / "lib" / "torch_cuda.dll").exists()


def test_cli_main_over_limit_exits_nonzero(tmp_path):
    src = _make_fake_dist(tmp_path)
    dst = tmp_path / "lite_cli"
    with pytest.raises(SystemExit) as excinfo:
        mld.main(["--source", str(src), "--dest", str(dst), "--max-gb", "0.0000001", "--offline"])
    assert excinfo.value.code == 1


def test_derive_lite_prunes_sam3_weights(tmp_path):
    """SAM3 权重裁剪锚（2026-09-01 spec datas 纳入批 FR-003）。

    full dist 经 spec datas 携带 weights/sam3（3.21GiB）后，lite 派生
    必须裁掉——lite 是 CPU-only 且 2GiB 硬预算装不下；引擎注册保留、
    load 走诚实失败路径（easyocr 同语义）。裁剪量须留档 marker。
    """
    src = _make_fake_dist(tmp_path)
    sam3 = src / "_internal" / "weights" / "sam3"
    sam3.mkdir(parents=True)
    (sam3 / "model.safetensors").write_bytes(b"\0" * 1024)
    (sam3 / "config.json").write_text("{}", encoding="utf-8")
    dst = tmp_path / "lite"

    mld.derive_lite(src, dst, max_bytes=10 * 1024**3)

    assert not (dst / "_internal" / "weights" / "sam3").exists(), (
        "lite 派生后 weights/sam3 应被整体裁剪（2GiB 预算 + CPU-only）"
    )
    assert (src / "_internal" / "weights" / "sam3" / "model.safetensors").exists(), (
        "裁剪只动 dst，full 源产物的权重必须原样保留"
    )
    marker = json.loads((dst / "LITE_MARKER.json").read_text(encoding="utf-8"))
    assert "weights/sam3" in marker["pruned_dlls"], (
        f"weights/sam3 裁剪应留档 marker（实测 pruned_dlls={marker['pruned_dlls']}）"
    )
    assert marker["pruned_bytes"]["weights/sam3"] == 1024 + 2


# ============================== 真产物守卫（FR-3.3） ============================== #


def test_real_lite_dist_guard():
    """真 lite 产物存在时：无 CUDA DLL + 总量 <2GiB + marker 与目录一致。

    体积与一致性口径排除 ``__pycache__``/``*.pyc``/``logs/``：蒸馏冒烟等
    ``PYTHONPATH=_internal`` 使用会生成字节码缓存；lite exe 被启动过即按
    cwd 相对落 ``logs/autovision.log``——均属使用痕迹而非产品内容
    （2026-08-31 实证：346B log 击穿字节级对账；与 make_lite_dist.
    _product_bytes 同口径，两处豁免面必须同步增减）。
    """
    if not _LITE_DIST.is_dir():
        pytest.skip(
            f"{_LITE_DIST} 尚未派生（真派生归主审 FR-3.5；CI 无构建产物）"
        )
    lib = _LITE_DIST / "_internal" / "torch" / "lib"
    names: Iterable[str] = (p.name for p in lib.iterdir()) if lib.is_dir() else []
    assert mld.select_cuda_dlls(names) == set(), "CUDA DLL 不得残留"
    # CPU 轮子替换必须真实发生（替换缺失 = 硬链 CUDA 的不可用 lite）
    torch_ver = _LITE_DIST / "_internal" / "torch" / "version.py"
    assert torch_ver.is_file(), "torch/version.py 应来自 CPU 轮子"
    assert "+cpu" in torch_ver.read_text(encoding="utf-8")

    def product_bytes(root: Path) -> int:
        return sum(
            p.stat().st_size
            for p in root.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix != ".pyc"
            and "logs" not in p.parts
        )

    total = product_bytes(_LITE_DIST)
    assert total < _TWO_GIB, f"PRD AC-3.2 要求 lite <2GiB，实测 {total} 字节"
    # W45·P3-14 余量棘轮：硬线 5MiB（现状 ~6.5MiB）；<10MiB 打预警非阻塞。
    # 棘轮只升不降——击穿硬线先减重（剪除/换 CPU 轮）再谈升线。
    margin = _TWO_GIB - total
    assert margin >= 5 * 1024 * 1024, (
        f"lite 余量 {margin / 1048576:.2f}MiB 击穿 5MiB 棘轮——先减重再调整"
    )
    if margin < 10 * 1024 * 1024:
        print(
            f"[WARN] lite 余量 {margin / 1048576:.2f}MiB < 10MiB 预警线"
            "（非阻塞；任一新依赖波动即破线，建议下个版本节点减重）"
        )

    marker_path = _LITE_DIST / "LITE_MARKER.json"
    assert marker_path.is_file()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["pruned_dlls"], "完整 dist 实测含 ~3.24G CUDA 栈，清单不应为空"
    assert marker.get("replaced_packages"), "CPU 轮子替换留档不应为空"
    for name in marker["pruned_dlls"]:
        assert not (lib / name).exists(), f"清单内 {name} 应已不在目录"
    assert total - marker["total_bytes"] == marker_path.stat().st_size
