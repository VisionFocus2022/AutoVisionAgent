# UIA 全面深入 W25 — 任务清单（L2）

> 关联 docs/prd-uia-deep-w25.md；每任务 TDD（RED→GREEN）+ 证据回填 state.json。

## T1 · FR-001 新 exe 复跑验收 〔P0·进行中〕

- 命令：`.venv/Scripts/python.exe -m pytest tests/uia -o addopts=`
- 证据：evidence/uia-rerun-acceptance.log（含跑前机器快照）
- 完成：6 passed rc=0；失败→三件套取证（应用侧审计 autovision.log/login 记录在场、日志零 ERROR、断言零修改）+ 归因记录

## T2 · 只读调查：权重来源与副作用面 〔P0·阻塞 T3/T4/T5〕

- 2a. test_import_annotate_train_deploy 训练产物落盘位置/格式/复跑耗时 → predict/eval 可用性判定；退路=预置小权重路径
- 2b. exe 模式 CONFIG_DIR 解析（dist/_internal/configs）下改密用例的 users.json/initial_credentials.txt 副作用与备份还原策略；python 模式对仓库 configs/ 的触达（W24 验证员 observation 提示 test_m2_e2e 已触达真 configs——本波不扩大该面）
- 2c. i18n 切换对既有 6 用例中文断言的影响面（词条键清单）

## T3 · FR-002 predict 推理页 UIA 用例 〔P0〕

- RED：test_predict_flow.py::test_predict_single_image（结果 ≥1 条带分数+预览更新）先失败（权重/导航任一环节缺失即红）
- GREEN：补 conftest 权重预置 fixture（依 T2a）至全绿；不加 sleep 硬等、复用 wait_status 家族

## T4 · FR-003 eval 评估页 UIA 用例 〔P1〕

- RED：test_eval_flow.py::test_eval_run_shows_metrics（指标数值+完成提示）
- GREEN：同 T3 权重策略

## T5 · FR-004 改密 + W24 sweep 联动用例 〔P1〕

- RED：test_user_mgmt_flow.py::test_first_login_change_password（初始密码登录→改密→initial_credentials.txt 消失→新密码重登/旧密码拒）
- GREEN：teardown 还原 users.json；断言文件消失走 exe 真实 configs（联动 W24 sweep 与 _remove 双路径）

## T6 · FR-005 move 划分 + i18n 用例 〔P2〕

- RED：test_datamanage_move_i18n.py::test_move_split_groups_subdirs（顶层清空+相对路径分组）+ test_i18n_switch_persists（English 重启保持）
- GREEN：i18n 用例自还原语言（teardown），不污染后续断言

## T7 · 回归与收口 〔P0〕

- 主门禁：`.venv/Scripts/python.exe -m pytest`（996/4 基线不回归；新测试文件在 tests/uia 默认 ignore，不进主门禁分母）
- UIA 全套：T1 命令含新用例全绿
- 验证器：`validate_workflow.py .workflow/uia-deep-w25/state.json` rc=0
- risks_open 清空（UIA flaky 环境归因按惯例留档不算开放风险）；最终摘要回填
