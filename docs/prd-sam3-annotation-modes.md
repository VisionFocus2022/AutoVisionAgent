# PRD：SAM3 标注双模式启用与真实效果实测（W53 · lite）

- 档位：🟡 L2（自治会话：S1 指令「将它SAM3用于标注之中，矩形内分割和中心点分割，启用项目并测试真实效果」+ S3 留痕）
- 确定性：高——装配链（W46：`AVA_SAM3_DIR`→`_load_sam3`→`attach_interactive` 覆盖 INTERACTIVE/REGION_SAM/SAM_BRUSH）与 UIA 真窗套件 `tests/uia/test_sam3_labeling.py` 均在库；本波新增量=量化+复跑+条件微调
- 影响半径：小——生产代码至多触 `predict_point_in_box` 实例选择一处；可逆：双向门

## 1. 背景与目标

W52 已将点击口径（中心点分割）优化至 0.546/0.572/63%（选择 v2 上产），但：
1. **矩形内分割（REGION_SAM · `predict_point_in_box`）从未在 val 上量化**——W47/W52 只测了点击口径；
2. 真窗端到端（GUI 装配→双模式交互→JSON 落盘）自 W46·C 后未在当前代码复跑；
3. `predict_point_in_box` 仍用 argmax 选择——W52 已证点击场景 nearest 更优（+0.025），区域场景未证。

目标：以 val 162 同口径产出区域分割真实数字；真窗复跑证明「项目启用 SAM3 双模式」；证据驱动决定选择策略是否统一。

## 2. 功能需求

- **FR-1 区域口径量化脚本**：`scripts/exp_sam3_region_caliber.py`——val 162 全量（W48 manifest），GT bbox 外扩 m∈{0,16,64} 模拟标注员拖框精度，点击锚=GT 质心（与点击口径同锚可比），选择策略 argmax（现产）vs nearest（W52 赢家）双测共享前向，W43 掩码∩矩形硬约束复刻。
- **FR-2 真窗启用实证**：`AVA_UIA_SOURCE=python` 复跑 `tests/uia/test_sam3_labeling.py` 三用例（交互式点击/SAM 区域/SAM 笔刷一图流 + AUTO 概念 + 伪权重诚实失败）——即「启用项目并测试真实效果」端到端证据。
- **FR-3 证据驱动微调（条件）**：nearest 在同 margin 下 Δmean≥0.01 优于 argmax → `predict_point_in_box` 落地 nearest（TDD 单测先行，与 `predict_point` v2 同语义）；否则生产零改动、数字留档。

## 3. 验收标准

- **AC-1**：六组（3 margin × 2 策略）mean/median/≥0.5 比例/零产出计数全部落档 docs/tasks 回填，与点击口径 0.546/0.572/63% 同表可比。
- **AC-2**：UIA 三用例真窗全绿（真权重 `weights/sam3`，JSON 铁证 ≥3 多边形）。
- **AC-3**：FR-3 证据门执行有据：落地（单测 RED→GREEN）或不落地（Δ<0.01 数字留档）二选一，无中间态。
- **AC-4**：主门禁 `pytest tests/ -q` 全绿（覆盖率棘轮 ≥92 不动）。

## 4. 范围

**In**：`scripts/exp_sam3_region_caliber.py`（新增）、`labeling/sam3_adapter.py`（条件 ≤25 行）、`tests/test_sam3_adapter.py`（条件 +1 测试类）、本 PRD + tasks 两篇。
**Out**：SAM1 默认后端切换（W46 AC-4「无 env 不变」契约不动，启用走 `AVA_SAM3_DIR` 设计通道）；exe 重打包；标注页 pole-seg 双后端接入；W52 点击口径重测（数字在档直接引用）。

## 5. 风险与假设（三栏并入）

- 已知：显存 5.5GB 空闲（SolidWorks/Qoder 占 6.8GB）可容 SAM3 推理 ~4GB；系统内存 33GB 充裕。
- 假设：区域口径预期 ≥ 点击口径（盒提示比 16px 代偿盒信息多）——待 AC-1 验证。
- 风险：①评测与 UIA 均需 GPU，**错峰串行**防 OOM；②真窗跑批期间用户桌面争抢（SetActive 已有对策，click 双发）；③W52 教训——不搞小样本，全 val 162。

## 6. 实现思路

评测脚本复用 `scripts/exp_sam3_inference_params.py` 骨架（manifest/GT 解析/IoU 同源），逐 margin 单前向双策略；生产微调提取 `_best_mask_near` 掩码级选择器供 `predict_point`（已上产语义）与 `predict_point_in_box`（本波条件落地）共用。UIA 复跑走既有命令（`tests/uia/test_sam3_labeling.py` 文档头）。
