---
trigger: model_decision
description: 分层动线、数据访问与配置约束。新增/修改 GUI 页面、标注模式、引擎、配置读写时必须遵守
---

# R03 分层、数据与配置约束

> 覆盖域：服务分层（域3）+ 数据访问（域4）+ 配置与开关（域5）

## 1. 分层动线（L0/L1）

1. **[L0] 主动线**：`gui/pages（页面/壳）→ 领域包（labeling/training/inference/exporter/evaluation）→ core（异常/配置/IO/审计）`；`serving`（gRPC+共享内存+.NET）独立对外层，只经 `serving/proto` 契约消费
2. **[L1] 领域逻辑不进 gui**：页面文件只做编排与视图绑定；重复领域逻辑下沉领域包（先例：`gui/pages/label/page.py → labeling/controller.py#AnnotationController → labeling/modes.make_labeler`）
3. **[L1] 页面规模守卫**：`page.py` ≤800 行；触发即抽取 worker/runner/Mixin（W39/W44 既定动作，不是意外）——新页面立项时预判落点可免波波撞线
4. **[L1] 契约缝优先**：给既有系统加能力先找注入缝（`set_detector`/`set_adapter`/`attach_interactive`）——新能力=新增 provider 而非改管线；同时核白名单（`attach_interactive` 漏 SAM_BRUSH 曾致 GUI 笔刷死路，W46 实证）

## 2. 数据访问（L1）

1. **[L1] 无 ORM/DB 边界**：持久化全文件态，禁止引入 sqlite/sqlalchemy 而不改本规则——LabelMe JSON 走 `labeling/io_labelme.py`（唯一读写口）；检测历史/审计走 core 单例（`detection_history.get_history()` / `audit_logger.get_audit_logger()`，JSONL，线程安全）
2. **[L1] 用户设置单一访问器**：可变配置只经 `configs/user_settings.json` + `gui/core/settings_io.py`；禁止页面绕过访问器直读写 JSON
3. **[L1] 原子写**：配置/JSONL 落盘用临时文件+替换（`tests/test_batch_tools_atomic.py` 先例），防中断截断

## 3. 配置与开关（L0/L1）

1. **[L0] core/config.py 保持最小面**：只存静态默认值（logging+inference 两节）；禁止复活 ConfigManager/多节 YAML 加载器（W13 审查删除收敛，生产消费仅两处实证）
2. **[L1] 环境变量 AVA_ 前缀**：新增环境变量沿用 `AVA_` 命名（现有 15 个：AVA_LOG_DIR / AVA_SAM* / AVA_UIA_*）；`configs/{users.json,license.key,user_settings.json}` 已 gitignore，禁止入库
3. **[L1] 开关默认保守**：新能力开关默认关/显式 env 开启；翻进程级全局态（静态开关）时同步审视同程序集测试并行面

## 4. 自检清单

- [ ] 新能力走契约缝注入；领域逻辑未落 gui
- [ ] page.py 未破 800 行；破线即抽取
- [ ] 配置经 settings_io；环境变量 AVA_ 前缀；core/config.py 未膨胀
