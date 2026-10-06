# W71 测评报告：MVTec(HALCON) blister 平台首案例实测

- **日期**: 2026-10-06
- **任务**: 找到 MVTec 深度学习图片数据集，对当前模型进行测评（用户指令）
- **方案**: A 平台首案例实测（用户门禁裁决）——数据标注 → 软件内真训练 → 软件内批量推理 → 对 GT 评分
- **对象**: dist\AutoVisionAgent\AutoVisionAgent.exe（2026-10-06 13:31 构建，含 W65-W70 全部修复）

## 1. 数据集

本地 MVTec 资产为 HALCON-18.11-Steady 示例图库（188 类 6727 张，无标注，
非 MVTec AD 基准）。选取 **blister（泡罩药板）** 类 20 张：

- 700×480 彩色系 7 张（blister_01-06 + blister_reference）
- 750×478 灰度系 13 张（blister_mixed_01-12 + blister_mixed_reference）
- 缺陷类型：深绿异色药丸 / 缺粒（露铝箔）/ 缺半

### GT 方法论（三重验证）

全图级视觉模型判读两轮互相矛盾（±1 格漂移、灰度图上幻觉"绿色"），不可
直接作真值。最终采用**裁片探针 + 程序证据交叉**：

1. **ORB 配准差分**：每图与同系列 reference 做特征配准（RANSAC 平移/旋转
   约束）后逐像素差分，差分连通域 = 候选缺陷框；
2. **视觉探针**：候选框高清裁片（2×放大）送视觉模型裁决缺陷真伪；
3. **像素佐证**：裁片中位色验证（暗绿药丸 rgb≈(46,62,59)、露箔偏蓝白
   亮度>200、正常药丸 (193,203,187)≈亮度 198）。

三者一致才入 GT。混合灰度系因网格周期性致配准歧义，改用视觉模型两轮
一致标注（同格两轮复现）。

### 划分

| 拆分 | 内容 | 图 | 框 |
|---|---|---|---|
| train | mixed 13 张 + blister_reference(净) + blister_03(3 缺陷) | 15 | 31 |
| eval | blister_01/02/04/05(缺陷) + blister_06(净) | 5 | 10 |

数据与 GT 快照：`E:\学习项目\mvtec_blister_w71\`（build_dataset.py /
eval_gt.json / train/ / eval/）。

## 2. 平台全链实测（UIA 驱动冻结 exe）

| 步骤 | 结果 | 耗时 |
|---|---|---|
| 登录 → 数据管理 → 选择目录 | 载入 15 张 | — |
| 下一步：训练（W65 自动导出） | YOLO det 导出 train=12/val=3，data.yaml nc=1 defect | ~4s |
| 任务自动选择（W69） | rectangle 5 列 → **det** ✓ | — |
| 开始训练（30 轮，AMP ok，cuda） | **真 ultralytics 训练**，33s；外层早停 21 轮（W58 一次性适配器语义，正常） | 37s |
| 产物 | outputs/det_final.pt 5.15MB ✓ | — |
| 推理页 → 加载模型 → 批量推理 eval | **批量完成 5/5**，batch_results.json 落 workspace | 28s |

**链路结论：标注态数据 → 自动导出 → 自动任务 → 真训练 → 权重 → 批量推理
→ 结果落盘，全链贯通。**

## 3. 评分结果（IoU≥0.3 框级，对 GT）

### 3.1 平台默认通道产物（det_final.pt）

- 内部 ultralytics 训练 **未学会**：末轮 precision=0.002 / recall=0.25 /
  mAP50=0.0075（outputs/train/results.csv）；学习率全程 ~1e-4 量级未起。
- eval 5 张（阈值 0.5→0.05 全扫描）：**零检出**，P/R 无定义（0 框）。
- 训练集自检同样零检出——非域移，是训练本身未收敛。

### 3.2 同数据脚本侧对照（适配器 docstring 声明的精度调优口径）

用**平台导出的同一份** `_auto_export/yolo/data.yaml`，仅改超参
（lr0=0.01, optimizer=SGD, epochs=100）：

- val（3 张 8 框）：**mAP50=0.506，P=1.000，R=0.345**
- eval 5 张（thr 0.1-0.5 稳定）：**P=1.000，R=0.300，F1=0.462**（tp=3 fp=0 fn=7）

逐图：blister_02 2/2 ✓（深绿药丸）、blister_04 1/4、blister_06(净) 0 误报 ✓；
未命中集中在**露箔缺粒类**（0/4——训练集仅 1 例）；深绿药丸类 3/4。

### 3.3 好权重回灌平台推理页

offline best.pt 经推理页加载 → 批量推理 eval → 检出 3 框（02×2+04×1），
与离线评分完全一致。**推理链可承载好模型。**

## 4. 结论与发现

- **F-1 链路可信**：软件全链（向导交接/自动导出/自动任务/真训练/批量推理/
  结果落盘）在真实首案例上贯通，此前 W58-W70 的整改全部生效。
- **F-2【产品缺陷，roadmap W1 候选】训练默认超参在小数据集失效**：
  optimizer=auto + 默认 lr 在 12 图 ×2 迭代/轮 ×30 轮下学习率未起
  （~1e-4），产出零检出死模型；同数据显式 lr0=0.01 即 mAP50 0.0075→0.506。
  建议默认改显式 SGD lr0=0.01（或小数据场景 lr0/epochs 自适应），并把
  "末轮 P/R" 显示到训练页（现只显示 loss）。
- **F-3 GT 工程方法论**：全图级视觉判读不可靠（±1 格漂移 + 灰度幻觉），
  裁片探针 + 配准差分 + 像素中位色三重交叉才可冻结真值。
- **F-4 first-case-time**：纯平台操作链（登录→选目录→训练→批量推理完成）
  ≈ 2.3 分钟（74s+65s，含两次启动），远低于 roadmap 北极星 2h；
  瓶颈在标注环节（真实用户 15 图手工标注约 10-20 分钟，可接受）。

## 5. 复现

```
E:\学习项目\mvtec_blister_w71\
  build_dataset.py        # 数据集构建（GT 冻结逻辑）
  run_w71_train.py        # 阶段1：UIA 训练 harness（train_result.json）
  run_w71_predict.py      # 阶段2：UIA 批量推理 harness（predict_result.json）
  score_w71.py            # 阈值扫描评分（score_result.json）
  cell_detector.py / fft_detector.py / ecc_diff.py / diff_*.py  # GT 探索链（留档）
  offline_train/det100/   # 脚本侧对照训练（best.pt + results.csv）
```

## 6. 局限

- 15 训练图为极小样本，P/R 数值仅对该 blister 案例负责，不代表模型上限。
- GT 为"三重验证代理真值"（探针+差分+像素），非人工像素级精标；
  eval 框 IoU≥0.3 的宽容度已据此放宽。
- eval 仅 5 张（4 缺陷 + 1 干净），漏检类的结论（露箔 0/4）受训练集
  单例限制，属数据量问题而非链路问题。
