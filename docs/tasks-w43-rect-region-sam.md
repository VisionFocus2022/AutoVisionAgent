# W43 矩形区域 SAM — 任务列表 (L2)

> 关联: prd-w43-rect-region-sam.md（门禁 2 已过）；实际执行：四层测试文件先行（15 用例一次 RED）→ 六层实现一次贯通 → spec 守卫连锁补注册 → 全量回归。
> 结果：15/15 新用例绿 + 既有 SAM 套件零改动 46 绿 + 全量 1129 passed / 4 skipped。

## 任务（实际执行序）
1. tests/test_w43_region_sam.py —— adapter×3 / labeler×8 / controller×2 / page×2（qapp 夹具前置修正一次）
2. labeling/base.py 枚举 REGION_SAM + sam_adapter.predict_point_in_box（组合 prompt+掩码∩矩形）+ modes 注册 + controller attach 扩展
3. labeling/modes/region_sam.py RegionSamLabeler（拖拽定区/区域内点击/提交/reset）
4. page _MODES(J)+_apply_mode 接线 + i18n 两键
5. autovisionagent.spec hiddenimports 注册（五方守卫连锁修复）
6. 全量回归 + 沉淀（EXP-2026-08-24d + learn-2026-08-24-w43）

## 偏差
- spec 守卫连锁（既定动作补注册）；既有「交互式」i18n 键缺失留档（变量键盲区，候选 FB）
