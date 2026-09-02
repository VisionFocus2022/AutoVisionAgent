# 标注模式裁剪 — 任务列表 (L2)

> 关联: [prd-labeling-mode-prune.md](prd-labeling-mode-prune.md) v1.0 | 2026-09-01 | 分支 feature/sam3-auto-discovery
> 串行执行（同域文件强耦合）；每任务跑自己的验证；末任务全量门禁。

### Task 1: 枚举与工厂收缩
- **步骤**: ①`labeling/base.py`：AnnotationMode 删 BRUSH/KEYPOINT/AUTO/SAM_BRUSH；manual_modes()→(POLYGON, RECTANGLE) ②`labeling/modes/__init__.py`：import 循环删 4 行、_MODE_LABELLER_MAP 删 4 映射、_MANUAL_FACTORIES 条件删 BRUSH/KEYPOINT、stub 枚举同步、docstring 更新 ③删 `labeling/modes/{brush,keypoint,brush_sam,auto}.py`
- **涉及文件**: labeling/base.py、labeling/modes/__init__.py、4 个删除文件
- **验证**: `python -m py_compile` 存活文件 0 错；`python -c "from labeling.base import AnnotationMode; print(len(list(AnnotationMode)))"` → 5

### Task 2: 页面/控制器/画布/会话/IO 同步
- **步骤**: ①`gui/pages/label/page.py`：_MODES 删 4 行；L63 SAM 集合删 SAM_BRUSH/AUTO；L67 手动集合删 BRUSH/KEYPOINT；相关注释 ②`labeling/controller.py`：L314 集合删 SAM_BRUSH；L332 AUTO on_result 分支删 ③`labeling/canvas.py` L349 KEYPOINT 渲染分支删 ④`gui/pages/label/sam_session.py` L217 AUTO 分支删 ⑤`labeling/io_labelme.py` L31/33/40 三映射删（loader 未知形态路径兜底）
- **涉及文件**: 上述 5 文件
- **验证**: py_compile 全绿；grep 生产目录命中=0

### Task 3: spec/i18n/守卫同步
- **步骤**: ①spec 删 4 行 hiddenimports（auto/brush/keypoint/brush_sam）②i18n 删 "SAM 笔刷"/"SAM 全图"/"SAM 全图零分割" 三键（"关键点"若剩 POSE 语境保留）③test_dynamic_import_guard.py 对齐 ④test_w24_scale_guards.py：label/page.py 行数若跌破 800 按棘轮失效断言删条目
- **验证**: spec 守卫测试绿（test_w26_spec_packaging.py + dynamic_import_guard）

### Task 4: 测试面收缩（~12 文件）
- **步骤**: 逐文件处理——删 BRUSH/KEYPOINT/SAM_BRUSH/AUTO 用例与 fixture，**保 INTERACTIVE/REGION_SAM/POLYGON/RECTANGLE/EDIT 全部用例**；test_sam_auto_entry.py 以 AUTO 为主则整文件删；UIA（test_sam3_labeling.py + uia_helpers.py）同步
- **涉及文件**: tests/test_labeling.py、test_gui.py、test_gui_label_page.py、test_labeling_controller_deep.py、test_sam_modes.py、test_sam_auto_entry.py、test_sam_wiring.py、test_w44_sam_candidates.py、test_sam3_adapter.py、test_dynamic_import_guard.py、tests/uia/ 2 文件
- **验证**: 保留用例子集跑绿

### Task 5: 末位集成验证（强制）
- **步骤**: ①全仓 grep AC-003 三族模式名=0（docs 历史档除外）②主门禁全量 rc=0（fail-under 92）③AC-001..006 逐条核对 ④总检 11 项 ⑤进度回填本文档
- **验证**: AC 全过；门禁 rc=0
- **UIA 回归**: N/A（spec 改动后需重打包才有意义，UIA 断言已同步；重打包归发版流程）

## 执行约定
- L2 修复尝试上限 3；每 3 任务汇报；commit 待用户批准。

---

## 执行进度回填（2026-09-01 · 五任务全部完成）

| 任务 | 结果 | 验证 |
|------|------|------|
| T1 枚举+工厂 | ✅ | enum=5（POLYGON/RECTANGLE/INTERACTIVE/REGION_SAM/EDIT）；factories=4；manual=2；4 模块文件 git rm |
| T2 页面/控制器/画布/会话/IO | ✅ | 生产域 grep=0；py_compile 全绿；labelme 读写映射收缩（point 旧数据走未知形态路径） |
| T3 spec/i18n/守卫 | ✅ | spec 4 行删除；i18n 3 键删除（"关键点"保留——POSE 任务类型仍消费）；dynamic_import+spec 守卫 15 passed |
| T4 测试面 | ✅ | 批量 184 passed / 1 skipped；test_sam_auto_entry.py 删除（快捷键唯一守卫移入 test_gui_label_page.py） |
| T5 终验 | ✅ | 全仓 grep 仅剩历史性 docstring；主门禁 **1238 passed / 5 skipped / RC=0 / 覆盖率≥92 保持**（92.9x%，分母 9369→9472） |

**AC 核销**：AC-001 ✓（modes 目录 5 文件+枚举 5）/ AC-002 ✓（工具栏 Q/R/I/J/E 五按钮、SAM 集 2、绘制集 5）/ AC-003 ✓ / AC-004 ✓ / AC-005 ✓（守卫在主门禁内全绿）/ AC-006 ✓。

**偏差与 S3 决策**：
1. **EDIT 保留**（用户清单未提）——多边形顶点编辑（W55 新建）属保留模式配套，删除将降级多边形体验；如需删一行跟进。
2. **适配器 API 保留**——sam3/sam_adapter 的 build_amg_detector/predict_points 为库级能力（零 UI 入口、独立测试），供批量流程复用；连带保留 TestBuildAmgDetector/TestPredictPoints。
3. **controller if 分支覆盖重写**——原 AUTO 队列测试改用 _ScriptedLabeler 等价钉住（test_handle_commit_if_branch_one_shape_per_call）。
4. sed 删行两处偏差当场修复（test_polygon_preview 丢装饰器、round_trip back[2] 越界索引）——批测与全量门禁双验证无残留。
5. UIA 断言同步：三模式流改两模式流（≥2 polygons），AUTO 概念分割用例删除；真窗复跑待下次重打包后（spec 已同步，发版流程统一）。

**改动清单**：生产 8 文件（labeling/base.py、modes/__init__.py、io_labelme.py、controller.py、canvas.py、gui/pages/label/page.py、sam_session.py、spec、i18n.py）+ 删除 5 文件（4 模式模块 + test_sam_auto_entry.py）+ 测试 8 文件编辑 + 本 PRD/tasks 两文档。**未 commit，待批准**（注：工作树混有并行会话的 data_manage/docs 改动，提交须按文件挑选）。
