# W43 矩形区域 SAM 分割 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-24 | 档位: 🟡 L2（高确定 × 大影响） | 可逆性: 双向门（增量模式，git 原子回退）
> 前置：docs/skolpha-sam-annotation-forensics.md §5（机制五源取证：矩形=box prompt + 掩码∩矩形硬约束 + ε 折点管线）；探索门禁已裁决（新独立模式 / 硬约束 / 干净基底 0dc63d7）。

## 1. 背景与目标

- **背景**：对标 SKolpha「矩形框定区域→区域内 SAM 分割」（取证报告：rect_edit+ai_edit 双模式、`ai_predict(point, boxs, image)`、`intersect_merge_mask`）。AVA 现有 INTERACTIVE 仅点击分割，大面积相似背景时 mask 易整幅蔓延。
- **目标**：
  1. 新标注模式「SAM 区域」：拖拽定矩形 → 区域内点击 → SAM(point+box) → 掩码∩矩形 → 折点多边形 → 双击/回车提交
  2. 现有 INTERACTIVE 行为零变化（回归证明）
  3. SAM 未加载诚实降级（状态栏指引，同既有语义）

## 2. 功能需求 (FR)

- **FR-001**: `SamAdapter.predict_point_in_box(image, point, box)` — point_coords+point_labels+box 三 prompt 同传（multimask=True 按分择优）；**掩码∩矩形硬约束**（mask 矩形外置零，等价 intersect_merge_mask）→ findContours 最大轮廓 → simplify_polyline(ε=2.0)。 | P0
- **FR-002**: `AnnotationMode.REGION_SAM` 枚举追加（不动既有值）+ `RegionSamLabeler`（样板 InteractiveLabeler）：press 记起点；release 位移≥5px=拖拽 → 设/重设区域（内部存 box）；release 位移<5px=单击 → 区域内且 SAM 就绪 → `predict_point_in_box` 缓存 pending；区域外单击忽略；commit（双击/回车）返回 Shape；reset 清区域与 pending；区域预览由 preview() 附加返回（区域矩形 + pending 多边形二选一：pending 优先）。 | P0
- **FR-003**: `controller.attach_interactive` 扩展认 REGION_SAM（INTERACTIVE 行为不变）。 | P0
- **FR-004**: 标注页接线——模式按钮「SAM 区域」（排在交互式之后）+ `_apply_mode` 的 draw_modes 集合含 REGION_SAM + 进入模式触发 `_ensure_sam` + i18n 词条（拖拽划定区域/区域内点击分割/区域外点击无效/未划定区域 等，zh 即键 + en_US 译文）。 | P0
- **FR-005**: 回归——labeling/sam 现有套件零改动全绿 + 全量回归 + 总检 + commit 门禁。 | P0

## 3. 验收标准 (AC)

- **AC-001**: adapter 单测——stub predictor 返回**跨越矩形边界的 blob mask** → 返回折点全部落在矩形内（硬约束证明）且 predict 收到 point+box 双 prompt [FR-001]
- **AC-002**: labeler 单测——fake adapter 断言：拖拽定区后区域内单击调 `predict_point_in_box(image, point, box=区域)`；区域外单击不调；commit 返回多边形 Shape；reset 清区域 [FR-002]
- **AC-003**: INTERACTIVE 现有测试（test_sam_modes/test_sam_wiring/test_sam_adapter）**零文件改动**全绿 [FR-002/003]
- **AC-004**: page 烟测——模式按钮存在且可切、i18n 词条入字典（守卫绿）[FR-004]
- **AC-005**: 全量回归绿；改动范围=PRD 列明文件集；歧义词 0 [FR-005]

## 4. 范围

- ✅ In: labeling/base.py（枚举）、labeling/sam_adapter.py、labeling/modes/region_sam.py（新）、labeling/modes/__init__.py（映射）、labeling/controller.py（attach 扩展）、gui/pages/label/page.py（按钮/模式/接线）、gui/core/i18n.py、对应测试
- ❌ Out: 不动 INTERACTIVE 交互语义；不做区域持久化/跨图保留；不做笔刷精修（报告 §6 演进项）；不接 AMG 自动标注；不动作门控（标注核心操作三角色可用，对齐 INTERACTIVE 现状）；UIA 用例不新增（SAM 权重离线不可得，降级路径已有单测覆盖）

## 5. 风险与假设

- 已知: predict_box/折点管线已在（仅缺组合调用）；AbstractLabeler 样板明确；并行会话基底已清（0dc63d7）
- 假设: 枚举追加不破坏序列化（LabelMe 输出按 POLYGON 落盘，REGION_SAM 仅交互态）
- 风险: ① page.py 刚被外部会话改过（已提交，工作树净）——若并行会话再动同文件，hunk 纯度甄别后汇报；② preview 双语义（区域框+pending 多边形）实现从简：pending 优先、无 pending 时回矩形预览

## 6. 实现思路

- 逐任务 TDD（adapter → labeler → controller → page）；stub predictor 用确定性合成 mask（圆盘 blob）证明硬约束；fake adapter 记录调用参数证明 prompt 组合

---

## ✅ 门禁

- [x] 门禁 1 探索门禁（2026-08-24 三问裁决：干净基底/新独立模式/硬约束）
- [x] 门禁 2 PRD：确认 → 执行（2026-08-24 用户确认）
- [x] 门禁 3 收尾：AC-001~005 全过 + 全量 1129 绿 + EXP-2026-08-24d/learning 沉淀 + commit 全部批准（2026-08-24）
