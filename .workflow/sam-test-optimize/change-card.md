# 变更卡: SAM 适配器性能与 device 接线优化 + 测试补强

| 字段 | 内容 |
|------|------|
| **日期** | 2026-08-18 |
| **档位** | L1（可逆 / 局部 / 测试可见 / 低不确定） |
| **分档依据** | SAM 适配器内部缓存策略 + label 页一行 device 接线 + 测试补强；行为可测、范围局部；无硬触发器 |

### What（改了什么）
- `labeling/sam_adapter.py`：`set_image` 增加 W21 快路径——同对象（is）直接命中；等值新对象哈希命中后更新引用（后续同对象零哈希）。旧行为每次调用都 `hash(image.tobytes())`（1600×1600 图 ~7.7MB/次，`to_shapes` N 点 N 次）。
- `gui/pages/label/page.py`：`_ensure_sam` 加载 device 从硬编码 `"cpu"` 改为 `resolve_device("cuda")`（W19 契约：cuda 可用透传/不可用回退 cpu，lite exe 的 CPU torch 自动回退）——本地 RTX 3060 不再白费 GPU。
- `tests/test_sam_adapter.py`：新增 TestSamAdapterSetImagePerf（tobytes 计数观测，2 条）、to_shapes 单 embedding 断言、TestSamDeviceWiring 源码守卫（防回退硬编码 cpu）、TestSamRealCheckpointSmoke（opt-in：`AVA_SAM_CKPT` 指向真实 sam_vit_*.pth 才跑，默认 skip，CI 安全）。

### Why（为什么改）
- 用户指令：AI 预标注（SAM）需要测试优化。调查结论：现有 9 条 mock 测试骨架健康；真实改进点=①交互期整图哈希性能缺陷 ②device 硬编码 cpu（W19 resolve_device 波漏项）③缺真权重端到端验证钩子（本机无 sam_vit 权重，不下载 375MB 大文件伪造覆盖）。

### Files（涉及文件）
- `labeling/sam_adapter.py` — 修改（set_image 重写 + `__init__` 引用字段）
- `gui/pages/label/page.py` — 修改（+3 行：import + device 接线 + 注释）
- `tests/test_sam_adapter.py` — 修改（+4 测试类/4 条断言用例）

### Verify（怎么验证）— 门禁三件套
- **命令**：`.venv/Scripts/python.exe -m pytest tests/test_sam_adapter.py tests/test_gui_label_page.py -o addopts=` → 35 passed/1 skipped（skip=真权重冒烟 opt-in）；全量 `python -m pytest`
- **预期**：RED 3 failed（快路径×2 + device 守卫）→ GREEN；全量门禁 rc=0
- **不达标分支**：回滚三文件即恢复旧行为

### Rollback（如何回滚）
- 还原三文件（缓存策略与 device 均可独立还原）。

### 启动条件
- [x] `request_evidence` 已记录；RED 失败测试先行（3 红 11 绿 1 skip）
