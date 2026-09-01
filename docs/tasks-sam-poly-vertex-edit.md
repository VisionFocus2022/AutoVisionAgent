# Tasks — SAM 标注顶点细化与编辑模式

> 档位：🟡L2｜日期：2026-09-01｜上游：docs/prd-sam-poly-vertex-edit.md（门禁 2 已过）

| # | 任务 | 依赖 | 验证 | 状态 |
|---|------|------|------|------|
| T1 | ε 单源常量：`labeling/geometry.py` 增 `SAM_POLY_EPSILON=0.5`；sam3_adapter `_mask_to_polygon` 与 sam_adapter 全部调用点（含降级桩）切换消费 | — | RED 先行：常量断言 + 合成圆弧 mask 顶点数门（pytest test_labeling + test_sam3_adapter） | ✅ |
| T2 | geometry 命中检测纯函数：`hit_vertex(points, pt, radius)`、`nearest_edge_point(points, pt)→(插入位, 投影点)` | — | 纯函数单测（含边界：无命中/共线/首尾边） | ✅ |
| T3 | canvas 编辑能力：选中态（`selection_changed` 信号 + 手柄渲染 + 高亮描边）、`select_shape/clear_selection`、`begin_vertex_edit`（undo 快照）、`move_vertex/insert_vertex/remove_vertex`（Shape replace 语义，删点保底 ≥3；闭合首尾副本同步） | T2 | qapp 单测：编辑操作 + undo 单步恢复 + 信号发射 | ✅ |
| T4 | controller EDIT 路由：`AnnotationMode.EDIT` 枚举、`make_labeler(EDIT)→None` 合法化（不 warning）、press（命中顶点→拖动 / 命中形状→选中 / 空白→取消）、move（拖动中）、release、双击边加点（`on_mouse_double_click` 新通道 + `handle_double_click` 便捷 API）、右键顶点删点、cancel 扩展清选中 | T3 | 便捷 API 单测全路径（含非 POLYGON 不可选） | ✅ |
| T5 | page 接线 + 守卫：`_MODES` 加 (EDIT,"编辑","E")、`_DRAW_MODES` 加 EDIT、shape_list↔画布选中双向联动；剪贴板抽 `gui/pages/label/clipboard.py` Mixin 保 page ≤800；i18n `"编辑": "Edit"`；test_w20 守卫 `_mode_label_keys` 正则补 E/G | T4 | 规模守卫绿 + i18n 守卫绿 + 页面测试（test_gui_label_page 增 EDIT 断言） | ✅ |
| T6 | UIA 真窗 E2E + 全量回归：python 模式编辑链路用例（画多边形→E 选中→拖顶点→保存 JSON 断言 points 变化）；主门禁 rc=0 覆盖率 ≥92 | T5 | UIA 用例绿 + `check-gate.sh` 聚合门禁 | ✅ |

**执行注记**：
- 每任务 TDD（RED→GREEN）；修复尝试上限 3 次（L2）
- T6 UIA 需桌面空闲；exe 重打包不在本批（收尾裁决）
- commit：批次全绿后 pathspec 提交（`feat: W55 顶点细化与编辑模式`，波次号收尾定）
