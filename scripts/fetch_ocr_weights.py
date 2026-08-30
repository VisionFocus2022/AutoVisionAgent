"""OCR 离线权重供给脚本（W32 · 离线优先平台必须显式供给）。

easyocr Reader 首用默认联网下载（craft_mlt_25k 检测器 + zh_sim/latin
识别器）。本脚本把权重预取到指定目录并写 sha256 manifest；离线机器
将该目录拷到目标平台后，在推理页以「该目录」为模型路径加载 OCR 引擎
（download_enabled 随之关闭，缺权重诚实报错）。

用法：
  python scripts/fetch_ocr_weights.py --dest D:/ocr_weights [--lang ch_sim en]

产出：
  {dest}/craft_mlt_25k.pth           检测器（~80MB）
  {dest}/{lang}.pth                  各语种识别器（zh_sim ~50MB / latin ~15MB）
  {dest}/manifest-sha256.txt         sha256 清单（供给方校验用）
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

# easyocr 权重直链（JaidedAI 官方发布）
_BASE = "https://github.com/JaidedAI/easyocr/releases/download/pre-v1.1.6/"
_DETECTOR = "craft_mlt_25k.pth"

# 识别器命名与 easyocr Reader 的模型文件名一致
_RECOG = {
    "ch_sim": "zh_sim_g2.pth",
    "en": "latin_g2.pth",
    "ch_tra": "zh_tra_g2.pth",
}


def _download(url: str, dest: Path) -> None:
    print(f"下载 {url} → {dest}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310  # 官方发布直链


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="easyocr 离线权重供给（W32）")
    parser.add_argument("--dest", required=True, help="权重输出目录")
    parser.add_argument(
        "--lang", nargs="+", default=["ch_sim", "en"],
        help="识别器语种（默认 ch_sim en；可选 ch_tra）",
    )
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    files = [(_DETECTOR, _BASE + _DETECTOR)]
    for lang in args.lang:
        name = _RECOG.get(lang)
        if name is None:
            print(f"不支持的语种: {lang}（可选: {'/'.join(_RECOG)}）", file=sys.stderr)
            return 2
        files.append((name, _BASE + name))

    manifest_lines = []
    for name, url in files:
        target = dest / name
        if not target.exists():
            _download(url, target)
        digest = _sha256(target)
        manifest_lines.append(f"{digest}  {name}")
        print(f"  sha256 {digest[:16]}… {name} ({target.stat().st_size} bytes)")

    manifest = dest / "manifest-sha256.txt"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"完成：{len(files)} 个权重 + {manifest}")
    print(f"离线加载：推理页加载模型路径填 {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
