# PRD-Lite：W61 数据管理页删除「翻转标注/切割标注」两按钮

- 版本：v1.0（2026-09-22）
- 档位：🟡L2（三门禁：探索✅ / PRD 并入本轮✅ / 收尾✅）
- 关联：W59 删标注页四按钮同型裁决（f4ed7bb）；上游无预裁决文档，现场取证

## 1. 背景与目标

用户截图数据管理页工具栏，裁决「翻转标注、切割标注，没有实际作用，删除掉」——
与 W59（AI 预标注等四按钮）同判例：业务上不用的功能不留 UI 面。

真实任务（JTBD）：用户当整理标注数据集时，希望工具栏只出现真正会用的操作，
以便不被无作用按钮干扰；翻转/切割在工作流中无使用场景。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 两按钮从工具栏移除 | 页面无 `btn_flip`/`btn_cut`/两槽函数属性 | `test_tool_flip_and_cut_removed` ✅ |
| FR-2 全链删除（用户裁决「全链删除（推荐）」） | workers 两函数、batch_tools 两函数、`__all__` 同步收敛 | `test_workers_flip_and_cut_removed` + `test_*_removed`（atomic）✅ |
| FR-3 文案与死键清理 | i18n 6 键删除，双向守卫绿 | check-gate i18n 段 ✅ |
| FR-4 存量测试同步 | 引用旧链路的测试改为「不存在守护」或收敛范围 | 42 定向绿 + W35 门控测试修复 ✅ |

## 3. 范围

**删除面**：page.py（按钮/挂接/`_op_buttons` 两项/`_OP_TITLES` 两项/两槽函数/
retranslate 两行）；workers.py（`flip_annotations`/`cut_annotations`+`__all__`+孤儿
json import）；batch_tools.py（`cut_labelme_json`/`flip_image_annotation`+`__all__`
+docstring 计数）；i18n.py（翻转标注/翻转模式:/翻转完成/切割标注/瓦片大小/格式错误/
切割完成/个瓦片——共 8 键，其中「格式错误」核实无其他消费者）。

**保留面（反目标守护）**：batch_tools 其余三函数+`atomic_write_json`（replace/
delete/statistics 按钮与 predict 侧消费）；`data_manage.batch_label_edit` 权限动作
（replace/delete 仍在用）。

## 4. 风险与假设

- 假设：无外部脚本依赖 `cut_labelme_json`/`flip_image_annotation`（grep 全仓证实）。
- 回归风险低：纯删除，主门禁 1244 绿 + 6 skipped、ruff 0、行数守卫 739/800。

## 5. 实现思路

与 W59 同口径：UI→槽→worker→工具函数→i18n→测试六层同批删净，不留无消费者
死代码；测试层由「行为验证」转「不存在守护」，防回潜。

## 6. 门禁记录

- 门禁 1（探索）：首次出示未响应（约 5 分钟），二次出示裁决「全链删除（推荐）」✅
- 门禁 2（PRD）：并入门禁 1 出示（变更卡式 L2 精简），裁决「绿后直接提交」✅
- 门禁 3（收尾）：主门禁全绿后直接提交（用户预授权）✅

## 7. AC 核验回填

| AC | 结果 |
|---|---|
| 定向 3 文件 42 用例 | ✅ 1.41s |
| 主门禁（首轮） | ❌ 抓到 W35 门控测试引用已删 `_tool_flip_annotation`——同步收敛为二工具后复跑 |
| 主门禁（复跑） | ✅ 1244 passed + 6 skipped / ruff 0 / 84.97s |
| 残留扫描 | ✅ 生产代码零残留（仅测试守护与注释中「已删除」字样） |
