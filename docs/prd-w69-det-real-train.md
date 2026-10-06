# PRD-Lite：W69 检测任务真训练通道 + 任务-数据格式自动对齐

- 版本：v1.0（2026-09-28）
- 档位：🟡L2（探索门禁出示未响应→S1 按用户指令完整修复，记偏差）
- 用户原话：「训练的太快了，不真实，还是参数不对」+ 截图（检测任务 100 轮
  秒完、教科书级光滑曲线）

## 1. 背景与目标

取证：截图曲线为模拟特征（无噪声单调衰减）；`DetYoloEngine` 无
`train_epoch`——W58 只给分割建了真通道，**检测任务必落「引擎不支持逐轮
训练」模拟回退**。用户数据=多边形（分割格式），任务框默认停在检测——
双重错配。且数据集字段已显示 W65 自动导出生效（`E:\学习项目\_auto_export`）。

真实任务：无论选什么任务，点开始训练都应该是真训练。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 det 真训练通道 | DetYoloEngine 继承 ultralytics 训练基座（train_epoch/save）；det 骨干解析不带 -seg 后缀 | `test_det_engine_has_train_epoch` ✅ |
| FR-2 det 权重离线兜底 | det 裸名无本地权重 → 回退随包 yolo26n.pt（ultralytics 8.4.81 离线加载实证 task=detect）+ 日志告知 | `test_resolve_backbone_det_falls_back_bundled_yolo26n` ✅ |
| FR-3 seg 通道不回归 | `_resolve_backbone(seg=True)` 默认行为不变 | `test_resolve_backbone_seg_default_unchanged` ✅ |
| FR-4 端到端真训练 | det 引擎 2 图矩形数据集 1 epoch cpu → 真实权重产物 >100KB | `test_det_real_train_channel_smoke`（e2e）✅ |
| FR-5 任务自动识别 | 数据集回填读标签格式（>5 列=分割，5 列=检测）自动设任务+状态告知 | `test_apply_external_dataset_autosets_seg/det` ✅ |
| FR-6 启动守卫 | 任务与数据格式不符 → 自动纠正+警告（复刻用户场景 det+seg 数据） | `test_correct_task_for_dataset/noop_when_match` ✅ |

## 3. 范围与实现

- `models/supervised/engines/_yolo_seg_base.py`：`_resolve_backbone(name,
  seg=True)` 任务感知（det 侧 yolo26n 兜底+日志）；train_epoch 按
  `self.task is SEG` 传参；模块级 logger。
- `models/supervised/engines/det_yolo.py`：`DetYoloEngine(_YoloSegBase)`
  （继承 train_epoch/save，保留自有 det load/infer）。
- `gui/pages/train/page.py`：`_detect_label_format`（YOLO labels/ 首行
  token 数）、`_set_task_combo`、`_correct_task_for_dataset`（守卫）；
  `_echo_dataset_stats` 漏斗（浏览+向导双路）接自动识别；`_start_training`
  接守卫；i18n +2 键。
- 测试：`tests/test_w69_det_real_train.py` 8 用例（含 1 个 e2e 真训练冒烟）。

**Out of Scope**：det 其余骨干（yolov8n.pt 等）离线捆绑（yolov8n.pt 下载
悬挂——网络不稳；yolo26n 兜底已覆盖默认路径）；逐轮真进度（W58 适配器
一次性口径不变，见其 docstring）。

## 4. 门禁记录

- 门禁 1（探索）：出示未响应 → S1 按「检查修复优化」指令实施推荐三件套。
- 门禁 2（PRD）：并入门禁 1。
- 门禁 3（收尾）：主门禁 1277 绿（W58 seg 通道零回归）+ ruff 0；**exe 重
  打包挂后台等用户关软件（watch-build-verify 链）**。

## 5. AC 核验回填

| AC | 结果 |
|---|---|
| W69 定向 8 用例 | ✅（7 单测 0.33s + 1 e2e 冒烟真训练通过） |
| 主门禁（首轮） | ❌ ruff I001×3/F401×2——--fix 后复跑 |
| 主门禁（复跑） | ✅ 1277 passed + 6 skipped / ruff 0 |
