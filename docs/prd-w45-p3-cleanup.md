# W45 v6 遗留 P3 五项清偿 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-24 | 档位: 🟡 L2 | 可逆性: 双向门
> 前置：v6 报告 §4.5 P3-6/7/11/14/15 + W39 顺延裁决；探索门禁已裁决（P3-6 统一回退 operator / 五项全清）。

## 2. 功能需求 (FR)

- **FR-001** (P3-6): `permissions` 未知/异常角色统一回退 operator——`_normalize_role(role) -> str`（非 ROLES 成员 → ROLE_OPERATOR），`page_allowed`/`action_allowed`/`check_action` 统一经其归一；未登记动作全角色拒绝（W29 语义）不变。测试：未知角色 × 已登记动作 = operator 同判定；未登录（None）路径行为不变（W39 测试全绿零改动）。 | P0
- **FR-002** (P3-7): 剪除包 import 守卫——新测试断言全仓（排除 .venv/__pycache__/tests 自身 stub）不得出现 `shapely|bidi|pyclipper` 顶层 import，且 `easyocr` 仅允许 `models/supervised/engines/ocr_easyocr.py` 惰性导入（lite 剪除断链防误用，仓侧先行）。 | P0
- **FR-003** (P3-11): `initial_credentials.txt` 首行显著警示「⚠ 工位交付后立即登录修改并删除本文件」；`_parse_initial_pwd` 正则（`^初始密码:` 多行匹配）不受影响（既有 UIA 测试口径零变化）。 | P0
- **FR-004** (P3-14): test_w19 lite 守卫补**余量棘轮**——apparent 总量硬断言 ≤ 2GiB 且余量 ≥ 5MiB（现状 6.5MiB 过）；余量 < 10MiB 打印预警（非阻塞）；棘轮注释声明「升线前须先减重」。 | P0
- **FR-005** (P3-15): `mask_codec` 下沉 `core/mask_codec.py`（纯函数移动零改动）；`serving/mask_codec.py` 改为 re-export shim（serving 三处引用零改动兼容）；`gui/pages/predict/workers.py` 改 import 自 core（消除 gui→serving 跨层）。测试：新导入点可用 + shim 兼容。 | P0
- **FR-006**: 全量回归 + 总检 + 沉淀（收尾检查 learning 阈值）。 | P0

## 3. 验收标准 (AC)

- **AC-001**: 新测试——`action_allowed("intruder", <已登记 operator 允许动作>)` is True、`action_allowed("intruder", "unregistered")` is False、`page_allowed("intruder", "settings")` is False（回退 operator）；W39 语义测试（w29/w35）零改动全绿 [FR-001]
- **AC-002**: 剪除包守卫测试绿；人为注入 `import shapely` 时红（自测用 monkeypatch 临时文件或以测试内 fixture 证明正则有效）[FR-002]
- **AC-003**: 凭据文件内容含首行警示；`re.search(r"^初始密码:", content, re.M)` 仍命中 [FR-003]
- **AC-004**: test_w19 lite 守卫含余量断言（dist 存在时）；<10MiB 预警可见于测试输出路径（capsys 或注释说明）[FR-004]
- **AC-005**: `from core.mask_codec import encode_mask_rle` 可用；`from serving.mask_codec import encode_mask_rle` 兼容；workers.py 无 serving 引用（grep=0）[FR-005]
- **AC-006**: 全量回归绿；歧义词 0 [FR-006]

## 4. 范围
✅ In: gui/core/permissions.py、tests（新 w45 + w19 扩）、gui/pages/login/page.py、core/mask_codec.py（新）、serving/mask_codec.py、gui/pages/predict/workers.py
❌ Out: lite 实际减重（棘轮只守不修）；users.json 角色枚举校验（回退已兜底）；dynamic import 守卫扩展

## 5. 风险与假设
- 已知: 解析正则多行匹配不受首行影响；lite 现余量 6.5MiB>5MiB 棘轮线
- 假设: core 纯 numpy 无 Qt 依赖（mask_codec 源码仅 numpy）——移动零风险
- 风险: shim 遗漏 straggler（grep 全仓消费面已列：workers/serialization/shared_memory 提及；shim 全覆盖）

## ✅ 门禁
- [x] 门禁 1 探索门禁（2026-08-24：统一回退 operator / 五项全清）
- [x] 门禁 2 PRD：确认 → 执行（2026-08-24 用户确认）
- [x] 门禁 3 收尾：AC-001~006 全过 + 全量 1150 绿 + EXP-2026-08-24f/learning 沉淀（4/5 未触发综合学习）+ commit 全部批准（2026-08-24）
