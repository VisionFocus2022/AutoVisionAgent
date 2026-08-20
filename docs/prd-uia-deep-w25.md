# UIA 全面深入：复跑验收 + predict/eval/改密/move+i18n 扩面 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-21 | 档位: L2 | 四维: 可逆/局部/测试可见/中不确定（predict 权重来源与改密 CONFIG_DIR 副作用待短调查）；auth 界面流程从严取 L2。见 .workflow/uia-deep-w25/state.json

## 1. 背景与目标

- **背景**：UIA 真窗 e2e 现仅 6 用例（1 主链 import→annotate→train→deploy + 5 极柱流）；predict 推理页（核心页）、eval 评估页、用户改密、move 划分/i18n 零 UIA 覆盖。W24 重打包 exe（08-21 03:56）尚未过 UIA 验收（当时机器忙留欠）。
- **目标**：①新 exe 复跑 6/6 验收闭环；②为四组盲区各增 ≥1 条 UIA 用例并全绿；③不改断言换取通过、零生产码改动（UIA 暴露缺陷时单独立卡）。

## 2. 功能需求 (FR)

- **FR-001**: 新 exe UIA 复跑验收 — 既有 6 用例对 08-21 03:56 exe 全绿；失败按 W16/21/22 惯例三件套取证（应用侧审计在场+日志零 ERROR+断言零修改） | 优先级 P0
- **FR-002**: predict 推理页 UIA — 选权重+选图触发单张推理，结果列表 ≥1 条带分数记录、预览更新 | 优先级 P0
- **FR-003**: eval 评估页 UIA — 选模型+数据集触发评估，指标数值展示与完成提示 | 优先级 P1
- **FR-004**: 用户管理/改密 UIA（联动 W24 sweep）— 初始密码登录→改密成功→initial_credentials.txt 消失→新密码可登、旧密码被拒 | 优先级 P1
- **FR-005**: 数据管理 move 划分 + i18n — move 划分后顶层清空+子目录相对路径分组（W20 行为）；中英切换重启持久化 | 优先级 P2

## 3. 验收标准 (AC)

- **AC-001**: 给定空闲机器与新 exe，当跑 `.venv/Scripts/python.exe -m pytest tests/uia -o addopts=`，应该 6 passed rc=0（失败时三件套取证在 evidence 且归因记录） [关联 FR-001]
- **AC-002**: 给定已导入数据集与可用权重（T2 调查定源），当 predict 页触发单张推理，应该结果区 ≥1 条带分数记录且应用日志无新增 ERROR [关联 FR-002]
- **AC-003**: 给定训练产物与数据集，当触发评估，应该指标区出现数值且状态提示完成 [关联 FR-003]
- **AC-004**: 给定 exe 首启生成的 configs/initial_credentials.txt，当用初始密码登录并完成改密，应该该文件消失、新密码重登成功、旧密码登录被拒，且测试 teardown 还原 users.json（不留密码改动） [关联 FR-004]
- **AC-005**: 给定已导入数据集，当 move 模式划分，应该顶层无散图且子目录按相对路径分组展示；当切换 English 并重启应用，应该主导航词条为英文且再次重启保持 [关联 FR-005]

## 4. 范围

- ✅ **In Scope**: FR-001~005 对应用例新增与复跑；tests/uia/conftest.py 必要辅助（权重预置/还原 fixture）；.workflow/uia-deep-w25/ 档案
- ❌ **Out of Scope**: python 模式（AVA_UIA_SOURCE=python）全量矩阵；lite exe 矩阵；性能/时延基准；UIA 暴露的生产缺陷修复（发现后单独立卡，本波只取证）

## 5. 风险与假设

- **风险**: ①机器非空闲致 flaky（缓解：用户腾机器+三件套归因惯例）；②改密用例写 exe 的 _internal/configs/users.json（缓解：teardown 备份还原+用例置于套件尾部）；③predict/eval 权重不可用（缓解：T2 调查链上产物落盘，退路=预置小权重，再退=用例 skip 留档）
- **假设**: 既有 6 用例对新 exe 语义不变（exe 含 W23/W24 生产码但均零行为变化设计）

## 6. 实现思路（给定方向，非完整方案对比）

- **拟采用**: 复用 ava_app fixture + uia_helpers（click_nav/draw_*/app_log_path）+ 离线登录 license 预置；新用例分文件 test_predict_flow.py / test_eval_flow.py / test_user_mgmt_flow.py / test_datamanage_move_i18n.py
- **复用**: test_import_annotate_train_deploy 的链上训练产物（T2 定位落盘路径与复跑成本）；test_pole_dataset_flows 的 pole_subset_dir/workspace_dir fixtures；W24 sweep_residual_initial_credentials 断言锚
- **注意**: exe 模式 CONFIG_DIR=dist/_internal/configs（改密副作用须还原）；i18n 切换会改变后续用例的中文断言文案（用例内自查词条或套件顺序控制）；UIA 超时在慢机上调 AVA_UIA_LAUNCH_TIMEOUT
- **落盘产物**: 新测试文件 4 个（git 跟踪）；.workflow/uia-deep-w25/evidence/*.log（跟踪，有意审计轨迹）；UIA 运行副作用 dist/*/configs/users.json|initial_credentials.txt（teardown 还原为策略，dist/ 已忽略不入库）

---

## 自检（6 项，提交前核对）

- [x] **完整性**: 每条需求有 FR 编号
- [x] **无歧义**: 命令 `grep -iE "快速|友好|高效|灵活|强大"` 本文件命中 = 0
- [x] **可追溯**: 每个 FR 有对应 AC
- [x] **范围清晰**: In / Out Scope 已列
- [x] **指标可量化**: 目标 / AC 有可判定标准
- [x] **落盘卫生**: §6 落盘产物已注明 .gitignore 忽略策略（无新增需忽略文件）

## ✅ 门禁（2 项）

- [x] G1：用户 AskUserQuestion 三答（2026-08-21）——范围=复跑+扩面、四组全选、先跑验收 → state.json approvals.G1
- [ ] G3：任务清单（docs/tasks-uia-deep-w25.md）经用户确认后进入实现
