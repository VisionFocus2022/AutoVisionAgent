# W56-0 五方消费方核查（FB-005）——AnnotationMode / TrainConfig 扩展安全网

> 日期: 2026-09-02 | 任务: tasks-skolpha-replication.md Task 1 | 用途: W56-A 枚举 +2 成员、W57-A TrainConfig +augmentation 段的影响面清单

## AnnotationMode（W56-A 扩展 CUT_LINE/OPERATION 影响面）

### ① 生产代码（16 文件）
- gui/pages/label/batch_prelabel.py
- gui/pages/label/page.py
- gui/pages/label/workers.py
- labeling/base.py
- labeling/canvas.py
- labeling/controller.py
- labeling/io_labelme.py
- labeling/modes/interactive.py
- labeling/modes/polygon.py
- labeling/modes/rectangle.py
- labeling/modes/region_sam.py
- labeling/modes/_base.py
- labeling/modes/__init__.py
- labeling/sam3_adapter.py
- labeling/sam_adapter.py
- labeling/__init__.py

### ② 单元测试（12 文件）
- tests/test_gui.py
- tests/test_gui_jobs_migration.py
- tests/test_gui_label_page.py
- tests/test_labeling.py
- tests/test_labeling_controller_deep.py
- tests/test_sam3_adapter.py
- tests/test_sam_adapter.py
- tests/test_sam_modes.py
- tests/test_sam_wiring.py
- tests/test_threaded_pages.py
- tests/test_w43_region_sam.py
- tests/test_w44_sam_candidates.py

### ③ UIA/e2e（0 文件直接引用）——tests/uia 无 AnnotationMode 引用；test_sam3_labeling.py 经 UI 文案驱动（按钮名新增不受影响，既有断言不数按钮数）
### ④ 脚本/工具（0 文件）——scripts/ benchmarks/ 无引用
### ⑤ 守卫测试：tests/test_dynamic_import_guard.py（五方一致性：modes 列表↔目录↔spec 集合断言，新增模块自动纳入）；tests/test_w24_scale_guards.py（页面≤800 行）

## TrainConfig（W57-A 扩展 augmentation 可选段影响面，本波仅审计）

### ① 生产代码（4 文件）
- gui/pages/train/page.py
- gui/pages/train/worker.py
- training/generic_trainer.py
- core/interfaces_supervised.py

### ② 单元测试（7 文件）——构造处全部按关键字段构造，新增带默认值字段零破坏（None=旧行为）
- tests/test_gui_train_page.py
- tests/test_m1_e2e.py
- tests/test_tasks_ui.py
- tests/test_trainer_generic.py
- tests/test_trainer_resume_edge.py
- tests/test_trainer_save_fail.py
- tests/test_trainer_tail.py

## 结论
- AnnotationMode 增量成员为非破坏性（枚举新增值；io_labelme 往返经 mode 自定义键自动支持）
- 需同步点：modes/__init__ 注册+桩枚举、page _MODES/_DRAW_MODES、canvas 渲染分支、io_labelme 映射、spec hiddenimports、i18n 键
- 风险点：test_sam_modes.test_manual_modes_still_work 将遍历新 manual_modes 成员（需工厂注册到位）；无 ==5 按钮数断言
