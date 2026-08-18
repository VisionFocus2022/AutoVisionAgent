# v3 第二波可测化解耦 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-17 | 档位: L2 | 四维分档依据: 见 `.workflow/wave18-v3-wave2/state.json`（reversible / module / test_visible / low）
> 来源: 架构审查 v3 报告 §9 第二波第 7-13 项 + 用户四项拍板（dispatcher=承认 registry 直连；角色=枚举化+诚实文档；CI=ci.yml 升级、首跑属用户侧；范围=主体+P3 全做）。

## 1. 背景与目标

- **背景**：W17 止血波已消除两条 P1 与异常路由系统性失配。第二波处理 v3 的 P2 主体：退出链"有界停机承诺被析构阶段打破"（P2-3）、dispatcher 在 GUI 进程从未接线的架构不一致（P2-7）、角色 tr() 字面量持久化与 license/chmod 不诚实表述（P2-8）、serving 非回环无告警（P2-9）、巨石治理（P2-10），外加六件 P3 观察项与 CI 配置就绪。
- **目标**：
  1. 退出链兑现承诺：批量任务可被注册表 cancel 停止、TrainWorker 析构崩溃窗口消除、超时路径语义明确；
  2. 架构单源：registry 直连成为 GUI 正式形态（dispatcher 降级 serving 专用），_EngineStub 消灭；
  3. 角色持久化 i18n 安全 + 认证文档与实现一致；
  4. serving 越界有告警、巨石治理落地、P3 六件清零、CI 配置就绪。

## 2. 功能需求 (FR)

- **FR-001**: 退出链补完 — predict 批量 worker 声明 `cancel` 参数并联检查（注册表 Event 与页面 `_batch_cancel` 任一置位即停，≤1 批粒度）；TrainWorker 构造去 parent + finished 信号接 deleteLater；closeEvent 训练线程超时路径落明确告警日志（"未在 1.5s 内停止，将随进程退出被强制终止"）；train 页补训练开始/完成的 INFO 级操作留痕（P3①） | P0
- **FR-002**: registry 直连正式化 — label 页零样本 dispatcher 回退桥删除（改为诚实报错/状态提示）；`exporter.export_onnx` 改签名为按需载荷（如 `(model, task_value, path, precision)`）消灭 deploy 页 `_EngineStub`；gui 包内 `get_dispatcher`/`VisionModelDispatcher`/`industrial_vision_platform` 引用清零（源码守卫）；vision_dispatcher 与 gui 侧注释同步声明"dispatcher=serving 专用、GUI=registry 直连"的正式架构；deploy/generic_trainer 两处 torch.load 直调加层次说明注释（需完整模型对象、weights_only=True 安全等价，P3④） | P0
- **FR-003**: 角色枚举化 + 诚实文档 — users.json 持久化改稳定枚举 admin/engineer/operator；读取端兼容迁移中文旧值（{"管理员":admin,"工程师":engineer,"操作员":operator}，未知回退 operator）；角色下拉显示 tr() 名、userData 存稳定枚举；login_success 传播稳定枚举；login QTimer 死导入删除（P3②）；license 离线模式 docstring 与 release-checklist 改诚实表述（存在性检查+确认框，单工位无签名校验）；os.chmod 注释改 Windows 实况说明 | P0
- **FR-004**: serving 非回环告警 — serve()/create_server() 对非回环 host（非 127.0.0.1/localhost/::1）打 WARNING（引用 ADR-0001）| P1
- **FR-005**: 巨石治理 — det_map 按职责拆内部函数（全部 ≤100 行）；_extract_state_dict_safe 加"有意豁免"注释（安全内聚单元，声明 195 行形态为审慎选择）；本波文档与状态禁用"清零"式宣称 | P1
- **FR-006**: P3 清扫剩余件 — serialization 部分失败回滚（masks 区域已建而 keypoints 写失败时释放已建区域，⑤）；run_generative_eval 样本帽参数化（max_images 默认 20，run_eval_task 透传，⑥）；spec 图标死条件删除并注释补图标方式（③） | P1
- **FR-007**: CI 就绪 — ci.yml 加 pip cache、加 dotnet test job（windows-latest 自带 .NET 8）、注释说明 cu121/cpu 索引权衡与首跑前置（需 git remote）。**真实首跑属用户侧动作，不在本波验收内** | P2

## 3. 验收标准 (AC)

- **AC-001**: 置位注册表 cancel Event 后，predict 批量 worker 在 ≤1 个批次粒度内退出（测试：FakeThread/真线程 + Event 置位断言循环 break） [FR-001]
- **AC-002**: TrainWorker 以无 parent 构造且 finished 触发 deleteLater（源码断言 + 行为测试不崩）；closeEvent 超时路径日志含"强制终止"语义（caplog） [FR-001]
- **AC-003**: gui 包内 `industrial_vision_platform|get_dispatcher|VisionModelDispatcher` 引用 = 0、`_EngineStub` = 0（源码守卫测试）；serving 侧 dispatcher 用例零回归 [FR-002]
- **AC-004**: exporter 新签名直测通过；deploy 导出流程改造后（含 W17 的 ModelExportError 用例）回归全绿 [FR-002]
- **AC-005**: 旧中文角色 users.json 读取后内部值为稳定枚举（迁移测试）；语言切到 en_US 后角色显示为英文且持久值不变；新注册写入的 role 字段为枚举字符串（json 断言） [FR-003]
- **AC-006**: release-checklist 与 login docstring 不再宣称"验证 License 文件"（表述与实现一致）；chmod 注释不再宣称"仅所有者可读写" [FR-003]
- **AC-007**: create_server(host="0.0.0.0") 触发 WARNING（caplog，消息含 ADR-0001 或回环提示）；host="127.0.0.1" 不告警 [FR-004]
- **AC-008**: AST 实测 metrics_supervised.py 全部函数 ≤100 行且 det 指标既有用例数值零回归（锚定用例不变绿）；_extract_state_dict_safe 含豁免注释 [FR-005]
- **AC-009**: 故障注入：keypoints 写 shm 失败时已建的 masks 区域被释放（区域计数回落/文件删除断言） [FR-006]
- **AC-010**: run_generative_eval 支持自定义 max_images（传 5 时 fid 收到 ≤5 张，mock 断言）；spec 无死图标条件且含补图标说明注释 [FR-006]
- **AC-011**: ci.yml 为合法 YAML（yaml.safe_load 解析通过）、含 pip cache 配置与 dotnet job、注释含首跑前置说明 [FR-007]
- **AC-012**: 全量门禁 rc=0 且覆盖率 ≥92；dotnet test rc=0；AST 复测 >100 行函数清单不含本波新增；状态验证器 rc=0 [全局]

## 4. 范围

- ✅ **In Scope**: FR-001~007 全部及对应测试；gui/dispatcher/exporter/login/serving/metrics/serialization/eval_flow/spec/ci.yml 注释与文档同步。
- ❌ **Out of Scope**: CI 真实首跑（需用户提供 git remote 并推送）；按角色 setEnabled 的页面权限模型（第三波）；多类评估语义；密码入日志（P2-2，第一波未选项）；lock↔freeze 6 包漂移补齐；exe 重打包与 UIA。

## 5. 风险与假设

- **风险**:
  1. exporter 签名变更影响面（deploy 页 + 既有 exporter 测试）→ 先全仓 grep export_onnx 调用点再改，测试同步更新。
  2. 角色迁移读旧值——users.json 为运行时文件（git 忽略），迁移仅读端兼容、不重写文件（写端在下次保存时自然升级）。
  3. label 零样本桥删除改变预标注失败路径行为（原为吞错）→ 改为状态栏诚实提示，测试锚定新文案。
  4. det_map 拆分属纯函数重构——必须保持数值逐位一致（锚定既有期望值用例，不改动断言）。
- **假设**:
  1. windows-latest runner 自带 .NET 8 SDK（dotnet test 可直接跑，无需 setup-dotnet）。
  2. FakeThread 接缝覆盖新增 cancel 参数形态（jobs.run_job 已支持 cancel 透传——W17 已验证）。

## 6. 实现思路（给定方向，非完整方案）

- **拟采用**: 六簇并行——A1 退出链→A2 dispatcher 收敛（同文件顺序执行）；B 角色枚举+login 文档；C serving 告警+serialization 回滚；D det_map 拆分；E spec/eval_flow 尾巴；F ci.yml。每簇 TDD 先红后绿，主审终审全量门禁。
- **复用**: jobs.run_job 的 cancel 透传（W15）；thread_bridge.ui_on_error（W17）；既有 FakeThread 接缝与守卫测试模式。
- **注意**: A1/A2 共享 shell.py/train/predict 页文件——必须顺序执行；det_map 拆分不改任何期望值断言；exporter 改签名先查全部调用点。

---

## 自检（5 项，提交前核对）

- [x] **完整性**: 每条需求有 FR 编号（FR-001~007）
- [x] **无歧义**: 命令 `grep -iE "快速|友好|高效|灵活|强大"` 本文件命中 = 0
- [x] **可追溯**: FR-001→AC-001/002；FR-002→AC-003/004；FR-003→AC-005/006；FR-004→AC-007；FR-005→AC-008；FR-006→AC-009/010；FR-007→AC-011；全局→AC-012
- [x] **范围清晰**: In / Out Scope 已列（CI 真实首跑明确出范围）
- [x] **指标可量化**: AC 均可判定（源码守卫/caplog/AST/数值锚定/YAML 解析）

## ✅ 门禁（2 项）

- [x] G1：用户四项拍板（AskUserQuestion 2026-08-17），证据入 state.json
- [ ] G3：用户批准任务与执行范围；完成后仍须 AC 全过并通过状态验证器
