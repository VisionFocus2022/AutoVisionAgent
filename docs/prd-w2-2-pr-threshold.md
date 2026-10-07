# PRD-lite：W2-2 评估增强——PR 曲线 + 阈值调优选荐

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2 ｜ 确定性：高（DetectionResult.scores 逐框分数在位；LossChart 可复用）｜ 影响半径：中（评估页新增分析区+跨页写阈值；纯增量）｜ 规模：中（新模块 ~170 + 页面 ~80 + 测试）｜ 可逆性：双向门
- **上游**: roadmap Wave2 W2-2；**并行批避让**：eval_flow/metrics_supervised 为对方在途文件——新独立模块 evaluation/pr_curve.py 自跑推理收集原始检出，零触碰
- **门禁**: 探索 ✅（用户指令）｜ PRD ✅（S2 预裁决：roadmap DoD）｜ 收尾 ✅（2026-10-07：单测 8 绿（曲线数学精确值/贪心独占采集/页面双线渲染+写入信号/报告落盘/predict 缝）；主门禁 1457 绿+ruff 0；exe 重打包）

## FR

- **FR-1 PR 计算纯模块**（新 `evaluation/pr_curve.py`）：
  `collect_detections(model, gt_dir, iou=0.5, conf=0.01, engine=None)`——
  LabelMe GT 框（矩形×2 + 多边形外接，全类别并为正类）vs 引擎低阈检出，
  贪心 IoU 打 TP/FP 标 + n_gt；
  `pr_curve(dets, n_gt, grid)` → [(threshold, P, R, F1)]；
  `best_f1_point(points)` → {threshold, precision, recall, f1}；
  `save_eval_report(...)` → workspace/eval_reports/eval_<ts>.json。
- **FR-2 评估页分析区**：任务=det 评估完成后「阈值分析」按钮可用 →
  worker 内 collect+curve → PR 图（LossChart 双线 P/R vs 阈值序）+
  推荐标签"推荐阈值 0.xx（F1=.. P=.. R=..）" + 「写入推理阈值」按钮；
  报告 JSON 落盘。非 det 任务按钮禁用（诚实禁用不隐藏）。
- **FR-3 跨页写阈值**：eval 页 `threshold_apply(float)` 信号 → main
  接线 → predict 页 `set_threshold(v)`（seam）+ 状态回显。

## AC

- AC-1 曲线数学：构造检出集（分数/TP 标/n_gt）网格点 P/R/F1 精确值；
  best_f1 取最大点。〔含空检出非 happy-path：不炸、n_gt=0 显式〕
- AC-2 采集：fake 引擎 + tmp LabelMe（矩形+多边形 GT）→ TP/FP 标注与
  贪心独占匹配正确。
- AC-3 页面：分析就绪后图两条序列各 ≥grid 点、推荐标签含阈值；
  非任务态按钮禁用；写入按钮发信号带推荐值。
- AC-4 报告落盘：JSON 含 rows/pr/best/时间，路径在 workspace。
- AC-5 主门禁全绿+ruff 0+行数守卫；predict set_threshold 生效。

## 范围

新：evaluation/pr_curve.py、tests/test_w2_2_pr_curve.py。
改：gui/pages/eval_/page.py、gui/pages/predict/page.py（set_threshold 缝）、
gui/main.py（接线）。i18n 字面量避让（同 W2-1，收口后补键）。
Out of scope：多类分别 PR、AP 面积、seg mask 级 PR（后续波）。

## 实施纪要（2026-10-07）

- 独立采集链设计：run_eval_task 只回聚合行且 eval_flow 为并行批在途
  文件——evaluation/pr_curve.py 自跑推理收集原始检出（conf 0.01 地板
  +贪心 IoU 0.5 独占匹配打 TP/FP），与对方文件零交集。
- 曲线可视化取 P/R-vs-阈值双线（比经典 P-vs-R 更直接服务选阈动作），
  复用 LossChartWidget；推荐点=F1 最大网格点。
- 阈值写入：eval.threshold_apply 信号 → main 接线 predict.set_threshold
  （不切页，状态就地回显）。
- 教训自留：手算期望两次错（网格 TP/FP 计数、偏移框 IoU 0.14<0.5）
  ——曲线类测试期望应先由实现算一遍再人工核对语义，而非心算。
