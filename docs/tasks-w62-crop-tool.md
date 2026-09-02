# 裁剪标注切分工具 W62 — 任务列表 (L2)

> 关联: docs/prd-w62-crop-tool.md | FR-011（docs/prd-skolpha-replication.md §3.1，D-23 裁决 B）| 2026-09-02

## Task 1 几何纯函数（RED→GREEN）
- [x] `tests/test_w62_crop_tool.py` 几何段先写（矩形 7 例+多边形 7 例，中点 x/y 手算锚 4.0/3.0）
- [x] `labeling/crop.py`：`split_rectangle_by_line` / `split_polygon_by_line` / 内部 `_line_seg_intersect`
- 验证: 新测试文件几何段全绿（RED 阶段先证伪）

## Task 2 画布批量替换（单步撤销）
- [x] `AnnotationCanvas.replace_shapes(replacements)`：单 `_save_state` + 逆序切片替换 + `_reset_selection` + 重绘/发信号
- [x] 测试：替换后 undo 一步恢复原对象（`is` 身份断言）、索引保序、空入参无副作用
- 验证: 新测试画布段绿

## Task 3 控制器 CROP 分支
- [x] `_crop_start` 状态 + `on_mouse_press/move` CROP 分支 + `handle_press/handle_move` 便捷路 + `cancel()`/`set_mode` 离场清理
- [x] `_commit_crop`：按形状类型分派几何函数，构造替换字典 → `replace_shapes`；预览复用 CUT_LINE 渲染
- [x] 测试：切矩形成二/一步 undo/CUT_LINE 免切/L 形多边形切分/右键取消
- 验证: 新测试控制器段绿

## Task 4 枚举+页面+i18n 接线
- [x] `base.py` 枚举 +CROP（注释标 X/FR-011）；`modes/__init__.py` make_labeler CROP→None（随 EDIT）
- [x] `page.py` `_MODES` +1 行、`_DRAW_MODES` +CROP；`i18n.py` 字典 +「裁剪/Crop」
- [x] 守卫增量：既有 7 处断言按 8 更新（FB-016）；spec hiddenimports 核对（labeling.crop 若列名制则补）
- 验证: 接线测试绿 + W20 i18n 守卫绿

## Task 5 集成验证与收尾
- [x] 主门禁全量（fail-under=92 不动）+ ruff 0 error + W24 规模守卫绿
- [x] RELEASES/PRD AC 回填、偏差账、记忆、EXP 沉淀；commit 待用户批准
- 验证: AC-1..5 全过
