# PRD：极柱专用分割模型——工程正解路线（W50 · lite）

## 定档声明

- 档位：🟡 L2（S1 用户指令「按 L2 流程立项开跑」+ S3 留痕）
- 确定性：中高——ultralytics YOLO-seg 与项目 seg 引擎同栈、产物直接可被推理链消费
- 影响半径：小（三新脚本 + 数据集目录 + 权重产物，生产零改动）；可逆：双向门
- 背景：W48/W49 证伪 SAM3 微调（零样本 0.515 为现上限，oracle 上界 0.546=vision 特征瓶颈）；本波转全监督专用小模型

## 1. 目标

811 缺陷图 GT（1941 多边形，单类 defect）训 YOLO-seg 专用模型，**同口径验收对比 SAM3 零样本 0.515**，目标 ≥0.75。

## 2. 需求（FR）

- **FR-1 数据转换** `scripts/convert_labelme_to_yoloseg.py`：LabelMe 多边形 → YOLO-seg 归一化 txt（单类 0）；**切分严格复用 W48 manifest**（train 649/val 162 缺陷图保同口径）；368 背景图全进 train（空标签防误检）；图像复制到 `dataset_yoloseg/images/{train,val}`（ultralytics images/labels 路径约定）+ data.yaml。
- **FR-2 训练** `scripts/train_pole_seg.py`：yolov8n-seg 预训练微调（epochs=60/imgsz=1280/batch 自适应/patience=20），产物 `weights/pole-seg/best.pt`。
- **FR-3 同口径验收** `scripts/eval_pole_seg.py`：**与 SAM3 验收完全同口径**——同 manifest val、同 GT 最大连通域、同「质心点击」语义（选包含质心的预测实例，无则 IoU=0）→ mean/median/≥0.5 三指标对表 SAM3 0.515/0.561/57%。
- **FR-4 测试**：转换脚本纯函数单测（归一化边界/类别行/切分对齐/背景空标签）。

## 3. AC

- AC-1：转换后 train 649 缺陷+368 背景、val 162；抽样归一化坐标 ∈[0,1]；空标签文件 368。
- AC-2：训练完成（best.pt 产出，无 OOM）。
- AC-3：同口径验收 val 162 图全量（不用 40 图截断），**mean IoU ≥0.75 达标**；三指标对表汇报。
- AC-4：主门禁零回归（+转换单测）。

## 4. 范围

**In**：三脚本+单测+数据集+权重。**Out**：标注页接入（验收达标后另波次）、多类（YS/ZW/TJYS/HS 合单类）、SAM3 弃用处置。

## 5. 风险与假设

- 已知：预训练权重已下（yolov8n-seg.pt）；内存 29GB/GPU 空；磁盘余量需 ≥10GB（图像复制）。
- 假设：1280 输入保住 40px 缺陷（32px 等效）；811 图单类微调收敛。
- 反目标：不断言混口径；训练 OOM 即降 batch 留痕；背景图不进 val（同口径铁律）。

## 6. 门禁（S1/S3）

探索=S1+三栏闭环（权重/数据/环境三路实证）；PRD=本文档；收尾=AC 回填+对表汇报。
