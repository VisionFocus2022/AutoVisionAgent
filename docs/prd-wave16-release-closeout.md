# PRD — wave16-release-closeout：发版收尾（jobs 跟进 + exe 重建 + UIA + tag）

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）：「继续实施剩余工作」。
> 范围 = W15 交付总结列出的发版检查单域剩余项。

## FR / AC

- **FR-001** J1 验证员三条非阻断建议：run_job start 失败回滚注册表（RED 先行）+ 无 join 替换线程在册用例 + rude 用例断言收紧。
- **FR-002** 门禁全量 rc=0 且覆盖率 ≥92（代码微变后回归）。
- **FR-003** exe 重打包（含 W13-W15 全部改动：settings_io/session/jobs 注册表/退出守卫/审计归属等）。
- **FR-004** UIA 6 用例真窗复跑（发版检查单第 3 步形态：专用进程 + 新 exe）。
- **FR-005** 归档：dotnet bin 下被跟踪 dll/pdb 出库（git rm --cached）+ git tag v2.0.0（与 pyproject 一致）+ 冒烟人工项说明留置。
- **FR-006** state 终态 + validate + 提交 + 记忆。

**AC-001** start 失败用例 RED→GREEN 且注册表零泄漏（消费方回归 27 passed）；**AC-002** 门禁 rc=0 覆盖 ≥92；**AC-003** dist exe 时间戳更新（晚于 87e19a3）；**AC-004** UIA 终态 6/6（或环境阻塞时诚实记录诊断与建议，不得宣称通过）；**AC-005** git ls-files 无 bin/ 产物 + tag 存在且指向本波提交；**AC-006** validator 0。

## 非目标

冒烟清单人工项（发版检查单第 4 步，需人工点检 UI 观感）；CI 真跑（无远程）；exe 外发。

## 风险

UIA 环境性超时复发（W14 教训：混合进程 COM 失效/登录层超时）——按专用进程形态跑，失败则诊断记录为阻塞而非伪装通过。
