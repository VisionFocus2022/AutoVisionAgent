# AutoVisionAgent 补救计划（架构审查 2026-08-24）

> 关联：`architecture-review.md`（发现 AVA-R1..R7）· `risk-map.dot`
> 排序原则：爆炸半径 × 业务影响 × 可逆性 × 工作量。所有者假设：单人维护者（无团队分工）。
> 每项含验收门禁——不满足验收不得宣称完成（对齐项目"发版宣称核销"制度）。

## P1 · 本周内（交付链止血）

### P1-1 打包环境机械防呆（AVA-R1）· 预估 0.5 天

**动作**：
1. `autovisionagent.spec` 头部加构建期断言：`sys.prefix` 必须含 `.venv`（否则 `sys.exit` 报错指明 R01 入口）；`import torch, numpy, cv2` 探针失败即中止。
2. 打包后冒烟脚本（可并入发版检查单）：exe 启动 + `--version`/引擎注册表探针（或 UIA 既有冒烟用例 T1 复用）。

**验收**：
- [x] 用系统 python 跑 `python -m PyInstaller autovisionagent.spec` → 立即失败并输出可读原因（2026-08-31 实测：Python39 ~0.2s `[BUILD-ABORT]`，退出码 1）
- [x] 用 `.venv` 打包 → 成功且冒烟通过（全链路 ~5.9min，exe 84.3MB/dist 6.36GiB；断言为构建期代码不改 bundle，无需 UIA 冒烟）
- [x] R01 规则文件同步登记该防呆（规则→机制的闭环）（sys 记录：`20260831_rule_spec-build-env-guard.md`）

### P1-2 推送 + CI 首跑验证（AVA-R2）· 预估 0.5 小时

**动作**：`git push giteu/github` 双发 feature 分支（或先合 master 再推）；观察 ci.yml 首跑（test + dotnet-test 双 job）。

**验收**：
- [ ] `git branch -r` 含 feature 分支
- [ ] GitHub Actions / Gitee 流水线出现本分支运行记录且绿；若红，修复后留档（这正是 CI 存在的意义）
- [ ] ci.yml 第 2 行过时注释（"本仓当前无 git 远程"）更新

## P2 · 两周内（守卫补强）

### P2-1 重建 dist-lite + 棘轮硬化（AVA-R3）· 预估 0.5 天

**动作**：
1. `.venv/Scripts/python.exe scripts/make_lite_dist.py` 重建 lite。
2. 评估将 test_w19_lite_dist 的 skip 语义收窄：`dist/ 存在且为本次构建 → lite 必须存在`（例如以 dist 构建时间戳/manifest 对齐判定），或至少在发版检查单加硬核销项。

**验收**：
- [ ] dist-lite 存在且 <2GiB（棘轮测试非 skip 而是 pass）
- [ ] `pytest -rs` 确认 lite 相关 skip 归零

### P2-2 覆盖缺口定向补测（AVA-R6）· 预估 1-2 天

**动作**：聚合 term-missing 报告，识别 668 缺口 top 模块；优先补"发布包 + gui 交互路径"缺口；纯脚本/死代码走 .coveragerc omit 或删除而非硬凑覆盖。

**验收**：
- [ ] 覆盖率 ≥93.5%（恢复 ≥1.5pt 缓冲）
- [ ] fail-under 棘轮不动（92），并留档缺口分布结论

### P2-3 完整 dist 体积棘轮（AVA-R5）· 预估 0.5 天

**动作**：仿 lite 棘轮新增守卫测试：`dist/ 存在时 <7GiB`（当前 6.36GiB + ~10% 余量）；先做体积构成分析（top-20 目录），确认 6.36GiB 中是否有可清项（对齐 v2.1.0 PYZ 清场先例）。

**验收**：
- [ ] 新守卫测试入主门禁（dist 缺失时 skip 同 lite 语义）
- [ ] 体积构成分析留档 docs/benchmarks/

## P3 · 一个月内（流程性改进）

### P3-1 UIA 定期化（AVA-R4）

夜间/发版 tag 触发的 UIA job（需自托管 windows runner + 桌面会话）；无 runner 条件下退化为"发版检查单强制项 + 每次 spec/页面结构变更后手动跑"并登记执行记录。

### P3-2 spec 清理 user_settings.json 打包（AVA-R7）

从 spec datas 移除该条件条目；首启默认值走代码路径。验收：构建产物内无 configs/user_settings.json，exe 首启为主题/语言默认态。

### P3-3 5 skip 归因 + 未知项清账

对齐报告 §4 未知表：`pytest -rs` 枚举；CI 首跑结果回填；.NET 客户端生产使用状态问询留档。

## 依赖与顺序

```
P1-2 (推送+CI) ──┐
                 ├─→ P2-1 (lite 重建依赖最新 dist 已定)
P1-1 (打包防呆) ─┘        └─→ P2-3 (体积棘轮依赖 lite 归位后的产物全貌)
P2-2 (补测) 可与 P1 并行
P3 全部串行尾随
```

## 维护注记

- 本计划文件与 architecture-review.md 同目录维护；每完成一项在对应复选框打勾并在 RELEASES.md/工作日志留档。
- 风险图 `risk-map.dot` 中风险节点消项后改为灰色 `fillcolor="#e2e8f0"` 并标 `已消`，不删除节点（保留审查轨迹）。
