# AutoVisionAgent 架构风险与质量审查报告

> 产出技能：`architecture-visualization:risk-quality-reviewer`（关系图格式：`graphviz`）
> 审查日期：2026-08-24 · 分支：`feature/sam3-auto-discovery`（领先本地 master 5 提交，未推送任何远端）
> 审查目标：全面评估架构健康度——发布/交付就绪性、质量属性缺口、风险与补救优先级
> 受众：项目维护者（单人开发流）· 风险容忍度：中（桌面工具交付，无在线服务 SLA）

## 0. 结论总览（按优先级）

| # | 发现 | 严重度 | 置信度 | 状态 |
|---|------|--------|--------|------|
| AVA-R1 | 打包环境无自动防呆——错误 venv 可产出"能启动但功能残废"的 exe | 高 | high（本会话实际发生） | **已补救**（2026-08-31 P1-1：spec 双断言落地，负/正双向验证通过） |
| AVA-R2 | 门禁证据本机孤岛——8 提交未推远端，CI 从未在本分支运行 | 高 | high（git 实证） | 确认缺陷 |
| AVA-R3 | dist-lite 缺失——lite 棘轮守卫"不存在则 skip"形成盲区 | 中高 | high（目录实证） | 确认缺陷 |
| AVA-R4 | UIA 真窗测试默认排除——GUI 交互回归仅靠发版手动兜底 | 中 | high（pytest.ini 实证） | 设计取舍+缺口 |
| AVA-R5 | 完整 dist 体积无棘轮——4.3→6.36 GiB（+48%）无门禁拦截 | 中 | high（跨期实测） | 确认趋势 |
| AVA-R6 | 覆盖率余量仅 0.87pt（92.87% vs fail-under 92） | 中 | high（主门禁输出） | 确认趋势 |
| AVA-R7 | spec 条件打包 configs/user_settings.json——开发机配置泄入交付物 | 低中 | high（spec L20-23 实证） | 确认缺陷 |

**一句话结论**：进程内工程质量扎实（1222 测试全绿/覆盖 92.87%/依赖方向零违规/线程模型统一/文档沉淀深），但**交付链路（打包环境纪律 → 远端同步 → CI 实际运行 → 双产物核销）存在系统性薄弱**——所有质量证据都产自单机，且本会话已实际演示过一次"错误环境打包"事故。

## 1. 系统快照

### L1 系统上下文

```
标注员/工程师 ── AutoVisionAgent 桌面 exe（PySide6）
                    ├── 有监督引擎栈（torch 2.5.1+cu121 / ultralytics 可选 / SAM3 可选）
                    ├── 零样本检测（DINOv3+CLIP，经 vision_dispatcher 双范式路由）
                    └── serving 层（gRPC + 共享内存）── .NET 客户端（VisionAgent.Shared）
```

### L3 模块度量（不含 dist/build）

| 模块 | py 文件 | 行数 | 职责 |
|------|--------|------|------|
| gui | 45 | 8,902 | 10 页面 + core（shell/jobs/thread_bridge/theme/i18n）+ widgets |
| labeling | 19 | 2,836 | 画布/控制器/SAM 适配器/SAM3 会话/批量工具 |
| core | 11 | 1,653 | 接口契约/配置/认证/审计/常量 |
| models | 16 | 1,402 | 9 任务引擎注册表 |
| serving | 9 | 1,773 | gRPC 服务 + 共享内存 + mask 编解码 + dotnet_client |
| scripts | 19 | 3,411 | 构建/评估/下载/实验脚本 |
| **tests** | **131** | **30,055** | 主门禁 1222 用例 + UIA 真窗套件 |

### 质量基建（证据）

- **主门禁**：`.venv/Scripts/python.exe -m pytest` → 本次审查实测 **1222 passed / 5 skipped / 0 failed**（115.6s），覆盖率 **92.87%**（棘轮 92）〔输出文件：任务 b00glo1vs〕
- **L0 聚合门禁**：`scripts/check-gate.sh` 三段（命名 + ruff 棘轮 1153→0 基线归零 + 主门禁）
- **CI**：`.github/workflows/ci.yml` 双 job（pytest offscreen + dotnet test），触发条件 push/PR——**但见 AVA-R2，从未在本分支运行**
- **依赖方向**：`gui → labeling/training/... → core` 单向，反向 grep **0 违规**；serving 独立经 proto 消费 core
- **线程模型**：`gui/core/jobs.py` 统一调度（注册表 + 协作取消 + 有界停机），11+ 调用点接线 `ui_on_error`；closeEvent 以 jobs 注册表为真相源（shell.py:328-370）
- **安全基线**：PBKDF2 ≥100k 迭代、删除项目路径遍历防护（CWE-22）、CSV/Excel 公式注入防护（CWE-1236）、三角色矩阵 + 审计锚点
- **文档沉淀**：docs/ 含 6 版架构分析 + ADR + 10 份 PRD + RELEASES.md 三态核销制

## 2. 发现详表

### AVA-R1 · 打包环境无自动防呆（严重度：高）

- **证据**：本会话记录——使用 hermes-agent venv（Python 3.11.15，无 torch/numpy/cv2）执行 `python -m PyInstaller` 产出 3.5 MB exe：GUI 正常启动，推理/训练全部静默不可用；后经任务 W-2 以正确 `.venv` 重建（6.36 GiB）才修复。`autovisionagent.spec` 无解释器路径/依赖自检断言。
- **为什么重要**：R01 规定唯一打包入口是 `.venv/Scripts/python.exe -m PyInstaller`，但这是**文档约束而非机械防呆**——任何会话/新人用系统 python 即可无声复现"残废 exe"。
- **可能性**：高（已实际发生）· **影响**：中高（交付物静默残废，GUI 可启动导致问题晚发现）· **置信度**：high
- **补救**：见 remediation-plan.md P1-1。

### AVA-R2 · 门禁证据本机孤岛（严重度：高）

- **证据**：`git branch -r` 仅 `gitee/master`、`github/master`；`feature/sam3-auto-discovery` **未推送任何远端**（grep 计数 0）；HEAD 领先 `gitee/master` **8 提交**。ci.yml 注释自述"待 git remote 接入后首次生效"（写入时无远端，现已有时注释过时），但无任何 CI 运行记录可证明其曾绿。
- **为什么重要**：全部"1222 绿/92.87%"证据产自单机 `.venv`。R01"推送须双发"规则当前被违反。机器故障 = 门禁停摆 + 8 提交工作存在单点丢失风险。
- **可能性**：已发生 · **影响**：中高（证据可信度依赖单机；工作丢失风险）· **置信度**：high
- **补救**：P1-2。

### AVA-R3 · dist-lite 缺失 + 棘轮软 skip（严重度：中高）

- **证据**：`dist/` 存在（6.36 GiB / 23,776 文件），`dist-lite/` **不存在**；`tests/test_w19_lite_dist.py` docstring 明示"不存在则 skip"；RELEASES.md 头部宣称双产物（完整版 + lite <2GiB）。
- **为什么重要**：lite 棘轮（R01 L0）在产物缺失时静默失效——当前主门禁 5 个 skip 大概率含 lite 守卫。lite 派生脚本（make_lite_dist.py）与最新 dist 的兼容性无人验证。
- **可能性**：已发生 · **影响**：中（发版双产物断链）· **置信度**：high

### AVA-R4 · UIA 真窗测试默认排除（严重度：中）

- **证据**：pytest.ini `--ignore=tests/uia` + 注释"需桌面会话 + 打包 exe，发版检查单手动执行"；ci.yml 注释"tests/uia 真窗测试默认 --ignore，不在 CI 跑"。
- **为什么重要**：本会话"exe 无关闭按钮"缺陷正是此类——静态单测全绿但真窗交互缺口。GUI 交互回归的最早发现点 = 发版检查单。
- **可能性**：中 · **影响**：中（回归晚发现）· **置信度**：high

### AVA-R5 · 完整 dist 体积无棘轮（严重度：中）

- **证据**：项目记忆基准 4.3 GiB（8,272 文件）→ 当前实测 **6.36 GiB（23,776 文件，+48%）**。lite 有 <2GiB 硬棘轮，完整 dist 无任何体积门禁。
- **可能性**：高（依赖升级自然膨胀，v2.1.0 曾手工 PYZ 清场 -355 模块）· **影响**：中（客户分发/磁盘压力）· **置信度**：high

### AVA-R6 · 覆盖率余量 0.87pt（严重度：中）

- **证据**：主门禁输出 `Required 92% reached. Total coverage: 92.87%`，缺口 668/9369 语句。
- **可能性**：中（一两次正常迭代即可跌破）· **影响**：低中（门禁假红阻塞，或被迫降棘轮失信于"只升不降"契约）· **置信度**：high

### AVA-R7 · user_settings.json 条件打包（严重度：低中）

- **证据**：`autovisionagent.spec` L20-23——`configs/user_settings.json` 存在则打入 exe；当前 configs/ 确实存在该文件（含最近目录/主题/语言等开发机状态）。
- **影响**：低中（客户首启继承开发者本地配置；轻微隐私/正确性问题）· **置信度**：high

## 3. 优势确认（非风险，防漂移基线）

1. **测试投资**：tests 30k 行 vs 源码 ~23k 行（不含 tests/scripts），1222 用例 116s 全绿；FakeThread monkeypatch 接缝设计（jobs.py:18-22 约束 2）体现可测试性优先。
2. **架构规则可执行**：依赖方向 L0 规则 grep 可验证且当前零违规；ruff 棘轮已清零；新模块"五方注册"清单。
3. **停机语义**：closeEvent 有界停机（jobs 注册表真相源 + TrainWorker 兼容双轨 + 超时上报未退出任务名）。
4. **可选依赖诚实门控**：requirements.txt 可选项注释声明 + try-import fail-honest 约定（R01 L1-3）。
5. **发布治理**：RELEASES.md 三态核销（兑现/部分/证伪）制度。

## 4. 未知与假设

| 项 | 状态 | 验证路径 |
|----|------|---------|
| CI 是否曾在任一提交上成功运行 | unknown | 推送后查看 Actions 首跑；或 gitee 对应流水线 |
| 5 个 skip 的具体构成 | unknown（推测含 lite 守卫） | `pytest -rs` 列出 skip 原因 |
| 668 缺口语句分布 | unknown | term-missing 报告聚合分析 |
| dist 6.36 GiB 中增量来源（torch 升级？SAM3 权重？） | unknown | dist 内 top-20 目录体积对比旧基准 |
| .NET 客户端实际消费方（生产在用？） | unknown | 问询维护者 |

## 5. 工件清单

| 工件 | 路径 |
|------|------|
| 本报告 | `docs/architecture-review/architecture-review.md` |
| 风险关系图（DOT 源） | `docs/architecture-review/risk-map.dot` |
| 补救计划 | `docs/architecture-review/remediation-plan.md` |
| 质量场景 | `docs/architecture-review/quality-scenarios.md` |

## 6. 下一步检查（审查后 7 天内）

1. 推送 feature 分支至双远端 → 观察 CI 首跑是否绿（验证 AVA-R2 假设）
2. 以正确 `.venv` 执行一次 `make_lite_dist.py` → 重建 lite 并核对 <2GiB（核销 AVA-R3）
3. `pytest -rs` 枚举 5 skip → 关联 AVA-R3/R4 归因
