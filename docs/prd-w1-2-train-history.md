# PRD-lite：W1-2 训练历史与模型资产页

- **版本**: v1.0（2026-10-06）
- **档位声明**: 🟡L2 ｜ 确定性：高（W63 向导交接/W59c request_page/审计落盘等既有模式复用）｜ 影响半径：中（新增页面+权限矩阵+训练完成钩子；不触数据/鉴权硬触发器）｜ 规模：中（新模块×2+4 文件改，+~400 行）｜ 可逆性：双向门
- **上游**: roadmap Wave1 W1-2；依赖 W1-1（artifact.metrics 含 P/R/mAP50/epochs_effective）✓ 已就绪
- **门禁**: 探索 ✅（用户指令"继续 W1-2"）｜ PRD ✅（S2 预裁决：roadmap DoD 锁定）｜ 收尾 ✅（2026-10-07：单测 12 绿；主门禁 1400 绿+ruff 0；UIA DoD 97s 全链——真 seg 训练完成→历史页新行→模型卡 defect/640→一键加载"模型已加载"→单张推理出分数）

## 1. 背景与目标

训练完成即"失忆"：产物散落 outputs/（det_final.pt/metrics.jsonl），用户
无处回看历次训练（轮数/P-R-mAP/数据集/类别），也无法从历史一键把模型
灌进推理页——W71 实测时只能手工找权重路径。Wave1 北极星"可信训练与
模型资产"要求训练产出成为**可管理的资产**。

**目标（DoD）**：训练完成→历史页出现该记录；模型卡含类别表/输入尺寸；
一键加载→推理页出推理结果。

## 2. FR

- **FR-1 历史存储**：`core/train_history.py` 纯模块——JSONL 追加 +
  新者优先读取（坏行容忍跳过），落 workspace 根（resolve_base_root，
  exe 持久）。记录字段：ts/task/real(真|模拟)/epochs_requested/
  epochs_completed/weights_path/data_yaml/backbone/imgsz/classes/
  best_metric/metrics{P,R,mAP50}。
- **FR-2 训练落账**：训练页 `_on_finished` 追加记录（best-effort，
  失败告警不挡完成流程）；real 标志由 `_make_trainer` 路径判定。
- **FR-3 历史页**：新 nav「训练历史」——QTableWidget 列表（时间/任务/
  轮数/P/R/mAP50/真实·模拟）+ 行内「模型卡」「加载推理」按钮；
  进入页面即刷新（showEvent 或 select 时）。
- **FR-4 模型卡**：对话框展示——任务/骨干/轮数（请求 vs 实际）/
  最佳指标/数据集路径/权重路径/**类别表（data.yaml names）**/**
  输入尺寸（imgsz）**/P/R/mAP50/时间。
- **FR-5 一键加载推理**：predict 页抽 `apply_external_model(path,
  task)`（复用加载链，无对话框；推理进行中拒载守卫保持）；历史页
  「加载推理」→信号→main 接线（加载+切推理页）。
- **FR-6 权限**：history 页 admin/engineer（ALL_PAGES）+ operator
  （只读+加载，与 predict 同级；不含训练动作）。

## 3. AC

- AC-1 存储：append→read 新者优先；坏行跳过不抛；workspace 定向。〔非 happy-path〕
- AC-2 落账：_on_finished 后 read_records 含新记录（real 与 simulated
  双形态各验一条）；写盘异常不挡完成回调。〔非 happy-path〕
- AC-3 页面：records 渲染行数/列文本正确；classes 缺失时模型卡显示
  "未知"。〔非 happy-path〕
- AC-4 模型卡：含类别表与输入尺寸字段（记录含 classes=["defect"],
  imgsz=640）。
- AC-5 加载缝：apply_external_model 设任务下拉+走加载链+状态
  「模型已加载」；推理进行中拒绝。
- AC-6 UIA（DoD）：真 seg 训练完成→历史页新行→模型卡（类别表+输入
  尺寸在屏）→一键加载→推理页「模型已加载」→单张推理出「分数」。
- AC-7 主门禁全绿+ruff 0+行数守卫（predict 731/800 内）。

## 4. 范围

新：core/train_history.py、gui/pages/train_history/{__init__,page}.py、
tests/test_w1_2_train_history.py、tests/uia/test_train_history_w1_2.py。
改：gui/pages/train/page.py（落账+real 标志）、gui/pages/predict/page.py
（抽加载缝）、gui/main.py（注册+接线）、gui/core/permissions.py（矩阵）、
gui/core/i18n.py（键）。
Out of scope：历史删除/筛选/对比、自动刷新（训练完成推送）、W1-4/W1-5。

## 5. 风险

| 项 | 评估 |
|---|---|
| 训练完成回调被落账拖慢/炸 | best-effort try/except + 告警（AC-2） |
| 权重路径随 cwd 漂移 | 记录绝对路径（artifact.weights_path 绝对化） |
| UIA 时长（真训练 100 轮） | 接受（wizard 同量级 329s 先例） |

## 实施纪要（2026-10-07）

- **设计变更 1（UIA 实证驱动）**：行内嵌操作按钮 → 选中行+工具栏操作——
  QTableWidget 单元格控件不入 UIA 可访问树（exe 探针 dump 证伪行内按钮，
  离屏 Qt 侧存在但 UIA 树不可见），工具栏按钮可达且更符合批量操作习惯。
- **缺陷修复 2（探针定位）**：①状态序——load_requested 同步执行加载，
  后发的"已请求加载"会覆盖"模型已加载"终态（py-spy 显示空闲+stderr 无
  异常 + python 模式复现 → 状态覆盖而非阻塞）；②showEvent 刷新——进入
  页面即重读（此前仅构造时读一次，训练完成后切页看到启动时快照）。
- 规模守卫连锁：build_window 102→拆 _make_home_stats_refresher；
  train/page.py 800/800 达标（_format_eta/_will_be_simulated 紧凑化）；
  页数钉 11→12（test_gui/test_m2_e2e）；w29 权限矩阵 +history。
- 磁盘事件：E 盘满（315G/0 可用）清除派生数据 3.4G
  （E:/学习项目/_auto_export=W66 排障导出副本 + build/ 缓存）后续跑。
