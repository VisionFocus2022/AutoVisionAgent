# PRD — SAM 标注顶点细化与编辑模式（ε=0.5 + E 键顶点编辑）

> 档位：🟡L2｜日期：2026-09-01｜分支：feature/sam3-auto-discovery
> 上游：用户需求「1 关键点太粗了，要更细；2 交互式 I 标注后的区域应该由多个关键点组成，这样后面可以对它编辑」

## 1. 背景与目标

交互式 I（及 SAM 区域 J / SAM 笔刷 B / SAM 全图 G，共用同一管线）提交的多边形经
`_mask_to_polygon(ε=2.0)` 折点简化（`cv2.findContours` + Douglas-Peucker），典型仅
10-30 个顶点，边界贴合粗；且画布层无任何顶点级编辑能力——SAM 分割不准时只能删掉重标。

**目标**：
1. 所有 SAM 模式掩码→多边形的折点容差 ε 2.0→**0.5**（顶点密度 3-5 倍，贴合掩码边缘）；
2. 新增**编辑模式**（工具栏按钮 + 快捷键 E）：点击多边形选中并显示顶点手柄，支持
   **拖动顶点 / 双击边插入顶点 / 右键删除顶点**，一次操作=一步 undo，对标 SKolpha
   `ai_edit/key_edit` 模式机。

## 2. 功能需求（FR）

| # | 需求 |
|---|---|
| FR-1 | ε 细化：`SAM_POLY_EPSILON = 0.5` 单源常量落 `labeling/geometry.py`；`sam3_adapter._mask_to_polygon` 与 `sam_adapter` 全部 6 处消费点统一改用该常量（手绘画笔 brush.py 轨迹简化**不动**，非 SAM 掩码管线） |
| FR-2 | `AnnotationMode.EDIT` 新成员 + `_MODES` 表驱动按钮（「编辑 E」）+ E 快捷键自动注册 + i18n zh/en 双键（「编辑」/Edit）+ 键数守卫计数同步 |
| FR-3 | 编辑交互（controller EDIT 分支路由 + canvas 能力下沉 labeling）：点击 POLYGON 选中（顶点手柄+高亮描边）；点击空白取消；shape_list ↔ 画布选中双向联动；拖动顶点（press 快照→拖→release，一步 undo）；双击边在最近投影点插入顶点；右键顶点删除（保底 ≥3 点，不足拒绝）；仅 POLYGON 可编辑（矩形/关键点/画笔形状点击不选中） |
| FR-4 | LabelMe 兼容：编辑后 `save_labelme` 格式不变（POLYGON points 任意顶点数天然兼容，零改动） |
| FR-5 | page.py ≤800 行守卫：剪贴板操作（`_copy_shapes`/`_paste_shapes` ~52 行）抽 `gui/pages/label/clipboard.py` Mixin（W27 SamSessionMixin 行为保持抽取先例） |

## 3. 验收标准（AC）

| # | 标准 | 判定 |
|---|---|---|
| AC-1 | 合成圆弧 mask 下 sam3/sam 双 adapter 顶点数显著多于 ε=2.0 基线（RED 先行）+ `SAM_POLY_EPSILON == 0.5` 常量断言 | pytest |
| AC-2 | canvas 编辑单测：select/move_vertex/insert_vertex/remove_vertex + undo 单步恢复 + `selection_changed`/`shapes_changed` 发射 | pytest |
| AC-3 | controller EDIT 路由单测：点选/拖动/双击加点/右键删点/空白取消/Esc 取消选中/3 点保底拒删/非 POLYGON 不可选 | pytest |
| AC-4 | i18n 键计数守卫同步 +N；page 规模守卫 ≤800 绿 | pytest |
| AC-5 | 主门禁 `.venv/Scripts/python.exe -m pytest` rc=0 且覆盖率 ≥92 不降 | pytest |
| AC-6 | UIA 真窗（python 模式）：E 模式选中→拖动顶点→形状点数变化 E2E ≥1 用例绿；既有 SAM3 UIA 用例零回归 | pytest tests/uia |

## 4. 范围

**In**：`labeling/{base,geometry,canvas,controller,sam3_adapter,sam_adapter,modes/__init__}`、
`gui/pages/label/{page,clipboard(新)}`、`gui/core/i18n`、`tests/`（单测 + UIA）。

**Out**：
- 画笔模式手绘轨迹 ε（非 SAM 掩码管线，行为保持）
- 整体形状拖动平移（用户未选）
- 矩形/关键点形状编辑（仅 POLYGON 参与）
- lite/full exe 重打包（python 模式验证即可；exe 侧使用需重打包+权重复制，收尾时用户裁决是否打包）
- 训练/评测基准数字刷新（ε 变化使 polygon 口径 IoU 轻微变化=预期改进，非回归）

## 5. 风险与假设

- **ε=0.5 顶点密度**：典型 30-80 点/形状，QPolygonF 渲染与手柄密度可接受；若实测过密
  （>150 点）可在收尾时按用户反馈回调常量（单源改动零成本）。
- **page.py 793 行现状**：+~11 行必破 800 线 → FR-5 抽取保余量（触发即抽取=既定动作）。
- **右键语义**：绘制模式右键=commit、EDIT 模式右键=删顶点——模式内互斥无冲突；Esc
  在 EDIT 下=取消选中（controller.cancel 扩展）。
- **make_labeler(EDIT)**：返回 None 合法化（controller 不再 warning），EDIT 模式鼠标事件
  由 controller 编辑分支接管，不经 labeler。
- **undo 粒度**：拖动=press 时快照一步；插入/删除=各自一步。
- **W53/W54 评测留档**：`scripts/exp_sam3_*` 若硬编码 ε=2.0 口径对比，刷新评测非本批
  范围；adapter 顶点变密只影响 polygon 级评测数字（预期略升），mask 级零影响。

## 6. 探索三栏（门禁 1 已过）

**已知**：ε=2.0 管线位置（sam3_adapter.py:53 / sam_adapter.py ×6）；画布无选中/编辑能力；
LabelMe POLYGON 导出兼容任意顶点数；SKolpha 原品有 ai_edit/key_edit 模式机；page.py 793 行。

**假设**：「关键点」=多边形顶点手柄（非新形状类型）；编辑能力对所有 POLYGON 通用（含
手动多边形），用户提 I 是因最近在用 I。

**未知→已裁决**（2026-09-01 AskUserQuestion）：
1. 细化程度 = **ε=0.5 精细档**（所有 SAM 模式统一）
2. 编辑能力 = **拖动 + 双击边加点 + 右键删点**
3. 编辑入口 = **编辑模式按钮 + 快捷键 E**

**反目标**：顶点细到数百个没法编辑；编辑与绘制模式冲突误触发新标注；拖动刷爆 undo 栈；
只改 I 不改 J/B/G 导致同分割顶点密度不一致（→全模式统一已定）。

---

✅ 门禁记录
- [x] 门禁 1（探索）：2026-09-01 三项裁决全按推荐项
- [x] 门禁 2（PRD）：2026-09-01 确认按 PRD 执行（推荐项）
- [x] 门禁 3（收尾）：2026-09-01 确认收尾+提交；exe 重打包延后至下次发版批（用户裁决）

## 门禁 3 裁决补充

- 提交：pathspec 严格隔离（共享工作树，并行 sam3-spec-datas 批在途）
- exe 侧：延后至下次发版批一并重打包+权重复制

## 执行结果（2026-09-01）

- T1 ✅ `SAM_POLY_EPSILON=0.5` 单源（geometry.py），sam3/sam 双 adapter 全调用点切换；校准探针：圆 r=25 掩码 ε=2.0→13 点 / ε=0.5→28 点
- T2 ✅ `hit_vertex`/`nearest_edge_point` 纯函数（geometry.py）
- T3 ✅ canvas 选中态+手柄渲染+`selection_changed` 信号+move/insert/remove_vertex（`dataclasses.replace` 新对象语义——undo 浅快照持旧引用，原位改会使撤销失效）
- T4 ✅ `AnnotationMode.EDIT` + make_labeler(EDIT)→None 合法化 + controller EDIT 事件路由（选中/拖动/双击加点/右键删点/Esc 清选中）
- T5 ✅ page 接线（_MODES 表+双向联动+双击转发）；剪贴板抽 `gui/pages/label/clipboard.py`（page.py 793→769 行）；i18n「编辑」键；test_w20 守卫正则 `[QRPKIJB]`→`[A-Z]`（顺带收编既有 G 键盲区）
- T6 ✅ UIA 真窗编辑 E2E（画三角形→E 选中→拖顶点→保存 JSON 前后对比：A 移动、B/C 逐点一致）；主门禁 1242 passed rc=0 覆盖率 92.85%（双采样；首轮 3 红=serving 瞬态，新鲜单跑 34/34 绿定谳）
- **执行期真缺陷修正**：闭合多边形（手动 Q 模式提交带收尾副本 A'）拖首点只动一份副本 → 首尾分裂。修：move/remove_vertex 首尾副本同步（拖动双写/删除并删）+ hit_vertex 平局取先（严格 `<`）。offscreen 真实事件路径探针 `move v=3` 一击定位（拖的一直是收尾副本 index 3）
- UIA 排障侧记：`draw_polygon_on_canvas` 的画布中心聚焦点击在 Q 模式会**多加一个顶点**（该助手为 SAM 幂等 on_press 设计，PolygonLabeler 每击必加点）——本批测试改自绘三角形规避；助手本身未动（既有用例依赖现状，记档）
