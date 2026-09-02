# SKolpha 3.3.2 AC-010 语义核对 — 波3 报告（文档级五源互证）

> 日期: 2026-09-02 | 批次: skolpha-replication AC-010 收口 | 关联: docs/skolpha-forensics-wave1.md / wave2.md / docs/prd-skolpha-replication.md（AC-010/D-4）
> 核对对象: ①cut_line_label 交互语义 ②operation_label 交互语义 ③batchPredict 双模式语义
> 结论速览: **两处推翻、一处证实**（详见 §3）；实机 GUI 走查受 UAC+加密狗双门槛未执行（§5），以产品自带手册+资产+字符串五源互证达成核对意图。

---

## 1. 证据源与取证方法（五源互证）

| # | 证据源 | 位置 | 性质 |
|---|--------|------|------|
| E1 | 官方快捷键说明 `快捷键介绍.txt` | `assets/new_label/`（随包交付） | 一手操作文档（7 模式+通用键） |
| E2 | 落盘模板 `save_json.py` | `assets/new_label/` | labelme 兼容 schema + 自有扩展字段 |
| E3 | exe 字符串簇对齐 | `%TEMP%/skolpha-forensics/{strings,chinese}.txt` | btn objectName ↔ 快捷键串 ↔ 中文 tooltip 按**偏移交错对齐** |
| E4 | 官方 chm 手册（已解包） | 同上 `chm/`（160 页，**GBK 编码**须 gb18030 解码检索） | 4.5.1.3.1-.9 逐模式专页 + 4.4.x 预测页 + FAQ |
| E5 | 版本迭代页 | chm page_89 | 功能时间线（v3.1.7 label+Stools / v3.2.4 加密狗+标注） |

**E3 对齐法**（本波方法论增量）：Nuitka 常量表里 ASCII 符号（strings.txt）与中文串（chinese.txt）按 exe 偏移交错——`create_label_mode` 工厂的按钮簇内 `模式名 → "快捷键<br>" → btn_objectName → 中文 tooltip` 逐项可对齐（例：`bias_ai_label@3d4eb8f → "Ctrl+W<br>"@3d4ebab → btn_bias_line@3d4ebd1 → 斜线标注@3d4ebc4`），把 wave2 的「符号级」证据升级为「语义级」。

## 2. 标注模式全映射（E1×E3×E4 三方一致）

chm 4.5.1.1（page_130）官方口径：**九个标注类型图标**——多边形标注、矩形标注、画笔、关键点标注、AI自动标注、斜线标注、交互式标注、OK标注、裁剪标注。

| shape_type（exe） | btn objectName | 快捷键 | 官方名 | 交互语义（chm 4.5.1.3.x） | AVA 对应物 |
|---|---|---|---|---|---|
| polygon | btn_polygon | Q | 多边形标注 | 逐点；**C 键闭合且 ≥4 点**；Ctrl+Z 撤点 | POLYGON（Q；闭合 ≥3 点） |
| rectangle | btn_rectangle | R | 矩形标注 | 拖拽 | RECTANGLE（R） |
| （落盘疑 polygon） | btn_pen | P | 画笔标注 | 笔刷描画；Ctrl+滚轮调粗细 | —（无） |
| point | btn_point | K | 关键点标注 | 点 | —（W37 裁剪，POSE 任务侧） |
| AI_label | btn_AI_label | W | AI自动标注 | SAM box prompt→掩码∩矩形（wave2 已证） | INTERACTIVE/REGION_SAM 家族 |
| **bias_ai_label** | **btn_bias_line** | **Ctrl+W** | **斜线标注** | **缺陷两边各打一点成穿缺陷斜线→自动标注该缺陷**（page_141） | —（最接近 AVA CUT_LINE 的「线形标注」意图） |
| **operation_label** | **btn_operation_label** | **I** | **交互式标注** | **拖矩形圈缺陷→左键点选缺陷交互分割；右键取消选中；C 完成**（page_142） | ≈INTERACTIVE（AVA 已有） |
| —（形态未确证） | ok_mode | — | OK标注 | 手册占位页无内容（page_156 "Write here..."） | — |
| **cut_line_label** | —（X 键进入） | **X** | **裁剪标注** | **画裁剪线切分既有图形**：矩形过两条对边→切为两个新矩形（过两宽取中点 x 替换交点 x；过两高取中点 y）；多边形边≥2 交点→切为若干新图形（page_159 + 几何 docstring @3d6d335-3d74763 互证） | —（**AVA 无此切分工具=真缺口**） |

E1（快捷键介绍.txt）滞后于 E4：仅列 7 模式（无 X 裁剪/OK 标注），与 E5 时间线一致（裁剪为后续版本新增）。

**E2（save_json.py）落盘语义**：labelme 兼容 `version "1.0.14"`；shape 级自有字段 **`mark`**（两示例均为空串，消费方未确证）；顶层自有字段 `image_path_list`/`channels`。AVA io_labelme 的「labelme 原生形态+mode 键扩展」方向与原品做法同族（原品用 mark 字段承载扩展语义）。

## 3. AC-010 逐项裁决

### 3.1 cut_line_label → **推翻**（推断=开放折线标注形态 ✗）
- wave2/PRD 推断：折线/切割路径**标注形态**（AVA FR-001 据此实现 CUT_LINE 折线+linestrip 落盘）。
- 实际语义（page_159+strings）：**编辑类切分工具**——对既有矩形/多边形画线一分为二/若干，原形删除、新形生成；非独立标注形态。W56 实现与其不等价；语义上最接近的「线形标注」其实是**斜线标注**（bias_ai_label，两点穿缺陷自动标注）。
- 状态机佐证：`create_cut_line_mode@3d21ba9 / start_cut_line@3d26fe5 / cut_line_final@3d26ff5 / OriginalWindow.start_cut_line@3d2aa73` + 状态串 斜线模式@3d61d78 / 切割线模式@3d61d95（两模式并存，非同一物）。

### 3.2 operation_label → **推翻**（推断=操作区域+操作名 ✗）
- wave2/PRD 推断：操作区域矩形+操作名（AVA FR-002 据此实现 OPERATION 矩形+mode 键）。
- 实际语义（page_142）：**交互式 SAM 分割标注**（I 键；拖矩形+点选；右键取消选中；C 完成）——语义上等价 AVA 既有 INTERACTIVE 模式，「operation」仅为代码内部命名。AVA OPERATION 的「区域+标签」语义在原品无直接对应物。

### 3.3 批量预测双模式 → **证实方向 + 语义补全**
- 官方口径（page_17/30/64，四任务页同文）：批量预测=**对导入的全部图片整批推理**；图片列表逐图显示 标注数/识别数/漏检/过杀；结果统计区给汇总（标注总数/预测总数/正确检出占比）。**漏检/过杀=预测结果与数据集 labelme JSON 对照**（FAQ #20；无 JSON 则统计无意义）；批量后可按 是否标注/标注类型/过杀漏检/文件名 筛选样本（FAQ #21）。**自动标注**按钮=把模型检出结果另存 JSON（预标注导出，存 `{projectName}/automaticLabel/yyyyMMdd_hhmmss/`）。
- 符号佐证：`batchPredict@3cfc90d → batchPredictThread@3cf05b0`（后台线程+进度+`end_batch_predict`/`batch_export_res_to_ui` 完成回调整批入表）；`batchPredictOnlyOne@3cf0503`（单图即时路径，`output_label_predict_info`/`addRowResultStatic` 逐行入表）。
- 与 AVA 对照：W56「batch 整批」模式与原品主路径同构 ✅；「incremental 逐张即时滚动+目录重扫」为 **AVA 原生增量设计（原品无对应）**，保留为自有能力；原品有而 AVA 缺的=**逐图/汇总 漏检过杀对照统计**与**预标注 JSON 导出**两个观察项（§4）。

### 3.4 附带范式差异小账（记录不改）
| 交互点 | SKolpha | AVA |
|---|---|---|
| 多边形闭合 | C 键、**≥4 点** | 右键/回车、≥3 点 |
| 边上加点 | 标注线上**左键单击** | EDIT 模式双击 |
| Esc | 进入编辑模式（FAQ #2） | 取消选中 |
| 右键 | 平移图片/取消选中（非提交） | 提交标注 |

## 4. 对 AVA 的修订建议（**已裁决 2026-09-02：用户批准 A+B**）

- **方案 A ✅（批准）**：W56 的 CUT_LINE/OPERATION 作为 AVA 自有能力**保留**（已测、labelme 互操作、工业线形/区域+标签需求真实）；本报告+术语表记录与原品语义差异。
- **方案 B ✅（批准随 A）**：**裁剪标注（X 切分工具）立项为 FR-011**——真缺口，page_159 即完整规格；斜线标注立项 **FR-012** 随其评估。
- **方案 C（否决）**：按原品语义更名/重构现有 CUT_LINE/OPERATION——churn 大、收益低。
- 观察项（已入 PRD §7.3 Future）：①批量预测的漏检/过杀对照统计（评估能力前置到预测页）；②自动标注（预标注 JSON 导出）。

## 5. 实机 GUI 走查状态（未执行——双门槛）

1. **UAC 提权**：`skolpha.exe` manifest 要求管理员（Popen 直启 WinError 740，证据 `.workflow/skolpha-replication/live_observe/run.err`；观察脚本已备 `live_observe_ac010.py` 可改造提权启动）。
2. **加密狗**：chm 版本页 v3.2.4 起「添加了加密狗的功能」——本机是否有狗未验证。

判定：AC-010 的**意图**（核对三处推断语义、防「做出来不是原品的」）已由文档级五源互证达成且结论明确；GUI 级走查留作用户可选加强项（如需：提权启动→标注页核对九图标与 X/I/Ctrl+W 行为；预期与本报告一致）。

## 6. 证据坐标索引

- chm 页：page_130（九类型）/136-140（.3.1-.3.5）/141（斜线）/142（交互式）/156-158（OK 占位）/159（裁剪）/145（图标模块）/17·30·64（批量预测）/86（缺陷生成）/109（FAQ）/89（版本）
- exe 偏移：按钮簇 3d4e9f1-3d4ec41；tooltip 中文 3d4ea39-3d4ecb7；模式状态 3d61c0a-3d61df6；切割几何 3d6d335-3d74763；切割状态机 3d21ba9/3d26fe5/3d26ff5/3d2aa73；预测簇 3cfc90d-3cfd540/3cf0503/3cf05b0
- 资产：`assets/new_label/{快捷键介绍.txt, save_json.py, *.png}`；`configs/parameter_setting_labelme_user_custom.yaml`（明文 recents）
