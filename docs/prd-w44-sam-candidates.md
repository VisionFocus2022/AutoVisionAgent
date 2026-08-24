# W44 留档候选清偿波（A i18n 变量键盲区 + B SAM 笔刷精修 + C SAM AMG 自动标注） — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-24 | 档位: 🟡 L2（高确定 × 中大影响） | 可逆性: 双向门（增量为主，git 原子回退）
> 前置：取证报告 §6（labelme Canvas start_sam/paint_to_shape/erase_points 笔刷精修 + SamSunPredictor AMG/thresh_iou 参数簇）；探索门禁已裁决（A+B+C / AMG 0.88+护栏）。

## 1. 背景与目标

- **A**：模式标签经 `tr(label_key)` 变量传入，字面量守卫永不覆盖——「交互式」键缺失（en_US 露中文）长期未被发现。
- **B**：对标 SKolpha 笔刷精修（取证：paint_to_shape——笔划采样为点提示 + SAM 迭代精修），AVA 缺拖划式细化能力。
- **C**：对标 SKolpha 预测页自动标注（取证：SamAutomaticMaskGenerator 参数簇 + thresh_iou 过滤），AVA AUTO 模式 detector 空置。

## 2. 功能需求 (FR)

**A 组（i18n 收口）**
- **FR-A1**: 补「交互式」词条；守卫新增 `_MODES` 表静态解析——test_w20 增加函数解析 page.py `_MODES` 字面量表提取 label_key，断言全部 ∈ `_EN_US`（静态可枚举，非白名单维护）。 | P0

**C 组（AMG 自动标注）**
- **FR-C1**: `SamAdapter.build_amg_detector(iou_thresh=0.88, min_area=64, max_masks=64)` → `(image) → List[Shape]`——官方 `SamAutomaticMaskGenerator(predictor.model, pred_iou_thresh, min_mask_region_area)`，掩码→轮廓→ε 折点（复用既有管线），按面积降序、**超 max_masks 截断 + logger.warning**（状态栏提示需信号管道，记偏差以日志留痕）。 | P0
- **FR-C2**: AUTO 模式接线——进入 AUTO 触发 `_ensure_sam`；`_sam_attach` 完成后若 mode=AUTO 则经 controller 注入 AMG detector（AutoLabeler.set_detector）；controller 注入通道扩展（attach_interactive 泛化或新 attach_auto）。 | P0

**B 组（SAM 笔刷精修）**
- **FR-B1**: `SamAdapter.predict_points(image, points, labels, box=None, mask_input=None) -> (poly, logits)`——多点提示 + 迭代 mask_input 通道（官方 logits 回传语义）。 | P0
- **FR-B2**: `AnnotationMode.SAM_BRUSH` + `BrushSamLabeler`——拖划采样点（点距≥4px 稀疏化）累积前景提示，每笔 release → predict_points(全部累积点 + 上轮 logits) → 刷新 pending 多边形；commit 双击/回车；reset 清累积与 logits。v1 仅前景笔划（背景笔划需修饰键管道，记偏差后续）。 | P0
- **FR-B3**: 页面接线（模式按钮「SAM 笔刷」快捷键 B、draw_modes、_ensure_sam）+ spec hiddenimports 注册 + i18n 词条。 | P0

**回归**
- **FR-R1**: 全量回归 + INTERACTIVE/REGION_SAM 既有测试零改动绿 + 沉淀。 | P0

## 3. 验收标准 (AC)

- **AC-A1**: 守卫解析 `_MODES` 全部 label_key ∈ 字典（先红：「交互式」缺失 → 补键后绿）；en_US 切换模式按钮无中文残留（字典断言） [FR-A1]
- **AC-C1**: AMG detector 单测——stub generator 返回多掩码（含小面积/低分）→ 按面积排序、min_area 过滤、max_masks 截断、Shape POLYGON 化 [FR-C1]
- **AC-C2**: AUTO 模式注入测试——controller AUTO + attach → labeler.detector 非 None [FR-C2]
- **AC-B1**: predict_points 单测——stub 断言多点+mask_input 透传、logits 回传 [FR-B1]
- **AC-B2**: BrushSamLabeler 单测——两笔累积点数递增、第二笔携第一笔 logits、commit 多边形、reset 清态 [FR-B2]
- **AC-B3**: 页面三模式接线烟测 + 五方守卫绿 [FR-B3]
- **AC-R1**: 全量回归绿；歧义词 0 [FR-R1]

## 4. 范围

- ✅ In: test_w20_i18n_completeness.py（守卫扩）、gui/core/i18n.py、labeling/sam_adapter.py、labeling/base.py、labeling/modes/brush_sam.py（新）、labeling/modes/__init__.py、labeling/controller.py、gui/pages/label/page.py、gui/pages/label/sam_session.py（AUTO 注入）、autovisionagent.spec、tests/test_w44_sam_candidates.py（新）
- ❌ Out: 背景笔划（修饰键管道）；AMG 阈值 UI；掩码层画布渲染（多边形预览够用）；笔刷/橡皮双模式（v1 前景单模式）；D 组 v6 遗留 P3 五项

## 5. 风险与假设

- 已知: 官方 AMG 构造签名/predict logits 语义公开；AutoLabeler detector 契约（run/队列）明确
- 假设: predictor.model 即 sam 对象（官方 SamPredictor 持有 .model）；掩码数上限截断以日志留痕可接受
- 风险: ① 大图 AMG 真实耗时（单测全 stub；真机验证留 UIA/手动——记局限）；② `_MODES` 解析正则脆弱（表为字面量元组列，格式稳定）；③ 波长较长——按 A→C→B 序，每 3 任务汇报

## ✅ 门禁

- [x] 门禁 1 探索门禁（2026-08-24：A+B+C 全做 / AMG 0.88+护栏）
- [x] 门禁 2 PRD：确认 → 执行（2026-08-24 用户确认）
- [x] 门禁 3 收尾：AC 全过 + 全量 1139 绿 + EXP-2026-08-24e/learning 沉淀 + commit 全部批准（2026-08-24）
