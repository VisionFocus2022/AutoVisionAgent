# 六工序流水线入驻 AutoVisionAgent
- 日期: 2026-08-30
- 类型: skill
- 执行者: 主对话（six-stage-pipeline/init-pipeline 技能，用户显式指令"对这个项目全面审查"）
- 等级: L0

## 变更内容

- 八领域调研（模块依赖/编码错误处理/分层/数据访问/配置/测试/构建实跑/流程文档），结论全部带文件路径或命令输出证据
- 用户拍板：分层动线=GUI→领域→core；门禁挂载=独立聚合脚本；domain skills 4 个全选；L0 红线 4 条全选
- 生成项目层资产：R01-R04 规则、4 个 domain skills、check-gate.sh 聚合门禁、ruff 棘轮基线（1153）、skill-bank.json、AGENTS.md、records 骨架
- 顺带安装 venv 缺失的 ruff（pyproject 声明了 [tool.ruff] 但从未装过——首次实跑发现 1153 存量问题，UP006/UP045/I001 占 62%）

## 涉及文件

- 新增：`.qoder/rules/R01-module-build.md` `R02-coding-error.md` `R03-layer-data-config.md` `R04-test-workflow.md`
- 新增：`.qoder/skills/domain/{add-annotation-mode,add-inference-engine,add-gui-page,run-eval-experiment}/SKILL.md`
- 新增：`scripts/check-gate.sh`、`scripts/ruff-baseline.txt`、`.qoder/skill-bank.json`、`.qoder/AGENTS.md`
- 框架层拷贝：`.qoder/{agents(6),rules(R00,R05),skills(process 2+base 3),records}` + `scripts/check-naming.sh`

## 验证结果

- 主门禁实跑：`1216 passed, 5 skipped, coverage 92.82% (≥92), 116.70s, rc=0`
- ruff 首测 1153 条（statistics：UP006=384/UP045=203/I001=131/UP035=128/F401=98），按棘轮立线只降不升
- `bash scripts/check-gate.sh` 聚合门禁实跑：三段全绿（check-naming PASS / ruff 1153≤1153 PASS / pytest 1216 passed 5 skipped coverage 92.82% 128.71s），rc=0
- 命名合规：check-naming.sh 通过（本记录文件名 20260830_skill_pipeline-onboarding 符合 R00）
