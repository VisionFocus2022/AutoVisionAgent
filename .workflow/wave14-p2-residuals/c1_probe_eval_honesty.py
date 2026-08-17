# -*- coding: utf-8 -*-
"""C1 adversarial probe: does the empty state actually RENDER the hint text
via paintEvent (visible state), and is the normal/TN-only path unchanged?"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.getcwd()))

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import gui.pages.eval_.page as ep
from gui.pages.eval_.page import ConfusionMatrixWidget, EvalPage

orig_tr = ep.tr

# ---- Probe 1: spy on tr() during offscreen grab of the EMPTY state ----
page = EvalPage()
seen = []
page._set_results_slot([
    ("IoU (Segmentation)", "0.8500", "n"),
    ("mIoU", "0.8200", "n"),
    ("Dice", "N/A", "n"),
])
assert page._confusion._matrix == [], "empty state driver"
page._confusion.resize(320, 260)

ep.tr = lambda s, *a, **k: (seen.append(s) or s)
try:
    page._confusion.grab()  # forces paintEvent render
finally:
    ep.tr = orig_tr
print("P1 empty-state drawText via tr():", seen)
assert seen == ["无混淆矩阵数据"], f"paintEvent empty branch must draw the hint, got {seen}"

# ---- Probe 2: pixel-level visible difference vs fabricated matrix ----
def img_np(img):
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, img.bytesPerLine())
    return arr[:, : w * 4].reshape(h, w, 4).copy()

w_empty = ConfusionMatrixWidget()
w_empty.resize(320, 260)
w_empty.clear_matrix()
ae = img_np(w_empty.grab().toImage())

w_fake = ConfusionMatrixWidget()
w_fake.resize(320, 260)
w_fake.set_matrix([[1, 0], [0, 1]], ["缺陷", "正常"])  # the old fabricated state
af = img_np(w_fake.grab().toImage())

diff = (ae != af).any(axis=2).sum()
total = ae.shape[0] * ae.shape[1]
print(f"P2 empty-vs-fabricated differing pixels: {diff}/{total} ({100*diff/total:.1f}%)")
assert diff > total * 0.05, "visible rendering must differ substantially from fabricated matrix"

# gray pen #64748b present in empty render (ARGB32 little-endian: B,G,R,A)
gray = ((ae[:, 2] == 0x64) & (ae[:, 1] == 0x75) & (ae[:, 0] == 0x8b)).sum()
print("P2b #64748b pixels in empty render (hint text color):", int(gray))

# ---- Probe 3: normal TP/FP/FN path unchanged, hint NOT drawn ----
page2 = EvalPage()
page2._set_results_slot([
    ("TP", "10", "n"), ("FP", "2", "n"), ("FN", "3", "n"), ("TN", "45", "n"),
])
assert page2._confusion._matrix == [[10, 2], [3, 45]], page2._confusion._matrix
seen2 = []
page2._confusion.resize(320, 260)
ep.tr = lambda s, *a, **k: (seen2.append(s) or s)
try:
    page2._confusion.grab()
finally:
    ep.tr = orig_tr
print("P3 normal-path tr calls during paint:", seen2)
assert "无混淆矩阵数据" not in seen2, "normal path must not draw the empty hint"
assert seen2 == ["→ 预测", "真实 ↑"], f"normal path axis titles, got {seen2}"
an_w = ConfusionMatrixWidget()
an_w.resize(320, 260)
an_w.set_matrix([[10, 2], [3, 45]], ["缺陷", "正常"])
an = img_np(an_w.grab().toImage())
ndiff = (an != ae).any(axis=2).sum()
print(f"P3b normal-vs-empty differing pixels: {ndiff}/{total} ({100*ndiff/total:.1f}%)")
assert ndiff > total * 0.05, "normal path renders the real matrix, visually distinct"

# ---- Probe 4: TN-only case keeps REAL data (not cleared, not fabricated) ----
page3 = EvalPage()
page3._set_results_slot([("TN", "5", "n")])
assert page3._confusion._matrix == [[0, 0], [0, 5]], page3._confusion._matrix
print("P4 TN-only matrix:", page3._confusion._matrix)

# ---- Probe 5: table rows in seg case ----
assert page._table.rowCount() == 3
print("P5 table rows:", page._table.rowCount())

# ---- Probe 6: i18n fallback — missing key returns source string ----
from gui.core.i18n import tr as real_tr
print("P6 tr('无混淆矩阵数据') ->", repr(real_tr("无混淆矩阵数据")))

print("ALL PROBES PASSED")
