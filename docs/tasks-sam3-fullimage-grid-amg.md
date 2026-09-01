# SAM3 全图网格盒全覆盖分割 + 诚实降级提示 — 任务列表 (L2 · tasks-lite)

> 版本: 1.0 | 日期: 2026-09-01 | 上游: docs/prd-sam3-fullimage-grid-amg.md v1.0（门禁 2 已过）
> 命名规约: 测试 `test_sam3_fullimage_acNN_<场景>`（AC ↔ 测试双向追溯）

## 任务分解（依赖序）

### T1 · RED：网格盒 detector 契约测试〔AC-001/002/003/004〕
- 文件: `tests/test_sam3_adapter.py`（改 1 旧断言 + 增 TestGridAmgDetector 类）
- 改旧: `test_empty_label_defaults_to_defect` → 空标签走盒通道（本批核心契约翻转，PRD FR-001 锁定）
- 增新: 空 label → `_run_instances` 收到非空 boxes 且形状非空（AC-001）；同掩码多盒 IoU 去重只剩 1（AC-002）；`_grid_boxes` 4000×3000 → 盒数 ≤9、联合覆盖全图、相邻重叠（AC-003）；"scratch" 仍走文本通道（AC-004 既有 `test_text_concept_passthrough_and_shapes` 已覆盖，补 boxes=None 显式断言已在位）
- 验证: `pytest tests/test_sam3_adapter.py -o addopts= -q` → 新用例红（网格分支未实现）

### T2 · 实现：`labeling/sam3_adapter.py` 网格盒 detector〔FR-001〕
- `_grid_boxes(w, h, cols=3, rows=3, overlap=_GRID_OVERLAP)` 纯函数（cell 外扩 overlap 比例，clamp 图界）
- `_mask_iou(a, b)` 纯函数
- `build_amg_detector(label="")`：空 → 网格分支（逐盒 `_run_instances(image, boxes=[[box]])` 循环——PRD 假设①的稳妥回退路径，单盒调用形态与既有调用方一致；score/min_area 过滤沿用 + 面积降序 + 跨盒 `_mask_iou ≥ dedup_iou(默认0.5)` 去重 + max_masks 截断 + Shape 尾段，shape label=`"auto"`）；非空 → 既有文本通道原样
- 验证: T1 用例全绿 + 既有 `TestAmgDetector` 其余用例不回归

### T3 · RED→GREEN：0 形状结果回调 + 接线 + i18n〔FR-002 / AC-005〕
- `labeling/modes/auto.py`: `AutoLabeler.set_result_hook(hook)`——run() 真实执行后以 Shape 数回调（含异常路径 0）；测试入 `tests/test_sam_modes.py`
- `labeling/controller.py`: `attach_detector(..., on_result=None)` 透传接线；测试入 `tests/test_w44_sam_candidates.py`
- `gui/pages/label/sam_session.py` `_sam_attach`: 空 label 直传（去 `or "defect"` 回退）+ count==0 → `status_changed.emit(tr("SAM 全图零分割"), tr("未分出标注：可改用区域/点击模式，或输入概念词"))`
- `gui/pages/label/page.py`: `QLineEdit("defect")` → `QLineEdit("")`（默认全图=网格分支，用户场景默认可达；`_apply_label` 自带 `or "defect"` 兜底不受影响）
- `gui/core/i18n.py`: zh/en 两新键（W55 注记段）
- `labeling/sam_adapter.py`（SAM1）: 空 label 规范为 `"auto"`（防清空输入框后 SAM1 形状空标签）
- 验证: 新用例绿 + `pytest tests/test_w20_i18n_completeness.py -o addopts= -q` 绿

### T4 · 集成验证：主门禁〔AC-006〕
- `.venv/Scripts/python.exe -m pytest` rc=0 且覆盖率 ≥92% 不降
- 守卫面: page.py ≤800 行（净 +1 行）、歧义词 grep 零命中、`test_sam3_auto_concept_flow`（非空标签语义）不回归

## 执行状态

| 任务 | 状态 | 备注 |
|------|------|------|
| T1 | ✅ 2026-09-01 | RED 确认：ImportError(_GRID_OVERLAP) + 6 hook 红 + on_result TypeError；夹具步长 3→5 自纠（相邻 IoU 0.53 会误触去重阈） |
| T2 | ✅ 2026-09-01 | `_grid_boxes`/`_mask_iou`/`_build_grid_detector` 落地；test_sam3_adapter 54 passed（1 skip=opt-in 真权重） |
| T3 | ✅ 2026-09-01 | hook/controller 透传/sam_session 接线/page 默认空标签/i18n 两键/SAM1 "auto" 规范；5 文件 115 passed 含 w20 守卫；页面装配面 50 passed |
| T4 | ✅ 2026-09-01 | 主门禁复跑（ruff 修复后）1267 passed / 5 skipped rc=0，覆盖率 93%（TOTAL 9682 · 694 miss）≥92% 棘轮 |

## 偏差记录

- T2 推理成本: 逐盒循环 9 前向（最坏 ~13s）——PRD 风险①已预案（批量前向属后续优化批）；本批按稳妥回退路径交付。
- 范围内小扩展（PRD §6「接线做薄」语义下）: page.py 标签框默认 "defect"→""（1 行）——否则空标签分支对用户不可达（默认文本恒非空），Goal 1 失效；_apply_label 自带 or "defect" 兜底，其余模式行为不变。
- 范围内小扩展: sam_adapter.py（SAM1）空标签规范化 "auto"（2 行）——防空标签 Shape 落 LabelMe 导出。
