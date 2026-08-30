# dotnet-decompile 技能 Python 反编译能力增强 — 任务列表 (L2)

> 关联: prd-dotnet-decompile-python.md v1.0 | 日期: 2026-08-30 | 目标技能目录: `C:\Users\888\.claude\skills\dotnet-decompile\`

## 任务列表

### Task 1: 侦察脚本 scripts/py_scan.py（TDD）

- **步骤**: 1. 先定义失败检查（RED）：对 `E:\计算机视觉` 跑 `py_scan.py` 应检出 ADWEB.exe=PyInstaller+3.11、SGamma python39.dll=CPython3.9、SKolpha skolpha.exe=Nuitka——脚本不存在时该检查失败 2. 实现：walk（默认 depth 4，跳过 .venv/site-packages/__pycache__/node_modules），exe 只读尾部 256KB 扫 CArchive cookie 魔数 `MEI\x0c\x0b\x0a\x0b\x0e` 与 `Nuitka`/`onefile` 特征串；pyc 读前 16 字节魔数→版本表（3.7~3.13 内嵌，不依赖 xdis）；pyd 解析 ABI tag（cp311 等）；python3XX.dll→版本 3. 常量路径内嵌源码（CJK 安全，对齐 ev_decrypt.py 风格）
- **涉及文件**: `C:\Users\888\.claude\skills\dotnet-decompile\scripts\py_scan.py`（新建）
- **验证**: `python -m py_compile py_scan.py` 0 error；实跑默认根，RED 检查三项全检出且无误报空跑 → AC-002

### Task 2: 能力参考文档 references/python-decompile.md

- **步骤**: 1. 判定树（按产物形态分流）2. 工具矩阵+版本覆盖+本机布局（含 xdis 分家、pycdc 未装如实标注、pylingual 禁用）3. 标准流程 A 侦察→B 提取→C 分档反编译→D 漂移对照→E 落盘笔记 4. 坑表（xdis 冲突/shim 不在 PATH/PYZ 空壳/明文源码≠运行代码/Cython 无字节码/Nuitka 引坑 #11/CJK 规则/16 字节头）5. ADWEB 全链路实证案例（含本次实测命令与发现）
- **涉及文件**: `references/python-decompile.md`（新建）
- **验证**: 文中命令逐条与本次会话实测一致（提取→dis→空壳识别可照抄复现）→ AC-003

### Task 3: SKILL.md 增量

- **步骤**: 1. frontmatter description 加 Python 触发词 2. §0 定位加「Python 产物静态取证」 3. §1 主表加 ADWEB 行 4. §2 工具链加 python 工具族行 5. §3 加 Phase F 短节（指向 python-decompile.md）6. §4 坑 #8 改指向 + 新增 2 坑 7. §6 自检加 python 链路检查项
- **涉及文件**: `SKILL.md`
- **验证**: grep 触发词命中；坑表三条到位 → AC-001/AC-004/AC-005

### Task 4: targets.md 增量

- **步骤**: 1. 主表加 ADWEB 行 2. 新增 ADWEB 详情节（形态/PYZ 规模/入口/空壳/漂移/取证入口）3. SGamma 节加 Python 组件行 4. 扩展槽位表 ADWEB 移出、SKolpha 行改「Nuitka onefile 已初判」
- **涉及文件**: `references/targets.md`
- **验证**: 与 SKILL.md 主表一致（ADWEB 两处同形态描述）；无残留「待侦察」矛盾

### Task 5: 集成验证（末位强制任务）

- **步骤**: 1. AC-001~005 逐条跑命令核对 2. 总检 11 项适配执行（py_compile/密钥 grep/文档一致性/档位回顾）3. Phase 4.6 经验沉淀（EXP + learning → SDW evolve/）
- **验证**: 全部 AC 通过 + 总检留痕（见下）
- **UIA 回归**: N/A（本任务对象为技能文件，无 UI）

## 执行留痕（S3 自治门禁记录）

| 门禁 | 裁决 | 依据 |
|---|---|---|
| 探索门禁 | ✅ S3 放行 | S1 用户指令 + PRD §5 三栏留痕（AskUserQuestion 不可用） |
| 门禁 2 PRD | ✅ S3 放行 | PRD 定稿，关键假设显式记录供纠正 |
| 门禁 3 收尾 | ✅ 2026-08-30 通过 | AC-001~005 全过（下表） |

### 任务完成与 AC 核验记录（2026-08-30）

| Task | 状态 | 验证证据 |
|---|---|---|
| 1 py_scan.py | ✅ | RED（脚本不存在）→ GREEN：默认根 0.26~0.4s 检出 ADWEB PyInstaller×3/CPython3.11、SGamma CPython3.9+SIVIDeploy.pyd×2、SKolpha Nuitka(64.7MB)+cp39；`py_compile` 0 error；对照阳性 AutoVisionAgent(PyInstaller 3.12) 正确检出无误报 |
| 2 python-decompile.md | ✅ | 全部命令本会话实测（提取 12,176 模块/原生 3.11 dis/空壳 110B）；坑表 10 条均有实证出处 |
| 3 SKILL.md | ✅ | description 触发词已生效（技能注册表即时刷新）；坑 8 改指向/13/14 新增；§2 工具 3 行；Phase F；§6 自检+1 项 |
| 4 targets.md | ✅ | 主表 3 行（EV/SGamma/ADWEB）与 SKILL.md 一致；ADWEB 详情节含漂移与空壳登记；槽位表 ADWEB 移出、SKolpha 改已初判 |
| 5 集成验证 | ✅ | AC-001 grep 命中=1；AC-002 检出行 9 条 0.34s；AC-003 文档命令照抄复现（dis 出 names、config.pyc 110B）；AC-004 坑 8/13/14 行 grep=1/1/1；AC-005 工具链行 grep 命中；沉淀 EXP-2026-08-30a + learning 文档 |

偏差记录：① Nuitka 探测窗口 256KB→头1MB+尾8MB（TDD 循环内定标，非计划偏差）；② AC-004 首验 grep 空结果系验证侧 pattern 被 markdown 链接打断（补验 1/1/1 通过，非实现缺陷）。

## 执行约定

- 修复尝试上限: L2 = 3 次；每 3 任务汇报；偏差记入本文件。
