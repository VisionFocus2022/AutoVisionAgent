# W44 留档候选清偿 — 任务列表 (L2)

> 关联: prd-w44-sam-candidates.md（门禁 2 已过）；实际执行：A 守卫扩展先红后绿 → C+B 测试文件先行（14 用例 RED）→ 补丁文件化（Write 工具，heredoc 陷阱绕开）→ 一次贯通 → 规模守卫抽取。
> 结果：全量 1139 passed / 4 skipped；SAM 三能力齐整（区域 J / 笔刷 B / 全图自动 W）。

## 任务（实际执行序）
1. A：test_w20 守卫扩 `_MODES` 源码解析 → RED（交互式缺失）→ 补键 GREEN
2. tests/test_w44_sam_candidates.py：AMG×2 + AUTO 接线×2 + predict_points×2 + 笔刷×3（RED）
3. sam_adapter：predict_points（多点+mask_input 迭代）+ build_amg_detector（0.88/64/64 护栏）
4. controller.attach_detector + sam_session._sam_attach 按模式分流（AUTO→AMG）
5. brush_sam.py BrushSamLabeler（笔划采样+跨笔划累积+logits 迭代）+ 枚举/注册/page/_MODES/i18n/spec
6. 规模守卫拦截（page 801>800）→ _SAM_MODES/_DRAW_MODES frozenset 抽取（799）
7. 全量回归 + 沉淀（EXP-2026-08-24e + learn-2026-08-24-w44）

## 偏差
- AMG 截断提示走日志（状态栏需信号管道）；笔刷 v1 仅前景（背景笔划待修饰键管道）；bash heredoc 长脚本失败两次改 Write 文件化（记入 learning）
