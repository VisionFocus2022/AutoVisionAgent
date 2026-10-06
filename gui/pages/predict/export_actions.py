"""推理页导出/统计动作（W24 规模拆分，2026-10-05 自 page.py 抽出）。

PredictPage 规模守卫（≤800 行）超限，导出三方法（CSV/Excel/JSON）与
统计报表按 VideoSuperActionsMixin 同模式抽出为 Mixin——invoke_main
槽名派发经 MRO 命中，行为不变（零逻辑变更，纯物理拆分）。

宿主契约：宿主需提供 self._results / self.status_changed / tr /
sanitize_csv_cell（经 workers）。pick_save_file 经宿主模块属性解析
（gui.pages.predict.page.pick_save_file）——与 page.py 原测试缝保持
兼容（既有 monkeypatch pred_mod.pick_save_file 仍然生效）。
"""
from __future__ import annotations

import csv
import json
import logging
import os

from gui.core.i18n import tr

# W24 拆分缝：logger 沿用 page 模块（既有测试 caplog 监听
# gui.pages.predict.page；日志归属页面而非 Mixin 文件）
from gui.pages.predict import page as _page_mod  # noqa: F401  测试缝：pick_save_file 经此解析

logger = logging.getLogger("gui.pages.predict.page")


def _pick_save_file(widget, title, filt):
    """经宿主模块（page）解析 pick_save_file——保留测试 monkeypatch 缝。"""
    return _page_mod.pick_save_file(widget, title, filt)


class ExportActionsMixin:
    """推理结果导出（CSV/Excel/JSON）与统计报表（R3-11）。"""

    def _export_csv(self) -> None:
        """导出 CSV。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = _pick_save_file(
            self, "导出CSV", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "task", "score", "labels"])
            for r in self._results:
                writer.writerow([
                    self._sanitize(r["file"]),
                    self._sanitize(r["task"]),
                    r.get("score", ""),
                    self._sanitize(", ".join(r.get("labels", []) or [])),
                ])
        logger.info("导出CSV: %s", path)
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    def _show_stats(self) -> None:
        """弹出统计报表对话框（R3-11）：总检测数/缺陷数/缺陷率/类别分布。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可统计"), "!")
            return
        total_imgs = len(self._results)
        total_dets = sum(
            len(r.get("boxes") or []) for r in self._results
        )
        defective = sum(
            1 for r in self._results if r.get("boxes")
        )
        defect_rate = (defective / total_imgs * 100) if total_imgs else 0.0

        # 类别分布
        from collections import Counter
        label_counter: Counter = Counter()
        for r in self._results:
            labels = r.get("labels") or []
            for lbl in labels:
                label_counter[str(lbl)] += 1

        # 构建摘要文本
        lines = [
            f"{tr('总图像数')}: {total_imgs}",
            f"{tr('总检测数')}: {total_dets}",
            f"{tr('缺陷图像数')}: {defective}",
            f"{tr('缺陷率')}: {defect_rate:.1f}%",
        ]
        if label_counter:
            lines.append("")
            lines.append(tr("类别分布") + ":")
            for lbl, cnt in label_counter.most_common():
                lines.append(f"  {lbl}: {cnt}")

        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(tr("统计报表"))
        msg.setText("\n".join(lines))
        msg.exec()

        self.status_changed.emit(
            tr("统计"), f"{defective}/{total_imgs} ({defect_rate:.1f}%)"
        )

    def _export_excel(self) -> None:
        """导出 Excel (.xlsx)（R3-11）。openpyxl 不可用时回退到 CSV。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = _pick_save_file(
            self, "导出Excel", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            # 回退到 CSV
            self.status_changed.emit(tr("openpyxl未安装，导出CSV"), "!")
            csv_path = path.rsplit(".", 1)[0] + ".csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["file", "task", "score", "labels"])
                for r in self._results:
                    writer.writerow([
                        self._sanitize(r["file"]),
                        self._sanitize(r["task"]),
                        r.get("score", ""),
                        self._sanitize(", ".join(r.get("labels", []) or [])),
                    ])
            self.status_changed.emit(tr("已导出CSV"), os.path.basename(csv_path))
            logger.info("导出Excel回退CSV: %s", csv_path)
            return

        wb = Workbook()
        ws = wb.active
        ws.title = tr("推理结果")
        # 表头
        headers = [tr("文件"), tr("任务"), tr("分数"), tr("标签"), tr("检测框数")]
        ws.append(headers)
        # 数据行
        for r in self._results:
            ws.append([
                self._sanitize(r["file"]),
                self._sanitize(r.get("task", "")),
                round(r.get("score", 0) or 0, 4),
                self._sanitize(", ".join(r.get("labels", []) or [])),
                len(r.get("boxes") or []),
            ])

        # 统计摘要表
        ws2 = wb.create_sheet(tr("统计"))
        total_imgs = len(self._results)
        total_dets = sum(len(r.get("boxes") or []) for r in self._results)
        defective = sum(1 for r in self._results if r.get("boxes"))
        defect_rate = (defective / total_imgs * 100) if total_imgs else 0.0
        ws2.append([tr("指标"), tr("数值")])
        ws2.append([tr("总图像数"), total_imgs])
        ws2.append([tr("总检测数"), total_dets])
        ws2.append([tr("缺陷图像数"), defective])
        ws2.append([tr("缺陷率"), f"{defect_rate:.1f}%"])

        wb.save(path)
        logger.info("导出Excel: %s", path)
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    def _export_json(self) -> None:
        """导出 JSON。"""
        if not self._results:
            self.status_changed.emit(tr("无数据可导出"), "!")
            return
        path = _pick_save_file(
            self, "导出JSON", "JSON (*.json)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._results, f, ensure_ascii=False, indent=2)
        logger.info("导出JSON: %s", path)
        self.status_changed.emit(tr("已导出"), os.path.basename(path))

    @staticmethod
    def _sanitize(cell) -> str:
        """CSV 注入防护（转发 core 约定实现，避免宿主依赖面变化）。"""
        from gui.pages.predict.workers import sanitize_csv_cell

        return sanitize_csv_cell(cell)


__all__ = ["ExportActionsMixin"]
