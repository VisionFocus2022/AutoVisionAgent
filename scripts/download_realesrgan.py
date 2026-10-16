"""Real-ESRGAN 离线权重供给脚本（对齐 fetch_ocr_weights.py 供给模式）。

官方发布权重较大（RRDBNet x4plus 约 64MB），离线优先平台须显式预取。
本脚本把权重下载到指定目录并写 sha256 manifest；离线机器将该目录拷到
目标平台后，在推理页以「该目录下的 .pth」为模型路径加载 SUPER 引擎
（super_router 按后缀路由到 RealEsrganEngine）。

用法：
  python scripts/download_realesrgan.py --dest D:/realesrgan_weights [--models x4plus x2plus]

产出（--dest 下）：
  RealESRGAN_x4plus.pth          RRDBNet x4 23 块（通用真实场景，~64MB）
  RealESRGAN_x2plus.pth          RRDBNet x2 23 块（~64MB）
  RealESRGAN_x4plus_anime_6B.pth RRDBNet x4 6 块（动漫/轻量，~18MB）
  realesr-general-x4v3.pth       SRVGGNetCompact x4（小模型，~5MB）
  manifest-sha256.txt            sha256 清单（供给方校验用）
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

# xinntao/Real-ESRGAN 官方发布直链（BSD-3-Clause）
_URLS = {
    "x4plus": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/"
        "RealESRGAN_x4plus.pth"
    ),
    "x2plus": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/"
        "RealESRGAN_x2plus.pth"
    ),
    "anime_6b": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/"
        "RealESRGAN_x4plus_anime_6B.pth"
    ),
    "general_x4v3": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
        "realesr-general-x4v3.pth"
    ),
}
_DEFAULT_MODELS = ["x4plus"]

# ModelScope 镜像（AI-ModelScope/Real-ESRGAN = ai-forever 再发布版，同款
# RRDBNet 架构、x4plus/x2plus 对应 RealESRGAN_x4/x2.pth）。GitHub releases
# CDN 国内常不可达，此为回退渠道；anime/general 无镜像，仅官方渠道。
_MIRROR_URLS = {
    "x4plus": (
        "https://modelscope.cn/models/AI-ModelScope/Real-ESRGAN/resolve/master/"
        "RealESRGAN_x4.pth"
    ),
    "x2plus": (
        "https://modelscope.cn/models/AI-ModelScope/Real-ESRGAN/resolve/master/"
        "RealESRGAN_x2.pth"
    ),
}
# 引擎按文件名推断架构，落盘统一用官方命名
_DEST_NAMES = {
    "x4plus": "RealESRGAN_x4plus.pth",
    "x2plus": "RealESRGAN_x2plus.pth",
    "anime_6b": "RealESRGAN_x4plus_anime_6B.pth",
    "general_x4v3": "realesr-general-x4v3.pth",
}


def _ssl_context():
    """企业内网/裸装 Python 常缺系统 CA——优先 certifi（pip 自带）CA 包。"""
    try:
        import ssl

        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def _fetch(url: str, dest: Path, retries: int = 2, timeout: int = 60) -> None:
    """带超时的流式下载（urlretrieve 无超时参数，黑洞连接会无限挂起）。"""
    print(f"下载 {url} → {dest}")
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            context = _ssl_context()
            with urllib.request.urlopen(  # noqa: S310  # 官方发布/镜像直链
                url, timeout=timeout, context=context
            ) as resp, open(tmp, "wb") as f:
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001 —— 逐渠道逐次重试后汇总
            last_exc = exc
            tmp.unlink(missing_ok=True)  # 半截文件不留（sha256 会误校验）
            print(f"  第 {attempt}/{retries} 次失败: {exc}", file=sys.stderr)
    raise last_exc  # type: ignore[misc]


def _download(key: str, dest_dir: Path) -> Path:
    """按渠道优先序下载：官方 GitHub release → ModelScope 镜像。"""
    dest = dest_dir / _DEST_NAMES[key]
    errors: list[str] = []
    for url in filter(None, [_URLS.get(key), _MIRROR_URLS.get(key)]):
        try:
            _fetch(url, dest)
            return dest
        except Exception as exc:  # noqa: BLE001 —— 渠道间容错
            errors.append(f"{url.rsplit('/', 2)[-2]}: {exc}")
    raise RuntimeError("全部渠道失败 → " + "; ".join(errors))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-ESRGAN 离线权重供给")
    parser.add_argument("--dest", required=True, help="权重输出目录")
    parser.add_argument(
        "--models", nargs="+", default=_DEFAULT_MODELS, choices=sorted(_URLS),
        help="要下载的权重（默认 x4plus；可选 " + " ".join(sorted(_URLS)) + "）",
    )
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    manifest_lines: list[str] = []
    ok = True
    for key in args.models:
        fname = _DEST_NAMES[key]
        try:
            target = _download(key, dest)
            digest = _sha256(target)
            manifest_lines.append(f"{digest}  {fname}")
            print(f"OK {fname} sha256={digest[:16]}…")
        except Exception as exc:  # noqa: BLE001 —— 供给脚本逐项容错汇总
            ok = False
            print(f"FAILED {fname}: {exc}", file=sys.stderr)

    if manifest_lines:
        (dest / "manifest-sha256.txt").write_text(
            "\n".join(manifest_lines) + "\n", encoding="utf-8"
        )
        print(f"manifest 已写入 {dest / 'manifest-sha256.txt'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
