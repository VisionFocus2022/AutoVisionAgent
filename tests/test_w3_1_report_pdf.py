"""W3-1 检测报告 PDF 测试（PRD docs/prd-w3-1-report-pdf.md）。

- AC-1 报告锚点：页数 ≥2 / metadata title 含"检测报告" / 统计值可提取
- AC-2 字体回退非 happy：字体全缺失仍产出（metadata 锚点不变）
- AC-3 中文路径输出成功
- AC-4 空检出（全净）→ 统计 0 且单页不炸
- AC-5 页面：无数据状态提示；worker 完成回发路径
"""
from __future__ import annotations

import pytest

pypdf = pytest.importorskip("pypdf")

pytestmark = [pytest.mark.unit]

from exporter.report_pdf import (  # noqa: E402
    build_detection_report,
)


def _mk_imgs(d, n=3):
    import cv2
    import numpy as np

    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = np.full((96, 96, 3), 120, np.uint8)
        img[20:40, 20:40] = 200
        cv2.imwrite(str(d / f"img{i}.png"), img)


def _results(d, defective=(0, 1)):
    out = []
    for i in range(3):
        out.append({
            "file": f"img{i}.png", "path": str(d / f"img{i}.png"),
            "task": "det", "score": 0.9,
            "boxes": [[20, 20, 40, 40]] if i in defective else [],
            "labels": ["defect"] if i in defective else None,
        })
    return out


class TestAc1ReportAnchors:
    def test_pages_title_and_stats(self, tmp_path):
        imgs = tmp_path / "imgs"
        _mk_imgs(imgs)
        out = tmp_path / "r.pdf"
        build_detection_report(_results(imgs), str(out),
                               {"task": "det", "model": "w.pt"})
        assert out.stat().st_size > 1024
        r = pypdf.PdfReader(str(out))
        assert len(r.pages) >= 2, "应有首页+样本页"
        assert "检测报告" in (r.metadata.title or "")
        txt = r.pages[0].extract_text()
        assert "3" in txt, "总图像数 3 应在首页"
        assert "66.7%" in txt, "缺陷率 66.7% 应在首页"


class TestAc2FontFallback:
    def test_missing_fonts_still_builds(self, tmp_path, monkeypatch):
        import exporter.report_pdf as rp

        monkeypatch.setattr(rp, "_CJK_FONT_CANDIDATES", ())
        imgs = tmp_path / "imgs"
        _mk_imgs(imgs)
        out = tmp_path / "r.pdf"
        build_detection_report(_results(imgs), str(out))
        r = pypdf.PdfReader(str(out))
        assert "检测报告" in (r.metadata.title or ""), "metadata 不受字体影响"


class TestAc3ChinesePath:
    def test_chinese_dir_output(self, tmp_path):
        imgs = tmp_path / "imgs"
        _mk_imgs(imgs)
        out = tmp_path / "报告输出" / "检测汇总.pdf"
        build_detection_report(_results(imgs), str(out))
        assert out.is_file()
        assert "检测报告" in (pypdf.PdfReader(str(out)).metadata.title or "")


class TestAc4AllClean:
    def test_no_detections_single_page(self, tmp_path):
        imgs = tmp_path / "imgs"
        _mk_imgs(imgs)
        out = tmp_path / "r.pdf"
        build_detection_report(_results(imgs, defective=()), str(out))
        r = pypdf.PdfReader(str(out))
        assert len(r.pages) == 1, "全净无样本页"
        txt = r.pages[0].extract_text()
        assert "0.0%" in txt, "缺陷率 0.0% 应在首页"


class TestAc5Page:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_empty_results_warns(self, qapp, monkeypatch):
        from gui.pages.predict import PredictPage

        page = PredictPage()
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append(t))
        page._export_report()
        assert any("无数据" in m for m in msgs)

    def test_report_done_slot_restores(self, qapp, monkeypatch):
        from gui.pages.predict import PredictPage

        page = PredictPage()
        monkeypatch.setattr(
            "gui.pages.predict.page.pick_save_file",
            lambda *a, **k: "x/rep.pdf",
        )
        page._results = [{"file": "a.png", "path": "a.png", "task": "det",
                          "score": 0.5, "boxes": [[1, 1, 2, 2]],
                          "labels": ["defect"]}]
        monkeypatch.setattr(
            "exporter.report_pdf.build_detection_report",
            lambda *a, **k: "x/rep.pdf",
        )
        page._export_report()
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append(t))
        page._report_done_slot("x/rep.pdf")
        assert page.btn_export_report.isEnabled()
        assert any("报告已导出" in m for m in msgs)
