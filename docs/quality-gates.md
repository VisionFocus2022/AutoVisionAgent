# AutoVisionAgent 代码审查与测试保障流程（四层质量门禁）

> 来源：工程保障团队 2026-10-07 方案（Archi 架构 + Cody 审查 + Tessa 测试 + Rex SRE 四方产出，主理人汇编）。
> 单一真源清单：pytest.ini（覆盖率门禁）、coverage_floors.py（per-package 地板）、ruff-baseline.txt（=0）、requirements.lock.txt（依赖）。

## 一、四层门禁总览

```mermaid
flowchart TD
    DEV[写码 feat+test 成对] --> COM[git commit]
    COM --> L1{L1 pre-commit ≤5s<br/>ruff/命名/卫生检查 仅暂存区}
    L1 -- 红 -->|就地修复| DEV
    L1 -- 绿 --> ITER[继续迭代 / WIP 可 --no-verify 逃生]
    ITER --> PUSH[git push] --> L2{L2 本地门禁}
    L2 --> L2A[test-changed.sh 快跑<br/>+ 自审清单 + AI 快审 diff]
    L2A -- 红 --> DEV
    L2A -- 绿 --> L3{L3 CI push 触发}
    L3 --> L3A[lint: ruff棘轮+命名+proto对账]
    L3 --> L3B[test: 全量 pytest 92门禁+floors]
    L3 --> L3C[dotnet-test]
    L3 -- 红 -->|回本地修| DEV
    L3 -- 绿 --> REL{发版?}
    REL -- 是 --> L4[L4 发版检查单: 全量门禁→打包→<br/>UIA 真窗→冒烟→归档+AI 深审]
```

| 层级 | 触发时机 | 执行内容 | 耗时预算 | 失败处置 |
|---|---|---|---|---|
| L1 提交钩子 | git commit | ruff（仅暂存文件）+ check-naming + 尾空白/大文件/私钥守卫 | ≤5s | 阻断提交；WIP 允许 `--no-verify`，push 前必须补跑 L2 |
| L2 日常快跑 | 写码中/提交前手动 | `test-fast.sh` / `test-changed.sh`（--no-cov）+ 自审清单档 A + `ai-review.sh`（feat/fix ≥50 行或高风险域必跑） | 1~3min | 红灯不提交 |
| L2 全量门禁 | git push 前 | `bash scripts/check-gate.sh`（命名 + ruff 棘轮 + marker 防回潮 + 全量 pytest 92 门禁） | 5~15min | 阻断推送 |
| L3 CI | push 自动 | lint / test（全量+floors）/ dotnet-test 三 job（现状保持） | 15~40min | 红灯期间不开新迭代周 |
| L4 发版检查单 | 打包发版前手动 | 既有 5 步 + 第 0 步 AI 深审本版累计 diff + 自审清单复核 | 人工 30~60min | 停止发版 |

**放置判据**：耗时 × 修复成本 × 拦截价值——修复成本随发现时机（写码时→提交时→推送时→CI→发版）指数上升，一切能在左侧层廉价拦住的问题绝不放行到右侧。反例禁则：全量 pytest 绝不进 L1/L2 日常路径；mypy 未清基线前绝不进 L1。

## 二、代码审查流程（单人项目 = 自审清单 + AI 第二审查者）

1. **每次 commit**：走查 [docs/self-review.md](self-review.md) 档 A（30 秒 ×8 条）。
2. **feat/fix 触碰高风险域**：档 B（3 分钟 ×17 条，按 PySide6/PyTorch/Windows/资源/异常/测试六域）。
3. **AI 辅助审查**：`bash scripts/ai-review.sh`（staged）/ `ai-review.sh HEAD~1`（最近提交）/ `ai-review.sh main..HEAD`（范围）——组装带项目硬约束的七维审查提示词。**必跑触发**：feat/fix 源码 diff ≥50 行，或触碰 gui/worker/模型加载卸载/文件IO/serving。AI 结论一律建议级，不阻断（阻断权归门禁脚本）。
4. **周迭代收官**：AI 深审本周累计 diff，问题清单归档当周记录。
5. **发版前**（L4 第 0 步）：AI 深审本版累计 diff + 人工过自审清单档 A+B。

## 三、测试分层执行矩阵

| 时机 | 跑什么 | 命令 | 耗时量级 | 通过判据 |
|---|---|---|---|---|
| T0 保存时 | 当前文件 + 强关联 | `bash scripts/test-fast.sh tests/test_xxx.py`（复跑失败加 `--lf`；稳定顺序加 `-p no:randomly`） | 秒级~1min | 全绿 |
| T1 提交前 | 改动包测试子集 | `bash scripts/test-changed.sh` | 1~3min | 全绿 |
| T2 推送前 | 全量门禁 | `bash scripts/check-gate.sh` | 5~15min | 三段全 PASS |
| T3 CI | 三 job | 现有 ci.yml（增量项见下） | 与 T2 同量级 | 全 job 绿 |
| T4 发版 | UIA 真窗 + 冒烟 | `pytest tests/uia -o addopts=`（既有约定） | 10~30min | 全绿 + log_evidence 留痕 |

**已装未用资产激活**（零新依赖）：pytest-randomly 5.0.0（乱序=免费顺序依赖检测器，失败用其打印的 `--randomly-seed=<N>` 复现）、pytest-timeout（CI 可加 `--timeout=600` 防挂死）、pytest-json-report（CI 可加 `--json-report` 供时长监控）。

**覆盖策略增量结论**：diff coverage 缓做（92%+floors 已压住藏匿空间）；变异测试不做（PyTorch/C#/GUI 混合栈成本不可承受）；rerunfailures 不装（重试即掩盖，单人当场修）。

## 四、marker 防回潮与补标

- 现状（2026-10-07 实测）：tests/ 顶层 148 个测试文件，125 个已打标，**24 个未标**（豁免清单冻结在 `scripts/check_markers.py` 的 `BASELINE_UNMARKED`，清偿一个删一个）。
- 新测试文件**必须**带 `pytestmark = [pytest.mark.unit]`（真模型/真训练用 `e2e`，触碰 cuda 追加 `gpu`）——check-gate 第 3 段强制，新增未标即红。
- 补标优先级：P0 真模型/真训练文件（`_real`/`_e2e` 后缀 → e2e+gpu）；P1 9 个 test_w*（→ unit）；P2 其余（→ unit）。

## 五、mypy 三阶段引入（复刻棘轮文化）

| 阶段 | 动作 | 退出条件 |
|---|---|---|
| **P1 摸底建基线**（约半天） | `pip install mypy types-PyYAML types-requests` 入 lock；pyproject exclude 收紧（追加 `_旧副本抢救/ unused/ dataset* weights/ deliverables/ _pb2`）；全量跑出 `scripts/mypy-stock.txt`；`grep -cE ':[0-9]+: error:' > scripts/mypy-baseline.txt`；CI 加非阻塞汇报步 | 基线数字落盘 |
| **P2 棘轮收缩**（每波一个 `chore: mypy 存量清偿 N→M`） | check-gate mypy 段转阻塞（当前 > 基线即红）；按包推进 core/project → inference/training/evaluation → exporter/serving → gui 最后；禁裸 `# type: ignore`（须带 `[具体码]`） | 基线 ≤50 进 P3 |
| **P3 新文件强制** | 基线升级为文件清单 `mypy-baseline-files.txt`：出错文件不在清单内即红（新文件零容忍）；可选新包 strict 起步；启用 pre-commit manual 钩子 | 文件清单棘轮运转 |

**版本纪律**：mypy 必须锁入 requirements.lock.txt——小版本间报错集漂移会让棘轮数字不可比；mypy 升级走专门提交 + 基线重生成。

## 六、棘轮维护 runbook（含破线处置）

**何时升**：某包覆盖率连续 2 个 W 波高于地板 ≥1pp；或新包合入（实测-1 入表）；或发版前发现地板明显低于实际。

**怎么升**：只改两个文件——pytest.ini（全局 92）+ coverage_floors.py（per-package 表，新值=近期两次实测最小值再 -0.5pp 取整）。单独提交 `chore(coverage): floor <pkg> 88→90`。

**破线分级处置**：
- **L1 统计噪声**（差 <0.5pp、重跑变绿）：重跑确认即过，不降板不记债。
- **L2 真回归**（重跑仍破线 ≥1pp）：当波内补测试修复；修不动走 L3。
- **L3 紧急放行**（发版窗口被卡，唯一合法降门禁路径）：① 开 issue 记债（原因+预计回收 W 编号）；② coverage_floors.py 该包临时降 1pp（**全局 92 永不下调**），commit 引用 issue 号；③ 下个 W 波补测试回位+关 issue。红线：单包累计下调 ≤2pp；连续两个 L3 未回收 → 冻结发版。

## 七、发版检查单增量（叠加到 docs/release-checklist.md）

```diff
 发版人工检查单（既有：门禁全量→PyInstaller→UIA→冒烟→归档）
+ [ ] 第 0 步: AI 深审本版累计 diff（bash scripts/ai-review.sh <上个tag>..HEAD）+ 自审清单档 A+B 复核
+ [ ] pre-commit: pre-commit run --all-files 全绿（等价证明钩子安装且健康）
+ [ ] pre-commit: 本 W 波无 --no-verify 提交
+ [ ] mypy: 基线无恶化（CI mypy 绿 且 baseline ≤ 上次发版记录值）
+ [ ] 棘轮: L3 破线记债 issue 全部已回收或含明确回收 W 编号
+ [ ] CI: 三 job 在发版 commit 上全绿，无 cache 冷装超时重跑
+ [ ] 归档增项: coverage_floors.py 快照 + mypy 基线文件一并归档
```

## 八、流程负担与风险对策

- **净负担**：每 commit +3~5s（pre-commit）；快跑每迭代循环 +30~60s；合计**每天 +6~10min**（<2% 开发时间）。红线：快跑 >90s 即裁范围。
- **最可能被绕过的环节**（按概率）：pre-commit 拖慢 → 快跑图省事 → 手动升地板 → mypy 基线收缩。对策：守规矩的经济学（钩子 ≤5s；`test-changed.sh` 单命令比手动挑包更省事）；pre-commit 本地红与 CI lint 等价，跳过钩子无妨但有 CI 兜底。
- **pre-commit 安装失败**：回退 check-gate.sh（等价覆盖 lint 部分）；中文路径编码问题设 `PYTHONUTF8=1`、`git config core.quotepath false`。
- **mypy 基线漂移**（改文件行数导致）：基线偏移超 ±20 条时全量重生成一次，专门 commit 注明"无类型修复，仅基线重置"。

## 九、后续 backlog（本期不做）

- .gitattributes 建立（`* text=auto` + `*.sh eol=lf`）+ 全仓 renormalize → 启用 mixed-line-ending 钩子
- flaky 隔离（`@pytest.mark.flaky` + CI 单次重试；等 UIA 真出现确定性 flaky 再议）
- diff coverage（团队扩张或地板失守时再启用）
- CI `--durations=30 --timeout=600 --json-report` 增量（一次 baseline 校准后）
- cache 预热分支 workflow（torch 升级周专用）
