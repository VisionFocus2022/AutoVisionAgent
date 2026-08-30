# Tasks W54 · 规则债务全面清偿

> 版本：v1.1（2026-08-30 执行完毕）｜ 关联：[prd-w54-rule-debt-clearance.md](prd-w54-rule-debt-clearance.md) ｜ 档位：🟡L2
> 真相源：本文件（跨压缩存活）；执行循环=选任务→编码→验证清单全绿→勾选

## 任务列表

- [x] **T1 · P0 真缺陷修复（24 处 / 13 文件）** ✅ 2026-08-30
  验证：`ruff --select F821,F811,B023,F632,W605` All checks passed；py_compile OK；
  快跑 6 文件 86 passed（w44/image_io/predict_flawgen/labeling/serving_serialization/shm_tail）
- [x] **T2 · 机械安全批** ✅ 1116 处自动修复（160 文件，+797/−916）
  偏差①：F401 自动修复误删 1 处有意 re-export（workers.py atomic_write_json）→ 14 测试红
  → PEP 484 显式重导出恢复 → 全仓净集审计（删除名外部消费者=0）→ 56 用例复绿 → 主门禁 1220 绿
- [x] **T3 · E402 ×35** ✅ exp 脚本 noqa+理由 / conftest+batch_tools 导入上移真修复 / login W18 re-export 区 noqa
- [x] **T4 · F401 ×8 残留** ✅ modes/__init__ 桩分支死导入删 / sseg_smp torch 可用性探针 noqa 留档 / UIA 死导入删 ×5 / chain_e2e 未用名删
- [x] **T5 · 等价改写批** ✅ SIM105×29 → contextlib.suppress（含 UIA 12 处）；SIM115×6 with 化；SIM117×2 合并 with；SIM108×1 三元；UP028×1 yield from
- [x] **T6 · 清理批** ✅ F841×17（含 label 页 default_name 死默认名、predict 页 engine/total/threshold 三连死捕获）；B007×5 `_
` 前缀；E741×4 改名；E701×6/E702×2 拆行；B905×7 zip strict（契约处 True/防御处 False 注明）
- [x] **T7 · 收口** ✅
  1. `ruff check .` = 0（All checks passed）→ 基线文件写 0
  2. `bash scripts/check-gate.sh` 三段全绿 rc=0：naming PASS / ruff 0≤0 / pytest **1220 passed, 5 skipped, coverage 92.93%**（≥92 棘轮，较 92.82 基线不降反升）
  3. 偏差③：check-gate.sh ruff 段零基线假红缺陷（wc -l 数到 "All checks passed!" 恒 1>0）→ 修复为 grep 只数真实违规行 + sys 记录 `20260830_script_check-gate-zero-ratchet` 留档
  4. 提交：pathspec 精确圈定（见偏差②排除清单）

## 进度与偏差

- **偏差①（已闭环）**：F401 自动修复误删有意 re-export → 恢复 + 全仓净集审计兜底（不只修表象，补了系统性审计证明其余 90 处删除无外部消费者）。
- **偏差②（共享工作区并发事件）**：本波执行期间 SAM3 盒悬崖修复流（对应未提交 docs/prd-sam3-region-cliff-fix.md）并发写入同一工作树：test_sam3_adapter.py +4 用例（TestRegionAdaptiveChain）、sam3_adapter.py 自适应链实现（+94/−43 混入本波风格修复）、exp_sam3_region_chain_e2e.py / exp_sam3_region_prompt_sweep.py 新脚本。处置：**本波提交排除 labeling/sam3_adapter.py 与 tests/test_sam3_adapter.py 两个混流文件**（其改动随该功能波次提交；rescue.py 经 diff 审查为纯风格改动，纳入本波）；对方 4 用例在本波主门禁中同绿（1220 含其 4 例）。工作树口径 ruff=0 已闭环。
- **偏差③（已闭环）**：门禁脚本自身缺陷（见 T7.3），W54 清零暴露、当波修复。
- 2026-08-30 全部任务完成，门禁证据回填 PRD §收尾。
