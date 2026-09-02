# SKolpha 3.3.2 全功能取证 — 波1 全景测绘报告

> 日期: 2026-09-02 | 批次: skolpha-full-forensics 波1（FR-001/AC-001/AC-002/AC-004 提前达成） | 关联: docs/prd-skolpha-full-forensics.md
> 目标: `E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18`
> 结论三态标注: 〔✅证实〕常量/文件直接证据 〔🔎推断〕强线索推导 〔❓不可考〕

## 1. 执行摘要

SKolpha 3.3.2 是 **S-Sigma（SSIGMA）的三星客户定制版**工业缺陷检测训练平台〔✅证实：包名 `samsuncn`、工程路径 `E:\SSIGMA\Projects\QP_PSEG_00003_1703234751`、开发路径 `D:/SourceCode/New_Code/S_Sigma3.0`、图标 samsunIcon1〕。技术栈：**PyQt5 UI + Nuitka(Py3.9) onefile 打包（67.9MB，常量区未压缩）**；训练引擎**双轨**——Ultralytics YOLOv8 定制 fork（det/seg/cls/pose）+ OpenMMLab mmcv/mmdet/mmseg（pseg/sseg）+ StyleGAN 缺陷生成 + ResNet50 异常检测 + 超分；标注器为 **labelme 定制 fork + 自研 new_label（内嵌完整 segment_anything SAM）**。全配置层（default.yaml/TrainConfigs 模板/.spro 工程文件）经 **Fernet 加密**，密钥为硬编码常量推导，**已破解**（§5）。

## 2. 取证方法（可复现）

| 步骤 | 手段 | 产物（%TEMP%/skolpha-forensics/） |
|---|---|---|
| 字符串/模块表 | 正则 `[\x20-\x7e]{5,}` + `包.模块` 全量提取（67.9MB → 271,700 串 / 2,559 模块候选 / 2,992 中文串） | strings.txt / modules.txt / chinese.txt |
| chm 手册 | `hh.exe -decompile` + GBK→UTF-8 标题提取（651 文件/160 标题） | chm/ / chm_titles.txt |
| 密钥挖掘 | Fernet 调用点邻域 ±1.4KB 常量 dump | fernet_candidates.txt |
| 解密验证 | cryptography.fernet 试解 | decrypt_skolpha.py |

## 3. 应用架构分层（模块表证据，AC-001）

```
┌─ UI 层 frontend.* ────────────────────────────────┐
│ frontend.ssigma_ui_main（主窗，SSigma 血统铁证）    │
│ frontend.modules / widgets / tools / utils         │
│ frontend.ui_function.model_train_function（训练页） │
│ label_listwidget_frame / setting_frame / ui_function│
├─ 标注层 ──────────────────────────────────────────┤
│ new_label.ui + new_label.ui_function.label_function │
│ new_label.utils.ai_segment（build_sam/modeling/     │
│   image_encoder/mask_decoder/prompt_encoder/        │
│   transformer/automatic_mask_generator = 完整 SAM） │
│ labelme（定制 fork，87 模块）+ S_Label 旧版标注器    │
├─ 引擎层 samsuncn.* ───────────────────────────────┤
│ samsuncn.ultralytics（160 模块，YOLOv8 定制 fork）  │
│ samsuncn.dl（968 模块）+ samsuncn.dl4ad（401，异常检测）│
│ samsuncn.mdl（43）+ samsuncn.utils（11）            │
│ mmcv/mmdet/mmseg/mmdeploy/timm/pytorch_lightning/   │
│ kornia/nncf(OpenVINO 压缩)/onnx → 部署链            │
├─ 加密层 frontend.utils.json_encrypt_helper ────────┤
│ save_encrypted_file / load_encrypted_file           │
│ （源码路径 E:\Project\gitProject\skolpha\...）       │
└────────────────────────────────────────────────────┘
```

## 4. 功能全图（三源交叉：chm 手册 + boxIcons + 训练模板，AC-002）

**官方手册口径（chm 160 页）— 8 大任务模块，每模块六步工作流**：

| # | 任务模块 (chm §) | 任务码 | 引擎 | 模板 | 预训练权重 |
|---|---|---|---|---|---|
| 1 | 实例分割-Pro (4.4.1) | pseg-ultra | mm 系 | 07_s_pseg_ultra_v1.0.py | pretrain_ultra-pseg.pth (241MB) |
| 2 | 实例分割 (4.4.2) | pseg | mm 系 | 01/02/03/04/05/06_s_pseg_*.py (normal/small/large×0.25) | pretrain_pseg.pth + resnet50_v1c |
| 3 | 目标检测 (4.4.3) | det | ultralytics | 01_s_det_normal_v1.0.yaml（=官方 yolov8.yaml）/02_seg_p2/03_slip2 | preptrain_det.pt + resnet50_ultra |
| 4 | 图像分类 (4.4.4) | cls | ultralytics | 01_s_cls_normal_v1.0.yaml | preptrain_cls.pt |
| 5 | 关键点 (4.4.5) | pose | ultralytics | 01_s_pose_normal_v1.0.yaml | preptrain_pose.pt |
| 6 | 语义分割 (4.4.6) | sseg | mm 系 | 01_s_sseg_normal / 02_s_sseg_ann_v1.0.py | pretrain_sseg.pth (174MB) |
| 7 | 异常检测 (4.4.7) | abdet | 自研(samsuncn.dl4ad) | 01_s_abdet_normal_v1.0.yaml | abdet_r50.pth + resnet18/v1c |
| 8 | 缺陷生成 (4.4.8) | sgan | StyleGAN(upfirdn2d) | 01_s_sgan_normal_v1.0.py | pretrain_sgan.pth + inception×2 (FID) |
| — | 超分（模板在、chm 未见独立节） | super | 🔎推断 mm 系 | 01_s_super_normal_v1.0.py | pretrain_super.pth |
| — | 实例分割(seg 泛化，2/3 号 det 变体) | seg | ultralytics | 02_s_seg_p2_v1.0.yaml | preptrain_seg.pt |

每模块六步：**项目管理 → 数据管理 → 模型训练 → 模型评估 → 模型发布 → 模型预测**（chm 各 §x.1–x.6 完整对应）。

**其他功能（四大主线外概览行）**：
- 4.1 软件安装 / 4.2 软件登录 / 4.3 主界面说明
- 4.5.0 切换界面颜色（daytime/night 双主题，configFile.style）
- 4.5.2 S_Tools 工具集：帮助文档、缺陷样品分类、裁剪数据集、标签替换、标签统计、照片尾缀修改、数据清洗、生成缺陷、标签删除
- 4.5.2.0 S_Label 旧版标注软件（assets/s_label，含 model/ 目录）
- 4.5.3 标注功能（new_label，AI 标注=SAM）
- 语言：ch_CN/en_US（assets/locale + configFile.selected_language）
- 训练技巧/常见问题/版本迭代信息（chm §2/§3/§0）
- createFlaw 缺陷样品合成（assets/createFlawconfigFile.json，指向用户压伤数据集）

**boxIcons 六功能盒映射**：dataManage(数据管理)/train(训练)/test(测试=评估)/predict(预测=推理)/export(发布导出)/programDataManage(工程数据管理) ↔ 六步工作流 UI 化〔🔎推断〕。

## 5. 加密体系与密钥（AC-004 ✅ 提前达成）

- 加密范围〔✅证实〕：根 `default.yaml`、`TrainConfigs/*.yaml|*.py`、工程文件 `.spro`（encrypted.spro 字符串在 json_encrypt_helper 邻域）。
- 密钥推导〔✅实证解密成功〕：`frontend/utils/json_encrypt_helper.py` 中 `_key = base64.urlsafe_b64encode(b"SAMSUN"*5 + b"CN")`（32 字节常量 `SAMSUNSAMSUNSAMSUNSAMSUNSAMSUNCN` @ exe 0x3d06e0a，`c` 型编译期常量，紧邻 `_key`/`urlsafe_b64encode` 符号）。
- 解密验证〔✅〕：default.yaml = Ultralytics 官方 default.yaml 原文（task/mode/epochs=100/batch=16/imgsz=640...）；det 模板 = 官方 yolov8.yaml；pseg 模板 = mmseg 风格 python config（my_samples_per_gpu/my_workers_per_gpu/my_endSplitData=0.8/my_data_expansion 等自研参数前缀 my_）。
- **复刻提示**：自家 AVA 若做配置加密勿照抄此模式——硬编码对称密钥可被常量挖掘直接恢复（本批即证）。

## 6. 四大主线初定位（波2 深挖锚点清单）

| 主线 | 已有锚点 | 波2 主攻模块 |
|---|---|---|
| 标注 | new_label.utils.ai_segment.*（SAM 全家）/ labelme / configs/parameter_setting_labelme_user_custom.yaml / 既往 2024-08-24 SAM 取证（矩形=SAM box prompt+∩合并） | new_label.ui_function.label_function 邻域 |
| 创建工程 | .spro 工程文件 + projects[] schema（projectName/projectID/taskType/savePath/dataInfo{dataPath,transferType:Split}/trainingParams{networkName,numEpochs,batchSize}/predictionParams{modelFile,threshold}/deploymentParams{endpoint,apiKey}）@0x3d06e46-0x3d07190；工程目录 `E:\SSIGMA\Projects\QP_PSEG_00003_1703234751\data\label.txt`（ID=任务码+序号+时间戳） | save_encrypted_file 调用方 |
| 训练 | model_train_function 21 函数全清单（randon_crop/flip/rotate/move_rotation/mean_and_std/samples_per_gpu 归一化/update_{sgan,sseg}_config_file/train_complete_clicked）；模板可解密全读 | frontend.ui_function.model_train_function 邻域 |
| 推理 | boxIcons.predict；deploymentParams{endpoint,apiKey}〔🔎推断支持 API 部署推理〕；mmdeploy/onnx/nncf 导出链 | frontend predict 相关 + samsuncn.mdl |

## 7. 波1 结论

- AC-001 ✅（2,559 模块候选，业务包 samsuncn/frontend/new_label/labelme/model_train_function 分层归类）
- AC-002 ✅（chm 160 标题 + boxIcons + 9 类模板三源交叉，8 大任务模块×六步 + 其他功能概览行）
- AC-004 ✅ 提前（密钥推导实证，全部密文可解）
- 修正认知：① UI=PyQt5（非 PySide6）；② TrainConfigs yaml/py 均为密文（明文假设修正）；③ languageFile.json 仅存语言状态，UI 文案在 exe 中文常量（chinese.txt 2,992 条待波2 用）
