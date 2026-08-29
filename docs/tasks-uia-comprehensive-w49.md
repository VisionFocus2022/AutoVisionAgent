# Tasks：UIA 全面化 + 日志铁证 + 自动修复（W49 · lite）

关联：[prd-uia-comprehensive-w49.md](prd-uia-comprehensive-w49.md)

| # | 任务 | 验证 | 状态 |
|---|------|------|------|
| T1 | log_evidence.py + 6 纯函数单测（打点隔离/尾部/ERROR 提取/轮询/审计解析/双模式） | 6/6 绿 + 主门禁 1203 | ✅ |
| T2 | 四用例 exe 模式 **4/4 全绿**；operator 用例 4 轮证据驱动收敛（见 learning EXP-W49-2/3） | run5 rc=0 | ✅ |
| T3 | conftest 会话级预检（<6GB 整组 skip） | 编译+收集验证（阈值路径逻辑同 W48 实测场景） | ✅ |
| T4 | 收官验证 | **全量 UIA 19/19 rc=0（8:59）+ 主门禁 1203/5/rc=0** + 文档/learning 已沉淀 | ✅ |
