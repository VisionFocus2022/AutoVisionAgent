# 变更卡: 推理页单张推理结果显示不全修复

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-18 |
| **档位** | L1（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | 单页 GUI 缺陷（预览缩放策略），RED→GREEN 可锁定；无硬触发器 |

### What（改了什么）
- `gui/pages/predict/page.py`：`_show_result` 两条路径（sv 渲染/legacy 降级）改为经 `_set_preview_pixmap`——记录全分辨率原始图，按**当前预览区**等比缩放（KeepAspectRatio + 8px 边距）；新增 `resizeEvent` 重适配（放大不留旧小图、缩小不裁切）。删除固定 `scaledToWidth(400)`。
- `tests/test_gui_predict_flawgen.py`：新增 `test_single_result_preview_fits_viewport`（RED 先行，QMainWindow 固定尺寸容器复现真实裁切约束）。

### Why（为什么改）
- 用户报告：推理页单张推理结果页面显示不全。根因：preview 为裸 QLabel（无滚动区）+ 固定 400px 定宽缩放——竖图（800×1800 → 400×900）超出预览区可视高度（实测 398px）下缘裁切；400 定宽同时浪费可用宽度。

### Files（涉及文件）
- `gui/pages/predict/page.py` — 修改（净 +30 行）
- `tests/test_gui_predict_flawgen.py` — 修改（+50 行测试）

### Verify（怎么验证）— 门禁三件套
- **命令**：`.venv/Scripts/python.exe -m pytest tests/test_gui_predict_flawgen.py -o addopts=` → 15 passed；全量 `python -m pytest`
- **预期**：RED（900 > 398 裁切精确复现）→ GREEN；全量门禁 rc=0
- **不达标分支**：回滚两文件即恢复旧行为

### Rollback（如何回滚）
- 还原两文件（纯展示层增量，无接口/数据变化）。

### 启动条件
- [x] `request_evidence` 已记录；RED 失败测试先行（失败形态=竖图 900px 超出预览区 398px 下缘裁切）
