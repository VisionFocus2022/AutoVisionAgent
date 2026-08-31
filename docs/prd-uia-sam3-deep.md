# PRD：SAM3 标注 UIA 深度测试（精简版）

## 0. 定档声明

- 档位：🟡 L2（低确定 × 小影响）
- 确定性：中 — 基建/规约可复用；深度交互时序执行期验证
- 影响半径：小 — 纯新增测试；例外路径 FR-5 可能触 spec 补丁（构建配置，非生产逻辑）
- 探索门禁：✅ 已过（2026-08-31，用户裁决：全 4 维度 / 最低集断言 / exe 模式）

## 1. 背景与目标

现有 `tests/uia/test_sam3_labeling.py` 3 用例覆盖四模式基本流 + 诚实失败，但断言
停留在"shape 存在 + 类型 + label"，交互状态机（多对象/撤销/换图/模式往返）零覆盖。
本 PRD 新增深度用例，度量「标注效果」质量并验证 SAM3 会话状态机端到端。

运行模式：**exe**（探测实证 `dist/AutoVisionAgent/_internal/transformers/models/sam3`
全套在场 + tokenizers/safetensors；lite 亦含 transformers，1.980 GiB 门禁不受影响）。

## 2. 功能需求（FR）

| FR | 需求 | 验证（AC） |
|----|------|-----------|
| FR-1 | 几何质量断言（最低集）：所有 SAM 产物 shape 断言 ①points ≥ 3 ②shapely Polygon 面积 > 0 ③所有点在 [0, imageWidth]×[0, imageHeight] 内 | 新用例产出的每个 shape 三条全过；JSON 的 imageWidth/Height 为准 |
| FR-2 | 多对象会话：同图 3 次（点击→右键提交）→ 3 个独立 polygon；连续两击不提交 → 仅 1 shape（INTERACTIVE pending 替换语义） | shape 计数 = 3；替换验证计数 = 1 |
| FR-3 | 撤销/重做/删除：提交 shape 后撤销→计数减 1；重做→恢复；删除路径（清空按钮→确认框→计数归零） | 状态栏计数逐级断言 |
| FR-4 | 换图重预热 + 模式往返：下一张→等"交互式标注就绪"（重预热）→新图交互产 shape（缓存失效验证）；SAM→多边形→SAM 往返后再次就绪且交互产 shape（adapter 复用快路径） | 新图 shape 计数增长；往返后就绪等待远短于冷加载 |
| FR-5 | exe 模式冒烟前置：首任务跑现有 `test_sam3_labeling.py::test_sam3_invalid_weights_honest_failure`（exe 模式）；若因 "SAM3 模块不可用" 失败 → spec hiddenimports 补 `labeling.sam3_adapter` + 重打包 + 复跑 | 冒烟绿，或补丁后绿 |

## 3. 范围

**In**：新建 `tests/uia/test_sam3_labeling_deep.py`；复用 conftest 夹具
（ava_app/pole_subset_dir/workspace_dir/sam3_weights_env）+ uia_helpers 原语
+ 本地原语（_canvas_click/_canvas_commit 从既有文件复制，同一套）。

**Out**：不改生产代码；不动既有 3 用例；adapter 契约（代偿盒/裁剪/背景空）
单测已盖（test_sam3_adapter.py）不重复；exe 重打包仅 FR-5 触发时执行。

## 4. 风险与假设

- `labeling.sam3_adapter` 函数级导入 → PyInstaller 静态分析不可见，spec
  hiddenimports 未列 → PYZ 可达性未知（FR-5 冒烟定夺；缺失则补丁+重打包 ~10min）
- SAM3 冷加载 10-25s / 单次交互 1.5-6s（1600² 极柱图）→ 用例级 timeout 沿用
  T_LOAD=120/T_INFER=12 规约；UIA 输入争抢沿用 SetActive 预聚焦 + 双发点击
- 权重缺失（weights/sam3）或极柱数据集缺失 → 夹具 skip（fail-honest）
- flaky 路由规约：控件找不到类失败消息含 "timeout"；断言类为 deterministic

## 5. 三栏账（探索产物并入）

【已知】exe 已带 sam3 栈（目录实证）；工具栏按钮全集与模式按钮全集（源码实读）；
adapter 契约单测已盖。
【假设】weights/sam3 与极柱数据集在场（夹具 skip 兜底）。
【未知→已裁决】覆盖面全 4 维度 / 最低集断言 / exe 模式（2026-08-31 用户确认）。

## 6. 实现思路

1. Task 1：FR-5 exe 冒烟（跑既有伪权重用例）→ 绿则继续 / 红则 spec 补丁+重打包
2. Task 2：FR-1+FR-2 合并用例（一图流：3 对象 + 替换验证 + 全量几何断言）
3. Task 3：FR-3 撤销/重做/清空用例
4. Task 4：FR-4 换图+往返用例
5. Task 5：全文件 exe 模式跑批 + 主门禁回归（tests/uia 仍默认排除，不影响 CI）

---

- 版本：v1.0（2026-08-31）
- 门禁 2（PRD）：✅ 已确认（2026-08-31，"确认，进入 Phase 3"）
