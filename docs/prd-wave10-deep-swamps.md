# PRD — 第十波：非 gui 大洼地与 gui 尾巴填平 + 棘轮推进（wave10-deep-swamps）

> 依据：用户 2026-08-17 指令"实施下一波候选"。候选 = W9 终态明示的 gui 尾巴
> （shell 83%/tasks_ui 82%/predict 85%）+ 门禁分母内从未动过的非 gui 大洼地
> （exporter 12%/data_manager_ext 38%/super_cv2 36%/controller 62% 等，均为
> W8 摸底实测数字且本轮权威复测确认）。
> 基线：W9 终态 507 passed / 2 skipped，门禁 fail-under=82（实测 82.95%）。
> 执行方式：Workflow 并行扇出 5 个测试编写代理（各管一个簇，互不相交的
> 测试文件与生产模块），每输出一个对抗验证代理复核（假绿/越界改动/RED 证据）。

## FR-001 exporter 填平（12% → ≥80%）

- exporter/supervised_exporter.py（127 未覆盖，全分母最大单文件洼地）：
  export_onnx 真路径（torch.onnx.export + 微型 torch 模型）、量化分支、
  TRT 不可用错误路径、校验/元数据路径。依赖缺失（tensorrt/onnxruntime 等）
  的分支不得伪造覆盖——如实跳过并在验证报告注明。

## FR-002 引擎家族五文件填平

- super_cv2 36%/cls_torchvision 39%/_yolo_seg_base 39%/pose_yolo 57%/
  pseg_yolo 52%（合计约 125 未覆盖）：装载失败、懒加载、推理契约与
  后处理分支；重后端（ultralytics/torchvision 真模型）以注入替身驱动，
  真可用轻路径直测。

## FR-003 labeling/controller + data_manager_ext 填平

- labeling/controller.py 62%（48 未覆盖）：鼠标事件三分发（press/move/
  release）、模式切换 labeler 重建、坐标转换、commit/cancel 路径。
- industrial_vision_platform/data_manager_ext.py 38%（93 未覆盖）：
  数据管理扩展 CRUD/扫描/统计纯函数路径。

## FR-004 gui 尾巴收尾

- shell 83%（31）、tasks_ui 82%（6）、theme 92%（5）、thread_bridge 94%（1）：
  主壳状态栏/页面切换/主题挂接/语言联动、任务下拉未注册分支、主题回退、
  无参 invoke_main 分支。
- predict 85%（70）：openpyxl 已随本波装入 venv → 真 xlsx 分支可测且 W8
  的 skip 测试自然转绿；另补 _show_result 回退分支、_boxes_to_jsonable
  分支、模型加载设备回退、导出取消/空态等杂线。

## FR-005 棘轮升门 + 终验

- 组合覆盖实测 ≥ 82（旧地板不降），fail-under 升至新实测地板取整。
- 全量 rc=0；state 终态 + validate_workflow + 提交 + 记忆更新。

## 验收标准

- AC-001（FR-001）：exporter 测试全绿，覆盖 ≥80% 或逐分支说明不可测原因。
- AC-002（FR-002）：引擎家族测试全绿，五文件覆盖显著提升（≥80% 或注明）。
- AC-003（FR-003）：controller ≥90%、data_manager_ext ≥80%，测试全绿。
- AC-004（FR-004）：gui 尾巴测试全绿；openpyxl 装入后 predict 真 xlsx
  分支覆盖、W8 skip 消除；shell/tasks_ui/theme/thread_bridge 杂线覆盖。
- AC-005：每个编写代理的输出经对抗验证：无假绿、无越界文件改动、
  所报真 bug 有 RED 证据。
- AC-006（FR-005）：全量 rc=0，fail-under ≥82 且 = 新实测地板。
