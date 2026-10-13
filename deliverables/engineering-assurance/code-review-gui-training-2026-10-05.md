# AutoVisionAgent 2.1.0 — 第二轮工程审查综合报告（gui/ + training/ + dataset/ + inference/）

**日期**：2026-10-05
**轮次**：第二轮（第一轮 core/+serving/ 审查后的扩展范围审查）
**审查范围**：gui/（43 文件，8,970 行，PySide6 桌面端）+ training/（2 文件）+ dataset/（3 文件）+ inference/（3 文件）
**审查方式**：两路并行独立审查（GUI 侧 / 数据-训练-推理链路侧），主理人交叉验证合并

---

## 📌 TL;DR（执行摘要）

- 整体结论：**🟡 有条件通过**——两个目录工程质量均高于同类项目平均水平（gui 无分层违例、jobs 调度体系成熟；training 安全面干净），但存在 **5 个 🔴 问题**，其中 training 侧两个（假 resume、train=val 同目录）直接摧毁"训练评估可信度"，gui 侧三个为用户可触发的竞态/卡死。
- 严重度分布：🔴严重 5 项 / 🟠高 13 项 / 🟡中 20 项 / 🟢低 6 项，共 44 项
- 最关键判断：**"train=val 同目录 + 假 resume + 无随机种子"三者叠加，使训练产物与指标整体不可信**——这是比任何单点 bug 都严重的结构性缺口。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过 |
| 🔴 项数量 | 5（gui 3 + training 2） |
| 最关键风险 | 训练评估可信度结构性缺口（指标虚高 + 假续训） |
| 分层纪律 | ✅ gui→serving 零违例（W45 重构约束守住） |
| 安全面 | ✅ training/dataset/inference 无不安全反序列化、torch.load 均 weights_only=True |
| 建议下一步 | P0 三修（train/val 划分、真 resume、推理中禁用模型加载）→ P1 竞态修复 → P2 卫生级 |

---

## ✅ 第一轮阻塞项修复记录（本轮前置工作）

第一轮的 2 个 🔴 安全阻塞项已于本轮开始时修复并验证：

| 项 | 修复内容 | 验证 |
|----|---------|------|
| S1 任意文件读取 | `shared_memory.py` 新增 `_shm_path_allowed()` 白名单（base_dir + ava_*.bin 双条件），read_array/read_bytes/read_range 三入口全接入；`server.py` FetchRegion 拒绝时统一 NOT_FOUND（fail-closed 防路径探测）；保留 AVA_SHM_ALLOW_ANY_FILE=1 逃生门 | 12 个新安全测试 + 102 个既有回归全过（114/114） |
| S2 恶意 RLE OOM | `core/mask_codec.py` 解码三道闸（元素上限 2^30 / 4 字节对齐 / 负游程拒绝 + int64 求和防回绕）；encode 侧 >2^31-1 显式拒绝（校验前置到 astype 前） | 同上；跨管理器合法读取（C# 链路模拟）测试锁定不受影响 |

测试文件：`tests/test_security_s1_s2.py`（12 例）

---

## 🔍 审查发现（按严重度，两源合并）

### 🔴 严重（5 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| R1 | 数据完整性 | dataset/format_export.py:121-127 | **data.yaml 写死 train:images / val:images 同目录**，全链路无 train/val 划分逻辑 → mAP 在训练集上计算，指标虚高；工业缺陷检测小数据集下严重误导模型质量判断 | 导出时按比例分层划分（如 8:2）分目录；至少在 data.yaml 与导出摘要显式警告"无验证集，指标不可信" | training |
| R2 | 断点续训 | training/generic_trainer.py:322-367 | **resume 是假的**：只恢复 epoch/best 元数据，从不恢复模型权重——docstring 声称调 strategy.load_state() 但实现无任何调用，ITrainStrategy 协议根本没有该方法；sseg_smp.py 自带 load_state 无人调用。续训=从头初始化权重+epoch 跳号+沿用旧 best_metric，产物语义完全错误 | ITrainStrategy 增加 load_state(path) 可选接口；_resume 实际装载权重；失败时明确警告"从随机权重续训" | training |
| R3 | 线程安全 | gui/pages/predict/page.py:265-269 | **推理进行中可卸载引擎**：批量推理时 btn_load_model 未禁用，点击后主线程 unload() 旧引擎而子线程正在 infer → use-after-unload → 崩溃或 CUDA 非法访存 | 批量/单张推理进行中禁用 btn_load_model，或 _load_model 入口检查 active_jobs | gui |
| R4 | 线程安全 | gui/pages/predict/page.py:327-339+443-448 | **单张推理结果跨线程裸传**：子线程写 `self._pending_single` 主线程读，依赖未声明的 QueuedConnection 时序契约；用户快速连点两次推理时第一次结果被覆盖静默丢失 | 信号传原始载荷（路径/score），或 dict[request_id] + 防重入守卫 | gui |
| R5 | UI 线程阻塞 | gui/pages/train/page.py:594-601 | **_stop_training 在 UI 线程 wait(5000)**：fit() 在长 epoch 中不检查 stop_flag 时 UI 冻结至多 5 秒；"正在停止..."文案在 wait 之后才可能渲染（事件循环已停转） | stop() 只置标志+禁按钮，让 finished_sig 正常回调复位 UI | gui |

### 🟠 高（13 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| O1 | 数据质量 | dataset/vision_dataset.py:88-89 | 标注 JSON 损坏时静默降级为空 boxes"无缺陷"负样本进训练——关键正样本标注损坏被当背景教坏模型，用户无感知 | 损坏样本跳过不进 items，至少收集计数上报 | training |
| O2 | 续训 | training/generic_trainer.py:121 | resume 后 LR 调度器全新构建不回放步数：Cosine 相位从 0 重启，续训前几轮 LR 回高位，与首轮轨迹不连续 | scheduler.last_epoch=start_epoch-1，恢复 no_improve 计数 | training |
| O3 | 日志落盘 | training/generic_trainer.py:113-163 | metrics_history 只存内存、artifact.metrics 仅留最后一轮；训练中断 history 全丢，GUI 曲线只靠实时回调 | 每 epoch 追加 metrics.jsonl，resume 回读重建 | training |
| O4 | 健壮性 | dataset/format_export.py:50-57,111 | imagePath 为空时 `base/""`=base 目录本身且 exists()=True → 返回目录，copy2(目录) 抛异常，整次导出崩溃 | 校验 name 非空且 is_file() 才返回 | training |
| O5 | 数据完整性 | dataset/format_export.py:110-114 | 同 stem 冲突静默覆盖：a.jpg/a.png 共存或跨目录同名时 copy2 与 labels/<stem>.txt 双双覆盖，无检测无警告 | stem 建索引检测冲突，重命名或报错统计 | training |
| O6 | 推理正确性 | inference/tiling_inferencer.py:153-205 | 跨瓦片 NMS 不区分类别仅按 IoU 全局抑制——多类别缺陷空间共现时低分类别重叠框被误删 | NMS 按类别分组或 class-offset trick | training |
| O7 | 线程安全 | gui/pages/label/sam_session.py:167-186+205-223 | _sam_state/_sam_adapter 在 worker 线程直接写主线程读，状态机跨线程无锁，契约脆弱（invoke_main 旧回调可能乱序改状态） | 状态迁移全收敛主线程，worker 只 invoke_main 回报 | gui |
| O8 | 资源泄漏 | gui/pages/data_manage/page.py:94-95 + label/page.py:175-176 | QThreadPool 页面销毁未清理；**LabelPage 在 QStackedWidget 内永不收到 closeEvent**，SAM 卸载兜底实际不可达 | shell.closeEvent 无条件清 _thumb_pool；SAM 卸载挂 MainWindow closeEvent | gui |
| O9 | 正确性 | gui/pages/predict/page.py:249-269 | _load_model 失败路径引擎残留半加载态：except 后 self._engine 仍非空，用户失败后直接点推理 → infer 崩溃 | except 分支补 `self._engine=None; reg.clear_cache(task)` | gui |
| O10 | 异常处理 | gui/pages/train/page.py:503-505 | `except Exception` 过宽捕获 _make_trainer：编码 bug（AttributeError）也变"训练失败"文案，掩盖真实缺陷且 _on_failed 无日志 | 元组收窄 + _on_failed 补 logger.exception | gui |
| O11 | 安全 | gui/pages/login/page.py:497-505 | 许可证导入无内容校验：任意 .key 文件复制进 configs/license.key 即过离线检查（去 DRM 决策已知，但无审计留痕、无大小上限） | 审计日志记录导入源+哈希；限制文件大小 | gui |
| O12 | UI 契约 | gui/pages/data_manage/page.py:310-315 | _on_ratio_changed 是空操作假实现（docstring 声称联动补偿，函数体 pass）——误导性 UI | 实现自动补偿或删连接与 docstring | gui |
| O13 | 数据完整性 | gui/pages/predict/workers.py:110-146+475 | 批量产物 stem 冲突：不同子目录同名图像 masks_*.npz / overlay_*.jpg 互相覆盖，batch_results.json 无法区分 | stem 加路径哈希后缀或保留相对层级 | gui |

### 🟡 中（20 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| M1 | 平台 | dataset/vision_dataset.py:117-133 | _TorchVisionDataset 是局部类：Windows spawn + num_workers>0 时 pickle 失败必崩（当前无生产调用方，潜伏地雷） | 类提至模块顶层；接线前必须修 | training |
| M2 | 健壮性 | training/generic_trainer.py:227-248 | checkpoint 无原子写：中途崩溃留半成品 .pt，resume 可能读坏权重 | .pt.tmp + os.replace；装载前校验 | training |
| M3 | 健壮性 | training/generic_trainer.py:173-185 | train_epoch 无 CUDA OOM 捕获/退避/降级重试 | 捕 OOM：empty_cache + batch 减半重试一次 | training |
| M4 | 正确性 | dataset/format_export.py:98-108 | YOLO 矩形行坐标不裁剪 [0,1]（polygon 分支有、rectangle 分支没有）——越界标注训练时报错或静默剔除 | rectangle 分支同样 clamp | training |
| M5 | 代码脆弱 | inference/tiling_inferencer.py:141-147 | `type(result)` 依赖 for 循环变量泄漏，行为碰巧正确但极脆弱 | 循环内显式记录 result_cls | training |
| M6 | 健壮性 | inference/tiling_inferencer.py:43-58 | compute_tiles 无参数防御：overlap>=tile_size 时 step<=0 死循环挂死 | 入口断言抛 ValueError | training |
| M7 | 一致性 | inference/sv_bridge.py:33-38 | class_id 按单图类别子集重排：跨图漂移，且与 format_export 全集字典序映射不一致（文件头声称一致） | 映射由全集类别表驱动 | training |
| M8 | 复现性 | training/generic_trainer.py + vision_dataset.py:156-160 | 全链路无随机种子控制（trainer/shuffle/ultralytics 均未设 seed），训练不可复现 | TrainConfig 加 seed，fit 入口统一设种并透传 | training |
| M9 | 正确性 | dataset/vision_dataset.py:65-69 | cv2 imdecode 失败走 PIL 兜底时 RGB 被无条件翻成 BGR——第一轮 M1（image_io 双语义）的又一处下游受害点 | 按来源分支处理或标记通道序 | training |
| M10 | 状态管理 | training/generic_trainer.py:40,116-117 | 同一 trainer 实例二次 fit（非 resume）时 _best_metric 沿用上一会话值，语义错乱 | fit 入口无条件重置 | training |
| M11 | 语义 | training/generic_trainer.py:201-225 | 早停只监控训练 loss；ultralytics 一次性适配器下 loss 恒定 → patience>=1 必然误触发早停 | 早停监控 val 指标或适配器场景禁用 trainer 层早停 | training |
| M12 | 可观测 | inference/tiling_inferencer.py:107-130 | 单瓦片推理失败仅吞日志，extra 记录总 tile 数而非成功数——部分漏检用户不可见 | extra 记录 failed_tiles/tiles_ok | training |
| M13 | 线程安全 | gui/pages/predict/batch_runner.py:66,79 | 批量循环读 page._batch_cancel + 子线程 append _results——依赖与 R4 同款隐式契约 | 文档化"invoke_main 队列即屏障"或收敛主线程 append | gui |
| M14 | 正确性 | gui/pages/data_manage/page.py:700 | export 进行中 btn_goto_train 未禁用，可读陈旧 _last_export_yaml 走错分支 | export 期间禁用或入口检查 active_jobs | gui |
| M15 | 资源 | gui/pages/data_manage/page.py:752-765 | _diff_dialog 非模态单实例引用，反复打开窗口堆积 | 复用 dialog 或 close 置 None | gui |
| M16 | 异常 | gui/widgets/file_dialog.py:19-45 | _load/_save_last_dir 裸 pass 吞异常 + 先读后写非原子 | 补 debug 日志（低优先） | gui |
| M17 | 正确性 | gui/pages/train/page.py:613 | _on_progress 用当前 spin_epochs 值反推 epoch——训练中表单未锁定，改值致日志错乱 | 训练期间禁用表单控件组 | gui |
| M18 | 安全 | gui/pages/predict/page.py:621,696,752 | CSV 注入已有 sanitize 防护（好）；JSON 导出未 sanitize（风险低） | 可选：JSON 字段同前缀处理 | gui |
| M19 | 正确性 | gui/pages/train/page.py:703-707 | SGD momentum/weight_decay 无 UI 配置入口，静默用默认 | 表单补充或文档声明 | gui |
| M20 | 线程安全 | gui/pages/predict/page.py + sam_session.py（模式层面） | "pending 属性跨线程传递"模式分布 3 处无统一屏障文档——本轮 R4/M13 的共同根因 | 写一份线程契约文档，统一收敛为信号载荷模式 | gui |

### 🟢 低（6 项）

| # | 文件:行 | 问题 | 来源 |
|---|---------|------|------|
| L1 | gui/pages/predict/page.py:764-765 | btn_video_super.setText 连续重复两行（复制粘贴残留） | gui |
| L2 | gui/pages/data_manage/page.py:417 | f-string 动态键查 i18n 字典必 miss，en_US 回退中文整句 | gui |
| L3 | gui/pages/predict/page.py:59 | _models_dir 死属性（只写不读） | gui |
| L4 | gui/pages/home/page.py:153 | `flags() & ~flags()` 绕写法（等价 setFlags(Qt.NoItemFlags)） | gui |
| L5 | gui/pages/label/sam_session.py:346-347 | unload_sam 的 except pass 完全静默无日志（同函数 326 行有日志） | gui |
| L6 | inference/tiling_inferencer.py:208-221 | should_tile 阈值 2048 与 tile_size=1024 语义不对齐；tiling 管线整体未接线（GUI 零引用） | training |

---

## 🔗 跨轮 / 跨目录交叉验证

| 关联组 | 发现 | 结论 |
|--------|------|------|
| 第一轮 M1（image_io BGR/RGB 双语义）× 本轮 M9（vision_dataset PIL 兜底再翻转） | 同一根因的第二处下游受害点 | 根因修复优先级应上调：修 image_io 单一侧，两处下游同时受益 |
| 本轮 O5（format_export stem 冲突）× O13（workers.py stem 冲突） | 同一模式在 dataset 导出与 GUI 批量产物两处独立存在 | 建议抽公共"安全文件名"工具函数统一修 |
| 第一轮 H6（shm TOCTOU）× 本轮 O7（SAM 状态跨线程） | 项目共性模式：跨线程共享状态靠 GIL 原子性 + 隐式时序假设 | 见 M20 线程契约文档建议 |
| 第一轮 H8（引擎并发 infer 无守卫）× 本轮 R3（推理中卸载引擎） | serving 与 gui 两侧都存在"模型生命周期与推理并发"冲突 | 模型生命周期管理可作为专题统一收口 |

**正面确认**（两轮审查的明确好消息）：
- gui→serving 分层零违例（W45 重构约束守住，predict/workers.py 已是纯函数层）
- training/dataset/inference 安全面干净：无 yaml.load/pickle.load 不安全调用，torch.load 均 weights_only=True，路径全 Unicode API
- gui 裸 `except:` 零处；CSV 注入有 sanitize 防护；jobs 调度体系（注册表+协作取消+有界停机）成熟

---

## ✅ 行动清单（按优先级）

| # | 行动 | 紧急度 | 预期完成 |
|---|------|--------|---------|
| 1 | R1：format_export 增加 train/val 分层划分（8:2 分目录），修复"指标虚高"根基 | P0 | 本周 |
| 2 | R2：实现真 resume（ITrainStrategy.load_state + 权重实际装载 + 失败明确警告） | P0 | 本周 |
| 3 | R3：推理进行中禁用 btn_load_model（+ _load_model 入口 active_jobs 检查） | P0 | 本周 |
| 4 | R5：_stop_training 去掉 wait(5000)，改协作式停止 | P1 | 下周 |
| 5 | R4+M20：单张结果改信号载荷传递，并起草线程契约文档收敛 pending 属性模式 | P1 | 下周 |
| 6 | O1：损坏标注跳过 + 计数上报；O6：NMS 按类别分组 | P1 | 下周 |
| 7 | O9：_load_model 失败清理半加载引擎；O4/O5/O13：stem 冲突与空路径防御（抽公共工具） | P1 | 下周 |
| 8 | M8：随机种子控制（TrainConfig.seed 全链路透传）——与 R1/R2 共同构成"训练可信度"修复三部曲 | P1 | W2 |
| 9 | M11：早停改监控 val 指标（依赖 #1 的验证集）；M2：checkpoint 原子写 | P2 | W2 |
| 10 | M1：_TorchVisionDataset 提顶层（DataLoader 接线前置条件）；M6：compute_tiles 参数防御 | P2 | W2 |
| 11 | O8：shell.closeEvent 无条件清线程池 + SAM 卸载挂 MainWindow；M17：训练中锁定表单 | P2 | W3 |
| 12 | 卫生级批量：L1-L5 + M12/M14/M15 + O10/O12 | P2 | W3 |

---

## ⚠️ 待完善 / 已知局限

- gui 审查以静态阅读为主，未运行 GUI 实例做动态验证（UIA 真窗测试套件存在但默认排除，见 docs/uia-test-plan-full-coverage.md）
- 线程安全问题（R3/R4/O7/M13）部分基于代码推理而非复现，修复时建议先写复现测试再修
- tiling_inferencer 与 VisionDataset DataLoader 管线均无生产调用方（半成品），问题严重度按"接线后"评估
- 第一轮 P1/P2 行动项（ADR-0005/0006、并发测试、E2E 等）不在本报告范围，仍按第一轮计划推进

---

## 📚 数据来源 & 审查产出索引

- gui 侧原始产出：22 项发现（🔴3/🟠7/🟡8/🟢4）+ 分层违例专项（零违例）+ 整体质量印象
- training 侧原始产出：22 项发现（🔴2/🟠6/🟡12/🟢2）+ 安全面正面确认 + 链路整体印象
- 主理人交叉验证：4 组跨轮/跨目录关联 + 4 项正面确认
- 前置修复：S1/S2（第一轮 🔴 阻塞项）已修复并 130 测试验证

---

> 本报告由两路并行代码审查汇编生成，关键决策请由人类工程负责人复核。
