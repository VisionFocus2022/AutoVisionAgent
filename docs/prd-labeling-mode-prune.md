# 标注模式裁剪 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-09-01 | 档位: 🟡 L2 | 确定性: 高（用户点名保留集，映射无歧义）| 影响半径: 大（删除公开枚举成员+注册模块，命中硬触发器②破坏性变更；多文件联动：枚举/工厂/页面/控制器/画布/spec/i18n/测试）| 可逆性: 双向门（git 可回滚）
> **门禁降级**（自治会话）：探索门禁=S1 用户显式指令（"保留多边形、矩形、点标(sam3)和矩形标(sam3)，其他的用不到，可以删除"）；S3 决策留痕见 §5。

## 1. 背景与目标

- **背景**：标注工具栏现有 9 种模式，用户的极柱工作流（SAM3 点击/紧框口径）只用其中 4 种 + 编辑；其余为对标复刻期遗留，删除以收缩维护面。
- **目标**：① 工具栏与注册表只剩保留集；② 删除后全量门禁绿；③ spec/i18n/守卫测试同步，无死引用残留。

## 2. 功能需求 (FR)

- **FR-001**: 模式保留集 = POLYGON(多边形 Q)、RECTANGLE(矩形 R)、INTERACTIVE(交互式 I=点标 SAM3)、REGION_SAM(SAM 区域 J=矩形标 SAM3)、EDIT(编辑 E)；删除 BRUSH(画笔 P)、KEYPOINT(关键点 K)、SAM_BRUSH(SAM 笔刷 B)、AUTO(SAM 全图 G) | P0
- **FR-002**: 四个模式模块文件删除，AnnotationMode 枚举/工厂注册/manual_modes 同步收缩 | P0
- **FR-003**: 页面工具栏、控制器分发、画布渲染、sam_session、io_labelme 读写映射同步 | P0
- **FR-004**: spec hiddenimports、i18n 键、动态导入守卫、各层测试同步删除/收缩 | P0

## 3. 验收标准 (AC)

- **AC-001**: `labeling/modes/` 只含 `_base/polygon/rectangle/interactive/region_sam` 模式模块；`AnnotationMode` 成员=5（含 EDIT）[FR-001/002]
- **AC-002**: label 页工具栏按钮=5（多边形/矩形/交互式/SAM 区域/编辑），快捷键 Q/R/I/J/E 保留 [FR-001/003]
- **AC-003**: 全仓 grep 四个被删模式（`AnnotationMode\.(BRUSH|KEYPOINT|SAM_BRUSH|AUTO)`、`modes\.(brush|keypoint|brush_sam|auto)`、BrushLabeler 等）命中=0（docs/RELEASES 历史档除外）[FR-002/003/004]
- **AC-004**: 主门禁全量绿（rc=0，fail-under 92 不动）[FR-004]
- **AC-005**: W24 规模守卫/动态导入守卫/spec 守卫按新现实更新且绿 [FR-004]
- **AC-006**: i18n 无死键（"SAM 笔刷"/"SAM 全图"/"SAM 全图零分割" 删除；"关键点" 若仅剩 POSE 任务类型用途则保留该语境）[FR-004]

## 4. 范围

- ✅ In Scope: 四模式删除全链路（代码/测试/spec/i18n）；io_labelme 读写映射收缩（旧 "point" 数据走 loader 未知形态路径，诚实不支持）
- ❌ Out of Scope: exe 重打包（发版时统一做，spec 已同步）；io_labelme 对历史 point 数据的迁移转换；EDIT 模式（保留，见 §5 S3-1）；project 页 POSE 任务类型的"关键点"文案（不同功能域）；RELEASES.md 历史记录

## 5. 风险与假设（三栏）

- **已知**: 引用面全清点——生产 8 文件、测试 10+UIA 2、spec 4 行、i18n 3 键；当前主门禁 1222/5/92.87%（2026-09-01 基线）。
- **假设**: ①旧标注数据无 brush/keypoint 依赖（极柱以 polygon 为主）→ 若有，loader 跳过未知形态，损失可接受；②并行会话未触 label 域（git status 仅 data_manage/docs 改动）→ 若冲突，以文件级隔离避免。
- **未知（S3 留痕）**: ①EDIT 保留而非删除——它是多边形顶点编辑（W55 刚建），属保留模式的配套，删除将降级多边形体验（如用户确认删，一行跟进）；②`_base.py` 与 sam3_adapter/sam_adapter 保留——INTERACTIVE/REGION_SAM 的依赖底座。
- **风险**: 删模式波及测试面大（~10 文件）→ 逐文件核对保留用例（INTERACTIVE/REGION_SAM 用例必须存活）；覆盖率分母变化 → 门禁实测把关。

## 6. 实现思路

- 拟采用: 纯删除+收缩，不重构；枚举删成员（非 deprecated 标记）——单人桌面工具无外部 API 消费者，git 即回滚通道。
- 复用: 既有 loader 未知形态跳过路径；W24 守卫自更新惯例（文件跌破棘轮阈值→删条目）。
- 注意: ①modes/__init__.py 的 stub fallback 枚举同步删；②`__all__` 自动生成自 _LABELERS，收缩注册循环即同步；③controller L332 的 AUTO on_result 分支、L314 SAM_BRUSH 集合、sam_session L217 AUTO 分支、canvas L349 KEYPOINT 分支、io_labelme L31/33/40 三映射；④测试里保留 INTERACTIVE/REGION_SAM 全部用例。

---

## 自检（5 项）

- [x] 完整性: FR-001..004 有编号 | [x] 无歧义: 无"快速/友好/高效/灵活/强大" | [x] 可追溯: FR↔AC 全挂 | [x] 范围清晰 | [x] 指标可量化: grep=0 / rc=0 / 按钮数=5

## ✅ 门禁（3 项 · 降级留痕）

- [x] 探索门禁 → S1 用户显式指令；映射表已在对话出示
- [x] PRD 门禁 → S2 无上游文档；本 PRD 即裁决记录，方向锁定用户点名保留集
- [ ] 收尾门禁 → AC-001..006 全过 + 主门禁 rc=0 + 总检（执行后回填）
