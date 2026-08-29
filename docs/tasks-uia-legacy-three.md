# Tasks：W46·B 遗留三项清偿（lite）

关联：[prd-uia-legacy-three.md](prd-uia-legacy-three.md)

| # | 任务 | 依赖 | 验证 | 状态 |
|---|------|------|------|------|
| T1 | 5 文件 11 处冗余 `usefixtures("ava_app")` 移除（AST 已核全为「签名已有」型） | — | grep=0 + collect 15 收 + 存量 11 用例 exe 实跑全绿 | ✅ |
| T2 | `enter_path_in_open_dialog` 真 True 语义（对话框消失才 True） | — | 主门禁 1182 绿 + 存量 11 用例 exe 实跑全绿 | ✅ |
| T3 | spec 补 `labeling.sam3_adapter` + 全量重打包(229s) + lite 重派生(余量 20.6MiB) + skip 探测器化 | — | PYZ toc 含 sam3_adapter=1 + 主门禁(含 w26 spec 守卫) 1182 绿 + SAM3 exe 三用例(后台运行中) | ✅ |
| T4 | 收官验证：主门禁 + 全量 UIA exe 模式（15 用例） | T1-T3 | **主门禁 1182/5/rc=0；UIA exe 15/15**（存量 11 + sam3 3×exe 模式首秀 147s） | ✅ |
