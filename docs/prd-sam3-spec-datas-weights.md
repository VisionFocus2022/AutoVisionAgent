# PRD — SAM3 权重 spec datas 纳入（构建自动带权重）

> 档位：🟡L2 | 日期：2026-09-01 | 版本：v1.0
> 上游：docs/prd-sam3-exe-auto-discovery.md（exe 闭环批遗留运维点：「重打包后须重新复制 3.3G；spec datas 纳入是独立发布决策，用户裁决延后」——本批即该决策的落地）
> 关联学习：learn-20260831-sam3-exe-closure（robocopy 手动复制为权宜态）

## ✅ 门禁记录

- [x] 门禁 1（探索，2026-09-01）：三栏账确认通过；D1 裁决=权重缺失时**硬失败 BUILD-ABORT**（仿 spec 头部 AVA-R1 防呆先例，防静默残废 exe）
- [ ] 门禁 2（PRD）
- [x] 门禁 3（收尾，2026-09-01）：四 AC 全过确认；提交 a33b319（7 文件 pathspec 隔离，push 留用户）

## 1. 背景与目标

上批 exe 闭环采用「重打包 → 手动 robocopy 3.21GiB 权重到 `_internal/weights/sam3` → 跑 UIA」的权宜链，遗留运维点：**每次重打包清空 dist 后须手动重复制权重**，漏做即静默产出无 SAM3 能力的 exe（自动发现落空 → 弹对话框）。本批把权重纳入 `autovisionagent.spec` datas，使构建自动带权重。

## 2. 功能需求（FR）

- **FR-001** spec datas 纳入：`autovisionagent.spec` datas 增加 `("weights/sam3", "weights/sam3")`，重打包后 `_internal/weights/sam3` 自动就位，运行时发现链（sam_session 约定目录）零改动。
- **FR-002** 缺失防呆：`weights/sam3/model.safetensors` 缺失时打包 `[BUILD-ABORT]` 硬失败（exit 1），提示下载指引（ModelScope transformers 格式，README 在 weights/sam3/README.md）——防「以为带了实际没带」的静默残废 exe。
- **FR-003** lite 同步裁剪：`scripts/make_lite_dist.py` 裁剪清单加 `weights/sam3`（easyocr 同语义：lite 是 CPU-only，3.4GB SAM3 CPU 推理不现实；引擎注册保留、load 走诚实失败路径），LITE_MARKER.json 留档裁剪字节。
- **FR-004** spec 守卫防回退：test_w26 增 datas 断言（AST 解析），锁定 weights/sam3 在 datas 内。

## 3. 验收标准（AC）

- **AC-1** 全量重打包（--noconfirm）成功，`dist/AutoVisionAgent/_internal/weights/sam3/model.safetensors` 存在且与源逐字节同大（3,439,938,512 B）。
- **AC-2** 临时改名 weights/sam3 后重打包 → `[BUILD-ABORT]` 退出码非 0 且报 SAM3 权重缺失提示；恢复后打包正常（防呆可逆验证）。
- **AC-3** lite 单测：假树含 `_internal/weights/sam3` → 派生后该目录不存在 + marker 留档裁剪量；主门禁 rc=0 覆盖率 ≥92 不降。
- **AC-4** UIA exe 模式抽验：`test_sam3_auto_discovery_no_env` 在重打包产物上实跑（非 skip）且绿——自动发现全链闭环。

## 4. 范围

**做**：spec datas + 防呆断言 / make_lite_dist 裁剪清单 / 守卫与单测 / release-checklist 及 README 打包说明小节更新。
**不做**：运行时发现逻辑（零改动）/ lite 产物本批不重派生（下次发版随流程走）/ git 纳管权重（3.21GiB 不入库）。

## 5. 风险与假设

- 构建+产物体积：full dist 4.4G→~7.6G，打包时长 +约 1 分钟（3.4G 复制）——已知成本，接受。
- 假设：PyInstaller 6.x datas 目录元组落点=`_internal/weights/sam3`（标准语义，AC-1 实证收口）。
- lite 真产物守卫（test_real_lite_dist_guard）字节对账口径排 logs/pycache，与本次裁剪无冲突；下次真派生自动生效。

## 6. 实现思路

spec 头部防呆区（AVA-R1 断言之后）加权重存在性检查 → datas 列表加元组；make_lite_dist 的 `_prune_optional_packages` 调用清单加 `"weights/sam3"`（注意现签名收包名列表、路径按 `_internal/{name}` 解析，weights/sam3 带子路径需确认该函数按目录名拼接是否兼容——若不兼容则新增专用裁剪调用）；测试三件：spec AST 守卫（datas 含元组）/ lite 假树单测 / 缺失防呆以 AC-2 实打包验证。
