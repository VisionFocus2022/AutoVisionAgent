# Tasks：SAM3 标注 UIA 深度测试（精简版）

关联：docs/prd-uia-sam3-deep.md v1.0（FR-1 ~ FR-5）

| # | 任务 | 依赖 | 验证 HOW | 量级 | 状态 |
|---|------|------|----------|------|------|
| T1 | exe 冒烟：跑既有 test_sam3_invalid_weights_honest_failure（AVA_UIA_SOURCE 默认 exe） | — | 用例绿；若 "SAM3 模块不可用" 红 → spec hiddenimports 补 labeling.sam3_adapter + 重打包 + 复跑绿 | M | ✅ 27.6s 绿（exe 栈本就位，无重打包） |
| T2 | 新建 test_sam3_labeling_deep.py：FR-1 几何断言 + FR-2 多对象会话用例 | T1 | exe 模式跑单用例绿 | M | ✅ 82.0s 绿（1 轮修复：base=-1 归一） |
| T3 | FR-3 撤销/重做/清空用例 | T2 | exe 模式跑单用例绿 | M | ✅ 49.7s 绿（1 轮修复：列表通道改 _iter_descendants） |
| T4 | FR-4 换图重预热 + 模式往返用例 | T2 | exe 模式跑单用例绿 | M | ✅ 81.7s 绿（1 轮修复：base 改列表通道取画布真值） |
| T5 | 全文件 exe 跑批（--timeout=900）+ 主门禁回归（tests/uia 仍默认排除） | T2-T4 | 4/4 用例绿 + 主门禁全绿 | S | ✅ 跑批 3 passed/210s + 主门禁 1216 passed/88s（lite 守卫红 1 例系上任务 lite GUI 冒烟运行痕迹污染对账，清扫后全绿——见 learning 2026-08-31） |

- 版本：v1.1（2026-08-31 执行完毕）
