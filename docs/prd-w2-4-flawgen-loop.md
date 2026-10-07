# PRD-lite：W2-4 缺陷生成一期（闭环：生成 → 落盘 → 回标注）

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2 ｜ 确定性：高（侦察：SGAN blend 引擎纯 OpenCV seamlessClone 离线可跑、页面生成+落盘已在，缺"回标注"链与无对话框缝）｜ 影响半径：小（两页各加一个缝+一个按钮+接线；纯增量）｜ 规模：小（3 文件 ±~60 行+测试）｜ 可逆性：双向门
- **上游**: roadmap Wave2 W2-4（粗 DoD：选中图跑生成引擎→产物落盘→可回标注页；UIA 最小链）
- **门禁**: 探索 ✅（用户指令）｜ PRD ✅（S2 预裁决：roadmap DoD）｜ 收尾 ✅（2026-10-07：单测 7 绿（load_folder 缝/按钮四态/sgan 真融合冒烟——seamlessClone 离线）；UIA 链 84s 全链（生成 2 张落盘→去标注→标注页列表见 synthetic_）；主门禁 1468 绿+ruff 0；exe 重打包）
- **并行批避让**：i18n.py 在途——新文案字面量（同 W2-1/2/3 惯例）

## FR

- **FR-1 标注页 `load_folder(path)` 缝**：自 `open_folder` 抽无对话框
  版（选目录后逻辑复用单源：扫描/列表/●标记/自动载入）；`open_folder`
  = pick_directory + `load_folder`。空目录行为不变（状态提示）。
- **FR-2 flaw_gen「去标注」按钮**：生成成功后启用；点击 emit
  `annotate_requested(out_dir)`；未生成/失败时禁用。
- **FR-3 main 接线**：`flaw_page.annotate_requested` →
  `label_page.load_folder(path)` + `win.select("label")`（先载后切，
  W1-2 模式）。
- **FR-4 UIA 最小链**：真驱动 exe——OK 模板目录（2 图）+ 缺陷库目录
  （1 图）+ 输出目录 → 开始生成 count=2 → "生成完成: 2 张" →
  点「去标注」→ 标注页文件列表出现 synthetic_ 图名。

## AC

- AC-1 load_folder：填文件列表/置 current_folder/无图状态提示；
  open_folder 对话框路径回归（monkeypatch pick_directory）。〔空目录非 happy〕
- AC-2 去标注按钮：初始禁用；生成成功回调后启用；点击发
  annotate_requested(输出目录)；失败路径不启用。〔非 happy〕
- AC-3 UIA 链（FR-4 全链一测）。
- AC-4 主门禁全绿+ruff 0+行数守卫（label 页当前行数内）。

## 范围

改：gui/pages/label/page.py、gui/pages/flaw_gen/page.py、gui/main.py；
新 tests/test_w2_4_flawgen_loop.py + tests/uia/test_flaw_gen_loop_w2_4.py。
Out of scope：mask→LabelMe 自动预标注（二期）、生成参数化（融合强度/
缺陷缩放）、批量撤销。

## 实施纪要（2026-10-07）

- **孤儿控件陷阱（UIA 探针实证）**：按钮"创建"≠"入布局"——首次实现只
  new QPushButton 未 addWidget，exe 树 dump 按钮缺失；入 tail_row 布局
  后一次通过。判例入 learning。
- 引擎侧零改动：SganBlendEngine（OpenCV seamlessClone）现状已满足
  DoD"选中图跑生成引擎→产物落盘"，本行只补回标注链（load_folder 无
  对话框缝 + annotate_requested 信号 + main 先载后切接线）。
- flaky 观察登记：test_build_window_assembles_and_wires 在满载+随机序
  下间歇红（隔离 8×/确定性/复跑全绿），定性负载相关非代码缺陷；
  候选根因=仪表盘统计的事件泵时序，留待稳定化批。
