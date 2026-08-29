# PRD：SAM3 极柱域微调（W48 · lite）

## 定档声明

- 档位：🟡 L2（S1「走微调路线」+ S3 留痕）；确定性：探针后转高；影响半径：小（全新增+权重产物，生产零改动，AVA_SAM3_DIR 指向即接入）；可逆：双向门

## 1. 背景与目标

W47 证明零样本域上限（点击 mean IoU 0.559，oracle 0.546）。本波用 811 张极柱缺陷图 GT 微调 SAM3 解码器栈，目标把交互标注精度提到可用区间。

**JTBD**：标注员点击缺陷时，SAM3 直接给出 ≥0.8 IoU 的多边形，人工只需微调折点而非重描。

## 2. 需求（FR）

- **FR-1 数据集**：`scripts/finetune_sam3.py` 内置 `PoleDefectDataset`——LabelMe JSON→缺陷组件（bbox+多边形）；确定性 80/20 按图切分（seed 42，manifest 落盘）；盒提示抖动（±10%）+ 水平/垂直翻转增强；多边形按目标分辨率直接栅格化（免 1600² 掩码物化）。
- **FR-2 训练**：冻结 vision(454M)/text(353M)，训 geometry+detr_enc+detr_dec+mask_dec+dot_product（32.6M，探针显存 4.53GB@13.9M 外推 <6GB）；DETR 匈牙利匹配（掩码 BCE+dice+box L1 代价）→ 正查询 focal+dice 掩码损失 + 全查询 objectness BCE；AMP fp16；AdamW 5e-5 + 余弦；按 epoch val 点击 IoU（模拟 32px 点击盒）选最优 ckpt。
- **FR-3 产物**：`weights/sam3-pole-ft/`（save_pretrained 全家）→ 与 `weights/sam3/` 同构，AVA_SAM3_DIR 可指（零代码接入）；manifest+history JSON 同目录。
- **FR-4 验收**：eval_sam3_accuracy.py 加 `--ckpt/--manifest/--n`；val 集（20% 留出）点击模式 mean IoU **≥0.70 达标 / ≥0.80 优秀**（基线 0.559）；主门禁零回归。
- **FR-5 测试**：数据集构建/切分确定性/抖动/栅格化/匈牙利匹配/损失函数单测（纯 CPU）；smoke 训练（--smoke 3 样本 2 步）真机验证。

## 3. 验收标准（AC）

- AC-1：`--smoke` 跑通（loss 有限、val 路径出 IoU、ckpt 可 save/load）。
- AC-2：全量训练后台完成；val 点击 IoU 相对基线 **+0.14 以上**（≥0.70）。
- AC-3：最优 ckpt 经 adapter 真实路径（AVA_SAM3_DIR 指向）复测，数字与训练内评估一致（±0.02）。
- AC-4：主门禁 1182+ 绿；新单测全绿。

## 4. 范围

**In**：scripts/finetune_sam3.py + tests/test_sam3_finetune_script.py + eval 脚本参数化 + weights/sam3-pole-ft。**Out**：vision 塔 LoRA（若解码器微调 plateau <0.70 的 v2 备案）、文本概念路径微调、训练 UI 集成、exe 打包微调权重。

## 5. 风险与假设（三栏）

- 已知：探针实测可训 32.6M@<6GB/0.78s 步；288² 掩码分辨率下 40px 缺陷≈7px（信号存在）；scipy 在 venv。
- 假设：oracle 上界主要受解码器/提示融合限制（若实为 vision 特征限制 → 解码器微调 plateau，触发 v2 备案）；~1500-2000 组件样本足够收敛。
- 反目标：不污染生产代码；不动 weights/sam3 原始目录（微调另存）；训练不写 repo 内大文件（ckpt 在 weights/ 已忽略）；显存 OOM 即减 batch/减可训面并留痕。

## 6. 实现思路

自包含脚本（不进 training/ 包避免覆盖分母波动）；损失/匹配/数据集为纯函数便于单测；val 评估复刻 adapter 点击语义（BGR→RGB + 32px 代偿盒 + best 实例）；最终验收用真实 adapter 独立进程复测防口径漂移。

## 7. 门禁（S1/S3 留痕）

探索=S1 指令+探针闭环（形状/显存/耗时三项未知全清）；PRD=本文档；收尾=AC 回填+主门禁+独立复测。训练 ckpt 落 weights/（gitignore 已覆盖）不算 commit。
