# 复刻计划 — 文档索引（README）

> ⚠️ **2026-07-01 订正**：本索引及其链接的 `execution-plan-rebaseline.md` 基于代码**旧快照**（`E:\学习项目\视觉大模型`，无 venv）所写，对 R0/R1/R2 完成度的判断已过时。真实树 `E:\计算机视觉\视觉大模型`（带 venv）已完成绝大部分且测试诚实。**当前真源 → `E:\计算机视觉\视觉大模型\docs\复刻计划\STATUS.md`**（1713 passed / 1 xfailed / 0 failed / 80.77%）。本目录文档保留为「方法论 / 决策档案」参考。

> 本文件夹是 **AutoVisionAgent**（对标复刻 `skolpha.exe` 3.3.2，去 DRM、留 Fernet 待决策）的规划文档集。
> 代码实际位置：`E:\学习项目\视觉大模型`（对标来源 `skolpha.exe` 在 `E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\`）。
> **2026-06-30 重定基线**：核查发现旧 DoD 与代码整体脱节 → 本索引下面的「状态」列反映代码事实，不是文档自报。

---

## 0. 先读这一段（重定基线结论）

既有 `tasks-fix-backlog.md §9` 的 DoD（9.5/10 完成、80% 覆盖率、1693 passed）**与代码实际状态大面积脱节**：

- 🔴 **det / seg / abdet 三个 P0 旗舰引擎根本不在磁盘上**（被 `engines/__init__.py` 的 `except ImportError` 静默吞掉）。
- 🟡 sseg / sgan / super 仍是 mmseg/mmedit 桩（`score=1.0` / `arr.copy()` / `INTER_NEAREST` 假回退），宣称的「Option A 轻量库真化」从未落地。
- 🔴 训练无任何真策略（`training/strategies/` 不存在）；`_SmokeStrategy` 改名 `_SimStrategy` 仍用 `math.exp` 造假 loss。
- 🔴 `enterprise/`（LicenseManager）、`core/encryption.py`（Fernet）、`run_app.py` 已整个删除，但计划仍宣称「沿用」。
- 🔴 P2 四项（3D / 视频超分 / OCR / SAM 全自动+ONNX）标 `[x]`，代码里 0 实现。
- ⚠️ 所谓 80% / 1693 passed **部分靠把未真化的引擎排除出覆盖率 + 测假回退路径**达成。

**剩余真实工作的单一真源 → [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md)**。

---

## 1. 文档清单（按状态分层）

| 文件 | 角色 | 状态 |
|------|------|------|
| **`execution-plan-rebaseline.md`** | 🔴 **当前真源**——诚实现状盘点 + 剩余真实工作 + 防假绿验证 | ✅ 2026-06-30 新建 |
| **`README.md`** | 本索引 / 导航 | ✅ 本文件 |
| `qoder-checklist-mfix.md` | 任务调度 + 进度勾选视图 | 🔧 2026-06-30 已订正（修假 `[x]` + 自相矛盾） |
| `tasks-fix-backlog.md` | fix-backlog 战役任务详情（v1.1.0） | 🔧 2026-06-30 已订正（DoD 重写 + 订正声明） |
| `tasks-tech-debt.md` | 10 条工程债登记 | 🔧 2026-06-30 已订正（补状态列：6 解 / 4 残） |
| `prd-fix-backlog.md` | fix-backlog 战役 PRD（v1.1.0） | 📌 era-3 设计意图存档；顶部已加订正横幅 |
| `design-fix-backlog.md` | fix-backlog 战役 Design（v1.1.0） | 📌 era-3 设计意图存档；顶部已加订正横幅 |
| `prd-skolpha-fork.md` | 最初完整对标 PRD（v1.0.0） | 📚 era-1 历史 |
| `design-skolpha-fork.md` | 最初架构 Design（v1.0.0） | 📚 era-1 历史（接口契约仍可参考） |
| `tasks-skolpha-fork.md` | 最初 37 任务路线图（v1.0.0） | 📚 era-1 历史 |
| `execution-plan-autovisionagent.md` | T-AVA-01..21 执行计划（v1.0.0） | 📚 era-2 历史（**已自述被取代**，见其顶部警告） |

**状态图例**：✅ 当前真源 · 🔧 已订正 · 📌 设计存档（执行以 rebaseline 为准）· 📚 历史存档（不再驱动执行）

---

## 2. 阅读顺序

**新人 / 接手者（3 步）**：
1. 本 README §0（了解为何要重定基线）。
2. [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §1 现状盘点 + §2 剩余工作（知道要做什么）。
3. [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §3 防假绿验证（知道怎样才算真完成——避免重蹈假绿）。

**想了解历史决策脉络**：era-1 三件套（`*-skolpha-fork.md`）→ era-2 `execution-plan-autovisionagent.md`（已取代）→ era-3 `*-fix-backlog.md`（已订正）→ era-4 `execution-plan-rebaseline.md`（当前）。

**想查具体任务签名/文件/验证命令**：`tasks-fix-backlog.md` 仍是任务详情库，但**任何「完成状态」以 rebaseline §1 + `qoder-checklist-mfix.md` 订正版为准**。

---

## 3. 三个文档时代（为什么有这么多文件）

| 时代 | 时间 | 文档 | 主旨 | 结局 |
|------|------|------|------|------|
| **era-1 fork 规划** | 2026-06-28 | `prd/design/tasks-skolpha-fork.md` | 完整对标 SKolpha 的宏伟蓝图（37 任务 / ~125 人日） | 止于规划；被后续执行超越 |
| **era-2 AVA 执行** | 2026-06-29 | `execution-plan-autovisionagent.md` | T-AVA-01..21 自主执行 | 标 ✅ 但埋下「假绿」；自述被 era-3 取代 |
| **era-3 fix-backlog** | 2026-06-29→30 | `prd/design/tasks-fix-backlog.md` + `qoder-checklist-mfix.md` + `tasks-tech-debt.md` | 补 9 项「标 ✅ 但未兑现」 | 标 ✅ 但**再次假绿**（Option A 未落地 / P2 全缺 / 引擎缺） |
| **era-4 重定基线** | 2026-06-30 | `execution-plan-rebaseline.md` + 本 README + 订正 | 拉回真实；接管剩余工作 | **当前真源** |

> 元教训：每代都「标 ✅」又都被下一代发现失真。era-4 的核心增量是 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §3 **防假绿验证标准**——把「怎样算真完成」机制化，打破循环。

---

## 4. 关键订正

1. **代码路径**：旧文档普遍写目标项目 `E:\计算机视觉\视觉大模型\`；实际代码在 `E:\学习项目\视觉大模型`。`E:\计算机视觉\` 下只有 skolpha.exe 对标来源。
2. **「9 引擎」**：枚举 `TaskType` 确为 9 成员，但磁盘上只有 6 个引擎文件（det/seg/abdet 缺），其中 3 个是桩。
3. **「80% / 1693 passed」**：技术上跑得过，但测的多是桩与回退；不等于功能真通。
4. **入口**：实际入口 `python -m gui.main`（无 `run_app.py`）。

---

## 5. 如何继续工作

- **开发**：从 [`execution-plan-rebaseline.md`](execution-plan-rebaseline.md) §2.1 R0-4（注册表止血）起步，按 §4 里程碑推进；每项过 §3 的 V-条款。
- **决策**：R1-1/R1-2/R1-3（Fernet / 授权 / 入口）需用户在「恢复承诺」与「撤销承诺改文档」之间拍板。
- **每完成一项**：同步更新 `qoder-checklist-mfix.md` 的勾选，并确保该 `[x]` 有代码事实支撑（不再自相矛盾）。

---

*本索引由 2026-06-30 重定基线产生。文档冲突时的优先级：`execution-plan-rebaseline.md` > 本 README > 订正后的 `qoder-checklist-mfix.md`/`tasks-fix-backlog.md` > era-3 设计存档 > era-1/2 历史。*
