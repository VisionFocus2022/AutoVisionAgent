# PRD — wave12-p0p1-fixes：P0-1 巨石函数拆分 + 六项 P1 修复

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）：「实施下一波候选」。
> 候选 = W11 交付总结明示：P0-1 拆巨石函数；P1 修复清单（shm reaper、训练保存失败上抛、
> 审计 flush、FID sqrtm 对称化、lock 补 index-url+README、RCE 回退 3 用例）。

## 背景

W11 架构审查 v2（docs/AutoVisionAgent-架构解析与优化方案-v2.md）终版 P0×1/P1×7/P2×27。
本波实施其中的 P0-1 与六项可独立落地的 P1（P1-2 config 双体系收敛需用户决策实装还是删除，本轮不做，留待用户选择）。
安全网：门禁 659 测试（覆盖 89.35%，fail-under=89）+ UIA 6 真窗用例（exe 重打包后回归）。

## 目标（对照 v2 缺点编号）

| # | v2 编号 | 内容 | 方式 |
|---|---|---|---|
| 1 | P0-1 | 9 个 >100 LOC 巨石函数拆分（train._build_ui=147 / eval_._run_eval=141 / data_manage._build_ui=133 / label._build_ui=118 / generic_trainer.fit=118 / predict._build_ui=115 / eval_._work=115 / theme._build_qss=109 / shell._build_shell=103） | 行为保持重构（AST 复测拆后均 ≤100） |
| 2 | P1-1 | serving/shared_memory：启动清扫陈旧 ava_*.bin + 区域数上限 | TDD RED |
| 3 | P1-3 | generic_trainer 最终权重 save 失败上抛（假成功→真失败） | TDD RED |
| 4 | P1-4 | audit_logger atexit flush + shell.closeEvent 显式 flush + deploy:222 except-pass 补日志 | TDD RED |
| 5 | P1-5 | FID sqrtm：eigh 前对称化，消除恒低估 ~2.5 倍 | TDD RED + scipy 对照 |
| 6 | P1-6 | requirements.lock.txt 补 --extra-index-url + 新建 README.md | 文档/配置 |
| 7 | P1-7 | _extract_state_dict_safe 三用例（正常 zip/恶意 pickle/非 zip） | 纯补测 |

## 功能需求（FR）

- FR-001 巨石函数拆分：9 函数全部 ≤100 行（AST 口径 end_lineno-lineno+1），行为保持——不改任何既有测试断言，objectName/信号接线/控件构造顺序不变；eval_._run_eval/_work 的业务逻辑抽为 evaluation 层纯函数并新增直测。
- FR-002 shm 生命周期：SharedMemoryManager 启动时清扫陈旧共享内存文件（按 mtime 年龄阈值），活跃区域数上限（超限明确报错或回收已释放条目），全程有测试。
- FR-003 训练保存失败上抛：最终权重 save 异常使 fit 抛出（TrainWorker failed 路由接管）；best-checkpoint 失败保留 best-effort 但决策写注释。
- FR-004 审计可生存性：get_audit_logger 注册 atexit flush；shell.closeEvent 退出前显式 flush；deploy 审计写入失败 logger.warning 不再静默。
- FR-005 FID 数学修复：sqrtm 对非对称协方差积先对称化再 eigh；同分布 FID≈0 性质测试 + scipy.linalg.sqrtm 参考对齐 + 非对称积不再系统性低估的回归测试。
- FR-006 构建可复现：lock 头部补 --extra-index-url https://download.pytorch.org/whl/cu121；README.md 含 clone→venv→pip install -r requirements.lock.txt→pytest 最小路径与 UIA/发版指引链接。
- FR-007 RCE 回退覆盖：3 个直测用例覆盖 _extract_state_dict_safe 成功提取/恶意 pickle 拒绝/非 zip 拒绝。
- FR-008 验证与交付：逐簇对抗验证（复跑+行为保持审查+RED 文件级 stash 复现+假绿猎杀+越界检查）；门禁全量 rc=0 且棘轮不降（若覆盖上升则升门）；exe 重打包 + UIA 6 用例真窗回归；state complete + validator 0 + 提交 + 记忆。

## 验收标准（AC）

- AC-001（FR-001）：AST 复测 9 函数均 ≤100 行；`.venv/Scripts/python.exe -m pytest` rc=0 且覆盖率 ≥89；git diff 无任何 tests/ 既有断言修改（新增测试文件/用例允许）。
- AC-002（FR-002）：RED→GREEN 证据齐（清扫前测试红）；陈旧文件清扫与上限各有独立断言；C# 侧清扫不做（偏差记录，v2 P1-1 的 C# 部分留待后续）。
- AC-003（FR-003）：RED 先行证明当前吞异常；修复后 fit 抛出且离屏测试证明 failed 路由可接管（或已有测试覆盖该路由并注明）。
- AC-004（FR-004）：atexit 注册可被测试证明；closeEvent flush 有调用证据；deploy warning 经 caplog 断言。
- AC-005（FR-005）：同分布 FID≈0（容差内）；修复值与 scipy 参考对齐（相对误差 <1e-9 量级或说明近似来源）；30 种子抽查不再恒低于参考。
- AC-006（FR-006）：lock 首部含 index-url 行；README 存在且步骤可执行（命令与真实路径一致）。
- AC-007（FR-007）：3 用例直调 _extract_state_dict_safe 全绿。
- AC-008（FR-008）：验证层全 accept 或 needs_fix 已闭环；UIA 在重打包 exe 上 6/6；棘轮不降；validator 返回 0。

## 范围与非目标

- 非目标：P1-2 config 双体系收敛（需用户决策实装/删除）；shm C# 侧启动清扫；P2-9/P2-10/P2-12 等旧残留；覆盖率大幅提升（只随修复自然变化 + RCE 用例）。
- 风险：重构回归——由 659 门禁 + UIA 真窗 + 对抗验证行为审查兜底；并行簇文件所有权互斥（见 tasks 表），验证员 RED 复现只允许文件级 `git stash push -- <file>`。
