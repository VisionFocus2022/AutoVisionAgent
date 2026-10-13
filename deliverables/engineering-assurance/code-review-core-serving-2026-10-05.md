# AutoVisionAgent 2.1.0 — core/ + serving/ 全面工程审查综合报告

**日期**：2026-10-05
**工作流**：工作流 1（全面代码审查，含架构影响与测试覆盖评估）
**参与成员**：Cody（代码审查师）/ Archi（系统架构师）/ Tessa（测试专家）
**审查范围**：core/（11 模块，1,693 行）+ serving/ Python 侧（6 文件，1,236 行）+ 测试体系对照（tests/ 143 文件，覆盖率快照 2026-09-29）

---

## 📌 TL;DR（执行摘要）

- 整体结论：**Request Changes**——工程质量与架构纪律显著优于同规模项目（反序列化加固、共享内存生命周期治理、ADR 实践均为正面样本），但 serving 对外暴露面存在 **2 个 🔴 安全阻塞项**（任意文件读取、恶意 RLE 致 OOM），必须修复后合入。
- 严重度分布：🔴严重 2 项 / 🟠高 10 项 / 🟡中 16 项 / 🟢低 12 项（含跨成员合并去重）
- 阻塞 / 非阻塞：**阻塞 6 项**（🔴2 + 建议列为 merge blocker 的 🟠4）；测试侧另有 2 个 🔴 级盲区（并发零测试、gRPC 真通道 E2E 缺失）虽不阻塞合入，但使并发类缺陷无回归守卫。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过（修复 6 项阻塞后可合入） |
| 阻塞项数量 | 6（🔴2 安全 + 🟠4 正确性） |
| 关键行动项 | 12 条（见行动清单） |
| 建议下一步 | P0 安全双修复 + 负路径契约测试 → P1 ADR-0005/0006 + 并发/E2E 补测 → P2 覆盖率棘轮地板 |

---

## 🔍 审查发现（按严重度排序，三源合并去重）

> 来源标注：C=Cody 代码审查，A=Archi 架构评估，T=Tessa 测试评估；"合并"表示多位成员独立发现、互相印证。

### 🔴 严重（2 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| S1 | 安全 | serving/server.py:205-237 + serving/shared_memory.py:415-427,535-540 | FetchRegion → read_range → _read_range_from_file 对任意 file_path 直接 open().read() 回传字节，不限于本进程 base_dir/ava_ 前缀。回环无鉴权（ADR-0001）下，本机任意进程可读取机器上任意可读文件（users.json、initial_credentials.txt、license.key 等），超出 ADR"推理接口暴露"的风险预期 | read_range/read_array/read_bytes 对非本进程区域加路径白名单：必须位于 base_dir 下且文件名匹配 ava_*.bin；FetchRegion 校验后再读 | C |
| S2 | 安全 | core/mask_codec.py:42-61（入口 serving/serialization.py:187-191） | decode_mask_rle 无载荷/形状上限：恶意客户端经 image_shm(dtype=bool_rle) 送 4 字节 runs=[N] + shape 总积 N=数十亿，runs.sum()==total 校验通过后 np.repeat 分配 N 字节 → 服务进程 OOM 被杀；且 runs.sum() 按 int32 求和可回绕绕过校验，负 runs 值未拒绝 | decode 前校验 total ≤ 与传输 length 关联的上限（如 length×8 且 ≤ 2^31）；runs 全部 ≥0；sum 用 int64；**同步补 4 例负路径契约测试**（见测试盲区 T5） | C+T 合并 |

### 🟠 高（10 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| H1 | 安全 | serving/server.py:111-119,115 + serialization.py:194-216 | 无鉴权接口 LoadModel/Detect 接受任意 weights_path/image_path，无白名单约束：可探测任意文件存在性 + 加载任意权重耗尽 GPU | weights_path 限制到配置的模型根目录（resolve 后校验前缀）；image_path 限制到指定数据目录 | C |
| H2 | 正确性 | serving/server.py:346 | add_insecure_port 返回值未检查：端口被占用/绑定失败时返回 0，serve() 打"已启动"日志后永久假运行 | ret = server.add_insecure_port(...); if ret == 0: raise RuntimeError | C |
| H3 | 正确性 | core/detection_history.py:135-141 | _persist_locked 的 mkdir(parents=True) 在 try 块外：审计目录不可写时每条 add_record 从锁内抛 OSError 上炸推理热路径。audit_logger.py:127 同类问题已修（W39·v6 P3-3），修复未同步 | mkdir 移入 try，与 audit_logger._flush_locked 同款处理（失败仅告警） | C |
| H4 | 正确性 | serving/shared_memory.py:338-341 | os.write(fd, raw) 单次调用未处理部分写：POSIX 下大载荷短写后文件实际长度 < len(raw)，mmap 超出文件尾，访问时 SIGBUS 直接杀进程（不可捕获） | 循环写满（类似 path_io.py:63-69 的分块循环）或写完重新 os.open 再映射 | C |
| H5 | 正确性 | serving/server.py:144 + proto 契约 | if request.threshold: 把显式 threshold=0.0 当缺省跳过（proto3 标量无 presence）——工业低阈值场景传 0 不生效，静默用 0.5 | proto 改 optional float threshold + 服务端 HasField("threshold")，缺省语义与显式 0 分离 | C+A 合并 |
| H6 | 正确性 | serving/shared_memory.py:391-427 | TOCTOU 竞态：锁内快照 entry 后锁外使用 mm；并发线程 release 同区域时 mm.close() 已执行，mm[...] 抛 ValueError 使请求崩溃（gRPC 8 worker 并发 + ReleaseSharedMemory 可稳定触发）；**且现有测试零并发用例，无回归守卫** | 锁内完成切片拷贝（with lock: data = bytes(mm[a:b])），或 release 与 read 共用同一读写锁/引用计数；**补并发压力测试**（见 T1） | C+T 合并 |
| H7 | 正确性 | serving/shared_memory.py:396,412,426 | mm 切片对负 offset 无校验：h.offset=-1000 时按尾部偏移静默拼接错位数据（检测结果错乱而非报错） | 入口校验 offset ≥ 0、length ≥ 0、offset+length ≤ 区域长度，非法抛 ValueError | C |
| H8 | 正确性/架构 | serving/server.py:342 + 引擎层 | 8 个 gRPC worker 并发调 dispatcher.infer/load_supervised，同一引擎并发 infer 的线程安全完全依赖各引擎实现（ultralytics 等未承诺线程安全），AbstractTaskEngine._model 无同步保护，无单飞守卫 | per-engine 锁/信号量单飞，或文档化"每任务串行"约束 + 并发用例；确认 dispatcher 线程安全并写入 ADR | C+A 合并 |
| H9 | 架构·生命周期 | serving/server.py:125-126 | UnloadModel 绕过 dispatcher 直调 registry.clear_cache（越层 import）：卸载后 dispatcher._engines 仍持引擎，Ping.loaded_tasks/GetTaskInfo.loaded 持续报 True（元数据失真） | ADR-0005：dispatcher 增 unload_supervised(task) 公共方法作单一所有者，约 0.5 人日 | A |
| H10 | 架构·跨语言契约 | serialization.py:41-47 + dotnet_client Mapper.cs:137 | 任务枚举双端漂移 + 双端 fail-open 静默回退：Python TaskType 10 值 vs C# 6 值（含 Python 不存在的 Vlm，缺 sseg/sgan/super/ocr）；未知 task 双端静默回退 DET——客户端发 "vlm" 会静默执行目标检测，错误路由无显式信号 | ADR-0006：服务端未知 task 改 abort(INVALID_ARGUMENT)；C# 枚举对账；MapTaskType 未知值显式异常，约 1 人日 | A |

### 🟡 中（16 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| M1 | 正确性 | core/image_io.py:23-24,45-46 | imread_unicode cv2 路径返回 BGR、PIL 回退返回 RGB，同函数两种通道语义，下游颜色错乱风险 | PIL 回退处转 BGR 或显式参数区分 | C |
| M2 | 正确性 | core/interfaces_supervised.py:441-443 | _to_numpy 中 Image.open 未用 with：文件句柄滞留至 GC | with Image.open(image) as im 上下文管理 | C |
| M3 | 正确性 | core/interfaces_supervised.py:42-61 | frozen dataclass DetectionResult 默认 __eq__/__hash__ 与 ndarray 不兼容：== 抛 ValueError、入 set/dict 抛 TypeError | eq=False 保持身份等值，或自定义 __eq__ | C |
| M4 | 性能 | serving/shared_memory.py:339 | 每次 write_raw 强制 os.fsync：36MB 大图热路径吞吐显著下降，MMF 同机读取由页缓存保证一致 | 去掉 fsync（崩溃残留由 2h 启动清扫兜底）或加开关 | C |
| M5 | 性能 | core/detection_history.py:123-141 | add_record 持锁做同步磁盘 I/O，阻塞并发 query/stats；与 audit_logger 批量缓冲模式不一致 | 仿 audit_logger 缓冲批量刷盘 | C |
| M6 | 安全·审计 | core/audit_logger.py:114-133 + server.py:134-164 | 审计日志纯明文 JSONL 无防篡改；且 serving 推理/LoadModel 路径零审计接入——对外暴露面恰是审计盲区 | 哈希链防篡改；Detect/LoadModel 接入 audit_logger | C |
| M7 | 正确性 | core/auth.py:35,61 | salt_hex/stored_hash 非法 hex 时 bytes.fromhex 抛未捕获 ValueError，users.json 半损坏会锁死登录 | verify_password 入口 try/except 返回 False | C |
| M8 | 正确性 | core/mask_codec.py:34,38 | encode 侧游程 astype(int32) 无溢出检查：>2^31 像素静默回绕 | 编码前断言 flat.size ≤ 2^31-1 | C |
| M9 | 可维护性 | core/interfaces_supervised.py:317 | torch._utils._element_size 私有 API，版本升级易碎 | try getattr 回退 dtype.itemsize | C |
| M10 | 架构·内聚 | core/interfaces_supervised.py（480 行） | 契约模块内嵌 ~230 行 RestrictedUnpickler 安全实现（有 v3 P2-10 豁免记录，属有意取舍），安全关键面可发现性差 | 抽 core/safe_torch_load.py，契约回归纯接口（非紧急） | A |
| M11 | 架构·跨语言 | 双端多处 | 2h 清扫、dtype 白名单、RLE 实现、64KiB 内联阈值、shm 目录解析（Python 有 home 兜底 vs C# GetTempPath）均为注释约定同步，无机器对账；TEMP 不一致时句柄路径直接失效 | 契约常量集中 proto/生成文件；目录解析统一无 home 兜底、失配显式报错 | A |
| M12 | 测试·集成缺失 | serving/server.py 全 RPC 面 | 全部测试直调 Servicer（_ctx()=None），从未走真 gRPC 通道：线程分发、流式 FetchRegion 帧协议、句柄跨 channel 序列化、abort 语义均未验证 | in-process 真 gRPC E2E（port=0 起服务 + insecure_channel stub 全链路） | T |
| M13 | 测试·死代码嫌疑 | core/detection_history.py:189-210 | query_from_file 全仓 0 调用方 + 0 测试；该模块 79.6% 为本区最低 | 补测试或删除 + 防复活守卫 | T |
| M14 | 测试·错误路径 | server.py:148/160-162/225-232 等 | Detect prompts 透传、序列化失败分支、FetchRegion 短读 abort 均无用例 | 三例错误矩阵补齐（~40 行） | T |
| M15 | 测试·错误路径 | core/interfaces_supervised.py:391-425/442-443 | 基类 unload()（GPU 显存回收链路）、_ensure_loaded、默认 infer_batch、str 分支 _to_numpy 全部未执行——UnloadModel RPC 是否真触达引擎 unload 无验证 | Fake 子类直测 unload/release 等价与状态复位 | T |
| M16 | 测试·门禁口径 | pytest.ini + .coverage 实测 | core 包单独精算 **91.2% < 92% 门禁**，被 12 包合计分母"抬"过线；无 per-module 地板（detection_history 79.6% 可藏匿）；分支覆盖未开启 | per-module 棘轮地板（每模块地板=当前值-1）；试开 --cov-branch 观察一轮 | T |

### 🟢 低（12 项）

| # | 类别 | 文件:行 | 问题描述 | 建议修复 | 来源 |
|---|------|---------|---------|---------|------|
| L1 | 可维护性 | audit_logger.py:84 等 | datetime.now() naive 无时区，跨机对账困难 | 统一 timezone.utc | C |
| L2 | 正确性 | config.py:80-85 | get_config 无锁懒初始化（实害低） | 加模块锁或注释接受 | C |
| L3 | 正确性 | audit_logger.py:176 等 | limit ≤ 0 时切片行为怪异无防御 | 入口 max(1, limit) | C |
| L4 | 性能 | serialization.py:69-71,153 | boxes 重复 asarray；env 每次读取 | 复用 + 模块级缓存 | C |
| L5 | 可维护性 | path_io/shared_memory/image_io 杂项 | mkstemp suffix 固定；release 注释与行为不符；imwrite 无 PIL 回退不对称 | 逐项微修 | C |
| L6 | 可维护性 | detection_history.py:143-210 | query 与 audit query 结构高度重复 | 抽公共 JSONL 查询助手 | C |
| L7 | 架构·残尾 | serialization.py:154、shared_memory.py:319/380 | serving/mask_codec.py shim 后仍有 3 处生产 import 走 shim | 机械改 core.mask_codec（0.5h） | A |
| L8 | 架构·生成链 | serving/proto/ | pb2 再生成需手工"包内相对导入修正"，生成物无 hash 对账 | 生成脚本化 + CI 对账 | A |
| L9 | 架构·协议面 | proto | FetchRegion/lease PoC 字段在生产 proto（additive，ADR-0002 冻结管控齐备） | 维持 ADR 管控 | A |
| L10 | 架构·包粒度 | industrial_vision_platform/ | 两文件包仅 serving 消费，物理隔离执行"gui 禁 import" | 可接受 | A |
| L11 | 架构·安全前置 | configs/ + .gitignore:43-45 | **前提修正**：users.json/license.key 均已 gitignore 且 git ls-files 为空，无密钥入库问题；license 仅存在性检查已诚实声明 | 维持；产品化再做签名 | A |
| L12 | 测试·脆弱耦合 | core/path_io.py | 100% 覆盖全靠超分引擎测试间接获得，重构即静默掉覆盖 | 补 tests/test_path_io.py 直测 3 例 | T |

---

## 🏗️ 架构影响评估（Archi 主笔）

**架构现状速写**：
- 分层纪律良好：core（零外部依赖）← serving（组合层）← dispatcher；gui 与 serving 互不依赖（grep 实证 0 命中），W45 跨层已消。
- 双通道契约单源成立：gRPC 控制信道 + 文件映射 MMF 数据通道；C# 以相对路径链接同一份 proto，无手工双份。
- 生命周期守护成熟：启动清扫 → TTL 惰性回收 + 64KiB 内联 → 租约/流式 PoC（ADR-0002 冻结留档，含 11.7x 实测基准）。
- ADR 实践真实：4 份 ADR 含冻结/再启条件/被拒备选。

**建议固化的 ADR**：
- **ADR-0005 UnloadModel 生命周期单一所有者**：dispatcher 增 unload_supervised(task)（持锁摘 _engines、锁外 unload）；server.UnloadModel 只调它。消除元数据失真与越层 import。代价约 0.5 人日。
- **ADR-0006 task 字符串契约收紧（fail-closed）**：未知 task 由静默回退 DET 改 abort(INVALID_ARGUMENT)；C# 枚举对账（删 Vlm 或补缺值）。双端同步改动 + 负例测试 + RELEASES.md 行为变更声明，约 1 人日。

---

## 🧪 测试覆盖评估（Tessa 主笔）

**覆盖实测总览**（行覆盖，快照 2026-09-29）：

| 模块 | 行数 | 覆盖率 | 评价 |
|---|---|---|---|
| serving/shared_memory.py | 543 | 99.2% | ★★★★★ 生命周期/TTL/租约/上限全覆盖 |
| serving/server.py | 398 | 92.6% | ★★★★☆ 缺错误分支 |
| serving/serialization.py | 245 | 93.1% | ★★★★☆ |
| core/auth.py / config.py | 113/94 | 100% | ★★★★★ |
| core/audit_logger.py | 286 | 94.8% | ★★★★☆ |
| core/interfaces_supervised.py | 480 | 91.5% | ★★★☆☆ 安全反序列化极强，但基类 unload/_ensure_loaded/infer_batch 全未跑 |
| core/image_io.py | 78 | 87.2% | ★★★☆☆ 缺 PIL 回退路径 |
| core/mask_codec.py | 64 | 82.8% | ★★☆☆☆ decode 错误路径全缺 |
| core/detection_history.py | 253 | **79.6%（本区最低）** | query_from_file :189-210 整函数零覆盖 |

**关键测试盲区（🔴 级 2 项）**：
1. **并发路径零测试**：生产 max_workers=8 并发 Detect，但"线程安全"宣称零线程测试背书——与 H6 TOCTOU 竞态互为因果。建议 `test_concurrent_write_read_release_under_ttl_reap`（8 线程读写释放 + TTL 回收线程，断言无异常、目录清洁、数据一致）。
2. **gRPC 真通道 E2E 缺失**：全部测试直调 Servicer，线程分发/流式 FetchRegion/句柄跨 channel 序列化/abort 语义未在真实栈验证。建议 in-process E2E（marker integration，回环可跑）。

**门禁稀释**：core 单独 91.2% < 92% 全局门禁（被 12 包分母抬过线）；分支覆盖未开启。建议 per-module 棘轮地板。

**正面样本**：shm 99.2% 对抗性覆盖、safe_extract 安全反序列化对抗用例、RED-first 测试纪律均属范例。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 修复 S1 任意文件读取：read_range/read_array/read_bytes 加 base_dir + ava_*.bin 白名单，FetchRegion 校验后再读 | 后端 | P0 | 本周 |
| 2 | 修复 S2 恶意 RLE OOM：decode 上限校验 + int64 求和 + 负 runs 拒绝，同步补 4 例负路径契约测试 | 后端 | P0 | 本周 |
| 3 | 修复 H2 端口假启动（add_insecure_port 返回值检查）、H3 mkdir 移入 try、H4 部分写循环、H5 threshold=0（proto optional + HasField） | 后端 | P0 | 本周 |
| 4 | 修复 H6 TOCTOU 竞态（锁内拷贝）+ H7 负 offset 校验，并补并发压力测试（Tessa 用例） | 后端+测试 | P1 | 下周 |
| 5 | 落地 ADR-0005（UnloadModel 单一所有者，0.5 人日） | 后端 | P1 | 下周 |
| 6 | 落地 ADR-0006（task 契约 fail-closed + C# 枚举对账，1 人日，含 RELEASES.md 行为变更声明） | 后端+C# | P1 | 下周 |
| 7 | 补 in-process 真 gRPC 通道 E2E（Ping/Detect/FetchRegion 流式/Release 全链路） | 测试 | P1 | 下周 |
| 8 | 确认引擎并发 infer 线程安全（H8）：per-engine 单飞守卫或文档化串行约束 + 并发用例，写入 ADR | 后端 | P1 | W2 |
| 9 | detection_history 清债：query_from_file 测试或删除（连同 _ensure_loaded 死代码判定），拉高 79.6% 至 ~95% | 测试 | P2 | W2 |
| 10 | H1 LoadModel/Detect 路径白名单（模型根目录 + 数据目录前缀校验） | 后端 | P2 | W2 |
| 11 | M16 覆盖率门禁改造：per-module 棘轮地板 + 试开 --cov-branch | 测试 | P2 | W3 |
| 12 | 卫生级批量清理：L7 shim 直连、M4 fsync 开关、M7 auth hex 防御、M6 审计接入 serving 路径、L12 path_io 直测 | 后端+测试 | P2 | W3 |

---

## ⚠️ 待完善 / 已知局限

- 审查范围聚焦 core/ + serving/ Python 侧；gui/（43 文件）、training/、labeling/ 未在本轮范围，C# 侧仅做契约对账未做代码审查。
- 引擎层（models/）线程安全为"范围内未证实"，非"已证实不安全"——H8 需专项确认。
- 覆盖率数据基于 2026-09-29 快照，若其后有提交需重跑校准。
- dotnet_client/Tests 的 C# 侧测试质量未评估，跨语言契约目前主要靠 C# 自测守卫。

---

## 📚 数据来源 & 成员产出索引

- Cody（代码审查师）原始产出：25 项发现清单（🔴2/🟠7/🟡10/🟢6）+ 5 项正面样本 + 结论 Request Changes（完整清单见本报告 🔍 章节 C 标注项）
- Archi（架构师）原始产出：11 项架构风险（🟠2/🟡2/🟢5 + 2 项前提修正/可接受项）+ ADR-0005/0006 建议 + 架构现状速写
- Tessa（测试专家）原始产出：覆盖实测总览（16 模块行覆盖率精算）+ 12 项盲区清单 + TOP5 高价值补测建议 + 门禁稀释结论
- 交叉印证记录：H5（C#9×A#5）、H6（C#7×T#1）、H8（C#19×A#4）、S2（C#2×T#5）——四组独立发现互相验证，可信度加权

---

> 本报告由工程保障团队 AI 协作生成（主理人：甄宇航；成员：科迪/阿奇/泰莎），关键决策请由人类工程负责人复核。
