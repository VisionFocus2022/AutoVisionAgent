# ADR-0002：serving 大载荷协议演进（租约 / 流式拉取）双方向 PoC

- **状态**：已接受（2026-08-18，W19 v3 第三波 FR-2）；**冻结**（2026-08-21，
  W24/v4 P3-2 复核）——双方向维持 PoC/协议能力形态不接线（W24 取证：
  C# 客户端零 lease/FetchRegion 调用，消费形态为内联+MMF 直读双路径、
  Release 不带 lease_id），生产默认路径零改动维持；**跨机场景再启**
  （重开条件见 §决策 4）
- **关联**：v2 架构审查 P1-1（共享内存生命周期）；W17 TTL/inline（PRD
  wave17 FR-004~005）；ADR-0001（回环拓扑）；PRD wave19 FR-2
- **范围**：`serving/proto`、`serving/shared_memory.py`、`serving/server.py`
  ——仅 PoC 能力落地，**生产默认路径零改动**（`serving/serialization.py`
  未动，既有用例原样通过即证）

## 背景

大块二进制（原图、掩码、关键点）走「gRPC 控制信道 + 共享内存文件映射」
双通道设计自 W3 起定型。生命周期守护经历了三代：

1. **W11（P1-1）**：启动清扫陈旧 `ava_*.bin` + 区域登记上限（默认 64，
   `AVA_SHM_MAX_REGIONS`）——兜住崩溃残留与忘 release 的静默泄漏；
2. **W17（P1-1 续）**：区域 TTL 惰性回收（`_reap_expired`，默认 300s，
   写路径触发）+ 小数组内联（<64 KiB 的 masks/keypoints 直接内联 proto，
   不建区域）+ Release 未命中不再假报成功——兜住随附 C# 客户端结构性
   无法回收结果区域的累积触顶；
3. **遗留张力**（本 ADR 议题）：
   - TTL reaper 与客户端消费窗口之间存在理论竞态——客户端还在读、
     服务端 TTL 到期即回收；
   - 消费端必须能做同机文件映射（MMF）。跨机/受限沙箱的消费者
     目前没有任何大数组取回通道。

对应两个演进方向：**方向 A（租约语义）**与**方向 B（服务端流式拉取）**。
W19 以 PoC 方式双方向并行验证：协议 additive 演进 + 管理器/RPC 语义
落地 + 测试与微基准实证，**不切换生产路径**。

## 方向 A：区域租约（lease）语义

### 设计

- `SharedMemoryHandle` 增 `lease_id=6` / `lease_ttl_ms=7`（additive，
  PoC 注释）；`ReleaseSharedMemoryRequest` 增 `lease_id=2`：非 0 时
  服务端校验归属（与在册租约一致才允许释放），不匹配 → `success=False`
  且区域不动。
- `SharedMemoryManager` 增租约登记表（进程内自增 lease_id）：
  - `acquire_lease(key, ttl_ms)` → lease_id（同区域覆盖式登记，单租约
    模型）；
  - `release_leased(file_path, lease_id)` → 校验归属后释放；
  - `_reap_expired` 跳过租约未到期的区域——**租约到期时钟与区域 TTL
    时钟独立**（两时钟取长者保护区域；租约到期后 TTL 回收恢复，
    非永久保护）；
  - `release`（任意路径回收）同步摘除在册租约。

### 测试结论（tests/test_w19_lease.py，4 用例全绿）

| 态 | 用例 | 结论 |
| --- | --- | --- |
| (a) 正确租约释放 | `test_correct_lease_releases_region` | ReleaseSharedMemory 携带正确 lease_id → success=True、文件删除 |
| (b) 错误租约被拒 | `test_wrong_lease_rejected_keeps_region` | 错误 lease_id → success=False + 非空 error，区域仍在 |
| (c) 活跃租约豁免 reaper | `test_active_lease_blocks_ttl_reaper` | 区域 TTL 已过 + 租约未到期，触发清扫后区域仍在且可读 |
| (c') 租约到期恢复回收 | `test_expired_lease_no_longer_blocks_reaper` | 两时钟均过期后 TTL 回收恢复（临时豁免而非永久保护） |

语义成立。但生产启用还需两处契约改动：服务端 serialization 在写出
结果区域时建租约并回填 handle 字段（本 ADR 明确**不做**，AC-2.4 默认
路径零改动），C# 随附客户端把 lease_id 透传进 Release——在竞态仅
理论存在（结果区域消费窗口远小于 300s TTL）时，收益不抵契约复杂度。

## 方向 B：FetchRegion 服务端流式拉取

### 设计

- proto 新增 `ArrayChunk { bytes data=1; int64 offset=2; bool last=3; }`
  与 `rpc FetchRegion(SharedMemoryHandle) returns (stream ArrayChunk)`
  （additive，PoC 注释）。
- 服务端按句柄 1 MiB 切块流式回传（`serving/server.py` FetchRegion，
  分块读走 `SharedMemoryManager.read_range`——优先本进程 mmap，否则
  按路径读文件）；区域不存在/已被回收 → `context.abort(NOT_FOUND)`；
  短读（文件被截断）同样 abort。
- 客户端按 `offset` 单调性拼块、`last` 收齐，逐字节校验。

### 测试与微基准

- 正确性（tests/test_w19_fetch_region.py，3 用例全绿）：2 MiB+非整块
  尾巴 → 3 块拼回逐字节相等；恰 1 MiB → 单块且 last；缺失区域 →
  NOT_FOUND abort。
- 性能（`scripts/bench_region_transfer.py`，64 MiB uint8 固定种子伪随机
  载荷，每路径 10 轮（计时轮仅收齐，逐字节一致性在每路径收齐后以一次
  额外补读整体校验），本机回环，Python 3.12 /
  grpcio 1.83.0，2026-08-18 实测）：

| 路径 | 轮数 | 中位时延 (ms) | 吞吐 (GB/s) | 最小/最大 (ms) |
| --- | --- | --- | --- | --- |
| (a) 直读 `read_bytes`（现消费端形态） | 10 | 18.91 | 3.549 | 17.11 / 28.75 |
| (b) gRPC FetchRegion 流式收齐 | 10 | 222.14 | 0.302 | 199.47 / 262.95 |

中位时延比 **11.7x**；两路径均与原文逐字节相等。测量口径：server 与
client 同进程但经真实回环 TCP + 完整 protobuf 序列化；服务端分块源为
本进程 mmap（与生产服务端读自有区域同形态），故 (b) 的开销是协议栈
（序列化/分帧/流控）而非磁盘。

## 决策（按实测数据）

1. **生产默认路径不变**：Detect 仍走 W17 形态（小数组内联 + 大数组 shm
   句柄 + 客户端 MMF 直读 + Release）；`serving/serialization.py` 零改动。
   依据：直读 3.55 GB/s 对 64 MiB 载荷 19ms 级取回，流式 0.30 GB/s
   （11.7x 劣势）——同机场景没有任何理由用方向 B 替代共享内存。
2. **方向 A（租约）以 PoC 形态留档**：管理器与 RPC 语义已落地且测试
   锁定，但 serialization/C# 不接线。竞态目前只是理论（消费窗口 <<
   300s TTL），提前启用等于给所有客户端加契约负担。
3. **方向 B（流式拉取）以协议能力形态保留**：additive RPC 对既有
   客户端零成本（不用即无开销）；它是未来跨机/无法 MMF 消费端的唯一
   取回通道，字节正确性已实证；吞吐瓶颈（1 MiB 块、Python 单流）届时
   可先调块大小/并发流再谈架构。
4. **再评估触发条件**（满足其一即重开本 ADR）：
   - 方向 A：现场出现「结果区域在消费窗口内被 TTL 回收」的实据
     （客户端 NOT_FOUND 落日志），或出现 >TTL 的长消费模式；
   - 方向 B：出现真实跨机部署需求（须与 ADR-0001 回环立场一并重评），
     或同机出现无法做 MMF 映射的消费端（受限沙箱等）；
   - 任一方向：W17 内联阈值（64 KiB）或区域上限（64）出现实测压力
     信号时，优先复核本 ADR 的载荷/吞吐假设。

## 备选方案（已拒绝）

- **默认启用租约**：契约复杂度（双端改动）先于需求落地，违背
  「协议 additive、默认路径零风险」原则。
- **用 FetchRegion 取代共享内存通道**：同机 11.7x 劣势，实测否决。
- **gRPC 大消息一次回传（非流式）**：单消息受 4 MiB 默认上限约束，
  调大上限会放大单消息序列化/拷贝峰值内存，流式分块是更稳的形态。
