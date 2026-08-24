# W45 P3 五项清偿 — 任务列表 (L2)

> 关联: prd-w45-p3-cleanup.md（门禁 2 已过）；实际执行：测试先行（11 用例，4 RED 基线）→ 补丁文件化一次落（mask_codec docstring 插入位语法错一次，Write 重写修复）→ 全绿。
> 结果：全量 1150 passed / 4 skipped；v6 台账（P1×2/P2×8/P3×16）全部清零。

## 任务（实际执行序）
1. tests/test_w45_p3_cleanup.py：语义×4 + 剪除包守卫×3（含正则自证）+ 凭据头×1 + mask_codec 迁移×3（RED 基线 4 败）
2. permissions `_normalize_role` 归一（page/action/check_action 三处）
3. 凭据首行警示 + w19 余量棘轮（硬 5MiB/预警 10MiB）
4. core/mask_codec.py 下沉 + serving shim + workers 改引（语法错一次→Write 重写）
5. 全量回归 + 沉淀（EXP-2026-08-24f + learn-2026-08-24-w45）

## 偏差
- docstring 外插文本 SyntaxError（全角冒号首报）一次修复——注记并入 docstring 内部
