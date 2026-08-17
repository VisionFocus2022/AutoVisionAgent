# UIA 自动化测试方案 · 全项目全流程（极柱真实数据）

> wave11-arch-uia（FR-002）。基于 uia-autofix-loop plan-phase 模板；runner 已合入技能 config。

## 栈探测

- `language=Python / uiFramework=PySide6（打包 exe 真窗）/ testFramework=pytest + uiautomation`
- evidence：`pytest.ini`（marker `uia`、默认 `--ignore=tests/uia`）；`tests/uia/{conftest,uia_helpers,test_full_workflow}.py` 既有骨架；venv 实装 `uiautomation 2.0.29 / pywinauto 0.6.9 / pytest-json-report（2026-08-17 装入）/ pytest-timeout 2.4.0`。
- 被测物：`dist/AutoVisionAgent/AutoVisionAgent.exe`（2026-08-17 10:00 重打包，含 W8-W10 全部修复）。

## runner / config 合入

- `~/.claude/skills/uia-autofix-loop/config.json`：`runner=uia-windows`、`uiaFlavor=windows`、`targets=["."]`、`perTargetTimeoutMs=rerunTimeoutMs=900000`（套件扩至 6 用例后 10 分钟不够）。
- 调用侧适配（内置调用是裸 `python -m pytest`，会吃 pytest.ini 的 coverage addopts 且被 `--ignore=tests/uia` 排除）：每次驱动 loop 脚本前导出
  `PATH=<venv>/Scripts:$PATH` + `PYTEST_ADDOPTS="tests/uia -o addopts= --timeout=300 --timeout-method=thread"`，不改技能脚本。

## 覆盖矩阵（功能 → 用例 → 断言通道）

| 被测功能 | 用例（tests/uia/） | 断言铁证通道 | 备注 |
|---|---|---|---|
| 登录→导入→标注→训练→部署全流程 | test_full_workflow.py::test_import_annotate_train_deploy（既有，保留） | 状态栏逐步 + 标注文件 | W4 建立假绿修复后基线 |
| 极柱真实数据导入 + 数据集划分 | test_pole_dataset_flows.py::test_pole_import_and_split | ①状态栏"导入完成/划分完成" ②磁盘：data 目录下 8 张 bmp；train/val/test 三子目录合计 8 张（0.8/0.1/0.1 随机分布只锁总量） | `(N)` 括号文件名 + 1600×1600 真图是读图路径天然探针 |
| 极柱标注：多边形 + 矩形 + 切图 + 保存 | test_pole_dataset_flows.py::test_pole_label_polygon_and_rectangle | ①状态栏"标注数" ②磁盘：两个 LabelMe JSON——polygon.json 含 shape_type=polygon、rectangle.json 含 rectangle，且 imagePath 互不相同（证明切图） | 多边形=左键 N 点 + 右键提交（labeling/controller.py:113-114）；矩形复用既有拖拽 |
| 项目创建流 | test_pole_dataset_flows.py::test_project_create_flow | ①状态栏"已创建/创建失败" ②磁盘：存储目录下出现项目目录 ③UIA 树：项目列表项含项目名 | 存储目录走"浏览"→「选择存储目录」对话框（_browse_root 触发 _init_store 重初始化） |
| 设置持久化（主题切换） | test_pole_dataset_flows.py::test_settings_theme_persist | ①状态栏保存成功 ②磁盘：user_settings.json 含 theme 键 | exe 模式写 `dist/.../_internal/configs/`（烤进包内，不污染仓库）；测后恢复深色 |
| 主页仪表盘渲染 | test_pole_dataset_flows.py::test_home_dashboard | UIA 树：仪表盘/快捷操作/最近项目/检测历史 标签存在 | W9 计数器修复后的页面加载冒烟 |

## 断言铁证通道（三级，无像素断言）

1. **状态栏文本**：`uia_helpers.read_status_text`（statusText+statusAccent 双 QLabel 按 bottom/left 定位拼接）+ `wait_status/wait_any_status` 轮询。
2. **磁盘产物**：划分子目录文件计数、LabelMe JSON 结构（shapes/shape_type/imagePath）、user_settings.json 键存在性。
3. **UIA 树属性**：控件存在性（find_control_by_name）、列表项文本。

**失败分类路由**（parse-uia-windows classifyKind 契约）：控件未找到类断言消息含英文 `timeout`（→kind=flaky 路由人工查稳定性，不改生产代码凑绿）；行为不符类（文件缺失/数量错/JSON 结构错/状态终态错）→ deterministic 进自动修。

## 应用生命周期

- 单实例：conftest teardown `taskkill /IM AutoVisionAgent.exe /F` 清残留 + 运行前确认无同名单实例。
- **每用例独立启动被测应用**（`ava_app` function 级，W11 基线实测教训：会话级复用在 6 用例下 UIA 树随页面内容膨胀渐进失稳，5/6→1/6 随机翻车；独立启动 ~20s/次彻底隔离）；`_ensure_logged_in` 前台化 + 清扫残留对话框 + 幂等探测。
- pytest 默认串行；每测试 `--timeout=300 --timeout-method=thread`（pytest-timeout）兜底原生对话框挂死，保证 json-report 落盘。
- license.key：conftest 预创建空文件进离线模式，会话结束清理（既有机制）。

## 运行配置

- 门禁默认排除（`pytest.ini --ignore=tests/uia`，覆盖率不掺入）。
- 手动/loop 运行：见上方调用侧适配。`AVA_UIA_POLE_DIR` 可覆写数据集路径（默认 `E:\学习项目\极柱外观检标注图`，1289 对 bmp+json）。
- 子集策略：每会话抽 4 张 `(N)` 正常 + 4 张纯数字缺陷前缀 bmp（conftest `pole_subset_dir`，session 级，~56MB 临时拷贝）。

## 条件用例（本轮不做，记录在案）

- AI 预标注（"AI预标注  W"）：需真权重/引擎，环境就绪后补。
- 推理页真模型批量 + 导出 CSV：`AVA_UIA_MODEL` 指向真 .pt 后补（W8 修的 numpy→json 路径届时在真窗复验）。
- 评估页 GT 对比、缺陷生成页：依赖真模型/生成引擎。

## 确认记录

用户指令原文（2026-08-17）：「使用架构师技能，对项目全面审查，并创建UIA自动化测试方案，对项目全面测试。 测试图片路径在E:\学习项目\极柱外观检标注图」——范围（全面测试）与数据源（极柱路径）由用户明示，充当 Phase 0 用户门确认；自主会话无交互确认，偏差已记录于 `.workflow/wave11-arch-uia/state.json`。
