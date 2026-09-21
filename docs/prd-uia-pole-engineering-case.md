# PRD：极柱工程案例 UIA 深测 + GUI 真训练通道（lite · L2）

> 档位：🟡L2 ｜ 版本：1.0 ｜ 日期：2026-09-16 ｜ 上游：用户指令（探索门禁已过：范围=软件整体 / 边界=全链含真训练 / 模式=python 源码）
> 探索门禁裁决：三问已答，未知栏清空 ✅

## 1. 背景与目标

W55-W57 刚落地 SAM 异步推理（ADR 0003）等改动，UIA 真窗面尚未首验；既有全流程用例（test_full_workflow）训练环节为**模拟口径**，且仓库已具备极柱真数据（2580 bmp + 1288 LabelMe JSON）、真权重（weights/pole-seg、weights/sam3）、真训练栈（cuda + ultralytics 8.4.81）。本 PRD 交付：

1. **GUI 真训练通道（使能件）**：打通「导出训练集(YOLO-seg) → 训练页真 ultralytics 训练 → 产物 best.pt」链路——架构钩子已预埋（`hasattr(engine, "train_epoch")` 即走真策略），缺三件：TrainConfig 数据源字段、训练页数据源选择 UI、seg 引擎 train_epoch 实现。
2. **极柱工程案例 UIA 全链用例**：新套件 `tests/uia/test_pole_engineering_case.py`，用软件生成完整工程案例（登录→导入→标注(手动+SAM3)→保存→导出训练集→真训练→真模型批量推理→导出 CSV），三级铁证断言，顺带完成 W55 异步化的真窗首验。

## 2. 功能需求（FR）

| # | 需求 | 说明 |
|---|------|------|
| FR-1 | GUI 真训练通道（seg 任务） | ① `TrainConfig` 增 `data_yaml: str = ""` 字段（additive，缺省不破坏既有构造）；② 训练页增「数据集(data.yaml)」选择行（浏览→open dialog）；③ `SegYoloEngine` 增 `train_epoch(epoch, cfg)/save(path)`（ultralytics 一次性适配器：首轮调用跑全量 `YOLO(cfg.backbone).train(data=..., epochs=cfg.epochs, imgsz, device, batch)`，后续轮次返回末轮 metrics；`save` 拷贝 ultralytics 产物 best.pt 到目标路径）；④ 未选 data_yaml / ultralytics 缺失 → 诚实回退既有模拟路径（警告语义不变） |
| FR-2 | 工程案例全链 UIA 用例 | `test_pole_engineering_case.py` 主用例分步：admin 登录→数据管理导入极柱子集→标注页手动多边形+矩形保存 LabelMe→SAM3 标注（AVA_SAM3_DIR=weights/sam3，≥3 次点击形状提交——W55 异步首验）→数据管理导出训练集(YOLO)→训练页选 seg 任务+data.yaml+epochs=2→开始训练→等「训练完成」→推理页加载产物 best.pt 批量推理→导出 CSV。每步状态栏断言 + 关键节点磁盘铁证 |
| FR-3 | 三级铁证断言 | ① 状态栏终态；② 磁盘产物（LabelMe JSON 结构 / yolo 目录 images+labels+data.yaml / best.pt 存在且 >1MB / 批量推理 JSON 非空 / CSV 存在）；③ UIA 树控件存在性。无像素断言 |
| FR-4 | 门禁口径不破坏 | tests/uia 仍默认排除主门禁；新增生产代码（FR-1）带单测进主门禁分母 |

## 3. 验收标准（AC）

| # | 标准 | 验证方式 |
|---|------|----------|
| AC-1 | python 模式（AVA_UIA_SOURCE=python）全链用例一次通过 | pytest tests/uia/test_pole_engineering_case.py 退出码 0；跑批日志含各步骤铁证 |
| AC-2 | 真训练产物落盘 | 训练输出目录 best.pt 存在且 >1MB（真权重非空壳）；训练页状态栏出现「训练完成」且无「（模拟）」警告 |
| AC-3 | 推理与导出真产物 | 批量推理 JSON 每图一条非空记录；CSV 文件存在且表头+数据行 ≥1 |
| AC-4 | 模拟回退不回归 | 无 data_yaml 时训练走模拟路径（单测：状态含模拟警告、不触 ultralytics）；既有 test_full_workflow 模拟路径单测/主门禁全绿 |
| AC-5 | SAM3 异步标注真窗可用 | 用例内 ≥3 次 SAM3 点击均产生形状提交（W55/ADR 0003 首验；如遇时序假红按「等状态栏终态」修用例不改生产代码——除非判定为生产缺陷） |
| AC-6 | 主门禁保持绿 | 全量 pytest ≥1254 passed + 新增单测全绿；ruff 0 |

## 4. 范围

**Out of Scope**：exe 打包模式跑批（交付时可选补跑一次）；训练精度指标断言（本 PRD 是流程铁证非精度评估）；DET/OCR/其他任务真训练引擎（仅 seg 打样，架构同构可后续扩）；评估页 GT 对比深测（沿用既有 eval UIA 面）。

## 5. 风险与假设

| 风险/假设 | 缓解 |
|-----------|------|
| 真训练时长（2 epochs × yolov8n-seg × 8 图 @RTX3060 ≈ 1-3 分钟） | epochs 钉 2、imgsz 640、backbone 用 n 系列；T_TRAIN 超时给 600s |
| ultralytics AGPL-3.0 | 项目决策已接受（seg_yolo.py:4 注记，R-5） |
| W55 异步时序致 UIA 假红 | ADR 0003 适配原则：等状态栏终态再断言；判定生产缺陷则单独修复并记录 |
| UIA 需桌面会话 + 内存预检 <6GB skip | 沿用 conftest 既有机制 |
| EngineTrainStrategy 期望 metrics dict | train_epoch 返回 {"loss": ...}（ultralytics results 末轮 box/seg loss 提取，缺省 0.0） |

## 6. 实现思路（任务映射见 tasks-lite）

T1 产品侧真训练通道（FR-1，TDD：先单测后实现）→ T2 UIA 助手扩展（spin/combo 设置原语）→ T3 全链用例编写（FR-2/3）→ T4 python 模式跑批收敛 + 主门禁回归（AC 全验）。

## ✅ 门禁记录

- [x] 门禁 1（探索）：2026-09-16 AskUserQuestion 三问裁决（范围=软件整体/边界=全链含真训练/模式=python）——未知栏清空
- [x] 门禁 2（PRD）：2026-09-16「按 PRD 实施（推荐）」
- [x] 门禁 3（收尾）：2026-09-21 见下方 AC 核验

## AC 核验记录（收尾）

| AC | 结论 | 证据 |
|---|---|---|
| AC-1 全链一次通过 | ✅（且连续两跑） | python 模式 153.36s / 153.32s 两跑 1 passed（AVA_UIA_SOURCE=python） |
| AC-2 真训练产物 | ✅ | 训练状态「训练已启动 seg」→「训练完成」；seg_final.pt 6.79MB（>1MB）；无模拟回退警告（用例内短窗探测） |
| AC-3 推理与导出 | ✅ | batch_results.json ≥4 条 task=seg 记录；predict_results.csv 落盘、表头 file、数据行 ≥1 |
| AC-4 模拟回退不回归 | ✅ | test_w58 回退单测绿；既有全流程/训练页用例绿（契约更新 2 处：test_gui_train_page / test_tasks_ui） |
| AC-5 SAM3 异步真窗 | ✅ | 用例内 3 次 SAM3 点击均形状提交（W55/ADR 0003 真窗首验通过，无假红） |
| AC-6 主门禁 | ✅ | 1265 passed + 5 skipped / ruff 0 / 覆盖 ≥92 棘轮随 addopts |

**exe 打包模式补充验证（2026-09-21，用户指令追加）**：重打包后全链
**两连绿**（166.10s / 148.88s）——发版检查单口径闭环。exe 专属问题两枚
均在跑批中定位并修复：
① 冻结态 DataLoader 多进程崩溃 → `sys.frozen` 时 workers=0（单测守护）；
② 冻结窗口态 exe 继承 pytest 控制台句柄 → ultralytics Rich 控制台探测
异常致 worker 无声死 → conftest exe 分支 stdout 改 PIPE 捕获（对齐 python
分支可诊断性，兼修句柄形态；双击启动无控制台形态不受影响）。
另：标注完成后经「卸载 SAM」释放 ~4GB 显存再训练（W56 卸载通道首次
实战，操作员真实流形态）。

**实施中顺带修复的产品缺陷**（探索未预见，属 FR-1 落地必要件）：
① 数据集导出取消/路径未接受时静默 return → 诚实发「已取消」状态（data_manage）；
② ultralytics project 相对路径触发 {runs}/{task} 嵌套落点漂移 → 绝对化钉死 {output_dir}/train；
③ save() 的 best.pt 源路径按 trainer.save_dir 动态解析（版本/落点无关）。
