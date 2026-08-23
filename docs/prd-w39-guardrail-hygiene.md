# W39 护栏收口+卫生清偿波（v6 二波 P2×5 + 三波 P3×9） — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-23 | 档位: 🟡 L2 | 确定性: 高（P2-3/4 语义已经探索门禁裁决：反转宽容态+离线降级） | 影响半径: 大（命中硬触发器 3：权限门控语义变更 + 多模块；均双向门） | 可逆性: git 原子提交
> 前置：v6 报告 §8 二/三波；W38（`29298b8`）后全量 1106 绿基线。

## 1. 背景与目标

- **背景**：v6 剩余项——二波护栏收口（P2-3 宽容态全放行 / P2-4 离线一键 admin / P2-6 data_manage 批量工具漏门控 / P2-7 预标注标签语义分叉 / P2-8 原子写三胞胎）+ 三波卫生 8 项 + 顺带 P3-5。
- **目标**：
  1. 角色护栏真正落地：未登录=operator 最小集、离线=operator、批量破坏性写盘操作入动作门控与审计
  2. 重复实现收敛（原子写单源）、语义统一（标签映射/门控顺序/审计字段）
  3. 卫生清偿：死键/死代码/死控件/unused//FakeThread 收敛；全量回归绿

## 2. 功能需求 (FR)

- **FR-001**: P2-3 宽容态反转 — 未登录（role=None）从「全 11 页可见+全动作放行」反转为「operator 最小集 + operator 动作集」：`shell.select`/`_apply_nav_visibility` 去除 None 特赦（经 `page_allowed` 既有未知角色→operator 回退）；`check_action` 未登录按 operator 矩阵判；登录页恒可见保持。W29 语义变更记入模块 docstring。 | P0
- **FR-002**: P2-4 离线降级 — `login/page.py:543` `login_success.emit("offline", ROLE_ADMIN)` → `ROLE_OPERATOR`；相关 docstring 与测试同步。 | P0
- **FR-003**: P2-6 data_manage 批量标签工具入控 — `_ACTION_MATRIX` 登记 `data_manage.batch_label_edit`（三角色全允许，同既有 3 动作语义=审计留痕+未来收紧挂钩）；批量替换标签/批量删除标签/标注统计三按钮入口 `check_action` 消费；页面级门控测试（哨兵模式，仿 test_w35）。 | P0
- **FR-004**: P2-7 标签语义统一 — `gui/pages/label/workers.py` 单张 AI 预标注 `labels[0]` 改逐框 `labels[i]`（与批量版一致，多类 DET 正确）；新增多类结果测试。 | P0
- **FR-005**: P2-8 原子写收敛单源 — `labeling/batch_tools.py` 强实现（mkstemp+告警）提升为公开 `atomic_write_json`；`gui/pages/predict/workers.py` 与 `gui/pages/label/batch_prelabel.py` 两处弱版删除改 import；既有测试全绿。 | P0
- **FR-006**: P3-1 门控顺序统一 — `predict/page.py` `_batch_infer` 与 `video_super_actions.py` 的 `check_action` 移至按钮入口首行（与 label 页及 docstring 约定一致）。 | P1
- **FR-007**: P3-2/3 审计一致性 — `check_action` 审计 `page=f"action:{action}"` 前缀区分两类 id；`predict/page.py:385` 裸 `pass` 补 `logger.warning`；`audit_logger` mkdir 移入 try + `_buffer` 硬上限（1000 条丢最旧+告警）。 | P1
- **FR-008**: P3-5/9/12/13 卫生 — permissions 模块头补「check_action 带副作用」声明；16 硬死键删除（删前主会话 grep 双源复核零消费）；「记住登录状态」死控件删除（删前 grep 测试引用，有引用则申报偏差改保留）；`unused/` rmdir。 | P1
- **FR-009**: P3-10/16 测试卫生 — test_w35 接线断言改行为化（构造登录回调断言 `session.get_current_role()` 生效）+ 删 FakeThread 死代码 + docstring 4→3；FakeThread/fake_threads 上移 `tests/conftest.py` 单源，全部本地副本删除（grep 清单驱动）。 | P1
- **FR-010**: 收尾 — 全量回归 + `git status` 范围核对 + commit 经门禁批准。 | P0

## 3. 验收标准 (AC)

- **AC-001**: 新语义测试：未登录时 operator 不可见页（train/deploy/settings 等）导航按钮隐藏且 `select` 拒绝+审计；未登录+未登记动作 → check_action 拒绝；未登录+已登记动作 → 放行 [FR-001]
- **AC-002**: 离线路径测试：`_do_offline` 后 `get_current_role()=="operator"`（行为化断言）[FR-002]
- **AC-003**: data_manage 三工具门控测试：monkeypatch check_action 拒绝时对话框未触碰+早退；放行时正常执行 [FR-003]
- **AC-004**: 多类 DET（labels 长度≥2 且不同）单张预标注结果逐框标签正确 [FR-004]
- **AC-005**: 原子写三处调用单源（grep 生产代码 `atomic_write_json` 定义=1 处）；predict/w30 既有测试全绿 [FR-005]
- **AC-006**: 门控顺序：grep 三消费点 `check_action` 均先于引擎/任务类型检查 [FR-006]
- **AC-007**: 审计：`action:` 前缀测试或 grep 证据；audit_logger 新增 buffer 上限测试（构造不可写目录时缓冲有界不炸）[FR-007]
- **AC-008**: 死键删除后 i18n 守卫与 test_w38 四方守卫全绿；`unused/` 不存在；死控件零残留 grep [FR-008]
- **AC-009**: FakeThread 定义 grep 全仓=1（conftest）；test_w35 行为化断言通过 [FR-009]
- **AC-010**: 全量回归 ≥1110 收集全绿（4 skipped 维持）；改动范围=PRD 列明文件集合；歧义词 0 [FR-010]

## 4. 范围

- ✅ **In Scope**: 上列 10 FR 对应文件（shell.py / permissions.py / login/page.py / data_manage/page.py / label workers+batch_prelabel / predict workers+page / video_super_actions / audit_logger / i18n.py / make 无 / tests 若干 + conftest）
- ❌ **Out of Scope**: P2-1 UIA 12/12（空闲机排期项）；P3-6 未知角色回退矛盾（语义决策）；P3-7 lite 剪除动态守卫（构建脚本）；P3-11 初始凭据（威胁模型内无增量）；P3-14 lite 余量 CI 挂钩；P3-15 mask_codec 分层（决策项）；单图 save() 路径；RELEASES.md（攒到下个版本节点）

## 5. 风险与假设（含探索三栏）

- **已知**: W29/W35 权限测试基础；conftest 在位；16 死键清单（一致性 agent 核验，删前双源复核）；W38 基线 1106 绿
- **假设**: test_w29/test_w35 中编码旧宽容态语义的断言=测试过时（用户已裁决变更），更新断言合法且必要；UIA 用例若引用旧语义（如登录前导航全可见）标注为待空闲机 UIA 轮回归（本轮不跑 UIA）
- **未知**: 无残留（2/2 已裁决）
- **风险**: ① 反转影响面超预期（登录前首页可达性/首次启动流程）→ 执行中逐任务回归，超预期即按协议升档汇报；② 死控件删除碰 UIA 引用 → 删前 grep，有引用则保留并记偏差；③ FakeThread 收敛动 ~6-10 测试文件 → 纯机械迁移+逐文件跑

## 6. 实现思路

- **拟采用**: 语义组（FR-001/002）先行建新测试基线再反转；登记组（FR-003）仿 test_w35 模式；收敛组（FR-005）公开化+import 替换；卫生组（FR-008/009）grep 清单驱动；每任务 TDD/受影响套件绿后下一任务
- **复用**: page_allowed 未知角色→operator 既有回退（FR-001 无需新矩阵）；test_w35 哨兵模式；batch_tools 强实现
- **注意**: FR-001 的 select 拒绝路径已带审计（`_audit_access_denied`），反转后未登录点锁页会写审计——role 字段为空串，保持现状即可；FR-005 gui→labeling import 已有先例（label/page.py）

---

## 自检（5 项）

- [x] 完整性: FR-001~010 全编号
- [x] 无歧义: 本文件歧义词 grep = 0
- [x] 可追溯: 每 FR 有 AC
- [x] 范围清晰: In/Out 已列
- [x] 指标可量化: AC 均可执行判定

## ✅ 门禁（3 项）

- [x] 门禁 1 探索门禁：2 问已裁决（2026-08-23：反转+降级 / 二波全+三波 8 项）
- [x] 门禁 2 PRD：AskUserQuestion 确认 → 进入执行（2026-08-23 用户确认；执行中 P2-4 重裁决：降 operator+UIA 改真登录）
- [x] 门禁 3 收尾：AC 全过 + 全量回归 1111 绿 + commit 全部批准 + FB-004 顺延/FB-005/006 反哺批准 + 综合学习消化（2026-08-23）
