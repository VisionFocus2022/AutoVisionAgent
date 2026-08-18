# 变更卡: 数据管理页划分副本同屏重复展示优化

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-18 |
| **档位** | L1（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | 单页展示语义调整（用户明确要求）；纯增量、无接口/数据结构变化、无硬触发器 |

### What（改了什么）
- `gui/pages/data_manage/workers.py`：新增纯函数 `collect_display_images(image_dir)` —— 顶层=活动数据集语义：顶层有图时返回顶层图像 + 直接子目录图像计数（hidden，不进列表）；顶层无图而子目录有图时按 `子目录/文件名` 相对路径分组返回。
- `gui/pages/data_manage/page.py`：`_refresh` 改用上述收集器（替换 `os.walk` 递归收集），子目录副本折叠为一条"已隐藏子目录图像 N 张"提示行（NoItemFlags）。
- `gui/core/i18n.py`：新增词条 `"已隐藏子目录图像"`。
- `tests/test_gui_datamanage_page.py`：重构自然排序测试（适配新语义）+ 新增复制划分去重、移动划分分组展示两测试（RED 先行，3 failed → GREEN）。

### Why（为什么改）
- 用户反馈：复制模式划分后根目录与 train/val/test 副本同屏重复也算"混乱"。旧行为 `os.walk` 递归收集：每图展示两次、"图像总数"统计翻倍；move 模式划分后顶层清空则显示语义无兜底。

### Files（涉及文件）
- `gui/pages/data_manage/workers.py` — 修改（+46 行纯函数）
- `gui/pages/data_manage/page.py` — 修改（_refresh 块，净 +9 行）
- `gui/core/i18n.py` — 修改（+1 词条）
- `tests/test_gui_datamanage_page.py` — 修改（净 +2 测试）

### Verify（怎么验证）— 门禁三件套
- **命令**：`.venv/Scripts/python.exe -m pytest tests/test_gui_datamanage_page.py tests/test_gui_misc_pages.py -o addopts=` → 39 passed；全量 `python -m pytest`
- **预期**：RED 3 failed（旧递归行为）→ GREEN；全量门禁 rc=0、覆盖 ≥93%
- **不达标分支**：回滚四文件改动即恢复旧行为

### Rollback（如何回滚）
- 还原四个文件（展示语义回退为递归收集；无持久化状态）。

### 启动条件
- [x] `request_evidence` 已记录用户原话；RED 失败测试先行（3 条新语义测试红、旧 19 条绿）
