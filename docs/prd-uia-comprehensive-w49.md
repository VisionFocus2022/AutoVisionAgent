# PRD：UIA 全面化 + 日志铁证 + 自动修复接线（W49 · lite）

## 定档声明

- 档位：🟡 L2（S1「创建更加全面的 UIA 方案，结合日志，能自动修复」+ S3 留痕）
- 确定性：高（取证完成——覆盖缺口/日志通道/循环契约三路实证）
- 影响半径：小（测试基建 + 新用例；生产零改动；不触硬触发器）；可逆：双向门
- 覆盖留痕：对齐 SDW v5.2 [`uia-test-creation-standard.md`]（§1.2 减量门/§5 断言纪律/§6 环境治理/§8 门控联动）

## 1. 背景与目标

现有 UIA 套件 15 用例（7 文件，exe 模式全绿）覆盖 login/label/train/eval/predict/data/user-mgmt/sam3。三缺口：①**flaw_gen/home 零覆盖**、角色门控（§8 联动类）无运行时证明；②断言仅状态栏+JSON+UIA 树，未用**应用日志铁证**（§5.1 通道三）；③未与 `uia-autofix-loop` 接线（自动修复能力缺位）。

## 2. 需求（FR）

- **FR-1 日志铁证基建**：`tests/uia/log_evidence.py`——`LogAnchor`（动作前打点，autovision.log 尾部增量轮询：`wait_line/error_lines`）+ `wait_audit_line`（AUDIT 行即时经 Python logging 落盘，jsonl 有缓冲故锚点一律打 autovision.log）；双模式落点自动解析（python=AVA_LOG_DIR 会话临时目录 / exe=dist\AutoVisionAgent\logs）。纯函数单测入主门禁。
- **FR-2 覆盖缺口用例**（`tests/uia/test_gap_flows_w49.py`，4 例）：
  a. flaw_gen 面板接线 + 诚实失败（三段 warn 状态 + 无 ERROR 日志）
  b. home 仪表盘卡片在场 + **登录审计锚点**（wait_audit_line login/admin）
  c. **operator 角色导航门控**（§8：可见 5 页/隐藏 6 页运行时证明 + operator 登录审计）
  d. deploy 导出**日志锚点深化**（导出前打点 → 「模型导出开始」行 + 进行中→失败双态 + 假模型完整闭环）
- **FR-3 自动修复接线**：失败消息含英文 "timeout"（flaky 路由）+ 三段式断言（预期/实际/定位）已达标；`uia-autofix-loop` configSnippet（runner=pytest、uiaFlavor=windows、PYTEST_ADDOPTS 适配）落本 PRD §6；本轮以「基线跑绿 + 人工分类修复演示」证明分类闸可用。
- **FR-4 环境治理**（W48 教训制度化）：conftest 会话级**提交内存预检**（<6GB 诚实整组 skip，`AVA_UIA_SKIP_ON_LOW_MEM=0` 关闭）——防并行 AI 代理僵尸 pytest 挤杀 UIA。

## 3. 验收标准（AC）

- AC-1：log_evidence 单测全绿（打点/尾部/审计解析/双模式解析）；主门禁零回归。
- AC-2：4 新用例 exe 模式全绿（含审计锚点命中）；存量 15 例不回归。
- AC-3：PRD §6 含可直接使用的 autofix-loop 运行配方；本波任何失败均按 deterministic/flaky 分类处置留痕。

## 4. 范围

**In**：上述四文件 + conftest 预检。**Out**：flaw_gen 真实生成流（需 GAN 权重）、home 数据正确性深测、settings 深路径、全量 autofix-loop 驱动跑（留待首个真实红灯波次）。

## 5. 风险与假设（三栏）

- 已知：AUDIT 行即时进 autovision.log（audit_logger.log() 同步 `_logger.info`）；operator 矩阵=home/label/data_manage/predict/eval+login；假模型导出全链确定性失败（占位字节→torch.load 异常→_on_export_failed）。
- 假设：admin/operator 登录审计 action=login 且 user=用户名（离线实证 user=offline；不中即修断言=auto-fix 演示）。
- 反目标：不断言像素；不放宽断言凑绿；日志锚点不打 jsonl（缓冲时序不可控）。

## 6. autofix-loop 运行配方（接线交付物）

```bash
# 循环消费形态（uia-autofix-loop windows flavor，pytest-json-report 已装 1.5.0）
export PATH="$PWD/.venv/Scripts:$PATH"
PYTEST_ADDOPTS="tests/uia -o addopts= --json-report --json-report-file=.autofix-loop/report.json \
  --timeout=600" <uia-autofix-loop 驱动器>   # 分类闸：deterministic→自动修；timeout 类→flaky 路由
```
纪律（§7 对齐）：Bash 10min 硬顶→run_in_background；验收红逐个新鲜复验；I4 主会话不读原生报告。

## 7. 门禁（S1/S3 留痕）

探索=S1 指令+三栏闭环（覆盖矩阵/日志 flush 时机/循环契约/账号种子钩子全实证）；PRD=本文档；收尾=AC 回填+全量 UIA+主门禁。
