# 变更卡: 数据管理页导入后缩略图顺序混乱修复

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-18 |
| **档位** | L1（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | 单页单点 GUI 缺陷（展示顺序），RED→GREEN 可锁定；无硬触发器 |

### What（改了什么）
- `gui/pages/data_manage/page.py`：`_refresh` 收集图像后新增确定性自然排序（`_natural_key`：全路径按 文本/数字 交替切块，数字块按数值、文本块小写比较）。
- `tests/test_gui_datamanage_page.py`：新增 `test_refresh_natural_order_after_import`（RED 先行）。

### Why（为什么改）
- 用户报告：数据管理页导入图片后图片展示混乱。根因：`_refresh` 用 `os.walk` 裸收集零排序，展示序=NTFS 枚举序（字典序），未补零数字名穿插成 `1,10,2…`，子目录遍历次序不受控（RED 实测 `pole_10` 排在 `pole_2` 前）。标注页（label/page.py）早有 `sorted(files)`，数据管理页缺失。

### Files（涉及文件）
- `gui/pages/data_manage/page.py` — 修改（+13 行：`import re`、`_natural_key`、排序一行）
- `tests/test_gui_datamanage_page.py` — 修改（+29 行测试）

### Verify（怎么验证）— 门禁三件套
- **命令**：`.venv/Scripts/python.exe -m pytest tests/test_gui_datamanage_page.py tests/test_gui_misc_pages.py -o addopts=` → 37 passed；全量 `python -m pytest` 门禁
- **预期**：新测试先 RED（字典序穿插失败形态精确复现）后 GREEN；全量 955+ passed / rc=0 / 覆盖 ≥93%
- **不达标分支**：回滚两文件即恢复原状（纯增量，无接口变化）

### Rollback（如何回滚）
- 还原上述两文件（改动为纯增量，无共享接口/数据结构变化）。

### 启动条件
- [x] `request_evidence` 已记录用户原始目标；RED 失败测试先行并确认失败原因=缺失行为（顺序无排序）
