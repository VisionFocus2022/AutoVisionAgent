# ADR 0003：SAM 推理异步化（请求-回投契约）

- 状态：已实施（W56 · v7 P1-3）
- 日期：2026-09-16
- 背景：v7 审查 P1-3——SAM 点击推理在 GUI 线程同步执行，SAM3 每击冻 UI 1.4-1.5s（W46 真机实测），AMG 全图更久；加载/预热早已在 worker（run_job + invoke_main），唯独推理留在 GUI 线程。

## 决策

SAM 类 labeler（INTERACTIVE / REGION_SAM / SAM_BRUSH / AUTO）的推理调用改为**请求-回投**两段式：

1. **请求**：labeler 在原推理点构造闭包 `fn`（捕获 adapter/image/点位），交 `channel.submit(fn, tag)`；受理后立即返回，GUI 线程不等结果。
2. **回投**：worker 完成后经「通道暂存 + invoke_main 原语唤起」回到主线程，页面做陈旧性校验后调 `labeler.deliver(tag, result)`，再 `controller.refresh_preview()` 重绘。

关键设计约束与取舍：

- **同步回退保留**：labeler 未注入通道（`_async_channel is None`）时走原同步路径——labeling/ 层单测与脚本消费面零变化（分层约束：labeling/ 不得 import gui/，通道对象由页面注入）。
- **忙时拒绝不回退**：通道存在但 busy（状态机非 idle）时 submit 返回 False，labeler 静默返回（页面已在 submit 内提示「SAM 处理中」）。**不得**回落同步推理——那会击穿 torch 前向串行约束（P2-5 状态机的存在理由）。
- **重对象按引用传递**：logits 张量 / Shape 列表不走 QVariant 载荷（thread_bridge 类型表不支持），经通道暂存属性 + 原语唤起（`_sam_predict_ready` 无参槽）传递——thread_bridge docstring 认可的页面暂存模式。
- **陈旧性双校验**：回投时校验 ①labeler 身份（模式切换会重建 labeler）②`_image` 引用（换图会失效/重注入）——任一不符即丢弃。这是 W55·P1-2（换图会话治理）在异步面的闭环：旧图推理结果不得落到新画布。
- **AUTO 哨兵扩展**：`run()` 返回值三态化——`-2` 受理中（结果经 deliver 回投）、`-1` 失败（W55·P2-4）、`0` 零检出/未就绪、`>0` 同步命中数。GUI 路径（on_press）不消费返回值。

## 后果

- 正面：点击/AMG 推理期间 UI 事件循环不冻结；连续点击被状态机串行化（后到点击得到「请稍候」提示）；推理异常仍走 W55 反馈通道（worker 内捕获 → 回投 error）。
- 代价：labeler 代码三分支（无通道/受理/忙）；预览在回投后才出现（点击 → 状态栏「推理中」→ 形状出现）。
- UIA 真窗测试影响：形状断言需容忍一跳事件循环延迟（套件本就以等待/轮询取态，预计无需改动；首次真窗跑批如遇假红，按「等状态栏终态再断言」修）。
- 深度取消（推理中途放弃 torch 前向）不在本 ADR 范围——torch 前向不可协作中断；「取消」语义 = 陈旧性丢弃（换图/换模式即弃结果）。
