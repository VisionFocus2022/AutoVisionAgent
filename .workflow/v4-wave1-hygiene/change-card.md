# 变更卡: v4 第一波三动作（W23）——仓库卫生收口 + 测试态日志隔离 + eval score/boxes 防御

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-19 |
| **档位** | L1 ×3（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | v4 架构审查 §9 第一波三动作（docs/AutoVisionAgent-架构解析与优化方案-v4.md P2-1/P2-1c/P3-3）；实施前 3 调查员并行取证（wf_a3d23b7a：卫生破坏面/日志四通道机制/score 防御设计）；行为可测、范围局部、无硬触发器 |

### What（改了什么）
- **动作 1 仓库卫生（P2-1 a/b）**：.gitignore 追加 5 条（.autofix-loop/、_i18n_report.txt、_missing_keys.txt、.benchmarks/、configs/initial_credentials.txt）+ 决策注释（.workflow/ 为有意审计轨迹保持跟踪）；`git rm --cached` 9 个瞬态文件（留盘转未跟踪+忽略）；`git rm` 删除 .workflow/wave11-arch-uia/extract_digest.py（含外部会话绝对路径的一次性脚本，零引用实证）。
- **动作 2 测试态日志隔离（P2-1c）**：引入 AVA_LOG_DIR 环境变量约定（env > config，生产不设 env 行为逐字节不变），四写入方统一接线——gui/main.setup_logging（env 覆盖 log_dir）、serving/server._resolve_log_dir（env 优先）、core/audit_logger._resolve_audit_dir、core/detection_history._resolve_history_dir（常量改函数）；根 conftest.py 收集前 setdefault 指向会话临时目录 + sessionfinish 清理；同波：misc_pages/serving_server 两处既有用例加 delenv（显式测生产行为）；tests/uia/conftest.py exe 分支剥 env（exe 日志保持落 dist 供 UIA 排查）。
- **动作 3 eval 防御（P3-3，附带统一）**：evaluation/eval_flow.py build_prediction 两处裸取改 getattr——score（缺属性 AttributeError/score=None TypeError 均逃出 except 元组炸整场评估→回退 0.0）与 boxes（同族同逃逸路径→与 boxes=None 同走 GT 回退）；:137 异常元组不动（防御收口在取值处）。

### Why（为什么改）
- v4 审查终版唯一 P2（公开仓明文凭据 .gitignore 缺口 + 9 瞬态文件被跟踪 + 日志污染 1,904→1,990 行加重）与对抗工程师新发现 P3-3；用户指令"根据建议实施下一步"= §9 第一波三动作（合计原估 <1 人日）。
- 日志污染机制（调查员实证）：tests/test_gui.py:210 调 main() 挂仓库 logs RotatingFileHandler 且零清理 + serving._resolve_log_dir CWD 相对 + audit/history 仓库绝对路径单例——四通道，monkeypatch 窄方案够不着子进程与单例，env 约定一处全覆盖。

### Files（涉及文件）
- .gitignore — 追加 8 行（5 条目 + 注释）
- conftest.py — 重写（+env 接线 +sessionfinish）
- gui/main.py — 修改（setup_logging env 覆盖，+5 行）
- serving/server.py — 修改（_resolve_log_dir env 优先，+6 行）
- core/audit_logger.py — 修改（常量→_resolve_audit_dir 函数）
- core/detection_history.py — 修改（+import os；常量→_resolve_history_dir 函数）
- evaluation/eval_flow.py — 修改（两处 getattr 防御）
- tests/test_eval_flow.py — 修改（+3 用例：缺 score/score=None/缺 boxes）
- tests/test_w23_log_isolation.py — 新建（5 用例）
- tests/test_w23_repo_hygiene_meta.py — 新建（2 元守卫用例）
- tests/test_gui_misc_pages.py / tests/test_serving_server.py — 修改（各 +delenv 3 行）
- tests/uia/conftest.py — 修改（exe 分支 env 过滤，+4 行）
- git 索引 — 10 文件出库/删除（9 --cached + 1 rm）

### Verify（怎么验证）— 门禁三件套 + 冻结验收
- **命令**：三段 RED→GREEN 单文件复跑 + 全量 `python -m pytest`
- **预期与实得**：RED 3+4+2=9 failed（异常形态原样暴露）→ GREEN 全转绿；终版全量 **976 passed / 4 skipped / 93.06% / rc=0**（966 基线+10 严丝合缝，覆盖率 93.05→93.06）
- **日志冻结验收（动作 2 专属）**：全量门禁前后 logs/ 四文件（autovision.log/serving.log/audit_20260819.jsonl/history_20260819.jsonl）mtime+字节+行数**逐字节一致**（此前单场门禁写入数千行）；正向去向实证 %TEMP%\ava-test-logs-*\autovision.log
- **不达标分支**：回滚对应文件即恢复旧行为（三动作相互独立）

### Rollback（如何回滚）
- 动作 3：还原 eval_flow.py 两处；动作 2：还原 7 文件（env 约定生产零行为变化，回滚纯测试态）；动作 1：`git restore --staged` + 提交恢复跟踪（9 文件仍在盘）。

### 启动条件
- [x] 实施前 3 调查员并行取证完成（wf_a3d23b7a，268.9k tokens/83 工具调用）；RED 先行（9 failed 实测在案）
