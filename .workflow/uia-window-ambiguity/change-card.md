# 变更卡: UIA find_main_window 同名窗口歧义修复

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-19 |
| **档位** | L1（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | 纯测试基建单点修复；RED→GREEN+真窗三重验证；无硬触发器 |

### What（改了什么）
- `tests/uia/uia_helpers.py`：`find_main_window` 的窗口搜索从 Name-only 改为 Name+ClassName（新增 `MAIN_WINDOW_CLASS = "MainWindow"`）——桌面存在同名顶层窗口（用户打开的 dist\AutoVisionAgent Explorer 文件夹窗，CabinetWClass）时按 UIA 枚举序错绑到文件夹窗，整套 UIA 在错误窗口里找控件。
- `tests/test_uia_helpers_guard.py`：新增守卫测试（源码扫描 WindowControl 搜索参数必须含 ClassName）。

### Why（为什么改）
W21 exe 重打包后 UIA 复跑 3 轮 6/6 **确定性**全挂（应用侧 6 次启动健康、零登录审计=点击从未到达）。探针实证：桌面存在同名 Explorer 文件夹窗时 Name-only 匹配错绑；ClassName=MainWindow 过滤恒健康。潜伏数周的测试基建坑。

### Files（涉及文件）
- `tests/uia/uia_helpers.py` — 修改（+10 行）
- `tests/test_uia_helpers_guard.py` — 新建（守卫测试）

### Verify（怎么验证）— 门禁三件套
- **命令**：守卫 `.venv/Scripts/python.exe -m pytest tests/test_uia_helpers_guard.py -o addopts=`；真窗 `pytest tests/uia -o addopts=`（诱饵窗在场）；全量 `python -m pytest`
- **预期**：守卫 RED→GREEN；修复前同条件 6/6 全挂 → 修复后不再全挂（单测可全绿）；门禁 964 passed/93.04%/rc=0
- **不达标分支**：还原两文件即回旧匹配

### Rollback（如何回滚）
- 还原两文件。

### 启动条件
- [x] RED 先行（守卫测试失败于无 ClassName 参数）；残余 flaky 以环境归因留档（deviations），断言零修改
