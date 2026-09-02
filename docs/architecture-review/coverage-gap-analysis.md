# 覆盖缺口与门禁基线分析（AVA-R6/R3/R5 取证 · 2026-09-01）

> 关联: [prd-remediation.md](prd-remediation.md) FR-004/AC-009 · [architecture-review.md](architecture-review.md) §4 未知表
> 数据源: `.workflow/ava-remediation/gate-baseline-20260901.log`（主门禁全量输出，RC=0）
> 取证脚本: `.workflow/ava-remediation/parse_gaps.py`

## 1. 主门禁基线（改动前 · 2026-09-01）

| 项 | 实测 | 与审查报告（08-24）对照 |
|----|------|------------------------|
| 结果 | **1222 passed / 5 skipped / 0 failed**，90.62s，RC=0 | 一致 |
| 覆盖率 | **92.87%**（668 miss / 9369 语句），fail-under 92 达标 | 一致 |
| 解析复核 | 119 文件逐行聚合 = 9369/668，与 TOTAL 严丝合缝 | — |

## 2. 5 个 skip 归因（审查 §4 未知项 #2 回填）

**结论：5/5 全部为设计内的 opt-in/环境门控，无一是 lite 守卫——审查"大概率含 lite 守卫"的推测证伪。**

| 位置 | 理由 | 定性 |
|------|------|------|
| tests/test_engine_abdet_real.py:293 | PatchCore 真实拟合→推理随训练流水线（M1-B），引擎层构造/错误路径/解析已覆盖 | 设计内显式 skip |
| tests/test_exporter_deep.py:238 | onnxsim 已安装 → ImportError 分支不可达 | 环境门控（已装即跳） |
| tests/test_exporter_deep.py:256 | onnxconverter_common 已安装 → ImportError 分支不可达 | 环境门控（已装即跳） |
| tests/test_sam3_adapter.py:382 | 未设置 AVA_SAM3_DIR（opt-in 真权重冒烟） | opt-in 权重门控 |
| tests/test_sam_adapter.py:300 | 未设置 AVA_SAM_CKPT（opt-in 真权重冒烟） | opt-in 权重门控 |

**对 AC-007 的修正**：lite 相关 skip 本来就是 0（产物守卫在产物存在时直接跑，见 §4），"lite skip 归零"天然满足；本表即为"其余 skip 逐项归因留档"的交付。

## 3. 668 缺口分布（审查 §4 未知项 #3 回填 · AC-009）

**按顶层模块聚合**（gui+labeling = 402/668 = **60%**，与 P2-2"优先补发布包+gui 交互路径"方针吻合）：

| 模块 | miss | 模块 | miss |
|------|------|------|------|
| gui | 260 | serving | 23 |
| labeling | 142 | industrial_vision_platform | 22 |
| core | 61 | inference | 15 |
| dataset | 43 | evaluation | 6 |
| project | 39 | training | 0 |
| models | 29 | exporter | 28 |

**最大单文件（miss≥15）**：

| 文件 | miss/stmts | 备注 |
|------|-----------|------|
| gui/pages/label/sam_session.py | **63/129** | 本分支 SAM3 会话新代码，缺口最大且最该补 |
| dataset/vision_dataset.py | 28/89 | |
| exporter/supervised_exporter.py | 28/142 | |
| gui/pages/label/page.py | 25/469 | |
| labeling/batch_tools.py | 25/131 | |
| labeling/geometry.py | 25/95 | |
| core/detection_history.py | 23/113 | |
| gui/pages/data_manage/page.py | 23/475 | |
| core/interfaces_supervised.py | 20/233 | |
| gui/pages/settings/page.py | 19/139 | |
| industrial_vision_platform/vision_dispatcher.py | 19/109 | |
| gui/main.py | 18/161 | |

**补测量化目标**（AC-008：≥93.5%，fail-under 92 不动）：
- 需 miss 668 → ≤609（**净补 ≥59 条**即达标）；到 94.0% 需 ≤562。
- 建议首批：sam_session(63) + vision_dataset(28) + supervised_exporter(28) + label/page(25) + batch_tools(25) + geometry(25) = 194 条池，按可测性取 80-120 条 → 预计落点 93.6-94.0%。
- 死代码/纯脚本缺口走 .coveragerc omit 或删除，不硬凑（处置结论随 T5 执行补记于此）。

## 4. 双产物体积实测（AVA-R3/R5 事实更新 · 2026-09-01，产品字节口径，排 __pycache__/*.pyc）

| 产物 | 实测 | 判定 |
|------|------|------|
| dist/AutoVisionAgent（完整版） | **7.588 GiB / 7,622 文件** | 审查时 6.36GiB → 08-31 重打包后又涨；**<7GiB 拟设阈值已失效，AC-010 须重定**（建议 8.5GiB 或待 T6 构成分析后定） |
| dist/AutoVisionAgent-lite | **1.980 GiB**（marker total_bytes 2,125,869,985；replaced torch/torchvision；derived 2026-08-31T02:20:18Z） | **<2GiB ✓，余量 ≈20.6MiB**；棘轮守卫随产物存在直接执行且 pass（test_w19_lite_dist.py 14 passed，非 skip） |

**AVA-R3 定性修正**：审查所查目录 `dist-lite/` 为错误路径（真实产物路径 `dist/AutoVisionAgent-lite/`，RELEASES.md 头部即此口径）；产物实际存在且守卫绿——**"产物缺失+棘轮 skip 盲区"不成立**，AVA-R3 建议回填为证伪（回填动作在 Task 9 统一执行）。

## 5. 打包防呆反测证据（AVA-R1 / AC-001 · 2026-09-01）

- 环境：`C:\Users\888\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`（**2026-08-24 事故同款解释器**，Python 3.11.15 + PyInstaller 6.21.0）
- 命令：`python -m PyInstaller autovisionagent.spec --noconfirm`
- 结果：**RC=1，564ms 即退出**（<5s，Analysis 前拦截），输出含 `[BUILD-ABORT]`×1、`.venv`×5、当前/期望解释器对照与 R01 入口指引（log：`.workflow/ava-remediation/guard-negative-test.log`）
- 正测旁证：08-31 完整 dist 即以 `.venv` 成功打包（lite 同源派生成功）；最终重打包合并 Task 7 后于 Task 9 执行
- 回归：tests/test_w26_spec_packaging.py + tests/test_dynamic_import_guard.py = **14 passed**（AST 守卫不受 spec 可执行断言影响）
