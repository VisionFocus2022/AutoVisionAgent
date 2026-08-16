# PRD — 第五波：supervision 标注优化（wave5-supervision）

> 依据：用户指定文章（roboflow/supervision 库介绍，mp.weixin.qq.com/s/JA6QqAG047IPFrBN46QWLw）
> 的方法落地到本项目"标注"两侧；用户经结构化提问确认"两者都做（推荐）"（2026-08-16）。
> 基线：W4 终态 341 passed / 0 failed / 1 skipped，门禁 69.02%。

## 背景（现状实证）

- predict 页 `_show_result`（gui/pages/predict/page.py）为文章吐槽的手写画法：QPainter
  红色死框 + 无底色文字，**分割掩码 / 关键点 / 语义图完全不可见**，无类别配色。
- 全仓无 LabelMe→YOLO/COCO 转换（grep 实证）：标注页存 LabelMe JSON，ultralytics
  训练需 YOLO txt——**标注成果无法喂进训练**（管线断链）。
- venv 原无 supervision；本波已装 0.30.0（MIT，核心 API BoxAnnotator/LabelAnnotator/
  MaskAnnotator 实测存在）。

## FR-001 sv.Detections 桥接 + 推理结果渲染升级

- 新模块 `inference/sv_bridge.py`（无 Qt 依赖，纯函数）：
  - `result_to_detections(result) -> sv.Detections`：boxes→xyxy、scores→confidence、
    labels→class_id（按类别名稳定排序映射）+ data["class_name"]；masks 形状与框数
    一致时挂载（ndim==2 语义图升维单实例）。
  - `render_result(image_bgr, result) -> ndarray`：BoxAnnotator（ColorLookup.CLASS
    类别配色）+ LabelAnnotator（类别+置信度）+ 掩码叠加（MaskAnnotator 或语义图
    半透明叠加）；关键点尽力而为（sv API 支持则画）。
- predict 页 `_show_result` 接线：渲染走 sv；sv 缺失时回退旧 QPainter 画法（真实
  旧行为降级 + 日志告警，非假数据）。
- 图像色彩序按 BGR（imread_unicode 契约，sv/cv2 原生）。

## FR-002 LabelMe→YOLO/COCO 训练集导出

- 新模块 `dataset/format_export.py`（纯函数）：
  - `labelme_dir_to_yolo(image_dir, annotation_dir, out_dir)`：rectangle→检测行
    （cls cx cy w h 归一化）、polygon→分割行（cls x1 y1 … 归一化）；产出
    labels/、images/ 软引用清单与 data.yaml（names/nc，类别名稳定排序）。
  - `labelme_dir_to_coco(image_dir, annotation_dir, out_json)`：标准 COCO
    images/annotations/categories（矩形 bbox xywh 绝对值、多边形 segmentation）。
  - 坏 JSON 跳过并计数，返回摘要（类别表/成功/跳过数）。
- 验证方式（文章方法的狗粮闭环）：导出产物由 `sv.DetectionDataset.from_yolo/
  from_coco` 回读，计数与类别一致。
- data_manage 页新增"导出训练集"（格式下拉 YOLO/COCO），worker 线程执行（W3 模式）。

## FR-003 环境与打包随迁

- requirements.txt 增 supervision；pip freeze 重锁；autovisionagent.spec
  hiddenimports 增 supervision（发版检查教训：动态/间接依赖显式列出）。

## 验收标准

- AC-001（FR-001）：sv_bridge 单测全绿——桥接字段映射、类别配色（两类→输出像素
  含不同色框）、掩码叠加改变掩码区像素、语义图路径、空结果不崩。
- AC-002（FR-002）：导出的 YOLO/COCO 产物可被 sv.DetectionDataset 回读且计数/
  类别与源一致；矩形行数值与手算归一化值一致；坏 JSON 计入 skipped。
- AC-003（FR-001/002）：predict 预览冒烟（offscreen pixmap 非空）；data_manage
  导出经 FakeThread 证明在 worker 线程执行；全量回归绿。
- AC-004（FR-003）：门禁全量 rc=0（fail-under=69 地板保持）；lock/spec 更新。
