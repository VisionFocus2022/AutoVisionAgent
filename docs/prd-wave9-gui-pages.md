# PRD — 第九波：label/main/data_manage/train/project 页覆盖填洼 + 棘轮推进（wave9-gui-pages）

> 依据：用户 2026-08-17 指令"实施下一波候选"（pytest.ini W8 注释所列候选：
> label 页 55% 最大绝对洼地、gui/main 48%、data_manage/train/project 65-66%）。
> 基线：W8 终态 440 passed / 2 skipped，门禁 fail-under=76（实测 76.02%，分母含 gui）。

## FR-001 label 页补测（55% → ≥88%）

- 文件夹批量加载（递归扫描、>500 上限+分页提示、空目录警告、坏图警告）、
  单张打开/取消、prev/next 边界与按钮可用性。
- 模式切换（五模式按钮态、dragMode 绘制/平移切换、SAM 未选权重诚实警告）、
  标签应用、撤销/重做按钮接线、删除选中、复制/粘贴（含偏移、空剪贴板）。
- 保存：正常落盘 LabelMe JSON、空标注提示、IO 失败显式报错、保存后
  自动切下一张（QTimer 真实触发）。
- `run_ai_prelabel` 纯函数：DET 引擎路径、零样本 dispatcher 回退路径、
  坏图返回 []；worker 包装 + `_prelabel_done` 落形状。
- `_ZoomableView.set_draw_mode`；`_on_thumbnail_loaded`；`retranslate`。

## FR-002 data_manage 页补测（65% → ≥90%）

- set_project_dir 布局定位（images/annotations 存在与否）、_select_dir
  兄弟 annotations 探测、_refresh（统计标签、>200 张分页提示、无效目录）。
- worker 基础设施 `_run_worker`：成功恢复按钮+刷新+完成标题、失败显式报错。
- 划分三闸门（无目录/比例≠1/无图像）+ 确认框 No/Yes、导入图像、
  标注统计（有数据/空数据）、替换/删除标签（含取消）、翻转、切割
  （含格式错误）、YOLO/COCO 导出（真实 format_export 落盘）。

## FR-003 train 页 + worker 补测（65%/62% → ≥90%）

- 预设应用（四预设字段）、`_build_config` 全字段、旧训练运行中拒绝重启、
  训练器构建失败显式报错、进度/完成/失败三回调（图表+进度条+日志）。
- `_make_trainer` 真实分支：引擎有 train_epoch → EngineTrainStrategy、
  无 train_epoch/未注册 → 模拟策略+显式警告。
- `EngineTrainStrategy`：dict/float 返回、save 委托、get_optimizer
  三分支（引擎直供/SGD 构建/None）。
- `TrainWorker`：fit 直调（进度/产物信号）、fit 异常→failed、stop 置位。

## FR-004 project/home/settings/main 杂项补测

- project：创建（目录+recent 落账）→ 列表(★) → 打开（project_opened
  信号）→ 删除（确认 No 保留/Yes 删除+recent 清理）；空名/未选提示；
  存储根浏览切换。
- home：update_stats 卡片、refresh_recent（空态/有数据）、refresh_history
  （零记录/有统计/异常回退）、快捷按钮 navigate、双击最近项导航。
- settings：_load_settings 全键恢复（theme/language/device/precision/
  workspace/cache）+ 坏 JSON 容错、路径选择器、_save 全字段持久化。
- gui/main：`build_window` 离屏全量组装（11 页注册/状态栏联动/导航/
  项目打开联动）、`setup_logging`（文件落盘+清理）、`_load_user_settings`。
- thumbnail_loader：QImage 线程安全化（见 FR-005）后的成功/失败信号。

## FR-005 修复：ThumbnailTask 工作线程使用 QPixmap（线程不安全）

- 现状：`run()` 在 QThreadPool 工作线程构造 QPixmap——Qt 契约 QPixmap
  仅限主线程（QImage 才可跨线程）。属 P1-3"主线程重活"家族的镜像问题：
  重活进了线程却携带非线程安全类。
- 修复：run() 改 QImage（构造+缩放线程安全），信号改 `Signal(str, QImage)`；
  label/data_manage 两页 `_on_thumbnail_loaded` 主线程 `QPixmap.fromImage`
  转 QIcon。测试锚定：真图→loaded(QImage)、坏图→failed。

## FR-006 棘轮升门 + 终验

- 组合覆盖实测 ≥ 76（旧地板不降），fail-under 升至新实测地板取整。
- 全量 rc=0；state 终态 + validate_workflow + 提交 + 记忆更新。

## 验收标准

- AC-001（FR-001）：label 页测试全绿，覆盖 ≥88%。
- AC-002（FR-002）：data_manage 页测试全绿，覆盖 ≥90%。
- AC-003（FR-003）：train 页+worker 测试全绿，覆盖 ≥90%。
- AC-004（FR-004）：project/home/settings/main/thumbnail 测试全绿。
- AC-005（FR-005）：QImage 化后双页缩略图回调测试全绿， QPixmap 不再
  出现在工作线程代码路径。
- AC-006（FR-006）：全量 rc=0，fail-under ≥76 且 = 新实测地板。
