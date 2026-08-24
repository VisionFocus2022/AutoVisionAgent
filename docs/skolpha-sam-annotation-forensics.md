# SKolpha 3.3.2 SAM 标注机制逆向取证报告

> 版本: 1.0 | 日期: 2026-08-24 | 档位: 🟡 L2 研究波（静态三层取证：Nuitka 常量挖掘 + help.chm 反编译 + 配置资产；零运行态）
> 取证对象: `E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\skolpha.exe`（64.7MB，Nuitka 编译 Python/PyQt5/torch）
> 关联: prd-skolpha-sam-forensics.md；AVA SamSessionMixin（W4-T3/W27）为映射目标

## 1. 核心结论（一句话）

**矩形不是"裁剪图片再送 SAM"，而是作为 SAM 的 box prompt 与用户点击 point prompt 一同传给 `SamPredictor.predict`（`ai_predict(point, boxs, image)`），分割得到的掩码经 `findContours + approxPolyDP` 折点多边形化后转为标注；另有掩码级 `intersect_merge_mask`（与已有区域/选中矩形求交合并）作为后处理。**

## 2. 三候选机制裁决（PRD AC-003 三角验证）

| 候选机制 | 裁决 | 证据（≥2 源） |
|---|---|---|
| ① 裁剪图片→子图送 SAM | **证伪**（作为矩形机制） | `ai_predict` 局部变量无 crop/roi（@0x3d6e84c）；所有 crop 字符串属 `cut_img_tools`（数据集透视裁剪，另一功能）与 AMG 内部 crop_n_layers（官方 AMG 机制） |
| ② 矩形=SAM box prompt | **证实（主机制）** | ①`ai_predict` 局部变量 `point, boxs, image, input_box`（@0x3d6e84c-0x3d6e87a）②官方 predictor API 全套在列（set_image×59/point_coords×36/point_labels×27/box 语义见官方 segment_anything）③模式对 `rect_edit_mode`+`ai_edit_mode`（@0x3d62de3/0x3d62da9） |
| ③ 全图分割后掩码求交/裁剪 | **证实（辅助后处理）** | `intersect_merge_mask`/`paint_intersect_label`（@0x3d6e15d/0x3d6e122）+ `bitwise_and`×3/`bitwise_or`×3/`fillPoly`/`connectedComponents`；`mask_input`×30（迭代精修 logit 累积）佐证交互式多轮点击 |

## 3. 架构全景（模块树证据）

```
skolpha.exe（Nuitka）
├─ frontend/                # 主框架（PyQt5）
│  ├─ ui_function/predict_function.py   # 预测页：批量预测/自动标注（batchPredict_ 约定 ← AVA 同源）
│  ├─ utils/node.py                     # 顶点/画布元素（restricted_rect 顶点限域）
│  └─ utils/scene.py                    # GraphicScene（旧标注页场景）
├─ new_label/utils/label_me/            # ★ 新标注页（自研 Qt 图形视图栈）
│  ├─ Graphics_view.py                  # 模式机：interact/ai_edit/rect_edit/paint_brush/
│  │                                    #        key_edit/bias_ai_label/cut_line/polygon
│  ├─ graphics_scene.py                 # add_rect/set_rect_item/paint_rect/
│  │                                    # intersect_merge_mask/paint_intersect_label/
│  │                                    # init_ai_model/ai_predict/contours_to_edges
│  ├─ interact_label.py / interact_lable_item.py
│  │        # InteractLabelItem(Node)：HSV 色域掩码（lower/upper_blue、get_hsv_range）
│  │        # ——「交互标注」= 魔棒式颜色分割，非 SAM
│  └─ GraphicRect                        # 矩形图元（node_move_rect/get_four_vertexs/get_feature）
├─ labelme/                              # 内嵌 labelme
│  ├─ ai_segment/                        # ★ 官方 Segment Anything 整包（build_sam/predictor/
│  │                                     #   automatic_mask_generator/modeling.*，torch 版）
│  ├─ widgets/canvas.py                  # 原 labelme Canvas + SAM 扩展（start_sam/
│  │                                     #   automatic_annotation/paint_to_shape/erase_points/
│  │                                     #   find_max_region —— 笔刷式 SAM 精修，旧标注页用）
│  └─ samsuncn_labelme/utils/            # 配置管理 + cut_img_tools（透视裁剪）
├─ samsuncn/                             # 算法层（800 模块）
│  ├─ dl/predictor.py:SamSunPredictor    # 预测页 SAM 推理封装（thresh_iou_hide IOU 阈值过滤）
│  ├─ mmseg/mmdet/mmcv/ultralytics(YOLO) # MMLab 训练栈
│  └─ utils/samsuncryptographic.py       # Fernet 配置加密（default.yaml gAAAAAB 之源）
└─ TrainConfigs/ 01_s_*_v1.x.yaml        # 模型配方（pseg=实例分割-pro 七代演进，见 chm page_109）
```

## 4. 「矩形区域 SAM 分割」完整交互链（证据重组）

1. `GraphicsView.rect_edit_mode`：绘制矩形 → `GraphicScene.add_rect/set_rect_item`（`GraphicRect` 图元，可拖动 `node_move_rect`）。
2. `ai_edit_mode` + 点击 → `GraphicScene.ai_predict(point, boxs, image)`：**点击点=point prompt（point_coords/point_labels），矩形=box prompt（input_box/boxs）**，经 `labelme.ai_segment.predictor`（官方 SamPredictor：`set_image` 预编码全图 + `predict`；`mask_input` 支持多轮点击迭代精修）。
3. 掩码后处理：`findContours` → `approxPolyDP(epsilon)`（局部变量 `approx_contours/epsilon` 佐证）→ `contours_to_edges` 转为标注多边形节点。
4. 区域约束：`intersect_merge_mask`/`paint_intersect_label` 将新掩码与选中矩形/已有区域做**掩码级求交合并**（bitwise_and/or）——保证标注被约束在划定区域内。
5. 平行机制（非 SAM）：`interact_label` 模式 = HSV 色域魔棒（`get_hsv_range`/inRange 语义）；`paint_brush` 笔刷；`bias_ai_label` 偏位样品专用；`cut_line` 线切割。
6. 另两处 SAM 消费方：旧 Canvas 笔刷精修（`start_sam`/`paint_to_shape`/`erase_points`）；预测页自动标注 = `SamAutomaticMaskGenerator`（参数簇 points_per_side/pred_iou_thresh/box_nms_thresh/crop_n_layers @0x3d14246-0x3d1436e）+ IOU 阈值过滤 UI。

## 5. AVA 实现映射建议（三机制对比 + 推荐）

| 落地机制 | 行为一致性 | 实现代价 | 备注 |
|---|---|---|---|
| **box prompt（推荐）** | ★★★ 与原品同构：矩形引导 SAM 注意力，掩码仍按图像语义收缩，边缘可略越界后由求交约束 | 低：SamSessionMixin 增加 box 入参（segment_anything predict 原生支持 `box=np.array([x1,y1,x2,y2])`），与 point 并存 | 需新增掩码→多边形管线（cv2.findContours + approxPolyDP）——AVA 现无此环节，为主增量 |
| 裁剪送 SAM（crop-then-encode） | ★ 越界问题消失但语义不同（子图重编码），坐标需回映，行为与原品不符 | 中（需子图 set_image + 坐标变换） | 取证已证伪为原品机制 |
| 事后纯裁剪（clip） | ★★ 简单粗暴，矩形外掩码直接丢弃 | 最低 | 可作为 box prompt 的兜底开关（=原品 intersect_merge_mask 的语义） |

**推荐组合**：`box prompt 主机制 + 掩码∩选中矩形严格约束（对齐 intersect_merge_mask）+ approxPolyDP 折点转 Shape`。预估：SamSessionMixin 扩展 ~0.5 天 + 掩码→Shape 管线 ~0.5 天 + 页面 rect_edit 模式接入 ~1 天（AVA 已有 RECTANGLE 形状与 INTERACTIVE 模式基建，接入点现成）。

## 6. 附带发现（超出本问但有复刻价值）

- `bias_ai_label_mode`：偏位样品专用 AI 标注模式（用户 recent_open_dir 恰为「偏位样品」目录，印证实际产线用途）。
- 预测页自动标注 = SAM AMG + IOU 阈值过滤（`thresh_iou_hide`）——AVA 自动预标注（DET 逐框）外的另一条技术路线。
- PyQt5（非 PySide6）；`SamsunCryptographic`=Fernet 加密配置/许可；加密狗 SamsunLock 授权体系。
- labelme 原生 Canvas 被 SAM 笔刷扩展（paint_to_shape/erase_points）——「笔刷精修」可作为 AVA 后续演进项。

## 7. 验证范围与局限

- Nuitka 编译无完整反编译，机制结论基于常量/标识符/局部变量名证据链（五源交叉），**未执行指令级验证**（调用参数值不可见）；如需指令级确证可后续按 EV 方法论反汇编 `ai_predict` 函数体。
- CHM 手册为功能级佐证（版本史/模型族），无交互机制描述；中文关键词 grep 空（GBK/分词差异），SAM 命中页均为授权/FAQ。
- 未启动 exe（零运行态承诺兑现）；动态行为（如 mask_input 是否跨点击复用）未观测。
- chm 提取产物在 `%TEMP%/skolpha_chm/`（651 文件）。
