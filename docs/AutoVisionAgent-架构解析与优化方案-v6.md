# AutoVisionAgent 2.1.0 深度审查报告（v6 · 增量主审 + 全仓横切）

> 版本: 1.0 | 日期: 2026-08-23 | 方法: SDW L2（prd-w37-v6-deep-review）· 主线 codegraph 调用链深审 + 五视角并行 agent（资深工程/安全/一致性/冗余）+ 攻方复核 + 运行时复现
> 审查对象: HEAD=`550ecbf`（v2.1.0）· 增量 `ea1013b..HEAD`（W35+W36，v5 之后；W26-W34 已由 v5 覆盖，仅核销其宣称）
> 与 v5 的关系: 回归轮 R3——不重审 v5 已覆盖模块，只核销 v5 宣称、深审其后增量、全仓五视角横切

## 1. 一句话总评

v2.1.0 三波清偿方向正确、多数宣称兑现（登记→消费闭环、lite 残留剪净、批量 imagePath 相对化），但**发版门禁有一处实质破口**（v5 P2-N4 UIA 空闲机取证未做即发版）与**两条 P1**（i18n 守卫对转义错位键假绿——运行时复现坐实；pyproject 版本元数据停在 2.0.0）；角色护栏经「未登录宽容态」「离线一键 admin」两条**正常操作路径**即可整体绕过，是声明目标「现场职责分离」与实际效果的最大落差。

## 2. v5 遗留核销表（回归轮 R3）

| v5 编号 | 宣称 | 核销结论 | 证据（本轮实测） |
|---|---|---|---|
| P2-N1 登记不消费 | W35「终局修复」 | **闭环（3 动作）+ 新漏网** | check_action 生产消费 3/3（label:560 / predict:400 / video_super:39），形态统一；但 data_manage 批量标签工具一组从未登记（→ 本轮 P2-6） |
| P2-N2 lite 残留依赖 | W35 清偿 + RELEASES 1.9935GiB | **闭环** | make_lite_dist.py:338-343 剪除清单 5 项落地；现存 dist `_internal` 中 bidi/pyclipper/shapely/easyocr 残留=0；apparent 实测 1.9935 GiB 与宣称精确一致 |
| P2-N3 i18n 完整性 | W35「补 22 处 + 零中文残留 + 完整性机械守卫」 | **部分闭环（宣称被证伪）** | 正向对账：双引号字面量 323 个缺失 0；但 22 条中 1 条转义错位运行时永不生效（→ P1-1），守卫另有单引号盲区漏 6 处（→ P2-5）——en_US 实测中文残留 ≥7 处，「零残留」不成立 |
| P2-N4 UIA 12/12 取证 | v5「发版前必须」 | **未闭环（已违约发版）** | RELEASES.md 自列「已知待办：UIA 全量 12/12 空闲机取证」；v2.1.0 已发版（→ P2-1） |
| P3#1 imagePath 绝对路径 | W36 相对化 | **闭环但引入回归** | 相对化落地 + test_batch_prelabel_imagepath_is_relative 通过；但跨盘符场景整批静默失败（→ P2-2） |
| P3#3 版本宣称陈旧 | W35「版本宣称与文档统一」 | **部分闭环** | README/RELEASES/settings 三方=2.1.0；pyproject.toml:3 仍 2.0.0（→ P1-2）；「五方打包一致性守卫」实为动态导入守卫（test_dynamic_import_guard.py:122-156），与版本无关；无 v2.1.0 tag |
| P3#4 unused/ 空目录 | （v5 开 rmdir 一条命令） | **未闭环** | `unused/` 仍在（空目录） |

## 3. 增量面深审（W35+W36，`ea1013b..HEAD` 20 文件）

### 3.1 逐文件覆盖映射（AC-001）

| 文件 | 审查去处 |
|---|---|
| core/session.py | §4.1 角色状态生命周期（P3-4）；锁纪律/空值归一/`__all__` 无问题 |
| gui/core/permissions.py | §4.1（P2-3/P2-6/P3-1/P3-2/P3-5/P3-6）；check_action 实现正确 |
| gui/main.py | §4.1 登录单点接线正确（win.set_role + set_current_role 同点）；P3-10 接线守卫强度 |
| gui/core/i18n.py | §4.2（P1-1/P2-5/P3-9）；其余 21 条新键逐字匹配无转义 |
| gui/pages/label/batch_prelabel.py | §4.3（P2-2/P2-7/P2-8/P3-8） |
| gui/pages/label/page.py | 门控消费正确（P3-1 顺序）；单图 save() 仍绝对路径（与批量不一致，随 P2-2 波次顺带决策） |
| gui/pages/predict/page.py | 门控消费正确（P3-1 顺序）；P3-3 审计裸 pass |
| gui/pages/predict/video_super_actions.py | 门控消费正确（P3-1 顺序）；W34 主体 v5 已审 |
| gui/pages/settings/page.py | 版本串 2.1.0 正确（P1-2 关联） |
| scripts/make_lite_dist.py | §4.5（P3-7）；剪除清单与静态扫描一致 |
| tests/test_w35_action_gate.py | 195 行：三页面门控测试为**真守护**（monkeypatch 页面缝 + 对话框哨兵，删门控必红）；P3-10（弱接线断言+死代码） |
| tests/test_w20_i18n_completeness.py | §4.2（P1-1 守卫归一化缺陷；源码静态提取机制真实，含防假绿探针） |
| tests/test_w30_batch_prelabel.py | imagePath 相对化测试通过（18/18 targeted green） |
| tests/uia/{test_datamanage_move_i18n,test_full_workflow}.py | 断言确定性迁移质量好（三态接受/combo 计数修正，注释留根因）——正面确认 |
| README.md / RELEASES.md | 宣称核对：3 条宣称中 2 条兑现、1 条被证伪（P2-N3「零残留」）；P2-1 待办自认 |
| .workflow/×2 state.json | 留痕完整（不审内容） |
| docs/prd-w35-release-hardening.md | 范围对照无缺口 |

### 3.2 关键调用链结论（codegraph）

- **动作门控链**（登记→check_action→页面早退→审计）：三动作全链路通；矩阵当前三角色全放行（W29「动作不收紧」语义），护栏价值=审计留痕+未来收紧的挂钩点。
- **角色接线链**：登录/离线/自动登录三条进入路径全部经 `login_success` 信号汇入 gui/main.py:271-275 单点——无双源漂移（正面确认）。
- **session 生命周期**：角色只设不清（无登出），见 P3-4。
- **批量预标注产物链**（pick_directory→run_batch_prelabel→save_labelme→manifest）：跨盘符断点见 P2-2。

## 4. 全仓横切（五视角）

### 4.1 权限与角色（安全/工程视角）

**P2-3 未登录宽容态 = 全放行（比 operator 更宽）** — `gui/core/shell.py:205,234`、`permissions.py:97`：`role is None` 时 11 页全部可见可进 + 三动作全放行。v5 P3#2 已声明此取舍，但与 P2-4 合观：**不登录或点离线即可绕过 W29/W35 全套护栏**，若「现场职责分离」是真实需求，护栏目前只有提示性价值。建议：宽容态语义反转为 `None→operator 最小集`（启动后仅登录页+home 可用）。

**P2-4 离线模式一键 admin** — `gui/pages/login/page.py:543`：`login_success.emit("offline", ROLE_ADMIN)`，license 缺失时确认框即可越过（:524-532）。单键取得含 settings 页的 admin 面。建议：离线角色可配置（默认降 operator）或需本地管理员口令二次确认；或 ADR 显式降级「护栏仅对登录用户生效」。

**P2-6 data_manage 批量标签工具未登记未消费** — `gui/pages/data_manage/page.py:582-620`：批量替换标签名/批量删除标签/标注统计三个**破坏性写盘操作**，`_ACTION_MATRIX` 无登记、`check_action` 零命中（grep 实证）；该页 operator 可见（permissions.py:41-43）。这是 v5 P2-N1「登记≠消费」的同类新实例（W3 遗留，未进任何动作冻结波）。建议：登记 `data_manage.batch_label_edit`（可拆三键）并在按钮入口消费；或 ADR 显式豁免。

### 4.2 i18n（一致性/工程视角）

**P1-1 补译键 `\\n` 转义错位，运行时永不匹配，守卫归一化把该 bug 类洗白** — `gui/core/i18n.py:88`（键）、`gui/core/shell.py:359`（调用）、`tests/test_w20_i18n_completeness.py:28-31`（归一化）。**运行时复现（本轮实测）**：`'有正在进行的操作（训练/推理）。\n' in _EN_US == False`；`set_language('en_US')` 后 `tr(该串)` 返回中文回退。守卫注释宣称「运行时两者等价，仅源文件文本形态不同」——**被复现证伪**；`k.replace("\\\\","\\")` 归一化使所有此类写错的键永久假绿，守卫恰在它要防的 bug 类别上失效。修复：键/值改单反斜杠 `\n`（i18n.py:448 旧条目即正确写法）；删归一化、改为断言字典键不含 `\\n` 字面量。

**P2-5 守卫单引号盲区 + 6 处漏翻** — 守卫正则仅 `\btr\("([^"]+)"\)`（双引号）；`data_manage/page.py:746,755,765,769` 的 `tr('旧')`/`tr('新')`/`tr('处差异')`/`tr('项')`/`tr('……其余')`/`tr('项略')` 六键**实测全部缺失**（`in _EN_US == False ×6`），en_US 版本对比对话框漏翻。修复：正则扩单引号或全仓统一双引号。

**P3-9 反向死 key 无守卫** — 双+单引号消费之外 70 键无字面量消费，其中 16 键硬死（`已撤销`/`平均值`/`感知损失`/`超分辨率` 等，字典 407 键的 ~4%）；54 键经动态链消费（pick_directory 参数、tr(label) 等）非死。建议：反向对账守卫 + 动态链豁免清单。

### 4.3 批量产物链（工程/冗余视角）

**P2-2 W36 imagePath 相对化在 Windows 跨盘符时整批静默失败** — `gui/pages/label/batch_prelabel.py:125`：out_dir 恒在 workspace 根所在盘（page.py:578 `autolabel_save_dir(None)`），用户扫描目录可在另一盘（工业场景常见：外接盘 D:/ 源图 + C:/ workspace）；`os.path.relpath` 跨盘抛 `ValueError` → 被 :131 `except (RuntimeError, OSError, ValueError)` 吞入 `manifest.failed` → **每张图失败、written=0、状态栏「完成 0/N」误导归因坏图**——W36 前绝对路径可正常工作，属功能回归。修复：`splitdrive` 判跨盘回退写绝对路径（LabelMe 兼容绝对路径），manifest 区分「跨盘回退」与「坏图」。附：同盘时 relpath 产生反斜杠分隔符，跨生态迁移建议 `.replace(os.sep, "/")`。

**P2-7 批量/单张预标注标签语义分叉** — `batch_prelabel.py:46` 逐框 `labels[i]` vs `label/workers.py:69` 全框共用 `labels[0]`，注释却宣称「语义同 run_ai_prelabel」：多类 DET 下两条 AI 预标注路径结果不同，注释误导后续维护者。修复：统一为逐框版（更合理）并修正注释。

**P2-8 原子写 JSON 三胞胎** — `predict/workers.py:148`、`label/batch_prelabel.py:58`（两处函数体**逐字重复**，且均为弱实现：固定 `.tmp` 名并发互踩 + 清理失败静默 pass）、`labeling/batch_tools.py:28`（强实现：mkstemp 随机名 + 清理失败 WARNING——孤悬未复用）。修复：强版提升为共享 util 单源。

**P3-8 save_dir 三胞胎** — batchPredict_/autolabel_/superres_ 三函数逐字同构仅前缀不同，抽 `results_save_dir(project_dir, prefix)`。

### 4.4 审计与测试卫生

**P3-3 审计失败路径强度三档 + logger 无界缓冲** — 最弱：`predict/page.py:385-386` `except Exception: pass`（连日志都没有，与 train/deploy/login 三处 logger 留痕不一致，一行修复）；`audit_logger.py:110-113` mkdir 在 try 外（不可写目录时每条 log 重试抛异常）+ `_buffer` 无上限增长。权限拒绝审计（check_action/shell）吞 `ImportError/OSError` 可接受（决策不受影响，仅证据丢失）。

**P3-10 test_w35 两处测试卫生** — ① 接线守卫是纯子串断言（`assert "set_current_role" in src`，删调用留 import 仍绿）——本次增量最关键接线由最弱测试形态守护（生产代码当前正确 + 三页面门控测试为真守护，故 P3 非更高）；② `FakeThread` 类与 fixture 整块死代码（三个页面测试均未用）+ docstring 称「4 个动作」实际 3 个。

### 4.5 其他横切

- **P3-1 门控顺序三页三样**（违 check_action docstring「按钮入口首行」约定）：predict 先引擎后门控、video_super 先任务类型、label 门控最前——收紧矩阵后提示顺序不可预测。
- **P3-2 审计 page 字段混载 action id**（`log_access_denied(page=action)`）：access_denied 流中 page 字段并存 `predict` 与 `predict.batch_infer` 两种 id。
- **P3-4 无登出/无超时 + reset_* 生产零消费**（四视角独立命中）：应用无 logout 入口（uia/test_user_mgmt_flow.py:6 证实），admin 离席后会话持续至进程退出；`reset_current_user/reset_current_role` 调用方全为测试，docstring「登出用」承诺未兑现。
- **P3-5 permissions 模块头「纯函数矩阵」失实**（check_action 有审计/i18n 副作用）。
- **P3-6 未知角色回退语义矛盾**：page_allowed 未知角色→operator 页集，action_allowed 未知角色→全拒——users.json 出现非标角色时行为不可解释（当前全放行矩阵下不可触发，埋雷）。
- **P3-7 lite 剪除清单归属假设硬编码无守卫**：将来任何包也依赖 shapely/pyclipper 时 lite 静默缺包；建议派生时动态求独占集或剪除后 import 冒烟。
- **P3-11 初始凭据明文文件**：configs/initial_credentials.txt 首登改密前明文存 admin 初始密码；`chmod(0o600)` 在 Windows 无效（代码自认）。威胁模型内能读 configs 者可直改 users.json 提权，无增量风险。
- **P3-12 「记住登录状态」死控件**：QCheckBox 无 isChecked 消费，虚假功能暗示。
- **P3-13 unused/ 空目录未删**（v5 P3#4 遗留，`rmdir` 一条命令）。
- **P3-14 lite 余量 ~6.5MB < 10MB 预警线**（1.9935 GiB / 2 GiB）：任何新依赖即破线；余量预警线建议挂 CI。
- **P3-15 gui→serving 跨层引用**（predict/workers.py:122 mask_codec）：功能无碍、分层纯度可议；可下沉 core/。
- **P3-16 导出面/测试复制卫生**：LOGIN_PAGE/ALL_PAGES 无外部消费者；FakeThread 测试替身至少 5-10 文件逐字复制（jobs.py:20 记载接缝约束）——可上移 conftest。

### 4.6 正面确认（防失衡清单）

PBKDF2-600k+随机盐+常数时间比较、torch.load 全 weights_only+RestrictedUnpickler 对抗测试、CSV 公式消毒、项目删除路径校验、eval/exec/subprocess 注入面零命中（威胁模型内）；core→gui 引用零违例；11 页全 ≤800 行（守卫三次拦截有效）；三页面门控测试真守护；UIA 断言取证质量好；离线/自动登录单点接线无漂移；lite 剪除无断链（shapely/bidi/pyclipper 全仓零 import，两轮探索一致）。

## 5. 缺点清单汇总（P1×2 / P2×8 / P3×16）

> 五元组详情见 §4 对应条目；此处为决策索引。

| 编号 | 级别 | 一句话 | 建议波次 |
|---|---|---|---|
| P1-1 | P1 | i18n 转义错位键运行时永不生效 + 守卫归一化假绿（§4.2） | 🚑 一 |
| P1-2 | P1 | pyproject 停 2.0.0 + 无版本守卫 + 无 v2.1.0 tag（§2） | 🚑 一 |
| P2-1 | P2 | UIA 12/12 空闲机取证未做即发版（§2） | 🚑 一（排期） |
| P2-2 | P2 | 跨盘符批量预标注整批静默失败——W36 回归（§4.3） | 🚑 一 |
| P2-5 | P2 | i18n 守卫单引号盲区 + 6 处漏翻（§4.2） | 🚑 一 |
| P2-3 | P2 | 未登录宽容态全放行，护栏日常旁路（§4.1） | 🔧 二 |
| P2-4 | P2 | 离线一键 admin（§4.1） | 🔧 二 |
| P2-6 | P2 | data_manage 批量标签工具未登记未消费（§4.1） | 🔧 二 |
| P2-7 | P2 | 批量/单张预标注标签语义分叉（§4.3） | 🔧 二 |
| P2-8 | P2 | 原子写 JSON 三胞胎（§4.3） | 🔧 二 |
| P3-1~16 | P3 | 门控顺序/审计卫生/无登出/死键/死控件/unused/余量线等（§4.4-4.5） | 🧹 三 |

## 6. 实测指标表（本轮 HEAD=550ecbf 实测）

| 指标 | v6 实测 | v5 对照 | 判定 |
|---|---|---|---|
| 门禁用例收集 | 1106 | 1096 | 正常（+10） |
| targeted 套件（w35×2/w30） | 18 passed / 1.81s | — | 正常 |
| 生产 LOC（11 目录） | 18,695 | 17,766（12 包，目录集略异） | 正常（增量趋势一致） |
| 单文件最大 | 792（data_manage/page.py） | 792 | 守卫线 800 未破（3 页 >700 临界） |
| broad except 密度 | 39 处 | 50 处 | 改善 |
| TODO/FIXME | 0 | 0 | 正常 |
| lite 体积 | **1.9935 GiB**（apparent；du -sm 2079MiB 系 NTFS 块伪影） | 1.9977 GiB | 改善（-2.4MB→余量 ~6.5MB，仍 <10MB 预警线→P3-14） |
| en_US 中文残留 | **≥7**（1 转义错位 + 6 单引号漏网） | 27 | RELEASES「零残留」**证伪** |
| i18n 正向完整度 | 双引号 323 字面量缺失 0 | 守卫缺位 | 正向闭环（守卫口径有两洞） |
| action 登记→消费 | 3/3 消费 + 1 组漏网 | 0 消费 | 大幅改善（P2-6 遗留） |
| P0/P1/P2/P3 | 0/2/8/16 | 0/0/4/4 | P1 净增 2（发版质量信号） |

## 7. 攻方复核台账（主会话反驳裁决）

| 候选发现 | 反驳 | 裁决 |
|---|---|---|
| lite 体积 2079MiB「破 2GiB 线」 | du 块粒度在 NTFS 小文件海下虚高 | **证伪**：apparent 1.9935 GiB 与 RELEASES 精确吻合 |
| 「登出后角色残留」P1 候选（主线 grep：reset 零生产消费） | 全仓不存在登出功能，残留态不可达 | **降级 P3-4**（无登出+死代码+docstring 失实，四视角合并） |
| 接线子串断言 P2（code-reviewer） | 生产代码当前正确 + 三页面门控测试为真守护（agent 逐条推演早退链） | **降级 P3-10**（测试强度债，非生产缺陷） |
| 跨盘符失败 P3（security）vs P2（code-reviewer） | Windows 双盘工业场景现实 + W36 前可工作=回归属性 | **升级 P2-2**（采信高判） |
| 「gui/core import shapely → lite 断链」担忧（主线） | 冗余视角两轮定向探索零命中 | **证伪，无发现** |
| i18n `\\n` 键 P1（code-reviewer） | 运行时复现：`query in _EN_US == False` + en_US tr() 返回中文 | **坐实 P1-1**（双源） |

## 8. 改进路线（按 ROI 排序）

### 🚑 第一波·发版纠偏（约 1-1.5 人日，低风险）
1. P1-1：改 `\\n` 键为 `\n` + 删守卫归一化 + 加「字典键禁含 `\\n` 字面量」断言（0.1 人日）
2. P1-2：pyproject 2.1.0 + 补 tag + 版本五方守卫测试（0.2 人日）
3. P2-5：守卫正则扩单引号 + 补 6 词条（0.2 人日）
4. P2-2：跨盘回退绝对路径 + manifest 区分回退/坏图（0.3 人日）
5. P2-1：UIA 12/12 空闲机取证排期执行（0.5 人日，需空闲机窗口）

### 🔧 第二波·护栏收口（约 1.5-2 人日，中风险）
6. P2-6：data_manage 批量工具登记+消费（0.5 人日）
7. P2-7：统一标签映射语义（0.3 人日）
8. P2-3/P2-4：宽容态反转 + 离线角色可配置（1 人日，涉 W29 语义变更，建议带 ADR）；或 ADR 显式降级护栏为「提示性」
9. P2-8：原子写收敛单源（0.3 人日）

### 🧹 第三波·卫生（约 0.5 人日，随时）
P3-1/2/3（审计与门控一致性，多为 1-3 行修复）、P3-13（rmdir）、P3-9/12/16（死键/死控件/测试复制）、P3-10（行为化接线测试+删死代码）

## 9. 覆盖矩阵（18 视角，增量更新 v5）

| 视角 | 状态 | 本轮关键更新 |
|---|---|---|
| C1 架构 | ✓ | 分层无新违例（P3-15 可议项）；角色接线单点正确 |
| C2 可维护性 | ✓ | 页面规模守卫有效；P2-7/P2-8/P3-8 重复簇收敛项 |
| C3 可靠性 | ✓ | P2-2 跨盘静默失败（回归）；P3-3 审计失败路径 |
| C4 可测试性 | ✓ | 1106 用例；P3-10 接线断言弱形态 |
| C5 可运维性 | ✓ | lite 余量预警线建议挂 CI（P3-14） |
| C6 安全 | ✓ | 硬底线全达标；P2-3/P2-4 护栏旁路（声明性 vs 实效） |
| S1 性能 | ✓ | 无新热点（同 v5） |
| S2 数据 | ✓ | imagePath 相对化落地 + P2-2 跨盘回归 |
| S3 并发 | ✓ | P2-8 固定 tmp 名并发互踩风险点 |
| S4 契约 | ✓ | proto 零改动；pyproject 版本元数据（P1-2） |
| S5 依赖 | ✓ | lite 剪除无断链；P3-7 归属假设无守卫 |
| S6/S7/S8 | N/A | 同 v5（单机/无 PII/单机） |
| S9 i18n | ✓ | **P1-1 + P2-5**：守卫两洞 + 残留 ≥7 |
| S10 演进 | ✓ | W35/W36 PRD/state 留痕完整；RELEASES 3 宣称 2 兑现 1 证伪 |

## 10. 验证范围与局限

- 审查中 git status 保持 clean（无并行会话在途干扰）。
- 两视角 Explore agent 工具面仅 codegraph（无 Read/Grep），目录穷举/注释正则/依赖声明对账受限——关键断言已由主会话 Wave B 一手复核（pyproject/6 键/data_manage 门控/离线 admin/标签分叉，5/5 坐实）。
- 指标多为单遍实测（关键项 lite 体积双口径）；UIA 12/12 本审未执行（需空闲机）；真机 cuda/OCR 离线验证维持 v2.1.0 已知待办（需目标硬件）。
- `705f1ee` 历史核实：commit 完好在 master（`git branch --contains` 确认），波次栈 rebase 叠加所致，无历史丢失。
