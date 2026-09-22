# PRD-Lite：W62 标注「下一步：数据管理」目录上下文交接

- 版本：v1.0（2026-09-22）
- 档位：🟡L2（三门禁：探索✅ / PRD 并入本轮✅ / 收尾✅）
- 关联：W59c 向导导航（request_page 泛化挂接）的补全——向导此前只切页不带上下文

## 1. 背景与目标

用户报：标注页选好已标注文件夹后点「下一步：数据管理」，数据管理页仍显示
没有图像（需手动重选目录）。根因：W59c 的 `request_page.emit("data_manage")`
仅经 `shell.select` 切页，无目录传递；标注页 `open_folder` 甚至未保存文件夹
路径（只存文件列表）。

真实任务（JTBD）：用户当标注完一个文件夹想导出/管理数据时，希望点「下一步」
落地即见该文件夹的缩略图与已标注统计，以便不重复选目录。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 标注页暴露当前文件夹 | `current_folder` 属性：open_folder 后=所开目录；open_image 后=图所在目录；未打开="" | `test_label_current_folder_property` / `..._single_image` ✅ |
| FR-2 数据管理页接收外部目录 | `apply_external_dir(path)`：平铺形态（图+同名 JSON 同目录，极柱）图像目录就位+已标注计数；经典形态（兄弟 annotations/）命中 | `test_apply_external_dir_flat_layout` / `..._sibling_annotations` ✅ |
| FR-3 向导接线（仅标注→数据管理） | emit request_page("data_manage") 后数据管理自动带入；标注页未开文件夹时零操作（不碰已选目录） | `test_build_window_handoff_label_to_data` / `..._empty_folder_noop` ✅ |
| FR-4 存量不回归 | W59c 导航、W59 统计口径原行为不变 | 两文件回归 14 过 + 主门禁 ✅ |

## 3. 范围与实现

- `gui/pages/label/page.py`（713 行）：`__init__` 存 `self._folder=""`；
  open_folder/open_image 各一行赋值；`current_folder` 只读属性。
- `gui/pages/data_manage/page.py`（748 行）：`_select_dir` 抽出
  `apply_external_dir`（同语义：兄弟 annotations/ 优先→W59 回退；无对话框
  无状态回显——刷新即证据），`_select_dir` 复用之。
- `gui/main.py`：`_wire_label_to_data_handoff(label_page, data_page)` 模块级
  接线函数（W24 百行守卫：内联写法把 build_window 顶到 103>100，抽出后达标），
  build_window 内一行调用；沿 `project_opened→set_project_dir` 既有先例。
- 测试：`tests/test_w62_wizard_context_handoff.py` 6 用例（RED 5 败→GREEN）。

**Out of Scope**：「数据管理→训练」向导不交接（训练页需 data.yaml，语义不同，
保持 W58「未选诚实回退模拟」设计）；交接不覆盖用户在数据管理页手选的目录
（仅空文件夹时零操作原则的反面：有文件夹即覆盖——向导语义=用户刚在标注页
选了它，覆盖即意图）。

## 4. 风险与假设

- 假设：向导交接覆盖数据管理页已选目录符合用户意图（探索门禁未响应，按
  「下一步=带入我刚标注的文件夹」常识语义实施，S1 记偏差）。
- 回归风险低：主门禁 1250 绿+6 skipped、ruff 0、行数守卫 713/748 内。

## 5. 门禁记录

- 门禁 1（探索）：两次出示均未响应（~3/2 分钟）→ S1 按报障原文最小修复
  （推荐项「只接标注→数据管理」）实施，记偏差。
- 门禁 2（PRD）：并入门禁 1 出示。
- 门禁 3（收尾）：主门禁全绿；**commit 待用户显式批准**（铁律 7 不降级）。

## 6. AC 核验回填

| AC | 结果 |
|---|---|
| 定向 14 用例（W62+W59+W59c） | ✅ 0.78s |
| 主门禁（首轮） | ❌ W24 百行守卫抓 build_window 103>100——抽出接线函数后复跑 |
| 主门禁（复跑） | ✅ 1250 passed + 6 skipped / 81.13s / ruff 0 |
