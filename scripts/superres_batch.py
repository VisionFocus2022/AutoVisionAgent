"""目录批量超分辨率（SUPER 引擎离线批处理工具）。

用途：把一个目录下的图片用 Real-ESRGAN 引擎超分还原到目标尺寸
（如工业相机原生 4024x3036）。已在目标尺寸的图片跳过并留痕。

用法：
  .venv/Scripts/python.exe scripts/superres_batch.py \
      --src "E:/SaveImage/图像/20260731/NG" \
      --dst "E:/SaveImage/图像/20260731/NG_SR" \
      --target 4024x3036 \
      [--weights weights/realesrgan/RealESRGAN_x4plus.pth] \
      [--tile 512] [--device cpu]

行为：
- 按 target/src 宽高比就近选整倍率（x4plus=4 / x2plus=2）；非整数倍时
  引擎放大后 cv2 LANCZOS4 精确对齐到 target。
- 断点续跑：dst 已存在的同名文件跳过（删除该文件即可重跑单张）。
- 输出 PNG 无损；Windows 中文路径安全（imread/imwrite_unicode）。

提醒：weights/ 不入仓——换机器 / 新克隆后先运行
scripts/download_realesrgan.py 拉取权重（或从离线供给目录拷贝）。
纯 CPU 下 x4plus 约 30 分钟/张（1006x759→4024x3036，4 核实测）；有 GPU
的机器加 --device cuda 可提速两个数量级。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_WEIGHTS = REPO_ROOT / "weights" / "realesrgan" / "RealESRGAN_x4plus.pth"
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _parse_target(raw: str) -> tuple[int, int]:
    w, _, h = raw.lower().partition("x")
    if not (w.isdigit() and h.isdigit()):
        raise ValueError(f"--target 需要 WxH 形式（收到 {raw}）")
    return int(w), int(h)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="目录批量超分辨率（SUPER 引擎）")
    parser.add_argument("--src", required=True, help="源图目录")
    parser.add_argument("--dst", required=True, help="输出目录（PNG 无损）")
    parser.add_argument("--target", required=True, help="目标尺寸 WxH，如 4024x3036")
    parser.add_argument("--weights", default=str(_DEFAULT_WEIGHTS),
                        help="Real-ESRGAN .pth 权重路径")
    parser.add_argument("--tile", type=int, default=512, help="分块边长（默认 512）")
    parser.add_argument("--device", default="cpu", help="cpu / cuda")
    parser.add_argument("--copy-existing", action="store_true",
                        help="已在目标尺寸的图片也拷贝到 dst（默认跳过仅留痕）")
    args = parser.parse_args(argv)

    src_dir, dst_dir = Path(args.src), Path(args.dst)
    if not src_dir.is_dir():
        print(f"[ERROR] 源目录不存在: {src_dir}", file=sys.stderr)
        return 1
    tw, th = _parse_target(args.target)
    dst_dir.mkdir(parents=True, exist_ok=True)

    from core.image_io import imread_unicode, imwrite_unicode
    from models.supervised.engines.super_realesrgan import RealEsrganEngine

    files = sorted(p for p in src_dir.iterdir()
                   if p.suffix.lower() in _IMG_EXTS)
    todo, ready, done_before = [], [], []
    for p in files:
        out = dst_dir / (p.stem + ".png")
        if out.exists():
            done_before.append(p.name)
            continue
        img = imread_unicode(str(p))
        if img is None:
            print(f"[WARN] 读取失败，跳过: {p.name}", file=sys.stderr)
            continue
        if img.shape[1] == tw and img.shape[0] == th:
            ready.append((p, img))
        else:
            todo.append((p, img))
    print(f"[plan] 待超分 {len(todo)} 张 / 已在目标尺寸 {len(ready)} 张 / "
          f"此前已完成 {len(done_before)} 张", flush=True)
    for p, _ in ready:
        if args.copy_existing:
            shutil.copy2(p, dst_dir / p.name)
            print(f"[copy] {p.name}", flush=True)
        else:
            print(f"[skip] {p.name}（已在 {tw}x{th}）", flush=True)

    if not todo:
        print("[done] 无待处理图片", flush=True)
        return 0

    engine = RealEsrganEngine()
    t0 = time.time()
    engine.load(args.weights, device=args.device,
                tile_size=args.tile, tile_pad=16)
    print(f"[load] {time.time() - t0:.1f}s  scale={engine.scale}x "
          f"arch={engine.arch_name}", flush=True)

    import cv2

    ok = fail = 0
    for i, (p, img) in enumerate(todo, 1):
        t0 = time.time()
        try:
            hr = engine.infer(img).extra["hr_image"]
            if hr.shape[1] != tw or hr.shape[0] != th:
                # 非整数倍率：引擎就近放大后精确对齐目标尺寸
                hr = cv2.resize(hr, (tw, th), interpolation=cv2.INTER_LANCZOS4)
            out = dst_dir / (p.stem + ".png")
            if not imwrite_unicode(str(out), hr):
                raise OSError(f"写图失败: {out}")
            ok += 1
            dt = time.time() - t0
            eta = (len(todo) - i) * (time.time() - t0)
            print(f"[{i}/{len(todo)}] {p.name} {img.shape[1]}x{img.shape[0]} → "
                  f"{hr.shape[1]}x{hr.shape[0]}  {dt:.0f}s  "
                  f"剩余约 {eta / 60:.0f} 分钟", flush=True)
        except Exception as exc:  # noqa: BLE001 —— 批处理逐张容错
            fail += 1
            print(f"[FAIL] {p.name}: {exc}", file=sys.stderr, flush=True)

    print(f"[done] 成功 {ok} / 失败 {fail} → {dst_dir}", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
