# PRD-lite：W1-4 AMP 预检异步化 + W1-5 初始密码参数化（Wave1 收尾双切片）

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2 ｜ 确定性：高（两处都是既有机制的小迁移）｜ 影响半径：中（训练启动线程模型 / 首启凭据交付）｜ 规模：小（2+2 文件，±~90 行）｜ 可逆性：双向门
- **上游**: roadmap Wave1 W1-4/W1-5；W67（预检假死案）/W68（凭据持久化案）余波
- **门禁**: 探索 ✅（用户指令"提交，然后继续"）｜ PRD ✅（S2 预裁决：roadmap DoD 锁定）｜ 收尾 ✅（2026-10-07：W1-4 真线程单测 3 绿（预检线程≠主线程/回退三联动/免检零打扰）；W1-5 单测 5 绿（参数生效无 txt/短密码回落/无参回归/二次不动库/双形态解析）；主门禁 1439 绿+ruff 0；exe 重打包；wizard UIA 110.7s 回归（worker 预检链））

## W1-4 AMP 预检异步化

**背景**：W67 后预检仍在 UI 线程（反馈前置只是消除静默，冷驱动时 UI
仍卡到预检结束）。DoD：预检在 worker。

- **FR-1**：`amp_preflight` 调用移入 `TrainWorker.run()`（fit 前）——
  失败 → `stage_msg("amp_fallback", reason)` 信号（码+详情，UI 侧翻译）
  + `dataclasses.replace(cfg, amp=False)` 经 fit 参数链生效
  （strategy.train_epoch 用的是 fit 传入 cfg，W58 契约）。
- **FR-2**：页面删 UI 线程预检块；`_on_stage_msg` 翻码为文案 + AMP 回退
  时取消勾选 chk_amp + 状态栏；预检日志留痕在 worker 侧
  （开始/结束/回退三行不缺）。
- **幽灵训练条款**：W66 挂账维持观察（复现即抓栈），本切片无动作。

**AC-4x**：①预检线程≠主线程（记录 threading.get_ident 对比）且
`_start_training` 即刻返回；②预检失败 → fit 收到 amp=False、状态
"AMP 预检失败，已回退 FP32"、chk_amp 取消勾选；③成功 → amp=True 保持。
〔非 happy-path=②〕

## W1-5 初始密码参数化

**背景**：首启随机密码落 initial_credentials.txt 明文文件（交付面风险）。
DoD：--init-pwd 参数生效；txt 不再生成。

- **FR-3**：`main()` 解析 `--init-pwd <pwd>`（简单 argv 扫描）→ 传入
  `LoginPage(init_password=...)` → `_ensure_default_admin` 库空时用该
  密码建 admin（must_change=True 保留）；**提供参数时不写 txt**
  （日志提示"已按 --init-pwd 配置"不含明文）。
- **FR-4**：无参数行为不变（随机密码+txt）；密码强度底线：非空且
  ≥8 字符，不满足按未提供处理并告警。

**AC-5x**：①--init-pwd 生效：users.json 哈希验证通过、无 txt、日志无
明文；②不合规参数（短/空）回落随机+txt 并告警；〔非 happy-path〕
③无参数回归不变。

## 范围与验证

改：gui/pages/train/worker.py、gui/pages/train/page.py、
gui/pages/login/page.py、gui/main.py；重写 tests/test_w31_amp_preflight.py
（真线程模式）、新 tests/test_w1_5_init_pwd.py。
验证：主门禁全绿+ruff 0+行数守卫；wizard UIA 回归（训练链含 worker 预检）。

Out of scope：预检结果缓存、--init-pwd 之外的安装器参数族。

## 实施纪要（2026-10-07）

- W1-4 信号设计：worker 无 i18n 上下文 → stage_msg 传**码**（amp_fallback）
  +详情，页面侧翻译文案并联动（chk_amp 取消勾选）；amp=False 经 fit
  参数链生效（strategy.train_epoch 消费 fit 传入 cfg，W58 契约零改）。
- w31 重写为真线程模式（FakeWorker 无法覆盖 worker 内预检）；测试事件泵
  纪律：跨线程排队信号必须 qapp.processEvents 轮询。
- W1-5 密码底线：非空 ≥8 字符，不合规告警回落随机+txt（交付安全默认）。
- 门禁噪声判例：满载时段一次 8 红（随机化+负载），隔离重跑全绿定性——
  门禁红先隔离复跑再定性，避免追幻影。
