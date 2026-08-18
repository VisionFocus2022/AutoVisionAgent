# v3 第一波止血（det 评估构造 + shm 区域回收 + on_error 收口） — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-17 | 档位: L2 | 四维分档依据: 见 `.workflow/wave17-v3-first-aid/state.json`（reversible / cross_system / test_visible / low）
> 来源: 架构审查 v3 报告 §9 第一波第 1/2/4 项（docs/AutoVisionAgent-架构解析与优化方案-v3.md），用户 2026-08-17 指令实施并拍板三个设计点。

## 1. 背景与目标

- **背景**：v3 审查实证两条 P1 与一条系统性 P2——①det 评估在"GT 框数与预测框数不一致"（真实数据常态，含引擎零检出于有 GT 图）时 numpy IndexError 穿透异常元组，评估按钮永久禁用；不崩时 labels/scores 为合成值，mAP 无意义（P1-2）。②C# 客户端结果 shm 区域结构性无法回收，累积 64 上限后 seg/pose 类 Detect 全部软失败直至重启（P1-1）。③10 个 run_job 消费点均未接 on_error，worker 抛出页面 except 元组外的异常类型（AppError 家族、IndexError 等）时按钮永久禁用或静默失败（P2-1）。
- **目标**：
  1. det 评估在 M≠N 全组合下不崩、按钮必可恢复，且 mAP 使用引擎真实逐框置信度；
  2. shm 区域不再无界累积：TTL 惰性清扫（全尺寸）+ 小数组内联（<64KiB 不建区域），正常消费模式下 64 上限不可达；
  3. 10 个 run_job 消费点异常必达 UI（按钮恢复 + 状态栏报错），源码守卫测试防回退。

## 2. 功能需求 (FR)

- **FR-001**: det 评估预测构造修复 — `evaluation/eval_flow.build_prediction` 输出的 boxes/scores/labels 三者长度恒等于预测框数 N；scores 取 `result.scores`（逐框置信度，空则回退 `[result.score]*N`）；labels 恒为 `[0]*N`（单类语义，GT 侧维持 extract_gt 现状）；`evaluation/metrics_supervised.det_map` 对 labels/boxes 长度不一致时防御（对齐处理，不抛裸 IndexError） | P0
- **FR-002**: shm 区域 TTL 惰性清扫 — `serving/shared_memory.SharedMemoryManager` 区域登记创建时间；每次写入前回收 age>TTL 的陈旧区域（mm.close→os.close→unlink 顺序）；`AVA_SHM_REGION_TTL_SECONDS` 环境变量，默认 300，≤0 关闭；清扫先于写盘与上限判定（顺带消除"先写后查"浪费） | P0
- **FR-003**: 小数组内联 — proto `DetectionResultProto` 新增 `bytes masks_inline = 10` / `bytes keypoints_inline = 11`（向后兼容增量）；serialization 对序列化后 nbytes < `_SHM_MIN_BYTES`(64KiB) 的数组内联进 proto（不建 shm 区域、句柄留空 length==0），≥阈值仍走 shm；C# `DetectionResultMapper` 优先读内联（含 bool_rle 解码），无内联时走原句柄路径 | P0
- **FR-004**: Release 语义与上限文案 — `ReleaseSharedMemory` 对 `release()` 返回 False 的路径回 `success=False` + 非空 error + `logger.warning`；上限 RuntimeError 文案改为含 TTL/Release 可执行指引 | P1
- **FR-005**: on_error 收口 — `gui/core/thread_bridge.py` 新增 `ui_on_error(widget, slot_name)`（闭包经 invoke_main 转发 `str(exc)`）；10 个 run_job 消费点全部传 on_error；无失败槽的页面补最小 `@Slot(str)` 失败槽（复位按钮 + 状态栏报错）；deploy/label 的 worker except 元组补 AppError 家族（保留既有面向用户的文案分支）；新增源码守卫测试断言全部 run_job 调用含 on_error | P0

## 3. 验收标准 (AC)

- **AC-001**: 给定 GT 框数 M>0 且预测框数 N≠M（含 N=0、N>M、N<M 三形态），`run_supervised_eval(task_key="det")` 全程不抛 IndexError 且返回结果行 [FR-001]
- **AC-002**: 给定引擎逐框 scores 可分辨（如两框 0.9/0.4 构成 TP+FP），det mAP/AP 按真实分数排序计算（断言与手算一致，区别于全零均匀分数的插入序结果） [FR-001]
- **AC-003**: 给定 M==N 且 scores 同前，AP 数值与修复前一致（回归锚定既有行为） [FR-001]
- **AC-004**: 给定 TTL=0.05s 且已登记 2 个区域，休眠超 TTL 后再写入 1 个区域，在册区域数回落至 ≤1 且被回收区域的文件已删除 [FR-002]
- **AC-005**: 给定 TTL 清扫后仍达 64 上限，写入抛 RuntimeError 且 Detect 返回 success=False（上限行为保持） [FR-002]
- **AC-006**: 给定 RLE 后 <64KiB 的 bool 掩码，`detection_result_to_proto` 结果 masks_shm.length==0、masks_inline 非空且未新建 shm 文件；给定 ≥64KiB 掩码，走 shm 且 masks_inline 为空 [FR-003]
- **AC-007**: C# DetectionResultMapper 对内联 masks_inline（bool_rle 与 raw 两形态）解码结果与 Python 侧编码一致（形状与元素值）；`dotnet test` 全绿 [FR-003]
- **AC-008**: ReleaseSharedMemory 对不存在/已释放路径返回 success=False 且 error 非空；既有 happy-path（真区域回收）测试仍绿 [FR-004]
- **AC-009**: 给定任一已接线页面的 worker 抛出 except 元组外异常（如 KeyError/AppError 子类），该页按钮恢复可用且状态栏收到错误文本（offscreen 单测覆盖 10 个消费点所在页面各 ≥1 例，含 eval 页 IndexError 专例与 deploy ModelExportError 专例） [FR-005]
- **AC-010**: 守卫测试读取页面源码，断言全部 run_job 调用含 `on_error=`（防回退） [FR-005]
- **AC-011**: 全量门禁 `pytest` rc=0 且覆盖率 ≥92；`dotnet test` rc=0；状态验证器 rc=0 [全局]

## 4. 范围

- ✅ **In Scope**: FR-001~005 全部；grpcio-tools 安装（版本对齐 grpcio 1.83.0）+ pb2 重生成 + requirements.lock.txt 追加该包行；C# DetectionResultMapper/相关 xUnit 测试；Python 侧新增/扩展测试。
- ❌ **Out of Scope**: 多类评估语义（LabelMe shape.label 词表映射，留第二波）；密码入日志（P2-2 其余项）；lock↔venv 既有 6 包漂移补齐（P2-4）；FID/LPIPS [:20] 样本帽；eval seg/abdet 路径重构（仅保证不回归）；exe 重打包与 UIA 复跑（发版域，另行走查）。

## 5. 风险与假设

- **风险**:
  1. proto 加字段需 C# 同步，若超预算 → 降级路径：FR-002(TTL) 独立生效即可消除 65 次故障，内联字段留作预留（记偏差）；缓解：C# 改动面经预检仅 Mapper 一处分支 + Reader 解码复用。
  2. pb2 重生成受 protobuf 7.x 工具链影响产生格式差异 → 生成后跑全量门禁比对 serving 测试（既有 proto 测试锚定字段行为）。
  3. TTL 误回收慢客户端未读区域 → 默认 300s 远大于正常消费窗口（客户端在 RPC 返回后即读），proto docstring 与模块注释写明 TTL 语义。
  4. C# 既有测试可能锚定 Release 恒 True 旧行为 → 实现前先查 AutoVisionAgentClientTests.cs 相关用例，同步更新并在偏差记录。
- **假设**:
  1. C# SharedMemoryReader 的 bool_rle 解码可从"读文件字节"重构为"读内存字节"复用（实现时验证；不成立则 C# 侧提取解码纯函数供两路共用）。
  2. grpcio-tools==1.83.0 与已装 protobuf 7.35.1 兼容（安装时验证，不兼容则选兼容版本并记偏差）。

## 6. 实现思路（给定方向，非完整方案）

- **拟采用**: TTL 在 SharedMemoryManager 写入口加 `_reap_expired()`（区域值携带 created_at，time.monotonic 计龄）；内联在 serialization 判定 nbytes 后分支（小→proto bytes 字段，大→既有 write_mask_compact/write_array）；det 修复聚焦 build_prediction 三数组定长构造 + det_map 入参防御；on_error 为 thread_bridge 纯函数助手 + 10 处机械接线。
- **复用**: `thread_bridge.invoke_main/_to_qarg`；`write_mask_compact`（RLE 编码）；C# 侧既有 RLE 解码逻辑；`det_map` 既有 PR 曲线实现。
- **注意**: v3 报告 P1-2 修复陷阱——不得将引擎字符串 labels（"defect_N"）直喂 det_map 的整数比较（`np.asarray(['defect_0'])==0` 全 False → mAP 归零），须在 build_prediction 侧归一为 `[0]*N`；numpy 数组不得做真值判断（项目已知反模式）；TTL 回收顺序必须 mm.close → os.close → unlink（Windows 句柄语义）。

---

## 自检（5 项，提交前核对）

- [x] **完整性**: 每条需求有 FR 编号（FR-001~005）
- [x] **无歧义**: 命令 `grep -iE "快速|友好|高效|灵活|强大"` 本文件命中 = 0
- [x] **可追溯**: 每个 FR 有对应 AC（FR-001→AC-001~003；FR-002→AC-004~005；FR-003→AC-006~007；FR-004→AC-008；FR-005→AC-009~010；全局→AC-011）
- [x] **范围清晰**: In / Out Scope 已列
- [x] **指标可量化**: 目标 / AC 均可判定（rc/覆盖率/区域数/字段值/AP 数值）

## ✅ 门禁（2 项）

- [x] G1：用户批准需求范围——2026-08-17 指令实施第一波止血三项 + AskUserQuestion 拍板（shm=两者都做 / det 评估=单类语义补全 / on_error=统一助手+10处接线），证据入 state.json
- [ ] G3：用户批准任务与执行范围；完成后仍须 AC 全过并通过状态验证器
