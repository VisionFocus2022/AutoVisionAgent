# PRD — wave13-config-resume-audit：P1-2 删除收敛 + trainer resume 修复 + 审计用户归属

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）：「继续实施剩余未做的 W11 P1，同时修复trainer resume
> 边界 NameError（既有潜在 bug），需要我决策的列出选项」+ AskUserQuestion 选择「删除收敛（推荐）」。

## 背景（v2 审查 P1-2/P1-4 残留 + W12 记录）

- **P1-2**：core/config.py 545 行双体系脱节——11 节中 9 节零引用、ConfigManager 全套加载器生产调用者 0、
  configs/default.yaml 永不加载；用户实际配置走 user_settings.json，但设置页写的 device 不回灌
  （predict 恒读 dataclass 默认 "cuda"）——设置页选 CPU 静默失效。附带死配置：ServerConfig host="0.0.0.0"、
  security 节 enable_rate_limiting 零消费（安全审查误判"有限流"）。用户已选定方向：**删除收敛**。
- **W12 记录既有 bug**：trainer resume 得到 start_epoch > cfg.epochs 时 for 循环不执行，
  `artifact.epochs_completed` 引用未定义变量 `epoch` → NameError。
- **P1-4 残留（用户归属）**：audit 调用不传 user（deploy/predict，默认恒 "system"），登录事件全程无审计；
  全仓无任何登录会话/当前用户持有者。

## 功能需求（FR）

- **FR-001 config 删除收敛**：config.py 仅保留生产真实消费面（logging 节、inference 节、get_config），
  删除 9 个零引用节 + ConfigManager 全套加载器 + load_config + configs/default.yaml；ServerConfig 整节删除
  （serving 侧自有 127.0.0.1 默认）。目标 ≤200 行。
- **FR-002 device 回灌打通**：设置页写入 user_settings.json 的 device 成为 predict 设备解析的真源
  （读不到时保持现有回退链：默认 cuda + torch.cuda.is_available() 兜底）；设置页选 CPU 对 predict 生效。
  读写收敛到单一访问器（沿用 user_settings.json 既有格式）。
- **FR-003 trainer resume 边界**：start_epoch ≥ cfg.epochs 时 fit 优雅完成（无 NameError），
  epochs_completed 语义正确（= start_epoch），终态保存与 artifact 构建照常。
- **FR-004 审计用户归属**：建立最小当前用户持有者（登录成功/离线模式时写入；默认 "system"）；
  deploy 与 predict 的审计调用传入当前用户；登录成功与进入离线模式两条事件落审计。
- **FR-005 验证与交付**：三簇对抗验证（RED 文件级 stash 复现 + 假绿猎杀 + 越界检查）；门禁全量 rc=0
  棘轮不降（若过 90 则升门）；pytest.ini 尾巴注释刷新；state complete + validator 0 + 提交 + 记忆。

## 验收标准（AC）

- **AC-001**（FR-001）：config.py ≤200 行且无 ConfigManager/load_config/default.yaml 残留；
  gui/main.py:41 与 predict 的既有消费行为不变；删除面在测试中同步收编（test_config.py 重写，
  被删 API 的用例随删并在 state 记录）。
- **AC-002**（FR-002）：RED 先行证明现状 device 不回灌；修复后设置页写 cpu → predict 设备解析得 cpu；
  无 user_settings 时回退链行为与旧版一致（离屏测试覆盖四分支语义保持）。
- **AC-003**（FR-003）：RED 先行（现状 NameError 实证）；修复后 start_epoch > epochs 优雅完成，
  epochs_completed == start_epoch，正常路径回归全绿。
- **AC-004**（FR-004）：RED 先行；登录后 deploy/predict 审计记录 user=登录名；离线模式记 "offline"
  （或实现等价语义并在测试断言）；登录成功与离线进入事件各有一条审计；未登录默认 "system" 不变。
- **AC-005**（FR-005）：验证员全 accept 或 needs_fix 闭环；`.venv/Scripts/python.exe -m pytest` rc=0
  且覆盖率 ≥89（过 90 则棘轮升 90）；validator 返回 0。

## 范围与非目标

- 非目标：exe 重打包（W13 生产的 gui 改动留给发版检查单重建，exe 当前为 W12 版）；P2 级残留
  （暗色内联样式、deploy:163 线程读、eval_ 示例矩阵、审计哈希链）；generative_metrics 真模型尾巴。
- 风险：config 删除面大 → 既有 test_config.py 大量用例随 API 消亡而删（合法删除，须在 state 偏差记录
  删除计数）；device 真源切换 → predict 设备解析离屏测试（W10 四分支）必须语义保持。
