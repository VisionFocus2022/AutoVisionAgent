"""派生 CPU-lite 发行版（W19 v3 第三波 FR-3.2；主审蒸馏冒烟后方案 v2）。

背景（v3 报告 #16 实测）：dist/AutoVisionAgent 4.4G，其中
``_internal/torch/lib`` 3.42G、CUDA 栈 ~3.24G；纯 CPU 栈仅 ~0.26G。

**方案 v1（仅裁 DLL）已被蒸馏冒烟实证否定**：CUDA 构建的 torch 2.5.1+cu121
（Windows wheel）中 ``torch_python.dll``/``shm.dll``/``torch.dll`` 与
``torchvision/_C.pyd`` 的 PE 导入表硬链 ``torch_cuda.dll``/``c10_cuda.dll``/
``cudart64_12.dll``/``cudnn64_9.dll``，且 ``torch/__init__._load_dll_libraries``
对 ``torch/lib`` 内每个 DLL 强制加载——裁掉 CUDA DLL 后 ``import torch`` 必崩
（WinError 126，实测三次递进定位：c10_cuda→caffe2_nvrtc→shm.dll）。

派生流程 v2（幂等前提：dst 不存在）：
1. ``shutil.copytree`` 完整复制 src → dst（full 产物不动，保 GPU 训练）；
2. 仅在 ``dst/_internal/torch/lib`` 内删除命中 CUDA 前缀白名单的 DLL（留档
   cu 构建真实裁剪量；含主审补录的残余 CUDA 链前缀 c10_cuda/caffe2_nvrtc/
   nvToolsExt）；
3. **CPU 轮子替换**：用版本严格对应的 CPU 轮子（torch/torchvision，本地 tag
   剥离后必须同版本）整目录替换 ``dst/_internal/{torch,torchvision}``——这是
   lite 可用的唯一路径（见上）。轮子目录缺失时自动 ``pip download``
   （``--offline`` 禁网则 exit(3)）；版本不符 exit(3)；
4. 写 ``dst/LITE_MARKER.json`` v2（裁剪清单+逐项字节+总量+时间戳+替换清单）；
5. 体积门禁：递归总量 ≥ max_bytes（默认 2GiB）→ stderr 报体积并 exit(1)。

设计约束：``select_cuda_dlls`` 为纯函数（与文件系统遍历解耦，可单测——
tests/test_w19_lite_dist.py）；真正对真 dist 的派生由发版主审执行（FR-3.5）。

用法::

    python scripts/make_lite_dist.py \
        --source dist/AutoVisionAgent --dest dist/AutoVisionAgent-lite \
        --cpu-wheels build/cpu_wheels --max-gb 2.0
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

# W19（v3 第三波 FR-3.2）：CUDA DLL 前缀白名单（allowlist 模式）。
# 大小写不敏感；精确 startswith 语义（子串不算，torch_cpu/c10/shm/fbgemm 等
# 纯 CPU 栈与 vcruntime/libiomp 运行库均不命中）。c10_cuda/caffe2_nvrtc/
# nvToolsExt 为主审蒸馏冒烟实证的残余 CUDA 链（依赖被裁的 torch_cuda/nvrtc）。
CUDA_DLL_PREFIXES: tuple[str, ...] = (
    "torch_cuda",
    "c10_cuda",
    "caffe2_nvrtc",
    "nvtoolsext",
    "cudnn",
    "cublas",
    "cusparse",
    "cufft",
    "cusolver",
    "curand",
    "nvrtc",
    "nvjitlink",
    "cupti",
    "cudart",
)

# CPU 轮子替换的包清单（顺序即处理顺序）
_CPU_WHEEL_PACKAGES: tuple[str, ...] = ("torch", "torchvision")
_CPU_WHEEL_INDEX = "https://download.pytorch.org/whl/cpu"

DEFAULT_SOURCE = "dist/AutoVisionAgent"
DEFAULT_DEST = "dist/AutoVisionAgent-lite"
DEFAULT_WHEELS_DIR = "build/cpu_wheels"
DEFAULT_MAX_GB = 2.0
_MARKER_NAME = "LITE_MARKER.json"
_TOOL_TAG = "[make_lite_dist]"


def select_cuda_dlls(names: Iterable[str]) -> set:
    """从文件名集合中选出 CUDA 栈 DLL（前缀白名单命中）。

    纯函数：与文件系统遍历解耦（PRD FR-3.2 要求可独立单测）。

    Args:
        names: 候选文件名集合（torch/lib 下任意来源）。

    Returns:
        命中白名单的文件名集合（大小写不敏感、精确 startswith 语义）。
    """
    return {
        name for name in names
        if name.lower().startswith(CUDA_DLL_PREFIXES)
    }


def _fail(code: int, message: str) -> None:
    """stderr 报错并退出（错误路径统一收口）。"""
    print(f"{_TOOL_TAG} {message}", file=sys.stderr)
    sys.exit(code)


def _prune_cuda_dlls(dst: Path) -> dict[str, int]:
    """仅删除 ``dst/_internal/torch/lib`` 内命中白名单的文件。

    Args:
        dst: 派生产物根目录（已复制完成）。

    Returns:
        ``{被删文件名: 字节数}``（供 LITE_MARKER.json 留档）。
    """
    lib_dir = dst / "_internal" / "torch" / "lib"
    if not lib_dir.is_dir():
        return {}
    pruned: dict[str, int] = {}
    for entry in sorted(lib_dir.iterdir()):
        if entry.is_file() and entry.name.lower().startswith(CUDA_DLL_PREFIXES):
            pruned[entry.name] = entry.stat().st_size
            entry.unlink()
    return pruned


def _prune_optional_packages(dst: Path, packages: tuple) -> dict[str, int]:
    """删除 ``dst/_internal`` 下可选包目录（W32：lite 明确排除 easyocr——
    推理-only 可选件不占 2GiB 预算；lite 内引擎照常注册、load 诚实报
    安装指引）。

    Returns:
        ``{被删目录名: 字节数}``（供 LITE_MARKER.json 留档）。
    """
    pruned: dict[str, int] = {}
    internal = dst / "_internal"
    for name in packages:
        pkg_dir = internal / name
        if not pkg_dir.is_dir():
            continue
        total = sum(
            f.stat().st_size for f in pkg_dir.rglob("*") if f.is_file()
        )
        import shutil as _shutil

        _shutil.rmtree(pkg_dir)
        pruned[name] = total
    return pruned


def _pkg_version(pkg_dir: Path) -> str | None:
    """从包目录探读 ``__version__``（version.py 优先，回退 __init__.py）。

    Returns:
        版本串（如 ``2.5.1+cu121``）；目录缺失/无可读版本 → None。
    """
    for candidate in ("version.py", "__init__.py"):
        path = pkg_dir / candidate
        if not path.is_file():
            continue
        match = re.search(
            r"__version__\s*=\s*['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8")
        )
        if match:
            return match.group(1)
    return None


def _find_wheel(wheels_dir: Path, pkg: str, base_version: str) -> Path | None:
    """在轮子目录找 ``{pkg}-{base_version}+cpu-*.whl``（版本严格对应）。"""
    if not wheels_dir.is_dir():
        return None
    for whl in sorted(wheels_dir.glob(f"{pkg}-{base_version}+cpu-*.whl")):
        return whl
    return None


def _download_wheel(wheels_dir: Path, pkg: str, base_version: str) -> Path:
    """pip download 取 CPU 轮子（唯一触网点；失败 exit(3)）。"""
    wheels_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "download",
        f"{pkg}=={base_version}+cpu",
        "--index-url", _CPU_WHEEL_INDEX,
        "--no-deps", "-d", str(wheels_dir),
    ]
    print(f"{_TOOL_TAG} 下载 CPU 轮子: {pkg}=={base_version}+cpu")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _fail(
            3,
            f"CPU 轮子下载失败（{pkg}=={base_version}+cpu）: "
            f"{result.stderr.strip()[-300:]}",
        )
    found = _find_wheel(wheels_dir, pkg, base_version)
    if found is None:
        _fail(3, f"下载完成但未找到轮子: {pkg}=={base_version}+cpu")
    return found


def _replace_with_cpu_wheels(
    dst: Path, wheels_dir: Path, allow_download: bool
) -> dict[str, str]:
    """用 CPU 轮子整目录替换 ``_internal/{torch,torchvision}``。

    版本严格对应：源包版本剥离本地 tag（2.5.1+cu121 → 2.5.1）后必须与
    轮子一致，否则 exit(3)（防 ABI 错配静默出库）。源包版本不可探读 →
    告警跳过该包（假树/裁剪模式兼容；真 dist 守卫测试断言替换留档非空）。

    Returns:
        ``{包名: 轮子文件名}``（供 LITE_MARKER.json 留档）。
    """
    internal = dst / "_internal"
    replaced: dict[str, str] = {}
    for pkg in _CPU_WHEEL_PACKAGES:
        pkg_dir = internal / pkg
        version = _pkg_version(pkg_dir)
        if version is None:
            print(
                f"{_TOOL_TAG} 警告: {pkg} 版本不可探读，跳过 CPU 轮子替换",
                file=sys.stderr,
            )
            continue
        base_version = version.split("+")[0]
        whl = _find_wheel(wheels_dir, pkg, base_version)
        if whl is None:
            # 报错区分"目录有轮子但版本不符"与"完全没有"（W19 测试锁定）
            others = sorted(
                p.name for p in wheels_dir.glob(f"{pkg}-*+cpu-*.whl")
            ) if wheels_dir.is_dir() else []
            hint = (
                f"轮子版本不符（目录含 {others}，需 {pkg}=={base_version}+cpu）"
                if others
                else f"CPU 轮子缺失（需 {pkg}=={base_version}+cpu）"
            )
            if not allow_download:
                _fail(3, f"{hint} 且 --offline: 目录 {wheels_dir}")
            print(f"{_TOOL_TAG} {hint}，尝试下载", file=sys.stderr)
            whl = _download_wheel(wheels_dir, pkg, base_version)
        with tempfile.TemporaryDirectory(prefix="ava_lite_whl_") as tmp:
            with zipfile.ZipFile(whl) as zf:
                zf.extractall(tmp)
            unpacked = Path(tmp) / pkg
            if not unpacked.is_dir():
                _fail(3, f"轮子内无 {pkg}/ 目录: {whl.name}")
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir)
            shutil.copytree(unpacked, pkg_dir)
        replaced[pkg] = whl.name
    return replaced


def _tree_bytes(root: Path) -> int:
    """递归统计目录内全部文件字节总量。"""
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _product_bytes(root: Path) -> int:
    """产品内容字节（排除 ``__pycache__``/``*.pyc`` 运行时字节码缓存）。

    与真产物守卫测试同口径：任何 ``PYTHONPATH=_internal`` 使用（蒸馏冒烟
    等）都会在产物内生成字节码缓存，属使用痕迹非产品内容；PyInstaller
    产物亦自带少量 .pyc——marker 与守卫必须同口径才可字节级对账。
    """
    return sum(
        p.stat().st_size
        for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
    )


def _write_marker(
    dst: Path,
    src: Path,
    pruned: dict[str, int],
    replaced: dict[str, str],
    total_bytes: int,
    max_bytes: int,
) -> None:
    """落 LITE_MARKER.json v2（裁剪+替换留档 + 总量 + 时间戳）。"""
    marker = {
        "version": 2,
        "derived_from": str(src),
        "derived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pruned_dlls": sorted(pruned),
        "pruned_bytes": dict(sorted(pruned.items())),
        "pruned_total_bytes": sum(pruned.values()),
        # CPU 轮子替换留档（空 = 纯裁剪模式；真产物守卫断言非空）
        "replaced_packages": replaced,
        # 裁剪后、写 marker 前的递归总量（marker 自身开销不计入，
        # 守卫测试以 total - marker_bytes == marker 文件大小 校验口径一致）
        "total_bytes": total_bytes,
        "max_bytes": max_bytes,
    }
    (dst / _MARKER_NAME).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def derive_lite(
    src: str | Path,
    dst: str | Path,
    max_bytes: int = 2 * 1024**3,
    cpu_wheels_dir: str | Path | None = None,
    allow_download: bool = True,
) -> Path:
    """完整 dist → CPU-lite dist 派生（W19 FR-3.2 方案 v2）。

    copytree → 裁剪 CUDA DLL（留档）→ （可选）CPU 轮子整目录替换
    torch/torchvision → 写 LITE_MARKER.json v2 → 总量 ≥ max_bytes 则
    stderr 报体积并 exit(1)。

    Args:
        src: 完整发行版目录（保持不动）。
        dst: lite 输出目录（必须不存在，拒绝覆盖已有产物）。
        max_bytes: 体积门禁上限字节（PRD AC-3.2 默认 2GiB）。
        cpu_wheels_dir: CPU 轮子目录（None = 纯裁剪模式，不替换——
            单测/边界场景；真派生必须提供以获得可用 lite）。
        allow_download: 轮子缺失时是否允许 pip download（--offline 关闭）。

    Returns:
        派生成功的 dst 路径。

    Raises:
        SystemExit: 源缺失/目标已存在/轮子缺失或版本不符（exit 2/3）；
            超限（exit 1）。
    """
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.is_dir():
        _fail(2, f"源发行版目录不存在: {src_path}")
    if dst_path.exists():
        _fail(2, f"目标目录已存在，拒绝覆盖: {dst_path}")

    shutil.copytree(src_path, dst_path)

    pruned = _prune_cuda_dlls(dst_path)
    # W32：lite 明确排除 OCR 可选件（引擎注册零成本，load 诚实报指引）
    pruned.update(_prune_optional_packages(
        dst_path,
        # easyocr 本体 + 独占依赖（pip Required-by 唯一依赖方=easyocr，
        # v5 P2-N2：余量 2.4MB 时 ~15MB 残留不可接受）
        ("easyocr", "bidi", "pyclipper", "shapely", "Shapely.libs"),
    ))
    replaced: dict[str, str] = {}
    if cpu_wheels_dir is not None:
        replaced = _replace_with_cpu_wheels(
            dst_path, Path(cpu_wheels_dir), allow_download
        )
    # marker 与门禁统一"产品字节"口径（排 __pycache__/.pyc，见 _product_bytes）
    total_bytes = _product_bytes(dst_path)
    _write_marker(dst_path, src_path, pruned, replaced, total_bytes, max_bytes)

    # 门禁用含 marker 自身在内的最终产品总量（宁可误杀，不可漏放；
    # marker 为 .json 不属排除项，天然计入）
    final_total = _product_bytes(dst_path)
    if final_total >= max_bytes:
        print(
            f"{_TOOL_TAG} 派生产物 {final_total} 字节"
            f"（{final_total / 1024**3:.3f} GiB）≥ 上限 {max_bytes} 字节"
            f"（{max_bytes / 1024**3:.3f} GiB），拒绝出库（W19 FR-3.2 体积门禁）",
            file=sys.stderr,
        )
        sys.exit(1)
    return dst_path


def main(argv: list[str] | None = None) -> int:
    """argparse 入口（默认参数对应发版主审 FR-3.5 的真派生命令）。"""
    parser = argparse.ArgumentParser(
        description="AutoVisionAgent CPU-lite 发行版派生（W19 v3 第三波 FR-3.2）",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"完整发行版目录（默认 {DEFAULT_SOURCE}）",
    )
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST,
        help=f"lite 输出目录（默认 {DEFAULT_DEST}）",
    )
    parser.add_argument(
        "--cpu-wheels",
        default=DEFAULT_WHEELS_DIR,
        help=(f"CPU 轮子目录（默认 {DEFAULT_WHEELS_DIR}；缺失自动 "
              f"pip download，版本与源严格对应）"),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="禁用轮子自动下载（缺失即 exit(3)，不触网）",
    )
    parser.add_argument(
        "--max-gb",
        type=float,
        default=DEFAULT_MAX_GB,
        help=f"lite 体积上限 GiB，超限 exit(1)（默认 {DEFAULT_MAX_GB}）",
    )
    args = parser.parse_args(argv)
    derive_lite(
        args.source, args.dest,
        max_bytes=int(args.max_gb * 1024**3),
        cpu_wheels_dir=args.cpu_wheels,
        allow_download=not args.offline,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
