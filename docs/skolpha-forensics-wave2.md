# SKolpha 3.3.2 全功能取证 — 波2 四大主线函数级深挖报告

> 日期: 2026-09-02 | 批次: skolpha-full-forensics 波2（FR-002/003，AC-003/005） | 关联: docs/skolpha-forensics-wave1.md
> 锚点格式：`模块.函数 @ exe偏移`（偏移=%TEMP%/skolpha-forensics/strings.txt 可复核）；三态标注同波1。

## 1. 标注主线（new_label + labelme fork + SAM）

**模块图**：`new_label.ui`（画布）→ `new_label.ui_function.label_function`（交互逻辑 21 方法）→ `new_label.utils.ai_segment.*`（SAM 推理）；旁路 `labelme` fork（87 模块，含 `labelme.project_manager`/`labelme.ai_segment.predictor`）与 S_Label 旧版标注器。

**函数级锚点**（label_function.py @0x3d521b0，方法簇 @0x3d51900-0x3d52200）：
| 函数 | 偏移 | 语义 |
|---|---|---|
| label_function.add_items / get_item_all_data | 0x3d51ca3/0x3d51910 | 添加/读取标注项（image_path 参数） |
| label_function.tabel_view_defect_feature | 0x3d51b98 | 缺陷特征表：[defect_name, width, height, area]（0x3d51bdf docstring） |
| label_function.save_items / set_image / show_min_image | 0x3d51c38/0x3d51c5b/0x3d51c66 | 保存/换图/缩略图 |
| label_function.item_move(key_flag: A or D) | 0x3d51dd9 | 键盘微移选中项 |
| label_function.get_cur_key(1,2,4..9) / set_cur_row | 0x3d51e40/0x3d51ea6 | 数字键快速切换标签 + 行联动 |
| label_function.delete_selected_items / remove_item | 0x3d52130/0x3d51932 | 删除 |

**7 种图形项形态**〔✅ @0x3d52001-0x3d5205b〕：`polygon / rectangle / point / AI_label / bias_ai_label / operation_label / cut_line_label`——AI_label 与 bias_ai_label 为 SAM 自动/半自动标注形态。

**SAM 栈**〔✅〕：`new_label.utils.ai_segment.{build_sam, modeling.{common,image_encoder,mask_decoder,prompt_encoder,sam,transformer}, automatic_mask_generator, predictor}` = segment_anything 官方代码全量内嵌。既往取证（2026-08-24）：矩形框定 → SAM **box prompt（非裁剪）** → 掩码 ∩ 矩形合并后处理。

**流程重建（伪代码）**：
```python
def annotate(image):                      # new_label.ui
    label_function.set_image(image)
    mode = pick(polygon, rectangle, point, AI_label, bias_ai_label, operation_label, cut_line_label)
    if mode in (AI_label, bias_ai_label): # SAM 辅助
        predictor = ai_segment.predictor(build_sam(weights))
        masks = predictor(box=drawn_rect)          # box prompt
        shape = intersect_merge(masks, rect)       # 掩码∩矩形
        label_function.add_items(shape)
    label_function.tabel_view_defect_feature([defect_name, w, h, area])
    label_function.save_items()            # → labelme JSON（configs/parameter_setting_labelme_user_custom.yaml）
```

## 2. 创建工程主线（.spro 加密工程）

**函数级锚点**（frontend/utils/json_encrypt_helper.py @0x3d06d10）：
| 函数/常量 | 偏移 | 语义 |
|---|---|---|
| json_encrypt_helper.save_encrypted_file / load_encrypted_file | 0x3d06dc8/0x3d06ddd | 工程文件读写（.spro @0x3d07196） |
| json_encrypt_helper.encrypt / decrypt / encrypt_data / decrypt_data | 0x3d06c80-0x3d06ce9 | Fernet 封装 |
| 常量 `SAMSUN×5+CN`（32B）+ `_key` | 0x3d06e0a/0x3d06e2c | urlsafe_b64encode → Fernet key |

**工程 schema**〔✅ @0x3d06e46-0x3d07190，官方示例明文〕：
```python
projects: [ { projectName: "Project A", projectID: "A001", taskType: ...,
  savePath: "/path/to/save/A",
  dataInfo: { dataPath, transferType: "Split",
              trainingParams: {networkName, numEpochs, batchSize},
              predictionParams: {modelFile, threshold},
              deploymentParams: {endpoint: "http://example.com/api", apiKey} } } ]
```
**工程目录约定**〔✅〕：`E:\SSIGMA\Projects\QP_PSEG_00003_1703234751\data\label.txt` → `E:\SSIGMA\Projects\{任务码}_{5位序号}_{unix时间戳}\data\label.txt`；transferType 取值 Rect/Polygon（标注形态联动）。

**流程重建**：新建工程（UI 表单）→ 组装 projects[] → `save_encrypted_file(json.dumps(data), path+".spro")` → 打开工程 = `load_encrypted_file` → decrypt → 回填六步工作流各页。

## 3. 训练主线（双引擎 + 子进程）

**函数级锚点**（frontend/ui_function/model_train_function.py @0x3cfab41，21 函数全列 @模块表）：
| 函数 | 语义 |
|---|---|
| randon_crop / randon_flip / randon_rotate / random_move_rotation_edit_normalization | 4 种数据增强（拼写 randon 为原品笔误〔✅〕） |
| mean_and_std_normalization | 均值方差归一化 |
| samples_per_gpu_and_workes_per_gpu_normalization | mmcv 术语 batch/worker 换算 |
| update_sgan_config_file / update_sseg_config_file | 按 UI 参数改写解密后的模板再加密落盘〔🔎〕 |
| train_complete_clicked / train_scal_lineedit_edit_finish / update_all_widgets_data / init_event / other_setting / switch_style_change | UI 事件 |
| is_decimal / is_validate / move / delete_config_file / get_max_pth_index | 工具（get_max_pth_index=权重序号管理） |

**执行模型**〔✅ @0x3c1a6af-0x3c3163e freeze_support/set_start_method/Popen/multiprocessing〕：训练在 **multiprocessing 子进程**运行（chm 4.1.2「启动训练软件」= 训练窗口独立）。

**引擎路由**〔✅ 训练源文件路径〕：
- det/cls/pose/seg → `samsuncn.ultralytics.yolo.v8.{detect,classify,pose,segment}.train`（fork，@0x40aaab5-0x40b2abc）
- pseg/sseg → `samsuncn.dl.mmseg.apis.train`（@0x3edd754；自研注意力模块 se_layer/self_attention_block/up_conv_block @0x3ace888-b00）
- sgan → `samsuncn.dl.mmgen.apis.train`（@0x3e38740；stylegan3/lpips 源码引用 @0x3e4867e/0x3e781f2）
- abdet → `samsuncn.dl4ad.dlad.anomalib`（**Intel Anomalib 全库内嵌** @0x3acf6d4-0x3ad01e8：btech/kolektor/folder 数据集模块）
- 统一五件套：`samsuncn.dl.{samsun_dataset, samsun_engine, samsun_trainer, samsun_validator, samsun_export}` @0x3acf2c6-0x3acf486

**流程重建**：训练页参数 → `mean_and_std/samples_per_gpu 归一化` → 解密模板 → `update_*_config_file`（my_* 参数 30+：img_scale/mean/std/split=0.8/data_expansion/max_rotate/translate/flip...）→ 重新加密落盘 → `multiprocessing.Process(target=引擎路由)` → 子进程 `samsun_trainer`/`ultralytics train` → `get_max_pth_index` 产物管理 → `train_complete_clicked` 回调 UI。

## 4. 推理主线（三路推理器 + 导出部署）

**函数级锚点**（frontend/ui/predictUi + frontend/ui_function/predict_function @0x3ae6480；UI 方法簇 @0x3cd3692-0x3cf06d5）：
| 符号 | 偏移 | 语义 |
|---|---|---|
| PredictFunction / predictWidget / btn_predict | 0x3cd3692/0x3cd36a3/0x3cd629e | 预测页类/控件 |
| batchPredictThread / batchPredictOnlyOne | 0x3cf05b0/0x3cf0503 | 批量推理线程（QThread） |
| predictWhenToComplete | 0x3ced22c | 完成回调 |
| Predict.json_file | 0x3ce4280 | 预测结果 JSON 落盘 |

**三路推理器**〔✅〕：`samsuncn.dl.predictor`（统一门面 @0x3acf23e）→ ① `samsuncn.ultralytics.yolo.engine.predictor` + v8 四任务 predict ② mm 系模型 ③ `ai_segment.predictor`（SAM 辅助标注共用）。
**导出/部署链**〔✅〕：`samsuncn.dl.samsun_export` + mmdeploy + onnx + nncf（OpenVINO 量化压缩）→ 本地或 API（deploymentParams.endpoint/apiKey〔🔎 API 部署形态〕）。

**流程重建**：
```python
class PredictFunction(QWidget):            # frontend.ui_function.predict_function
    def predict(self):                     # 单图
        model = samsuncn.dl.predictor(load(.spro.predictionParams.modelFile))
        for img in batch:                  # batchPredictThread 后台
            result = model(img, threshold=predictionParams.threshold)
            Predict.json_file(result)      # 结果落盘
        predictWhenToComplete()            # UI 回调
```

## 5. AC 核验

- AC-003 ✅：四主线各含模块图+方法/函数清单+伪代码，锚点数：标注 10+ / 工程 6 / 训练 21+8 / 推理 8+ —— 全部 ≥5 且带 exe 偏移。
- AC-005 ✅：全文三态标注，证实论断均带偏移锚。
- AC-004 ✅（波1 已达）。
- AC-006 ⚠️ 部分：静态交叉核对 2 处完成（①密钥推导对 3 个密文文件解密一致；②chm 六步工作流 ↔ predictUi/model_train_function/项目管理模块面对齐）。**实机动态观察未执行**（GUI 程序需人工操作）——按 PRD FR-004 约定可由用户手测补充，收尾门禁披露裁决。

## 6. 对 AVA 复刻的映射建议（顺带产出）

- 工程生命周期：.spro 加密工程 + `{任务码}_{序号}_{时间戳}` 目录约定 ↔ AVA 已有 configs/ 体系；加密不必须，但**工程 schema 五段（savePath/dataInfo/training/prediction/deployment）是成熟分栏**。
- 标注：7 形态中 operation_label/cut_line_label（操作标注/切割线）是 AVA 未覆盖的工业形态候选。
- 训练：multiprocessing 子进程 + 模板参数化（解密-改写-加密）模式可借鉴为「训练配置生成器」。
- 推理：batchPredictThread + 结果 JSON 落盘 ↔ AVA predict 页同构，可对照补批量线程与完成回调语义。
