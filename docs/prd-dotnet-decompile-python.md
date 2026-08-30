# dotnet-decompile 技能 Python 反编译能力增强 — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-30 | 档位: 🟡 L2 | 确定性: 低（探索后转中） | 影响半径: 小（个人技能文件级编辑，无数据/鉴权/接口破坏，未命中 7 类硬触发器） | 可逆性: 双向门
> 前置: Phase 0 需求探索已完成。
> ⚡ 自治门禁留痕（S3）: 本会话为自治模式，`AskUserQuestion` 不可用。按 `references/autonomous-gates.md` 阶梯降级——
> **S1（用户显式指令）**: 「优化反编译技能 dotnet-decompile，增强 python 的反编译能力」——授权整体方向与对技能文件的直接修改。
> **S3（自主留痕）**: 关键解释性决策记录于本 PRD §5 三栏与任务列表，供用户事后纠正；无单向门、无破坏性操作。

## 1. 背景与目标

- **背景**: 技能 dotnet-decompile 目前只覆盖 .NET 侧（ilspycmd/BAML/EV 解密）。但 2026-08-30 扫描实证，目标注册表生态里存在成建制的 Python 产物：ADWEB 0.52 是 **PyInstaller（Python 3.11）打包**且随包混发明文源码与 `.venv`；SGamma 内嵌 **CPython 3.9 + SIVIDeploy.pyd（Cython）**（坑 #8 的 Fernet 之所在）；SKolpha 是 **Nuitka 单 exe**（坑 #11 已有 ad-hoc 取证法）。技能对这三类要么标「另立项」，要么散落坑表，无系统章法、无工具链、无脚本。
- **目标**:
  1. 技能新增 Python 产物（PyInstaller/pyc/内嵌 CPython/Cython/Nuitka）的**静态取证与反编译能力**，全链路在本机已实证可行；
  2. 目标注册表完成 Python 侧登记（ADWEB 晋级主表 + SGamma Python 组件 + SKolpha 指针）；
  3. 配一个可复用的 Python 产物侦察脚本 + 一篇能力参考文档（判定树/工具矩阵/流程/坑）。

## 2. 功能需求 (FR)

- **FR-001**: 触发词与注册表扩展 — SKILL.md frontmatter description 增加 Python 反编译触发词（PyInstaller/pyc/PYZ/内嵌 CPython 等）；targets.md 登记 ADWEB（晋级主表+详情节）、SGamma Python 组件、SKolpha Nuitka 指针 | P0
- **FR-002**: 能力参考文档 — 新增 `references/python-decompile.md`：产物形态判定树、工具矩阵与版本覆盖、标准流程（侦察→提取→分档反编译→漂移对照→落盘）、坑表、ADWEB 全链路实证案例 | P0
- **FR-003**: 侦察脚本 — 新增 `scripts/py_scan.py`：扫描目录树，识别 PyInstaller exe（CArchive cookie 魔数）、Nuitka 特征、内嵌 CPython 运行时（python3XX.dll→版本）、pyc（魔数→版本）、pyz、pyd（ABI tag），默认跳过 venv/site-packages/__pycache__ 噪声 | P0
- **FR-004**: 工具链登记 — SKILL.md §2 工具链表增加 Python 反编译工具族（本机布局：py3.9 装 uncompyle6/decompyle3、uv tool 装 pyinstxtractor-ng、uv 裸 3.11/3.12 做原生 dis 兜底）| P1
- **FR-005**: 坑表更新 — 坑 #8 改指向 python-decompile.md（SIVIDeploy.pyd 走 Cython 取证法）；新增 xdis 版本冲突分家坑、PYZ 空壳模块坑 | P1

## 3. 验收标准 (AC)

- **AC-001**: `grep -iE "python|pyinstaller"` SKILL.md frontmatter description 命中 ≥1 处；且「python 反编译」类请求可命中本技能描述 [FR-001]
- **AC-002**: `python scripts/py_scan.py`（默认根 `E:\计算机视觉`）能检出：ADWEB.exe 为 PyInstaller+3.11、SGamma python39.dll 为 CPython3.9、SKolpha skolpha.exe 的 Nuitka 特征——三者齐且无误报空跑；运行 ≤120s [FR-003]
- **AC-003**: 按 python-decompile.md 的 ADWEB 实证案例照抄命令，能从 ADWEB.exe 复现「提取→app.pyc 反汇编→常量/空壳识别」全链路 [FR-002]
- **AC-004**: SKILL.md 坑表含「xdis 版本冲突/工具分家」与「PYZ 空壳模块」两条；坑 #8 文本指向 python-decompile.md [FR-005]
- **AC-005**: SKILL.md §2 工具链表含 pyinstxtractor-ng（uv tool 路径与版本 2026.7.3）、uncompyle6/decompyle3（py3.9，≤3.8）条目 [FR-004]

## 4. 范围

- ✅ **In Scope**: SKILL.md / targets.md 增量修改；新建 references/python-decompile.md；新建 scripts/py_scan.py；本机工具安装布局记录（已完成安装的动作本身也是交付物一部分）
- ❌ **Out of Scope**: ADWEB 业务逻辑逆向研究本身（另立项）；pycdc 本地构建（本机无 cmake 工具链，只在文档记录构建路径）；pylingual 等在线反编译服务（违反技能「不外传」授权边界，默认禁用）；native pyd 深度逆向；动态调试

## 5. 风险与假设（含需求探索三栏）

- **已知（确证事实）**:
  1. 技能现有 3 文件（SKILL.md/targets.md/ev_decrypt.py），无任何 Python 反编译章节；Python 相关仅坑 #8（Fernet/另立项）与坑 #11（Nuitka 取证法）
  2. 目标生态 Python 产物实证：ADWEB 0.52 = PyInstaller ≥6 onedir + Python 3.11（ADWEB.exe 94.8MB 内嵌 PYZ **12,176 个模块**，入口 app.pyc）；SGamma = python39.dll + SIVIDeploy.pyd ×2（根 + SmsAlg），**无任何 pyc/pyz**（Cython 原生）；SKolpha = Nuitka onefile 单 exe；ADWEB 顶层另随包明文源码（adweb_gui/ 等）+ .venv（3.11 pyc 语料）
  3. 本机解释器：PATH python=3.9.13；另有 python.org 3.12（`py` 默认）与 uv 管的 3.11.15/3.12.12（裸解释器，无 pip）；pip 网络可用
  4. 工具链已装并冒烟通过：uncompyle6/decompyle3/xdis 6.1.8 @py3.9；pyinstxtractor-ng 2026.7.3 + xdis 6.3.0 @uv tool（shim 在 `C:\Users\888\.local\bin`，**不在 PATH**）；提取 ADWEB.exe + 原生 3.11 反汇编 app.pyc/src 全链路实证
- **假设（待验证 · 不成立则…）**: 「增强 python 的反编译能力」= 为技能增加 Python 产物的静态取证与反编译能力（不改 .NET 主线定位）→ 若用户实指其他（如改写技能脚本本身），以本 PRD 留痕供纠正，返工成本限于 4 个文件的编辑
- **未知（已问/查清，或显式接受残留）**:
  1. ADWEB `src/config.pyc` 为 110B 空壳（仅 RESUME/RETURN）——真实业务代码位置属 ADWEB 研究问题，**不阻塞技能增强**，登记为坑
  2. 3.9-3.12 pyc 的本地源码还原（pycdc）当前不可用——能力矩阵**如实标注「部分」**，主路径为反汇编+常量挖掘（接受残留）
- **风险**: ① xdis 版本冲突（pyinstxtractor-ng 要 6.3.0 / uncompyle6 钉 6.1.8）→ 已用 uv tool 隔离分家解决，写入坑表防复发；② SKILL.md 膨胀 → 细节全进 references/python-decompile.md，主文件只加短节+指针；③ 坑 #5/#6 CJK 规则在新脚本同样适用 → py_scan.py 默认路径内嵌源码，风格对齐 ev_decrypt.py

## 6. 实现思路

- **拟采用**: 手术式增量——SKILL.md 加 Python 触发词/主表 1 行/工具链几行/Phase F 短节/坑 2 条；targets.md 加 ADWEB 行+详情节、SGamma Python 组件行、SKolpha 行改判；新建 python-decompile.md（判定树+矩阵+流程+实证）与 py_scan.py（tail 扫描魔数，不整读大 exe）
- **复用**: ev_decrypt.py 的脚本骨架风格（argparse/中文 docstring/CJK 路径内嵌/exit code 语义）；坑 #10 native 取证范式收编 Cython/Nuitka 侧；坑 #11 Nuitka 经验直接引用
- **注意**: pyinstxtractor-ng shim 不在 PATH 需全路径或 `uv tool update-shell`；提取产物一律落 `E:\vision-agent\Temp\py_decompile\`（勿写目标目录）；pyc 头 16 字节（PEP 552）后才是 marshal 体

---

## 自检（5 项）

- [x] **完整性**: 每条需求有 FR 编号（FR-001~005）
- [x] **无歧义**: 目标与 AC 均为可验证描述（检出项/命令/数值）
- [x] **可追溯**: 每个 FR 有对应 AC（001↔FR-001 … 005↔FR-004/005 分摊覆盖，FR-005 由 AC-004 覆盖）
- [x] **范围清晰**: In / Out Scope 已列
- [x] **指标可量化**: AC 均有可判定命令或命中标准

## ✅ 门禁

- [x] 门禁 2（PRD）— 自治降级 S1+S3：用户指令覆盖方向；关键假设已留痕于 §5 ⚡ 块，编码放行
- [x] 门禁 3（收尾）— 2026-08-30 编码完成，AC-001~005 逐条验证全过（命令与输出见任务列表执行留痕）；总检 11 项适配核对：代码质量 py_compile 0 error / 残留调试与密钥 grep 0 命中 / 文档更新含技能 4 文件 / 档位回顾 L2→L2 无偏差 / 经验沉淀 EXP-2026-08-30a + learn-20260830-dotnet-decompile-python.md；UIA/界面文案/性能 benchmark 类 N/A（纯技能资产+CLI 脚本，无 UI，性能=扫描 0.3s 远低于 120s AC 线）
