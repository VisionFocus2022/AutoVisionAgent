# GUI 线程契约（Threading Contract）

> **文档 ID**: M20 · 2026-10-05 二轮工程审查收口
> **适用范围**: gui/ 全部页面与 gui.core 后台任务设施
> **状态**: 生效（新代码必须遵守；存量代码按此文档逐步收敛）

---

## 1. 背景与动机

2026-10-05 两轮工程审查发现：跨线程交互高度依赖**未成文的隐式契约**
（GIL 原子性 + QueuedConnection 排队顺序 + 属性传递模式），同一模式
分布在 3+ 处且无统一文档。R4（单张结果覆盖丢失）、M13（批量 append
时序）、O7（SAM 状态跨线程写）三组问题共享同一根因。

本文档将这些隐式假设**显式化为契约**，并给出标准模式与禁用模式。

---

## 2. 线程模型总览

| 线程 | 创建者 | 生命周期 | 典型职责 |
|------|--------|---------|---------|
| **主线程（UI）** | Qt | 进程级 | 全部 QWidget 操作、信号槽、状态机迁移 |
| **jobs worker** | `gui.core.jobs.run_job` | 任务级（daemon） | 推理/导出/扫描等重活（不碰任何 QWidget） |
| **TrainWorker (QThread)** | train 页 | 训练会话级 | GenericTrainer.fit 驱动 |
| **缩略图池** | `QThreadPool(_thumb_pool)` | 页面级 | 缩略图加载 |

---

## 3. 核心契约

### 契约 C1：跨线程 UI 更新唯一通道 = `invoke_main`

worker 线程**不得直接触碰任何 QWidget / QPixmap / QModel**（offscreen
平台下部分调用静默成功，真窗口平台崩溃——不可依赖）。唯一例外：
`QThreadPool` 的 `QRunnable.run` 内**禁止**任何 UI 调用；必须经
`invoke_main(page, "slot_name", *args)` 派发回主线程。

**happens-before 依据**：`invoke_main` 底层是 `QMetaObject.invokeMethod`
（QueuedConnection）。Qt 文档保证：排队调用携带的参数在**主线程执行
槽之前**对所有观察者可见；且同一 worker 发出的多次 invoke 按发送顺序
在主线程执行。**此排序保证是本项目跨线程数据传递的时序基石。**

### 契约 C2：worker → 主线程数据传递的标准模式（按优先级）

| 优先级 | 模式 | 适用 | 例子 |
|--------|------|------|------|
| ① 推荐 | **信号载荷**：结果作为 Qt Signal 参数直接传 | 数据可被 Signal 携带（str/int/float/object） | `finished_sig(TrainArtifact)` |
| ② 允许 | **pending 属性 + invoke_main 通知**：worker 写 `self._pending_x`（带请求 ID），invoke_main 通知主线程槽读 | 载荷不适合做信号参数（如大 ndarray + 多字段） | predict 页 `_pending_single` |
|③ 禁止 | worker 直接调 UI 方法 / 直接改 UI 状态属性 | 一律 | — |

**模式②的强制规则**（R4 修复后确立）：
1. **必须带请求 ID**（单调递增 int），主线程槽校验 ID 一致才消费；
   过期结果丢弃并 `logger.warning` 留痕（不允许静默吞）。
2. **单写者**：同一 pending 属性同一时刻只允许一个 worker 写——入口
   处禁用触发按钮（防重入），必要时用请求 ID 使旧写失效。
3. **docstring 声明**：使用模式②的方法必须在 docstring 标注
   "契约 C2 模式②"（可 grep 审计）。

### 契约 C3：主线程 → worker 的控制信号

- 取消标志：`threading.Event`（jobs 注册表统一管理）或页面 bool 属性
  （如 `_batch_cancel`，**只允许主线程写、worker 读**，单向）。
- worker 轮询检查，不阻塞等待。UI **不得**在主线程 `wait()`/`join()`
  等 worker（R5 教训：`_stop_training` 曾 wait(5000) 冻结 UI 5 秒）。

### 契约 C4：状态机迁移只在主线程

页面级状态（如 SAM 的 IDLE/LOADING/READY）只允许主线程槽内迁移；
worker 只能 invoke_main 回报事实，由主线程决定状态变更（O7 教训：
worker 直接写 `self._sam_state` 使守卫与迁移出现乱序窗口）。

### 契约 C5：任务进行中的按钮态矩阵

任何后台任务启动时，除自身按钮外，**所有会与该任务竞争共享资源的
入口都必须禁用**，并在完成/失败/取消全部路径恢复：

| 任务 | 必须禁用 | 恢复路径 |
|------|---------|---------|
| 单张/批量推理 | btn_single、btn_batch、**btn_load_model**（R3：use-after-unload） | _single_done / _single_failed / _batch_done / _batch_failed |
| 训练 | btn_start + **表单配置组**（M17） | _on_finished / _on_failed |
| 数据集导出 | btn_export + **btn_goto_train**（M14） | _op_done / _op_failed |

新增后台任务时，对照本表补全按钮矩阵（审查检查项）。

---

## 4. 审查检查单（新 PR 必过）

- [ ] worker 线程内零 QWidget 调用（grep `invoke_main` 之外的模式）
- [ ] 跨线程数据传递符合 C2（信号载荷优先；pending 属性带请求 ID）
- [ ] 无主线程 wait/join worker（C3）
- [ ] 状态机迁移全在主线程槽（C4）
- [ ] 任务进行中按钮态矩阵完整，全部恢复路径覆盖（C5）
- [ ] 模式②使用处 docstring 有"契约 C2 模式②"标注

---

## 5. 存量收敛记录

| 日期 | 项 | 动作 |
|------|-----|------|
| 2026-10-05 | predict `_pending_single` | 升级模式② + 请求 ID（R4） |
| 2026-10-05 | predict `_load_model` 入口守卫 | active_jobs 检查（R3/C5） |
| 2026-10-05 | train `_stop_training` | 去 wait 阻塞（R5/C3） |
| 2026-10-05 | train 表单锁定 | _set_form_enabled（M17/C5） |
| 2026-10-05 | sam_session 状态迁移 | 待收敛至 C4（O7 遗留，P3 排期） |

> 本文档由工程审查驱动建立，随收敛进展更新"存量收敛记录"表。
