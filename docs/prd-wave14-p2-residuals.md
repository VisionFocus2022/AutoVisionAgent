# PRD — wave14-p2-residuals：P2 级残留修复 + 覆盖尾巴收敛

> L2 档。G1/G3 证据 = 用户指令原文（2026-08-17）：「继续实施优化 P2 级残留与依赖门控尾巴」。
> 候选来源：docs/AutoVisionAgent-架构解析与优化方案-v2.md P2 清单（P2-1..27）+ pytest.ini 尾巴注释。

## 范围（六簇，文件所有权互斥）

| # | v2 编号 | 内容 |
|---|---|---|
| C1 | P2-9 | eval 页无 TP/FP/FN 时不再展示编造的完美混淆矩阵（[[1,0],[0,1]]），ConfusionMatrixWidget 增"无数据"空态；seg/IoU 类指标跑分不再呈现虚构完美结果 |
| C2 | P2-15+P2-16 | deploy worker 线程读 QWidget（task_value）改主线程预读传参；thread_bridge._to_qarg 支持 None/tuple/numpy 标量（offscreen 实测过 TypeError），invokeMethod 返回 False 时 logger.warning |
| C3 | P2-13+P2-11+P2-18+P2-17+P2-23 | 静默 except 重点 5 处补日志（ListTasks/Release/serialization×2/home 历史/warmup）；死代码清理（register_into_container 断链删除、run_m3_verification 幽灵引用）；server docstring 示例 0.0.0.0→127.0.0.1；login 初始密码 print 删除 + 角色字面量 tr() 化；log_train_complete 接线到训练完成；补 ADR-0001（serving 回环锁定决策） |
| C4 | P2-24+尾巴 | .coveragerc omit proto 生成码（结构性噪声 78 miss，注明理由）；shm/generic_trainer/generative_metrics 剩余 miss 补测；W13 验证员跟进（predict_tail 测试打桩目标注入化）；可选装 onnxsim+onnxconverter-common 解 exporter 门控（装失败诚实跳过） |
| C5 | P2-12+P2-14+P2-10 | gui/pages/__init__ 补 FlawGenPage（消除 main.py deep import 双真源）；QLockFile 单实例互斥（双开提示并退出）；动态导入四方一致守卫测试（modes/engines 列表↔目录↔spec hiddenimports）+ canvas.py:220 冗余动态导入改静态 |
| C6 | P2-4(C#)+P2-8 | C# 客户端启动清扫陈旧 ava_*.bin（与 python F1 同语义）+ File.Delete 空 catch 接 NLog；零样本死线诚实化：list_all_tasks 去 zero_shot 条目（C# 测试同步）+ vision_dispatcher docstring 修正 + label 页回退 except 加 warning |

## 非目标（记偏差）

- P2-1/P2-2/P2-3：线程模型三套并存收敛 + 退出守卫/线程生命周期 —— 量大，独立专题波。
- P2-19 gui 操作日志铺开、P2-26 CI、P2-21 setuptools CVE 升级（环境 churn）、P2-22 DataManagerExt 死代码裁决、P2-27 offscreen 集中兜底（有误伤 UIA 真窗的风险）。
- P2-5 git tag（发版检查单职责）、P2-20 serving 文件日志（可与 P2-19 同波）。

## FR / AC

- **FR-001**（C1）eval 展示诚实化；**FR-002**（C2）线程契约修复；**FR-003**（C3）静默异常可观测 + 死代码清零 + 杂修；**FR-004**（C4）覆盖尾巴收敛（结构性 omit + 补测）；**FR-005**（C5）注册表统一 + 单实例 + 打包守卫；**FR-006**（C6）跨语言清扫与能力广告诚实化；**FR-007** 验证与交付（对抗验证全 accept、门禁 rc=0 棘轮按实测地板、C# dotnet test 全绿、state complete + validator 0 + 提交 + 记忆）。
- **AC-001** 无 TP/FP/FN 指标时矩阵区显示空态标识而非 [[1,0],[0,1]]（offscreen 断言）；**AC-002** deploy 线程 target 参数化（不读控件）+ thread_bridge 四载荷类型直调不再 TypeError、False 返回有 warning（RED 先行）；**AC-003** 五处补日志经 caplog 断言、register_into_container 删除后全仓无引用、ADR 存在；**AC-004** proto 生成码移出门禁分母（.coveragerc 注明理由）、三模块剩余 miss 下降或说明不可测边界；**AC-005** 11 页注册表单源 + QLockFile 二次启动被拒（离屏可测）+ 守卫测试对 modes/engines/spec 四方一致（人为制造不一致的探针用例证明守卫可红）；**AC-006** dotnet test 全绿 + python 门禁全绿 + ListTasks 不再含 zero_shot；**AC-007** 验证层全 accept 或闭环、门禁棘轮不降（升门按实测地板）、validator 0。

## 风险

- .coveragerc omit 会被视为"棘轮作弊"——必须只 omit 生成码（*_pb2*.py）并在偏差记录 omit 前后分母/miss 数对比；生产码一行不 omit。
- ListTasks 契约变化需同波 C# 测试同步并跑 dotnet test（跨语言闭环）。
- QLockFile 单实例不得误伤 UIA 测试（uia conftest 先杀残留进程再启动——顺序上安全，验证员复核）。
