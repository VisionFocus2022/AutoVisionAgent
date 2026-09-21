# Tasks：极柱工程案例 UIA 深测 + GUI 真训练通道（lite · L2）

> 上游：[prd-uia-pole-engineering-case.md](prd-uia-pole-engineering-case.md) v1.0 ｜ 版本：1.0 ｜ 日期：2026-09-16

| # | 任务 | 内容 | 验证（V 级） | 规模 |
|---|------|------|--------------|------|
| T1 | 真训练通道产品侧（FR-1） | ① TrainConfig 增 `data_yaml=""`；② SegYoloEngine 增 `train_epoch/save`（ultralytics 一次性适配器）；③ 训练页增「数据集」选择行 + cfg 接线 + 未选时诚实回退模拟 | 单测（monkeypatch YOLO）+ 回退单测（V2）；主门禁绿（V4） | M |
| T2 | UIA 助手扩展 | uia_helpers 增 spin 设值（ValuePattern）/combo 按文本选项原语 | 原语级自测（T3 内消费即验） | S |
| T3 | 全链用例编写（FR-2/3） | test_pole_engineering_case.py：登录→导入→手动+SAM3 标注→保存→导出训练集→真训练→批量推理→CSV 导出，三级铁证 | 用例代码评审 + 语法（V1） | M-L |
| T4 | 跑批收敛 + 回归 | python 模式跑批至绿（含 W55 异步时序适配，ADR 0003 原则）；主门禁 + ruff 回归；AC-1..6 全验 | AC 逐条（V3/V4） | M |

依赖：T1 → T3（用例依赖真训练通道）；T2 → T3；T4 最后。

## ✅ 门禁记录

- [x] 门禁 1（探索）：三问裁决见 PRD
- [x] 门禁 2（PRD）：2026-09-16 「按 PRD 实施（推荐）」
- [x] 门禁 3（收尾）：2026-09-21 AC-1..6 全过（见 PRD 核验表）；主门禁 1265 绿 + UIA 两连绿
