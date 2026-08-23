# PRD：W35 发版清偿波（v5 第一波+第二波#5 · L2）

> v1.0 · 2026-08-23 · 上游：docs/AutoVisionAgent-架构解析与优化方案-v5.md §7（用户指令「帮我决策继续优化」）
> 定档：🟡L2（硬触发器 #3 权限消费）· 门禁代偿：v5 报告可复核 + 用户指令

## FR 与 AC（全部实现 ✓）
- FR-1 lite 剪除 easyocr 独占依赖（P2-N2）：prune 列表 +bidi/pyclipper/shapely/Shapely.libs；AC：lite _internal 四名 0 命中 ✓ 余量 2.4→**6.7MB**（实测回收 **4.4MB**——v5 估算 ~15MB 为未标注推断，本轮实测修正并留档）
- FR-2 i18n 补译+守卫（P2-N3）：22 词条（含 W31 AMP 漏网）+ tests/test_w20_i18n_completeness.py（tr() 字面量 ∖ 字典键=空集 + 扫描面探针）；AC：守卫 2/2 ✓
- FR-3 action_allowed 消费接线（P2-N1）：core/session 增角色持有（set/get/reset，None=未登录宽容）；permissions.check_action 统一门控（拒绝→文案+access_denied 审计）；三按钮入口消费（label.batch_prelabel/predict.batch_infer/predict.video_super）；登录处理器单点 set_current_role；AC：7 用例（早退不触对话框哨兵×3/门控三态/审计/接线守卫）✓
- FR-4 发版卫生：unused/ rmdir ✓；版本 v2.0.0(M2)→v2.1.0(M3)（About+README）✓
- FR-5 UIA 12/12 取证（P2-N4）：后台全量跑中，结果留档

## 接缝教训（第 4 次应验）
页面模块级绑定 check_action 时，patch 源头模块不拦截——三处测试 patch 目标随迁页面绑定（Mixin 也统一提升为模块级 import 保持接缝一致）。

## 验证：全量门禁 1101 passed / 4 skipped / rc=0（1092+9 新：7 门控+2 守卫）；--clean 重打包 rc=0；lite 1.9935GiB 守卫 21/21；独占依赖 0 残留
