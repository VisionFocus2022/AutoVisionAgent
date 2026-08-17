# PRD — wave15-thread-convergence：P2-1/2/3 线程模型收敛 + P2-19/20 日志 + P2-21/22/26/27

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）+ AskUserQuestion 三项选择：
> P2-1=轻量收敛（run_job 统一入口+注册表）、P2-22=删除 DataManagerExt、P2-26=待命 CI 文件。

## 现状（本轮实测核实）

- P2-1：gui 内裸 `threading.Thread` ×10（data_manage×2/deploy/eval_/flaw_gen/label×3/predict×2）、`invoke_main` ×41、三套线程模型并存、thread_bridge（73 行）不封装生命周期。
- P2-2：shell.py:256-283 closeEvent 退出守卫——`getattr(widget,'_btn_batch')` 属性名失配（predict 实为 `btn_batch`）批量推理中退出无确认；10 处 daemon 线程仅 `_worker` 一处被感知；批量标注/推理 JSON 直写 truncate-then-write（batch_tools×3、predict×1），退出截断即损坏。
- P2-3：确认退出后不 stop/join TrainWorker(QThread)、不清两个缩略图 QThreadPool——Qt "QThread destroyed while running" 确定性崩溃路径。
- P2-19：gui 关键操作日志密度 2.11/千行，label/data_manage/train 等 8 页为 0。
- P2-20：serving 独立进程仅 console 日志，无文件 handler/轮转。
- P2-21：setuptools 70.2.0 处于 CVE-2024-6345 影响区间。
- P2-22：DataManagerExt 零生产调用方（仅包 __init__ 自引用）；data_manage 页 docstring 宣称对接不存在的 DataManager。
- P2-26/27：无 CI 且 git 无远程；QT_QPA_PLATFORM=offscreen 靠 28 个测试文件逐文件自设，无集中兜底。

## 目标（两阶段七簇，文件所有权互斥）

**阶段一（并行）**
- **J1**：新建 gui/core/jobs.py——run_job() 统一入口（启动 daemon Thread + 主动注册表登记 + 异常路由回调 + 协作 cancel Event 透传）+ active_jobs()/request_stop_all(timeout)；threading.Thread 按调用期属性解析（保 FakeThread 测试接缝）；单测覆盖注册/完成自摘除/异常路由/取消/并发。
- **L1**（P2-20）：serving serve 入口接 RotatingFileHandler（logs/serving.log，5MB×3 轮转，路径可注入），import 期零副作用；测试证明 handler 挂载与轮转配置。
- **M1**（P2-21/26/27）：setuptools 升级出 CVE 区间并同步 lock；新建 .github/workflows/ci.yml（windows-latest + lock 安装 + offscreen + pytest 含 92 门禁，注明"待命——当前无 git 远程"）；新建根 tests/conftest.py offscreen 集中兜底（仅无交互桌面会话时 setdefault，不误伤 UIA 真窗）。

**阶段二（并行，依赖 J1 落地后读实际 API）**
- **J2**：data_manage/eval_/flaw_gen 三页 4 处裸 Thread 迁移 run_job（回调/按钮/文案行为保持，FakeThread 类既有测试零改动全绿）+ 各页 2-3 条关键操作 logger.info（P2-19）+ data_manage docstring 如实化（P2-22 页侧）。
- **J3**：label/predict/deploy 三页 6 处裸 Thread 迁移 run_job + 关键操作日志 + predict 批量 JSON 写盘 temp+os.replace 原子化（P2-2）。
- **J4**：shell.closeEvent 重写——退出守卫改查 jobs 注册表（修属性名失配）+ 确认后 TrainWorker.stop() 有界等待 + 两 QThreadPool waitForDone(有界)；保留 W12 审计 flush 与 registry 清缓存行为。
- **A1**：labeling/batch_tools.py 三处写盘原子化（temp+os.replace，RED：replace 未调用即红 + 故障注入原文件完好）+ 删除 data_manager_ext.py 与其测试 + 包 __init__ 导出清理。

## FR / AC

- **FR-001** jobs 统一入口与注册表（J1）；**FR-002** serving 文件日志（L1）；**FR-003** setuptools/CI/offscreen 兜底（M1）；**FR-004** 六页迁移+操作日志（J2/J3）；**FR-005** 退出守卫+线程生命周期（J4）；**FR-006** 原子写盘+死代码删除（A1）；**FR-007** 对抗验证+门禁棘轮+终态交付。
- **AC-001** jobs 单测全绿且并发安全（注册/摘除/异常/取消各有断言）；**AC-002** serve 入口挂载轮转 handler（tmp 注入实测）、import 无副作用；**AC-003** setuptools 出 CVE 区间且 lock 同步、ci.yml 语法合法且步骤与实仓一致（注明不可本地真跑）、根 conftest 在无桌面时兜底 offscreen 而有桌面时不覆盖（两向测试）；**AC-004** 10 处裸 Thread 全部经 run_job（grep 守卫断言 gui 内 threading.Thread 直调=0，jobs.py 自身除外）、既有页面测试零改动全绿、关键操作日志经 caplog 断言；**AC-005** 活跃任务存在时退出必弹确认（含 predict 批量场景 RED 先行）、确认后线程被请求停止且有界等待、审计 flush 保留；**AC-006** 四处写盘均 temp+os.replace（机制断言+故障注入双证）、DataManagerExt 全仓零残余引用、包导入完好；**AC-007** 七簇验证全 accept 或闭环、门禁 rc=0 覆盖 ≥92、validator 0、提交+记忆。

## 风险

- 线程迁移行为漂移：FakeThread 接缝 + 790 门禁 + 验证员 diff 审查（回调/按钮/文案逐项对照）。
- closeEvent 改写不得引入 UI 卡死：所有等待有界（超时上限常量）。
- conftest 兜底与 UIA 真窗互斥：条件（无桌面才 setdefault）双向测试证明。
