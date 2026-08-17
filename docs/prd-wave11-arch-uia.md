# PRD — wave11-arch-uia：架构全面审查 + UIA 自动化测试方案与全流程测试

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）：
> "使用架构师技能，对项目全面审查，并创建UIA自动化测试方案，对项目全面测试。 测试图片路径在E:\学习项目\极柱外观检标注图"

## 背景

- 上次架构审查（2026-08-16，docs/AutoVisionAgent-架构解析与优化方案.md，4 P1 + 14 P2）后，W7-W10 已落地 36 提交：gui 纳入门禁分母、覆盖率棘轮 74.74→89.35、659 门禁测试、13 个真 bug 修复（numpy 真值族 ×6、引擎标签映射反模式、QPixmap 越线程等）、.NET 掩码 RLE 压缩默认开启。当前架构态势需要一次基于实测的全面复审。
- UIA 真窗测试现状：仅 1 条合成图 happy-path（登录→导入→矩形标注→模拟训练→部署触发）。home/project/eval/predict/flaw_gen/settings 页、多边形标注、数据划分、真实工业数据集路径从未在真窗下验证。exe 自 W7 后未重打包（不含 W8-W10 修复）。
- 极柱外观检数据集（E:\学习项目\极柱外观检标注图）：1289 对 bmp+json，1600×1600，LabelMe polygon；文件名带 `(N)` 括号与中文路径——历史上正是 cv2.imread 失败的真实形态，是读图鲁棒性的天然探针。

## 目标

1. 产出 v2 架构审查文档：当前态实测指标、18 视角覆盖矩阵、P0/P1/P2 缺点定级（每条带实测证据）、改进路线。
2. 产出 UIA 测试方案文档并落地扩写：极柱真实数据导入/标注/保存、多边形标注、数据划分、设置页主题切换、首页/项目页冒烟，全部 deterministic 断言。
3. exe 重打包含 W8-W10 全部修复，UIA 真窗全流程在 autofix-loop 驱动下收敛 GREEN。

## 功能需求（FR）

- **FR-001 架构全面审查**：基于实测度量（LOC/依赖/质量信号/覆盖率）对当前代码态做 18 视角评审，多视角扇出 + P0/P1 发现对抗反驳验证，产出 docs/AutoVisionAgent-架构解析与优化方案-v2.md。
- **FR-002 UIA 测试方案**：按 uia-autofix-loop plan-phase 模板产出 docs/uia-test-plan-full-coverage.md（覆盖矩阵/断言铁证通道/生命周期/确认记录），runner 合入 uia-windows。
- **FR-003 exe 重打包**：PyInstaller autovisionagent.spec 重打包，含 W8-W10 全部生产修复。
- **FR-004 UIA 测试扩写**：以极柱真实数据为核心的新用例（导入括号文件名 bmp、标注页真实图矩形+多边形+保存 JSON 铁证、数据划分 copy 模式落盘铁证、设置页主题切换状态断言、首页/项目页加载冒烟），不放松既有全流程用例。
- **FR-005 autofix-loop 收敛与终验**：baseline-uia → 循环协议（deterministic 修生产 / visual·flaky 路由不修）→ GREEN（或诚实 STUCK 报告）；门禁全量回归 rc=0、fail-under=89 不降；state complete；validator 通过；提交与记忆同步。

## 验收标准（AC）

- **AC-001**：v2 审查文档含：实测指标表（关键数字带重验留痕）、18 视角覆盖矩阵（交付时无"待补"）、缺点条目全部 `**P{0,1,2}-N**` 格式且带实测数字或 file:line、P0 缺点全部经反驳尝试存活、「验证范围与局限」与「完整性批判记录」章节齐备。
- **AC-002**：方案文档含覆盖矩阵（每用例标注断言通道：状态栏文本/磁盘产物/UIA 树属性）、生命周期（单实例清理/串行/会话级 app fixture）、确认记录（用户指令充当 G1，偏差已记录 state.json）。
- **AC-003**：dist/AutoVisionAgent/AutoVisionAgent.exe 时间戳晚于 W10 提交（0bc218a），UIA 会话能启动并找到主窗口。
- **AC-004**：新用例全部 deterministic 断言（无 screenshot/像素 diff）；极柱标注保存的 JSON 落盘且 shapes 数 > 0；数据划分后 train/val 目录文件数 > 0；每条断言消息含预期行为 + 实际值 + 指向。
- **AC-005**：autofix-loop 终态 GREEN（或 STUCK 时产出报告列明剩余失败与建议）；`.venv/Scripts/python.exe -m pytest` 全量 rc=0 且覆盖率 ≥ 89；validate_workflow 返回 0；单波 git 提交（不含 gitignored 产物）。

## 范围与非目标

- 非目标：真实 GPU 训练全流程、FID/LPIPS 真模型评估、SAM 带真权重交互（依赖缺失，留待环境就绪）；C# 客户端 UIA（dotnet 侧已有 45 测试门禁）；发布/外发。
- 风险：真窗 UIA 冷启动偶发首跑找不到按钮（历史 3 次首启 1 次，复跑即过）——循环协议的 flaky 路由可隔离；桌面会话丢失 → conftest 自动 skip（fail-honest 记录为阻塞）。
