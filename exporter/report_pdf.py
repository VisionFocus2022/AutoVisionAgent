"""检测报告 PDF 生成（W3-1，roadmap Wave3 体系化起步）。

matplotlib PdfPages 多页：首页参数+统计表（口径对齐 W2-1 模型卡/
R3-11 统计），样本页检出图叠加检测框。CJK 优先 Windows 系统黑体，
缺失回退 DejaVu+英文标签（不产豆腐块）；metadata title 恒为中文
（机读锚点不受字体影响）。纯后端（无 Qt），中文路径直写。

测试侧锚点约定（tests/test_w3_1_report_pdf.py）：
- metadata title 含 "检测报告"；
- extract_text 含统计值（图像数 / 缺陷率百分数，如 "66.7%"）。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import matplotlib

# W3-1 审查修复（2026-10-07）：PDF 只需 Agg——若不钉死，pyplot 在
# PySide6 已加载的进程里会自选 Qt 后端，双 GUI 工具包同进程在套件
# 收尾析构时随机段错误（全量随机序实证一次，确定性/复跑绿=时序型）。
# gui.main 已设 MPLBACKEND=Agg，本模块兜底进程内强制（force 覆盖已有
# 选择），对纯 PDF 渲染零功能影响。
matplotlib.use("Agg", force=True)

logger = logging.getLogger(__name__)

REPORT_TITLE = "AutoVisionAgent 检测报告"
_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
)
_SAMPLES_PER_PAGE = 2


def _register_cjk_font() -> bool:
    """注册 Windows 系统中文字体；成功 True（rcParams 已切），缺 False。"""
    import matplotlib
    from matplotlib import font_manager

    for path in _CJK_FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                font_manager.fontManager.addfont(path)
                name = font_manager.FontProperties(fname=path).get_name()
                matplotlib.rcParams["font.family"] = [name, "DejaVu Sans"]
                matplotlib.rcParams["axes.unicode_minus"] = False
                return True
            except Exception:  # noqa: BLE001  # 字体注册失败回退
                logger.warning("中文字体注册失败: %s", path, exc_info=True)
    logger.warning("未找到系统中文字体，报告标签回退英文")
    return False


def _stats(results: list[dict]) -> dict[str, Any]:
    """统计口径（对齐 R3-11/W2-1）：总数/检出/缺陷图像/缺陷率/类别分布。"""
    total = len(results)
    total_dets = sum(len(r.get("boxes") or []) for r in results)
    defective = sum(1 for r in results if r.get("boxes"))
    dist: dict[str, int] = {}
    for r in results:
        for lbl in (r.get("labels") or []):
            dist[str(lbl)] = dist.get(str(lbl), 0) + 1
    return {
        "total": total, "detections": total_dets, "defective": defective,
        "rate": (defective / total * 100) if total else 0.0, "dist": dist,
    }


def _first_page(pdf, stats: dict, params: dict, cjk: bool) -> None:
    """首页：标题/时间戳/参数/统计表。"""
    import matplotlib.pyplot as plt

    L = (lambda zh, en: zh) if cjk else (lambda zh, en: en)
    fig = plt.figure(figsize=(8.27, 11.69))  # A4 纵向
    fig.suptitle(REPORT_TITLE, fontsize=18, y=0.96)
    rows = [
        (L("生成时间", "Generated"), time.strftime("%Y-%m-%d %H:%M:%S")),
        (L("任务", "Task"), str(params.get("task", "-"))),
        (L("模型", "Model"), os.path.basename(str(params.get("model", "-")))),
        (L("阈值", "Threshold"), str(params.get("threshold", "-"))),
        (L("设备", "Device"), str(params.get("device", "-"))),
        ("", ""),
        (L("总图像数", "Images"), str(stats["total"])),
        (L("总检测数", "Detections"), str(stats["detections"])),
        (L("缺陷图像数", "Defective"), str(stats["defective"])),
        (L("缺陷率", "Defect rate"), f"{stats['rate']:.1f}%"),
    ]
    if stats["dist"]:
        rows.append(("", ""))
        rows.append((L("类别分布", "Class distribution"),
                     "  ".join(f"{k}:{v}" for k, v in
                               sorted(stats["dist"].items()))))
    ax = fig.add_axes([0.05, 0.05, 0.9, 0.85])
    ax.axis("off")
    tbl = ax.table(
        cellText=[[a, b] for a, b in rows],
        colLabels=[L("项目", "Item"), L("数值", "Value")],
        colWidths=[0.35, 0.55], loc="center", cellLoc="left",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 1.6)
    pdf.savefig(fig)
    plt.close(fig)


def _sample_pages(pdf, samples: list[dict], cjk: bool) -> None:
    """样本页：原图+检测框（每页 2 张，标题=文件名(检出数)）。"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    L = (lambda zh, en: zh) if cjk else (lambda zh, en: en)
    for i in range(0, len(samples), _SAMPLES_PER_PAGE):
        batch = samples[i:i + _SAMPLES_PER_PAGE]
        fig, axes = plt.subplots(len(batch), 1,
                                 figsize=(8.27, 11.69 * 0.55 * len(batch)))
        if len(batch) == 1:
            axes = [axes]
        for ax, s in zip(axes, batch, strict=True):
            ax.imshow(s["image"])
            for box in s.get("boxes") or []:
                x1, y1, x2, y2 = box
                ax.add_patch(Rectangle(
                    (x1, y1), x2 - x1, y2 - y1,
                    fill=False, edgecolor="#ef4444", linewidth=1.5))
            n = len(s.get("boxes") or [])
            ax.set_title(f"{s['name']}  ({L('检出', 'det')}: {n})",
                         fontsize=10)
            ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)


def build_detection_report(
    results: list[dict],
    out_path: str,
    params: dict | None = None,
    sample_limit: int = 6,
) -> str:
    """生成检测报告 PDF（W3-1 FR-1）。

    Args:
        results: 批量推理记录（file/path/task/score/boxes/labels——
            result_to_record 契约）。
        out_path: 输出 pdf 路径（中文路径直写）。
        params: 报告参数（task/model/threshold/device）。
        sample_limit: 样本页上限（有检出记录的前 N 张）。

    Returns:
        out_path（成功即返回；渲染异常向上抛由调用方显式处理）。
    """
    params = params or {}
    cjk = _register_cjk_font()
    stats = _stats(results)
    samples = _load_samples(results, sample_limit)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(out_path, metadata={
        "Title": REPORT_TITLE,
        "Creator": "AutoVisionAgent",
    }) as pdf:
        _first_page(pdf, stats, params, cjk)
        if samples:
            _sample_pages(pdf, samples, cjk)
    logger.info("检测报告已生成: %s（样本 %d 张）", out_path, len(samples))
    return out_path


def _load_samples(results: list[dict], limit: int) -> list[dict]:
    """有检出记录 → 原图+框样本（读图失败跳过，不挡报告）。"""
    from core.image_io import imread_unicode

    samples = []
    for r in results:
        if len(samples) >= limit:
            break
        boxes = r.get("boxes") or []
        if not boxes:
            continue
        img = imread_unicode(str(r.get("path") or ""))
        if img is None:
            continue
        samples.append({"name": str(r.get("file", "")), "image": img,
                        "boxes": [list(b) for b in boxes]})
    return samples


__all__ = ["REPORT_TITLE", "build_detection_report"]
