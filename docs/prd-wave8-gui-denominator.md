# PRD — 第八波：eval/deploy worker + login 注册流补测 + gui 纳入门禁分母（wave8-gui-denominator）

> 依据：用户 2026-08-17 指令"eval/deploy 页 worker 路径、login 注册流补测，然后把
> gui 纳入门禁分母（需先把 eval 36% 这类洼地填平）"。
> 基线：W7 终态 391 passed / 0 failed / 1 skipped，门禁 fail-under=74（实测 74.74%）。
> 摸底（--cov=gui --cov-fail-under=0 全量）：gui ≈59%（3742 语句/1524 未覆盖），
> 直接纳入分母 → 组合 68% < 74，棘轮不可降，故须先填洼地。

## FR-001 eval 页 worker 路径补测（36% → ≥90%）

- `_run_eval` 全路径：参数校验（无模型/无标注目录）、fid/lpips 生成式分支、
  supervised 分支（LabelMe JSON 装载、引擎加载失败回退 GT 自比较警告、
  引擎推理成功、NaN/Inf 指标 N/A）、无标注数据行。
- 槽：`_eval_progress_slot`、`_set_results_slot`（TP/FP/FN 解析构建混淆矩阵，
  无 TP/FP/FN 时示例矩阵）、`_eval_failed_slot`、`set_results`、`retranslate`。
- `ConfusionMatrixWidget`：set_title/set_matrix/clear_matrix + paintEvent
  （offscreen `grab()` 触发自绘，含空矩阵"无评估数据"分支）。

## FR-002 deploy 页 worker 路径补测（48% → ≥90%）

- `_do_export`：参数校验；worker 内 torch.load 装载（dict 含 "model" 解包、
  无 eval 属性→"无法识别的模型格式"）、onnx 导出、TRT 转换成功/失败降级
  （不中断导出）、异常路径；槽 `_on_export_finished`（审计日志记录）、
  `_on_export_failed`、`set_progress`、`retranslate`。
- 采样导出器与 torch.load 注入（monkeypatch），不依赖真权重/TRT。

## FR-003 login 注册流与账户安全路径补测（67% → ≥90%）

- `_do_register`：许可证导入成功（copy 到 configs/license.key + 状态）、
  导入失败、取消选择。
- 登录安全：连续失败计数持久化 → 5 次锁定（lockout_until 持久化）、
  锁定期内拒绝登录、must_change 首登翻转、哈希迁移（verify_and_migrate
  返回 rehash_info 时更新记录）。
- `_ensure_default_admin`：空库首启创建随机密码 admin（must_change=True）、
  已有库不覆盖；`_load_users_db`/`_save_users_db` 异常路径。

## FR-004 predict + flaw_gen 页补测（组合分母达标所需）

- predict 页（46%）：单图/批推理 worker 路径、结果渲染分支
  （含 W7 修复的 numpy 真值路径）、CSV/JSON 导出、预览清除等可在离屏
  驱动的路径。
- flaw_gen 页（55%）：缺陷生成 worker 路径（参数校验/生成/失败）。

## FR-005 gui 纳入门禁分母 + 棘轮升门

- pytest.ini 增 `--cov=gui`；注释同步（gui 覆盖由单元离屏测试 + UIA 真窗
  双承担）。
- 组合覆盖率实测地板 ≥ 74（旧地板不降），fail-under 升至新实测地板。
- 全量门禁 rc=0；state 终态 + validate_workflow + 提交 + 记忆更新。

## 验收标准

- AC-001（FR-001）：eval 页测试全绿，覆盖 ≥90%（含 paintEvent 离屏触发）。
- AC-002（FR-002）：deploy 页测试全绿，覆盖 ≥90%（导出器注入，无真 TRT）。
- AC-003（FR-003）：login 注册流/锁定/迁移测试全绿，覆盖 ≥90%。
- AC-004（FR-004）：predict+flaw_gen 测试全绿；组合 gui 覆盖使总分母 ≥74%。
- AC-005（FR-005）：pytest.ini 含 --cov=gui，全量 rc=0，fail-under ≥74 且
  = 新实测地板（只升不降）。
