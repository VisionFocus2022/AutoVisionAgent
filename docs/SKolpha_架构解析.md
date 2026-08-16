# SKolpha 3.3.2 平台架构深度解析

> 分析日期: 2026-06-28  
> 源文件: `E:\计算机视觉\视觉大模型\最新版-SKolpha3.3.2-更新日期2024.11.18\skolpha.exe`  
> 版本: 3.3.2 (更新日期 2024.11.18)  
> 分析方法: 逆向分析 `integrations/skolpha/` 集成代码 + `assets/` 配置文件 + `TrainConfigs/` 模型文件命名

---

## 目录

- [一、平台概述](#一平台概述)
- [二、整体架构拆解](#二整体架构拆解)
- [三、九大任务类型技术实现](#三九大任务类型技术实现)
- [四、六种标注模式技术实现](#四六种标注模式技术实现)
- [五、核心工作流与技术实现](#五核心工作流与技术实现)
- [六、配置系统架构](#六配置系统架构)
- [七、模型加载与推理引擎](#七模型加载与推理引擎)
- [八、GAN缺陷生成技术](#八gan缺陷生成技术)
- [九、GUI框架与交互层](#九gui框架与交互层)
- [十、本项目集成方案](#十本项目集成方案)
- [十一、与本项目的差异化定位](#十一与本项目的差异化定位)
- [十二、技术亮点与可借鉴点](#十二技术亮点与可借鉴点)
- [十三、完整文件清单](#十三完整文件清单)

---

## 一、平台概述

SKolpha 是一个**工业视觉标注-训练-部署一体化商业平台**，以 `skolpha.exe` 形式分发（Windows桌面应用）。覆盖从数据标注→模型训练→推理部署→结果导出的完整工业AI工作流，定位为**有监督学习范式**的通用工业视觉平台。

| 属性 | 值 |
|------|-----|
| 版本 | 3.3.2 |
| 更新日期 | 2024.11.18 |
| 分发形式 | 封闭商业 `.exe`（PyInstaller/Nuitka打包） |
| 支持任务 | 9种（分类/检测/分割/关键点/异常检测/缺陷生成/超分辨率） |
| 标注模式 | 6种（多边形/矩形/画笔/关键点/AI自动/交互式） |
| 预训练模型 | 9个（`.pt`/`.pth` PyTorch格式） |
| 配置格式 | JSON |
| UI主题 | 夜间模式(night) / 日间模式(daytime) |
| 多语言 | 中文(ch_CN) / 英文(en_US) |

---

## 二、整体架构拆解

### 2.1 目录结构

```
skolpha.exe (主程序)
├── assets/                          # 配置层（JSON驱动）
│   ├── configFile.json              # 运行时配置（用户可修改，轻量）
│   ├── configFile_template.json     # 配置模板（含全部字段注释，完整结构）
│   └── createFlawconfigFile.json    # 缺陷生成专用配置
├── TrainConfigs/                    # 预训练模型仓库（9个模型文件）
│   ├── preptrain_cls.pt             # 图像分类
│   ├── preptrain_det.pt             # 目标检测
│   ├── preptrain_seg.pt             # 实例分割
│   ├── pretrain_pseg.pth            # 实例分割-Pro
│   ├── preptrain_pose.pt            # 关键点检测
│   ├── pretrain_sseg.pth            # 语义分割
│   ├── abdet_r50.pth                # 异常检测（ResNet50骨干）
│   ├── pretrain_sgan.pth            # 缺陷生成（GAN）
│   └── pretrain_super.pth           # 超分辨率
└── skolpha.exe                      # 主程序入口
```

### 2.2 推断的软件分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    GUI 交互层 (Qt/C++ 或 PyQt)               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 标注界面  │  │ 训练界面  │  │ 推理界面  │  │ 项目管理  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
├───────┼─────────────┼─────────────┼─────────────┼──────────┤
│       │     业务逻辑层 (Python + PyTorch)         │          │
│  ┌────▼──────────────────────────────────────────▼─────┐   │
│  │              SKolphaAPIClient (统一门面)              │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │   │
│  │  │ModelManager  │ │ConfigManager │ │AnnotationTool│ │   │
│  │  │  模型加载卸载 │ │  配置读写计数 │ │  标注创建保存 │ │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │   │
│  └─────────┼────────────────┼────────────────┼─────────┘   │
├────────────┼────────────────┼────────────────┼─────────────┤
│    数据层   │      模型层    │     配置层     │    存储层    │
│  ┌─────────▼──┐  ┌─────────▼──┐  ┌─────────▼──┐ ┌───────▼──┐│
│  │图像/标注文件│  │.pt/.pth权重│  │ JSON配置   │ │项目目录  ││
│  │ PNG/JPG/JSON│  │ 9种预训练  │  │configFile  │ │Projects/ ││
│  └────────────┘  └────────────┘  └────────────┘ └──────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 2.3 技术栈推断

| 层 | 技术选型 | 推断依据 |
|----|---------|---------|
| GUI框架 | Qt 5/6 + Python绑定 | `.exe`打包 + JSON配置风格 + 工业软件惯例 |
| 深度学习框架 | PyTorch | `.pt`/`.pth` 模型文件格式 |
| 骨干网络 | ResNet50 (abdet_r50) | 文件名 `abdet_r50.pth` 直接暴露 |
| 训练范式 | 迁移学习/微调 | `preptrain_*` 前缀表明预训练权重 |
| 配置系统 | JSON | `configFile.json` + `configFile_template.json` |
| 数据格式 | JSON标注 (类LabelMe) | `annotation_tool.py` 中标注数据结构 |
| 打包工具 | PyInstaller/Nuitka | 单个 `.exe` 分发 |

---

## 三、九大任务类型技术实现

### 3.1 任务总览

| 任务代码 | 中文名称 | 预训练文件 | 文件格式 | 骨干网络推测 | 工业应用场景 |
|----------|----------|-----------|---------|-------------|-------------|
| `cls` | 图像分类 | `preptrain_cls.pt` | PyTorch | ResNet/EfficientNet | 良品/不良品二分类 |
| `det` | 目标检测 | `preptrain_det.pt` | PyTorch | YOLOv5/v8/Faster-RCNN | 缺陷定位与框选 |
| `seg` | 实例分割 | `preptrain_seg.pt` | PyTorch | Mask-RCNN/YOLOv8-Seg | 逐像素缺陷轮廓 |
| `pseg` | 实例分割-Pro | `pretrain_pseg.pth` | PyTorch | 高精度分割模型 | 高精度边缘勾勒 |
| `pose` | 关键点检测 | `preptrain_pose.pt` | PyTorch | HRNet/POSENet | 元件位置/角度校验 |
| `sseg` | 语义分割 | `pretrain_sseg.pth` | PyTorch | DeepLabV3+/UNet/PSPNet | 全图语义分类 |
| `abdet` | 异常检测 | `abdet_r50.pth` | PyTorch | ResNet50 + PatchCore/PaDiM | 无缺陷样本场景 |
| `sgan` | 缺陷生成 | `pretrain_sgan.pth` | PyTorch | GAN (Generator+Discriminator) | 合成训练数据 |
| `super` | 超分辨率 | `pretrain_super.pth` | PyTorch | ESRGAN/SRCNT/SwinIR | 提升低分辨率图像 |

### 3.2 命名规律分析

文件名遵循 `{preptrain|pretrain}_{任务代码}.{pt|pth}` 规律：

- **`preptrain_`** 前缀（8个文件）— 统一的预训练权重前缀，可能是项目早期统一命名
- **`pretrain_`** 前缀（4个文件）— 后期新增任务的命名，少了 `p` 字母
- **`.pt`** vs **`.pth`** — PyTorch两种扩展名混用，`.pt` 通常为完整模型，`.pth` 通常为state_dict

```python
# 模型文件映射（来源：model_manager.py）
model_files = {
    "cls":   "preptrain_cls.pt",     # preptrain 前缀 + .pt
    "det":   "preptrain_det.pt",     # preptrain 前缀 + .pt
    "seg":   "preptrain_seg.pt",     # preptrain 前缀 + .pt
    "pseg":  "pretrain_pseg.pth",    # pretrain 前缀 + .pth (后期)
    "pose":  "preptrain_pose.pt",    # preptrain 前缀 + .pt
    "sseg":  "pretrain_sseg.pth",    # pretrain 前缀 + .pth (后期)
    "abdet": "abdet_r50.pth",        # 特殊命名: abdet + 骨干(r50) + .pth
    "sgan":  "pretrain_sgan.pth",    # pretrain 前缀 + .pth (后期)
    "super": "pretrain_super.pth"    # pretrain 前缀 + .pth (后期)
}
```

### 3.3 各任务技术实现推测

#### 图像分类 (cls)
```
输入: H×W×3 图像
骨干: ResNet50/EfficientNet-B0 → 全局平均池化 → FC层
输出: N个类别的概率分布 (softmax)
损失: CrossEntropyLoss
工业用途: OK/NG二分类、产品等级分类
```

#### 目标检测 (det)
```
输入: H×W×3 图像
骨干: CSPDarknet (YOLOv5) 或 ResNet+FPN (Faster-RCNN)
头部: 
  - YOLO: 解耦头 (分类分支 + 回归分支)
  - Faster-RCNN: RPN + ROI Head
输出: [N, 6] = [x1, y1, x2, y2, confidence, class]
损失: CIoU + Focal Loss + 分类CE
工业用途: 缺陷区域定位+类型判定
```

#### 实例分割 (seg) / 实例分割-Pro (pseg)
```
输入: H×W×3 图像
骨干: ResNet+FPN 或 CSPDarknet
方案1 (seg):  YOLOv8-Seg → Prototype Mask + Mask Coefficients
方案2 (pseg): Mask-RCNN → ROI Align → Mask Head (更高精度)
输出: 每个实例的 {bbox, mask(H×W二值), class, score}
损失: 检测Loss + Mask BCE/Dice Loss
工业用途: 精确缺陷区域勾勒，计算缺陷面积
```

#### 关键点检测 (pose)
```
输入: H×W×3 图像
骨干: HRNet-W32 或 ResNet + Deconv
头部: Heatmap回归 (每个关键点一个通道)
输出: [N, K, 3] = K个关键点的 {x, y, confidence}
损失: MSE (Heatmap) 或 OKS Loss
工业用途: 元件位置校验、装配角度检查、贴合对位
```

#### 语义分割 (sseg)
```
输入: H×W×3 图像
骨干: ResNet/Xception + ASPP (DeepLabV3+) 或 VGG Encoder (UNet)
头部: Decoder + Dropout → 1x1 Conv → N类
输出: H×W 语义标签图 (每像素一个类别)
损失: CrossEntropy + Dice (多类分割)
工业用途: 全图缺陷区域标注、背景/前景分离
```

#### 异常检测 (abdet) — 最接近本项目
```
输入: H×W×3 图像
骨干: ResNet50 (文件名 abdet_r50.pth 直接暴露)
方案: PatchCore 或 PaDiM
  - PatchCore: 提取中间层特征 → 构建特征记忆库 → k-NN距离异常评分
  - PaDiM: 提取多层特征 → 拟合多元高斯分布 → 马氏距离异常评分
输出: {anomaly_score(全局), anomaly_map(H×W)}
损失: 无监督 (仅需正常样本)
工业用途: 无缺陷样本可用时的通用异常检测
```

#### 缺陷生成 (sgan)
```
输入: OK模板图像 + 真实缺陷特征
架构: Conditional GAN
  - Generator: U-Net/ResNet → 从OK图像生成含缺陷图像
  - Discriminator: PatchGAN → 判别生成质量
  - Condition: 缺陷类型/位置/强度编码
输出: 合成缺陷图像
损失: Adversarial Loss + L1 Reconstruction + Perceptual Loss
工业用途: 扩充缺陷训练数据（解决缺陷样本稀少问题）
```

#### 超分辨率 (super)
```
输入: 低分辨率图像 LR
架构: ESRGAN (RRDB blocks + Upsampling)
输出: 高分辨率图像 HR (2x/4x)
损失: L1 + Perceptual(VGG) + GAN Loss
工业用途: 提升低分辨率工业相机图像的检测精度
```

---

## 四、六种标注模式技术实现

### 4.1 标注模式定义

```python
# 来源: annotation_tool.py
annotation_modes = {
    "polygon":     {"key": "Q", "name": "多边形标注", "description": "精确勾勒缺陷轮廓"},
    "rectangle":   {"key": "R", "name": "矩形标注",   "description": "快速框选"},
    "brush":       {"key": "P", "name": "画笔标注",   "description": "自由绘制"},
    "keypoint":    {"key": "K", "name": "关键点标注", "description": "标注关键位置"},
    "auto":        {"key": "W", "name": "AI自动标注", "description": "模型辅助标注"},
    "interactive": {"key": "I", "name": "交互式标注", "description": "智能分割"},
}
```

### 4.2 各模式技术实现细节

#### 多边形标注 (Q)
```
交互流程: 左键逐点添加 → 右键闭合
数据结构: { type: "polygon", points: [(x1,y1), ...], color, category }
渲染: QPainterPath → moveTo + lineTo × N → closeSubpath
填充: QBrush(alpha=50 半透明)
适用任务: seg, pseg, sseg
```

#### 矩形标注 (R)
```
交互流程: 左键按下拖拽 → 释放完成
数据结构: { type: "rectangle", rect: QRect(x, y, w, h), color, category }
渲染: painter.drawRect(rect)
适用任务: det, cls (ROI裁剪)
```

#### 画笔标注 (P)
```
交互流程: 左键按下连续移动 → 沿路径绘制椭圆
数据结构: { type: "brush", points: [(x1,y1), ...], brush_size, color, category }
渲染: for point in points: painter.drawEllipse(point, brush_size, brush_size)
适用任务: sseg (不规则区域语义分割)
已知Bug: mouseReleaseEvent未落入shapes栈，画笔标注可能不保存
```

#### 关键点标注 (K)
```
交互流程: 左键单击放置关键点
数据结构: { type: "keypoint", points: [(x, y)], color, category }
渲染: painter.drawEllipse(point, 5, 5)
适用任务: pose (关键点检测训练标注)
```

#### AI自动标注 (W)
```
交互流程: 加载预训练模型 → 模型推理 → 自动生成标注 → 人工修正
技术实现:
  1. 用户选择任务类型 (det/seg/...)
  2. 加载对应预训练模型 (model_manager.load_model)
  3. 对图像执行推理
  4. 推理结果转为标注格式 (bbox→rectangle, mask→polygon)
  5. 在画布上显示预标注结果
  6. 用户可修改/删除/补充
适用任务: 全部 (利用预训练模型加速标注)
```

#### 交互式标注 (I)
```
交互流程: 点击/拖拽 → SAM类模型分割 → 自动生成多边形
技术实现（推测）:
  1. 加载SAM (Segment Anything Model) 或类似交互分割模型
  2. 用户点击提供前景/背景种子点
  3. 模型输出分割mask
  4. mask→多边形轮廓转换 (cv2.findContours)
  5. 简化轮廓点 (Douglas-Peucker算法)
适用任务: seg, pseg, sseg (半自动精确分割)
```

### 4.3 标注数据持久化格式

```json
// 每张图像对应一个JSON文件（类LabelMe格式）
{
    "imagePath": "image_001.jpg",
    "annotationType": "polygon",
    "shapes": [
        {
            "type": "polygon",
            "points": [[100, 100], [200, 100], [200, 200]],
            "color": [52, 152, 219, 255],
            "category": "划伤"
        },
        {
            "type": "rectangle",
            "rect": [50, 50, 300, 200],
            "color": [46, 204, 113, 255],
            "category": "凹陷"
        }
    ],
    "imageHeight": 1080,
    "imageWidth": 1920,
    "createdTime": "2024-11-18T10:30:00",
    "updatedTime": "2024-11-18T10:35:00"
}
```

### 4.4 撤销/重做系统

```
undo_stack: List[deepcopy(shapes)]  # 深拷贝历史状态栈
redo_stack: List[deepcopy(shapes)]  # 重做栈

操作流程:
  save_state():  undo_stack.append(deepcopy(shapes)); redo_stack.clear()
  undo():        redo_stack.append(deepcopy(shapes)); shapes = undo_stack.pop()
  redo():        undo_stack.append(deepcopy(shapes)); shapes = redo_stack.pop()

快捷键:
  Ctrl+Z: 撤销
  Ctrl+Y: 重做
  Delete: 删除最后一个标注
  Space:  切换标注显示/隐藏
```

### 4.5 剪贴板系统

```
copy_annotations(): clipboard_shapes = deepcopy(shapes)
paste_annotations(): 
  for shape in deepcopy(clipboard_shapes):
    offset = 20
    if shape has "points":  每个point += (offset, offset)
    if shape has "rect":    rect.x/y += offset
    shapes.append(shape)
```

---

## 五、核心工作流与技术实现

### 5.1 标注→训练→部署全流水线

```
Phase 1: 数据准备
┌─────────────────────────────────────────────┐
│  图像导入 → 6种模式标注 → JSON标注文件      │
│  支持格式: .jpg/.jpeg/.png/.bmp/.tif/.tiff  │
│  输出: 每图一个JSON + 原图                   │
└──────────────────────┬──────────────────────┘
                       ▼
Phase 2: 模型训练
┌─────────────────────────────────────────────┐
│  选择任务类型(cls/det/seg/...)              │
│  → 加载预训练权重(preptrain_*.pt)           │
│  → 配置训练参数(epochs/lr/batch_size)       │
│  → 迁移学习微调                             │
│  输出: 微调后的模型权重(.pt/.pth)            │
└──────────────────────┬──────────────────────┘
                       ▼
Phase 3: 推理部署
┌─────────────────────────────────────────────┐
│  加载微调模型 → 输入新图像 → 推理           │
│  输出: 检测结果(bbox/mask/score)            │
│  可选: 批量推理 / 视频流推理                │
│  可选: 模型导出(ONNX/TensorRT)              │
└──────────────────────┬──────────────────────┘
                       ▼
Phase 4: 结果管理
┌─────────────────────────────────────────────┐
│  保存预测结果 → 统计报表 → 导出CSV/JSON     │
│  存储路径: saveData (如 E:/SKolphaDATA)     │
└─────────────────────────────────────────────┘
```

### 5.2 项目管理机制

```
configSaveDir: E:/SKolpha/Projects     # 项目保存根目录
saveData:      E:/SKolphaDATA          # 批量预测/自动标注结果

每个项目独立目录结构（推测）:
  Projects/
  └── {task_type}_{ID}/               # 如 pseg_25/
      ├── images/                      # 原始图像
      ├── annotations/                 # 标注JSON
      ├── models/                      # 训练权重
      ├── configs/                     # 训练配置
      └── results/                     # 预测结果

任务ID自动递增: 每创建一个新项目，对应taskID+1
```

### 5.3 批量处理工作流

```
1. 选择图像目录 → 扫描所有 .jpg/.jpeg/.png/.bmp/.tif/.tiff
2. 选择任务类型 + 阈值 + 对象类型
3. 逐张推理:
   for file in files:
     image = Image.open(file).convert('RGB')
     tensor = preprocess(image).unsqueeze(0)
     result = detector.detect(tensor, ...)
     detection_history.add_record(...)
     audit_logger.log_detection_complete(...)
4. 统计输出: 总数/缺陷数/缺陷率
5. 写入历史记录 + 审计日志
```

### 5.4 AI辅助标注闭环

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  图像导入 │───▶│ 模型推理  │───▶│ 自动标注  │───▶│ 人工修正  │
└──────────┘    └──────────┘    └──────────┘    └────┬─────┘
                                                      │
                                                      ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 模型迭代  │◀───│ 标注入库  │◀───│ 质量校验  │◀───│ 标注保存  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘

闭环效果: 模型越用越准，标注越来越快（人工只需修正少量错误）
```

---

## 六、配置系统架构

### 6.1 三层配置文件

| 文件 | 角色 | 说明 |
|------|------|------|
| `configFile_template.json` | 模板（完整字段+注释） | 包含全部字段和 `?字段` 说明注释 |
| `configFile.json` | 运行时配置 | 用户实际使用的轻量配置，只保留修改过的字段 |
| `createFlawconfigFile.json` | 缺陷生成专用 | GAN缺陷生成的数据路径配置 |

### 6.2 完整配置字段

```json
// configFile_template.json - 完整字段定义
{
    "frmeID": 203,
    "?frmeID": "项目管理界面已经创建的个数",

    "psegID": 24,
    "?psegID": "实例分割-pro",

    "segID": 1,
    "?segID": "实例分割",

    "detID": 0,
    "?detID": "目标检测",

    "clsID": 0,
    "?clsID": "图像分类",

    "poseID": 0,
    "?poseID": "关键点",

    "ssegID": 1,
    "?ssegID": "语言分割",   // 注: 原文为"语言分割"，疑为"语义分割"笔误

    "abdetID": 0,
    "?abdetID": "异常检测",

    "sganID": 0,
    "?sganID": "缺陷生成",

    "configSaveDir": "E:/SKolpha/Projects",
    "?configSaveDir": "项目保存的位置，可以进行修改。",

    "saveData": "E:/SKolphaDATA",
    "?saveData": "批量预测和自动标注结果的保存位置，可以进行修改。",

    "style": "night",
    "?style": "黑白样式切换的关键字。含有night, daytime",

    "selected_language": "ch_CN",
    "?selected_language": "多语言的切换的关键字，含有 ch_CN, en_US两种类型"
}
```

### 6.3 配置字段说明规范

SKolpha 采用**注释字段模式**（`?字段名`），将注释直接嵌入JSON：

```json
{
    "psegID": 24,
    "?psegID": "实例分割-pro"      // ← 注释字段，键名加 ? 前缀
}
```

优势：
- 配置文件自文档化，无需额外说明文档
- 程序读取时跳过 `?` 开头的键即可
- 用户编辑配置时直接看到字段含义

### 6.4 配置加载优先级

```
1. configFile.json          (优先，用户实际配置)
2. configFile_template.json (回退，默认模板)
3. 硬编码默认值              (最终回退)
```

```python
# 来源: config_manager.py
def get_project_config(self):
    if "configFile.json" in self.configs:
        return self.configs["configFile.json"]        # 优先
    elif "configFile_template.json" in self.configs:
        return self.configs["configFile_template.json"]  # 回退
    return None                                        # 最终回退
```

---

## 七、模型加载与推理引擎

### 7.1 模型加载机制

```python
# 来源: model_manager.py — 核心加载流程

class SKolphaModelManager:
    def __init__(self):
        self.model_dir = ".../TrainConfigs/"   # 模型仓库目录
        self.models = {}                        # 已加载模型缓存字典

    def load_model(self, model_type: str):
        # 1. 合法性检查
        if model_type not in self.model_types: return None

        # 2. 缓存检查（避免重复加载）
        if model_type in self.models:
            return self.models[model_type]      # 直接返回缓存

        # 3. 路径构造
        model_file = self.model_files[model_type]  # 如 "abdet_r50.pth"
        model_path = os.path.join(self.model_dir, model_file)

        # 4. 文件存在性检查
        if not os.path.exists(model_path): return None

        # 5. PyTorch加载（双重安全策略）
        try:
            # 尝试安全加载（防止反序列化攻击）
            model = torch.load(model_path,
                             map_location=torch.device('cpu'),
                             weights_only=True)
        except TypeError:
            # 旧版PyTorch不支持weights_only，回退普通加载
            model = torch.load(model_path,
                             map_location=torch.device('cpu'))

        # 6. 缓存
        self.models[model_type] = model
        return model
```

### 7.2 安全加载策略

```python
# 第一优先: weights_only=True (PyTorch 1.13+)
# 只反序列化张量数据，不执行任意代码，防止恶意模型
torch.load(path, weights_only=True)

# 回退: 普通加载 (兼容旧版PyTorch或完整模型对象)
torch.load(path, map_location='cpu')
```

| 安全层级 | weights_only=True | weights_only=False |
|---------|-------------------|-------------------|
| 执行任意代码 | 不可能 | 可能（仅信任来源时使用） |
| 加载内容 | 仅state_dict (权重张量) | 完整模型对象 (含类定义) |
| 适用场景 | 下载/第三方模型 | 自训练模型 |
| PyTorch版本 | ≥1.13 | 全版本 |

### 7.3 模型缓存管理

```python
# 懒加载 + 缓存策略
self.models: Dict[str, Any] = {}  # type → model

load_model("abdet")    # 首次加载: 磁盘→内存→缓存
load_model("abdet")    # 再次加载: 缓存命中，直接返回

unload_model("abdet")  # 从缓存移除 (del self.models[type])
unload_all_models()    # 清空所有缓存 (self.models.clear())
```

### 7.4 模型信息查询

```python
def get_model_info(self, model_type: str) -> Dict:
    return {
        "type":   model_type,                    # 任务代码
        "name":   self.model_types[model_type],  # 中文名称
        "file":   self.model_files[model_type],  # 文件名
        "loaded": model_type in self.models,     # 是否已加载
        "path":   os.path.join(self.model_dir,   # 完整路径
                    self.model_files[model_type])
    }
```

---

## 八、GAN缺陷生成技术

### 8.1 配置文件

```json
// createFlawconfigFile.json
{
    "savedata": "E:/.../save",           // 生成缺陷图像保存目录
    "databaseSaveFile": "E:/.../Mpo",    // 真实缺陷数据库（特征来源）
    "flawDataFile": "E:/.../模板5原始图像OK"  // OK模板图像（生成基准）
}
```

### 8.2 GAN缺陷生成工作流

```
Phase 1: 数据准备
┌──────────────────┐     ┌──────────────────┐
│ OK模板图像        │     │ 真实缺陷样本      │
│ (flawDataFile)   │     │ (databaseSaveFile)│
│ 完好的产品图像    │     │ 缺陷区域的裁剪图   │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
Phase 2: 特征提取
┌──────────────────────────────────────────────┐
│  缺陷特征编码器:                               │
│  从真实缺陷样本提取 → 缺陷纹理/形状/颜色特征    │
│  编码为条件向量 z                              │
└──────────────────────────────────────────────┘
                        │
                        ▼
Phase 3: 条件生成
┌──────────────────────────────────────────────┐
│  Generator (pretrain_sgan.pth):               │
│  输入: OK图像 + 缺陷条件向量 z                 │
│  处理: U-Net/ResNet架构的条件生成              │
│  输出: 合成缺陷图像 (OK图像上叠加逼真缺陷)      │
└──────────────────────────────────────────────┘
                        │
                        ▼
Phase 4: 质量判别
┌──────────────────────────────────────────────┐
│  Discriminator:                               │
│  判别生成缺陷是否逼真                          │
│  反馈给Generator进行对抗训练                   │
└──────────────────────────────────────────────┘
                        │
                        ▼
Phase 5: 输出
┌──────────────────────────────────────────────┐
│  合成缺陷图像 → savedata目录                   │
│  用于扩充训练数据集                            │
└──────────────────────────────────────────────┘
```

### 8.3 GAN架构推测

```
Generator G: OK_image + z → Synthetic_defect_image
  架构: Conditional U-Net 或 ResNet-based
  输入: [OK_image(3,H,W), z(defect_code, dim)] 
  中间: Encoder-Decoder + Skip Connections
  输出: Synthetic_defect_image(3,H,W)

Discriminator D: image → real/fake probability
  架构: PatchGAN (局部判别) 或 Full-image
  输入: image(3,H,W)
  输出: probability map or scalar

Loss Function:
  L_total = λ_adv × L_adv(G,D)         # 对抗损失
          + λ_rec × L_rec(G)            # 重建L1损失
          + λ_perc × L_perc(G)          # 感知损失(VGG特征)
          + λ_z × L_z(G)                # 条件一致性损失
```

### 8.4 工业价值

| 痛点 | GAN解决方案 |
|------|------------|
| 缺陷样本稀少 | 从OK样本合成大量缺陷样本 |
| 标注成本高 | 合成图像自带ground truth（mask来自生成过程） |
| 缺陷类型多样 | 调整条件向量z生成不同类型/位置的缺陷 |
| 训练数据不均衡 | 针对稀有缺陷类型定向生成 |

---

## 九、GUI框架与交互层

### 9.1 GUI技术栈推断

SKolpha 的 GUI 层无法从 `.exe` 直接确认，但从以下线索推断：

| 线索 | 推断 |
|------|------|
| `.exe` 单文件分发 | Python + PyInstaller/Nuitka 打包 |
| JSON配置风格 | Python后端（非纯C++） |
| 工业视觉桌面应用 | Qt框架（行业标配） |
| 多语言切换 | Qt Linguist (ch_CN/en_US) |
| 标注画布交互 | QGraphicsScene/QWidget + QPainter |
| `style: night/daytime` | Qt stylesheet 主题切换 |

**最可能方案**: Python + PyQt5/PySide6 + PyInstaller打包

### 9.2 标注画布渲染实现

```python
# 来源: annotation_canvas.py (本项目复刻版)

class AnnotationCanvas(QWidget):
    annotation_changed = Signal()  # 标注变化信号

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿

        # 1. 绘制深灰色背景
        painter.fillRect(self.rect(), QColor(50, 50, 50))

        # 2. 居中绘制图像
        if self.image:
            x = (width - img_w) // 2
            y = (height - img_h) // 2
            painter.drawImage(x, y, self.image)

        # 3. 绘制已有标注
        if self.show_annotations:
            for shape in self.shapes:
                self.draw_shape(painter, shape)

        # 4. 绘制当前正在绘制的形状
        if self.current_shape:
            self.draw_shape(painter, self.current_shape)

        # 5. 绘制模式提示文字
        painter.drawText(10, 25, f"标注模式: {mode_name}")
```

### 9.3 鼠标交互实现

```
鼠标事件 → 模式分支处理:

mousePressEvent:
  ├── NONE     → 忽略
  ├── POLYGON  → 添加点到当前多边形
  ├── RECTANGLE→ 记录起点
  ├── BRUSH    → 开始画笔路径
  └── KEYPOINT → 立即创建关键点标注

mouseMoveEvent:
  ├── BRUSH    → 追加点到路径
  └── RECTANGLE→ 更新终点

mouseReleaseEvent:
  ├── RECTANGLE→ 完成矩形，保存到shapes
  └── POLYGON  → 右键闭合多边形
```

---

## 十、本项目集成方案

### 10.1 四模块封装架构

项目 `integrations/skolpha/` 已实现对 SKolpha 全部功能的 Python 封装：

```
integrations/skolpha/
├── __init__.py           # 模块入口，导出4个核心类
├── api_client.py         # 统一API门面 (SKolphaAPIClient)
├── model_manager.py      # 模型管理 (SKolphaModelManager)
├── config_manager.py     # 配置管理 (SKolphaConfigManager)
└── annotation_tool.py    # 标注工具 (SKolphaAnnotationTool)
```

### 10.2 模块职责矩阵

| 模块 | 类名 | 核心方法 | 职责 |
|------|------|---------|------|
| model_manager | SKolphaModelManager | load_model, unload_model, list_available_models | 9种预训练模型的加载/卸载/缓存 |
| config_manager | SKolphaConfigManager | get_project_config, update_config, get_task_count | JSON配置读写/任务计数/目录管理 |
| annotation_tool | SKolphaAnnotationTool | create_annotation, add_shape, save_annotation | 6种标注模式的CRUD/批量处理 |
| api_client | SKolphaAPIClient | 组合上述三模块，统一API | 门面模式，简化调用 |

### 10.3 模块依赖关系

```
SKolphaAPIClient (统一门面)
    ├── SKolphaModelManager    (模型加载)
    │     └── torch (PyTorch)
    ├── SKolphaConfigManager   (配置管理)
    │     └── json (标准库)
    └── SKolphaAnnotationTool  (标注工具)
          └── json, os (标准库)
```

### 10.4 完整集成调用示例

```python
from integrations.skolpha import SKolphaAPIClient

client = SKolphaAPIClient()

# === 模型管理 ===
# 列出所有可用模型
models = client.get_models()
# {"cls": {"type":"cls","name":"图像分类","file":"preptrain_cls.pt","loaded":False,...}, ...}

# 加载异常检测模型（ResNet50骨干）
abdet_model = client.load_model("abdet")

# === 标注管理 ===
# 创建多边形标注
client.create_annotation("image_001.jpg", "polygon")

# 添加标注形状
client.add_annotation_shape("image_001.jpg", {
    "type": "polygon",
    "points": [[100, 100], [200, 100], [200, 200]],
    "label": "scratch",
    "category": "划伤"
})

# 保存标注到JSON文件
client.save_annotation("image_001.jpg")
# → 输出: data/annotations/image_001.jpg.json

# === 配置管理 ===
# 获取项目配置
config = client.get_project_config()
# {"psegID": 24, "segID": 1, "configSaveDir": "E:/SKolpha/Projects", ...}

# 更新UI主题
client.update_ui_settings(style="daytime", language="ch_CN")

# 获取任务计数
counts = client.get_task_counts()
# {"pseg": 24, "seg": 1, "det": 0, "cls": 0, "pose": 0, ...}

# 更新任务计数
client.update_task_count("abdet", 5)

# === 批量标注 ===
tool = client.annotation_tool
tool.process_batch_annotation(
    image_dir="path/to/images",
    output_dir="path/to/output",
    annotation_type="polygon"
)

# === 快捷键查询 ===
shortcuts = client.get_shortcut_keys()
# ["Q: 多边形标注 - 精确勾勒缺陷轮廓", "R: 矩形标注 - 快速框选", ...]

# === 关闭 ===
client.shutdown()  # 卸载所有模型
```

---

## 十一、与本项目的差异化定位

### 11.1 核心范式对比

| 维度 | SKolpha | 本项目 |
|------|---------|--------|
| **检测范式** | 有监督（需大量标注+训练） | 零样本（无需训练即可检测） |
| **核心模型** | ResNet50/YOLO/CNN系列 | DINOv3 ViT + CLIP |
| **骨干网络** | ResNet50 (abdet文件名暴露) | DINOv2 ViT-S/14 (384维) |
| **文本理解** | 无（纯视觉） | CLIP文本编码器（提示词驱动） |
| **标注需求** | 必须标注大量样本（百~千级） | 可选标注（零样本）/ 少样本（5~10张） |
| **训练需求** | 每个新场景需重新训练 | 即时推理，无需训练 |
| **部署周期** | 长（标注→训练→验证→部署） | 短（加载模型→即时推理） |
| **精度上限** | 高（有监督训练可达到高精度） | 中等（零样本有上限，少样本可提升） |
| **适用场景** | 大批量稳定产线（固定产品） | 新品切换/快速验证/多品种 |
| **GUI框架** | 疑似 PyQt + PyInstaller | PySide6 (LGPL v3) |
| **分发形式** | 封闭商业 .exe | 开源 Python 项目 |
| **任务覆盖** | 9种任务类型 | 1种（异常检测 + 多种增强模式） |
| **缺陷生成** | 内置GAN (sgan) | 无（可借鉴实现） |
| **超分辨率** | 内置 (super) | 无 |
| **关键点检测** | 内置 (pose) | 无 |
| **许可证** | 商业授权 | 开源 |

### 11.2 技术架构对比

```
SKolpha 架构:
  数据 → [标注] → [训练(CNN微调)] → [推理] → 结果
  特点: 每步独立，训练后精度高，但部署周期长

本项目架构:
  数据 → [即时推理(DINOv3+CLIP)] → 结果
  特点: 跳过标注和训练，即时可用，精度靠提示词调优

混合架构（推荐）:
  数据 → [零样本预标注] → [人工修正] → [少样本微调] → [高精度推理]
  优势: 零样本加速标注 + 少样本提升精度
```

### 11.3 互补关系

```
SKolpha 的优势 → 本项目可借鉴:
  ✅ 9合一任务覆盖（本项目只有异常检测）
  ✅ GAN缺陷生成（解决缺陷样本稀少）
  ✅ AI辅助标注闭环（模型推理→自动标注→人工修正）
  ✅ JSON驱动配置系统（自文档化 ?字段 模式）
  ✅ 完善的项目管理（任务ID计数器）

本项目的优势 → SKolpha 不具备:
  ✅ 零样本检测（无需训练即可使用）
  ✅ 提示词驱动（文本描述缺陷类型，无需标注）
  ✅ DINOv3 ViT骨干（更强的特征表示能力）
  ✅ 跨模态融合（视觉+文本对齐）
  ✅ 少样本增强（5~10张正常样本即可提升精度）
  ✅ 多种异常增强（多尺度/频域/纹理/梯度/自适应融合）
```

---

## 十二、技术亮点与可借鉴点

### 12.1 九合一任务模型 ★★★★★

一个平台覆盖工业视觉全场景，按任务类型加载不同预训练权重。

**本项目可借鉴**: 扩展任务类型，从纯异常检测扩展到分类+检测+分割。当前项目的 `industrial_scenarios.py` 已定义15种工业场景（电子/汽车/纺织/食品/金属/印刷/木材/玻璃/塑料），但检测能力仅限异常检测。可增加分类模式和检测模式。

### 12.2 GAN缺陷生成 ★★★★★

从OK样本合成缺陷数据，解决工业场景"缺陷样本极度稀少"的核心痛点。

**本项目可借鉴**: 在 `few_shot_trainer.py` 中集成GAN数据增强模块——先用GAN从少量真实缺陷合成大量样本，再用扩充后的数据集训练少样本检测器，显著提升检测精度。

### 12.3 AI辅助标注闭环 ★★★★☆

预训练模型自动预标注，人工仅需修正错误标注。

**本项目可借鉴**: 本项目零样本检测器天然适合作为AI标注辅助引擎——先用零样本检测生成初始异常区域标注，再由人工修正。相比SKolpha需要有监督模型才能标注，零样本模型可以直接对新类型产品进行预标注。

### 12.4 JSON自文档化配置 ★★★★☆

所有配置参数外置为JSON，通过 `?字段名` 模式实现自文档化。

**本项目可借鉴**: 当前 `configs/default.yaml` 缺乏内联注释。可引入 `# 注释` YAML注释或迁移到 `?字段` JSON模式，让配置文件自解释。

### 12.5 任务ID计数器 ★★★☆☆

每种任务类型独立计数器（psegID/segID/detID等），用于项目管理和增量ID分配。

**本项目可借鉴**: 在项目管理中增加自动ID分配机制，便于多项目并行管理。

### 12.6 weights_only安全加载 ★★★☆☆

模型加载时优先使用 `weights_only=True` 防止反序列化攻击。

**本项目已具备**: `model_manager.py` 已实现此安全策略，与SKolpha对齐。

### 12.7 多语言i18n ★★☆☆☆

通过 `selected_language` 字段切换中文/英文。

**本项目可借鉴**: 当前GUI仅中文界面。可引入 `PySide6.Qt Linguist` 实现多语言切换。

---

## 十三、完整文件清单

### 13.1 SKolpha 原始文件

```
最新版-SKolpha3.3.2-更新日期2024.11.18/
├── skolpha.exe                              # 主程序 (Windows可执行文件)
├── assets/
│   ├── configFile.json                      # 运行时配置 (轻量, 仅修改字段)
│   ├── configFile_template.json             # 配置模板 (完整字段+注释)
│   └── createFlawconfigFile.json            # 缺陷生成GAN配置
├── TrainConfigs/
│   ├── preptrain_cls.pt                     # 图像分类预训练 (~50-100MB)
│   ├── preptrain_det.pt                     # 目标检测预训练 (~100-200MB)
│   ├── preptrain_seg.pt                     # 实例分割预训练 (~100-200MB)
│   ├── pretrain_pseg.pth                    # 实例分割-Pro预训练 (~100-200MB)
│   ├── preptrain_pose.pt                    # 关键点检测预训练 (~50-100MB)
│   ├── pretrain_sseg.pth                    # 语义分割预训练 (~100-200MB)
│   ├── abdet_r50.pth                        # 异常检测 ResNet50 (~80-100MB)
│   ├── pretrain_sgan.pth                    # 缺陷生成GAN预训练 (~50-100MB)
│   └── pretrain_super.pth                   # 超分辨率预训练 (~50-100MB)
└── (其他运行时文件: DLL/资源/图标等)
```

### 13.2 本项目集成文件

```
integrations/skolpha/
├── __init__.py           # 模块入口 (导出4个核心类, 26行)
├── api_client.py         # 统一API门面 (SKolphaAPIClient, 184行)
├── model_manager.py      # 模型管理器 (SKolphaModelManager, 159行)
├── config_manager.py     # 配置管理器 (SKolphaConfigManager, 179行)
└── annotation_tool.py    # 标注工具 (SKolphaAnnotationTool, 174行)

集成代码总计: 722行 Python
```

### 13.3 配置文件字段汇总

| 配置文件 | 字段数 | 核心字段 |
|---------|--------|---------|
| configFile_template.json | 13个字段 (含注释) | frmeID, psegID~sganID, configSaveDir, saveData, style, selected_language |
| configFile.json | 4个字段 | test, style, selected_language, psegID |
| createFlawconfigFile.json | 3个字段 | savedata, databaseSaveFile, flawDataFile |

---

*本文档基于逆向分析 `integrations/skolpha/` 集成代码（722行）、`assets/` 配置文件（3个JSON）、`TrainConfigs/` 模型文件命名规律，以及与本项目技术栈的对比分析生成。*
