# PRD-lite：W1-6 小数据训练默认超参修复

- **版本**: v1.0（2026-10-06）
- **档位声明**: 🟡L2 ｜ 确定性：高（W71 已隔离根因并验证修复方向）｜ 影响半径：大（改训练引擎默认行为，影响所有 YOLO 真训练产物质量；不触数据/鉴权硬触发器）｜ 规模：中（约 4 文件 +80/-10 行生产代码 + 新测试文件）｜ 可逆性：双向门（git revert 单提交）｜ 依据：roadmap W1-6 行 + W71 F-2 证据
- **上游**: roadmap-autovisionagent.md Wave1 W1-6；docs/eval-mvtec-blister-w71.md §4 F-2
- **门禁**: 探索 ✅（2026-10-06：W1-6 先行/B-1 先提交/方案 B 自适应）｜ PRD ✅（S2 预裁决锁定：门禁未响应，按上游书面裁决方案 B+roadmap DoD 实施，2026-10-06）｜ 收尾 ✅（2026-10-06：AC-1/2/3 单测 10/10、AC-5 主门禁 1374 绿+ruff 0、AC-4 DoD exe 实跑 `训练完成 det P=1.00 R=0.35 mAP50=0.51`（30→100 自适应，81.4s））

## 实施纪要（2026-10-06）

- 范围内偏差 1：AC-4 首跑 mAP50=0.27（yolo26n 回退骨干）未达 0.3——补
  spec 打包 yolov8n.pt（det 正主骨干）后复跑 0.51 达标；yolo26n 保留为
  离线兜底。
- 范围外连带修复 2（B-1 批遗留红灯，二轮审查测试全量门禁首跑暴露）：
  ①shm read 与并发 release 竞态在 Windows 上被白名单误报为 ValueError
  （resolve() 对消失路径失败被 except 吞）——白名单失败时复核存在性消歧，
  15 连跑全绿；②W58 一次性适配器测试断言按新 metrics 键收敛
  （epochs_effective）。

## 1. 背景与目标

W71 首案例实测实证：YOLO 适配器 `model.train()` 裸调（不传 optimizer/lr0），
ultralytics `optimizer=auto` 在小数据（12 图 ×2 迭代/轮）下学习率全程 ~1e-4
未起，产出零检出死模型（内部 P=0.002/mAP50=0.0075，训练集自检也零检出）；
同数据显式 SGD lr0=0.01 → val mAP50 0.506。且训练页完成状态只显示
loss，P/R 不可见——用户无法发现"训练没学"。

**目标**：默认配置在 ≤20 图案例可收敛（DoD：val mAP50>0.3），训练页
完成状态显示末轮 P/R/mAP50。

**NFR 底线**：大中数据集（>50 图）训练行为不回退（显式 SGD lr0=0.01 为
ultralytics 官方默认同款，不劣化）；单测全绿 + 主门禁不红；train/page.py
行数守卫 800 内。

## 2. FR

- **FR-1 显式优化器透传**：`_yolo_seg_base` 的 `model.train()` 增加
  `optimizer="SGD", lr0=0.01`（YOLO 通道独立默认；`cfg.lr` 仍归 torch
  路径，不动其他引擎）。
- **FR-2 小数据轮数自适应**：训练图数 N ≤ 50 时，实际轮数
  `max(cfg.epochs, 100)`；日志+完成状态显式说明（"小数据集 N≤50：轮数
  X→Y 自适应"），**UI spinner 值不被偷改**（用户输入保真，运行时策略
  透明化）。N>50 完全按用户轮数。
- **FR-3 训练图数统计**：适配器从 data.yaml 的 train 目录数标签 txt
  （复用 P0-1 划分布局，labels/train/*.txt）。
- **FR-4 末轮 P/R/mAP50 回传**：`model.train()` 后 best-effort 提取
  （优先 `model.trainer.metrics`，键名 det/seg 自适配；缺失时 fallback
  `model.val()` 一次）写入返回 metrics（precision/recall/map50），
  GenericTrainer → artifact.metrics 链路自动携带。
- **FR-5 完成状态显示**：训练页 `_on_finished` 状态显示
  `P=0.xx R=0.xx mAP50=0.xx`（无指标时保持原「训练完成」文案不报错）。

## 3. AC

- **AC-1**：monkeypatch YOLO 捕获 `model.train()` kwargs：含
  `optimizer="SGD"`、`lr0=0.01`、小数据 N=12 且用户 30 轮 → `epochs=100`；
  N=500 → `epochs=用户值`。〔非 happy-path〕
- **AC-2**：fake trainer 提供 det 形态 metrics 键 → 返回 metrics 含
  precision/recall/map50 三键；trainer 无 metrics 时 fallback val() 路径
  被调用；两级都失败时 metrics 不含三键且不抛异常（训练仍成功）。
- **AC-3**：`_on_finished` 对含指标 artifact 显示 P/R/mAP50 文案；对
  无指标 artifact（模拟引擎）维持原文案。〔非 happy-path〕
- **AC-4（DoD 端到端）**：用 W71 工作区同一 15 图数据集经软件训练，
  内部 val mAP50 > 0.3，完成状态含 P/R/mAP50。
- **AC-5**：主门禁 1279+ 全绿、ruff 0、行数守卫内。

## 4. 范围

改：`models/supervised/engines/_yolo_seg_base.py`、
`gui/pages/train/page.py`、`gui/core/i18n.py`（自适应说明键）、
新 `tests/test_w1_6_small_data_hyperparams.py`。
**Out of scope**：逐轮实时进度/曲线（W1-1）、训练历史页（W1-2）、模拟
显式化（W1-3）、UI 可调超参（用户已裁决暂不做）、batch/imgsz 自适应。

## 5. 风险与假设

| 项 | 评估 |
|---|---|
| lr0=0.01 对大数据劣化？ | ultralytics 官方默认即 SGD lr0=0.01（auto 只是运行时改写），不劣化 |
| 100 轮小数据耗时？ | W71 实测 100 轮 12 图 ≈2 分钟 GPU，可接受 |
| trainer.metrics 键名跨版本漂移 | best-effort + fallback val() + 双失败不阻塞（AC-2 三态） |
| Q-1（已决）: 自适应阈值 50 图/100 轮的取值依据？ | W71 单点证据 + ultralytics 惯例，后续案例可再标定；不阻塞 |
