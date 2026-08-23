# AutoVisionAgent 2.0.0 架构解析与优化方案（v5 · 回归轮 R2）

> 轮次声明：**回归轮（第二轮）**。基线：v4（2026-08-19，零 P0/P1）@ `f20f12b`（W25 后）；增量 = **W26–W34 九波**（HEAD `4dec2cf`，2026-08-23），84 文件 +5,109/−466 行、47 个新增文件。审查模式：§3 Phase 7 回归轮三件套（核销 + 增量深审 + 整改攻方复核）+ §11.2 面板伸缩（主会话反驳裁决，台账见 §6）。架构解析全文（§2–§6 分层/机制/启动链）以 v4 为准仍然有效，本文不重写、只记漂移。
> 档位：L2 · 领域：机器视觉桌面应用 · 读者：开发者/发版决策者

---

## 1. 一句话总评

**v4 全部 12 项立案（1×P2 + 8×P3 + 3 波路线）核销：10 项真实闭环、1 项 defer 留档、1 项未动（空目录）；九波新增面（11 个生产模块）架构质量整体达标且守卫体系三次实际拦截规模爬升，但攻方复核揭出 4 条新 P2——全部集中在「登记≠消费」型半收口与预算/完整性缺口：action_allowed 零消费点、lite 残留 easyocr 独占依赖（余量仅 2.4MB）、i18n 缺译 27 处且无机械守卫（含 v4 S9 判定被推翻修正）、UIA 12/12 空闲机取证自 W26 起累计拖欠。** 无 P0/P1；发版（对外分发）前需清偿上述 4 条 P2，合计约 2–3 人日。

## 2. v4 回归核销表（逐条，证据重验）

| v4 立项 | 判定 | 证据（重验 token） |
|---|---|---|
| P2-1a 瞬态产物跟踪 | ✅ 闭环（W23） | `git ls-files` 瞬态模式命中 **0**（重验: 本轮 grep，一致） |
| P2-1b 明文凭据 .gitignore | ✅ 闭环（W23） | `git check-ignore configs/initial_credentials.txt` rc=0（重验: 一致） |
| P2-1c 测试态/生产态日志隔离 | ✅ 闭环（W23） | `logs/autovision.log` 含 pytest-of **0 行**（v4 时 1,904 行）（重验: grep -c，一致） |
| P3-1 页面规模无守卫 | ✅ 闭环（W24 守卫 + W27/33/34 收敛） | Top3 = data_manage **792** / predict **773** / label **766**，全 <800（重验: wc -l，一致）；守卫 `tests/test_w24_scale_guards.py` 在门禁内，W33/W34 两次撞线即触发抽取（守卫实际拦截的证据） |
| P3-2 lease PoC 决策 | ✅ 闭环 | `docs/adr/0002:3` 状态行「已接受(08-18)；**冻结**(08-21)，重开条件见 §决策 4」（重验: Read 一致） |
| P3-3 eval score 裸取 | ✅ 闭环（W23） | `evaluation/eval_flow.py:121` `getattr(result, "boxes", None)` + :130 per_scores 同族防御（重验: commit f20f12b 信息 + 源码现存双源） |
| P3-4 versioning TOCTOU | ⏸ defer（有意留档） | 计划 defer-with-trigger 清单明示「单用户桌面低价值，verify/restore 已护栏」 |
| P3-5 broad except 密度 | 📉 改善 | **50 处 / 17,766 行 = 2.81/千行**（v4: 59 处 ≈3.07/千行）（重验: 独立 grep 两遍，一致）；九波新增仅 1 处（`project/paths.py:36`，带日志+noqa 声明） |
| P3-6 豁免上限声明 | ✅ 闭环 | `core/interfaces_supervised.py:192`「豁免上限 220 行，超出须复审拆分」（重验: grep 一致） |
| P3-7 凭据补删 | ✅ 闭环（W24） | `gui/pages/login/page.py` `sweep_residual_initial_credentials`（重验: 本轮 Read 源码一致） |
| P3-8 unused/ 遗留 | ❌ 未动 | `ls unused/` 存在（**空目录**，total 8 无内容；W26 计划卫生项「rmdir」漏执行） |
| v3 第三波#8 角色消费 | ✅ 超额完成（W29） | permissions 纯函数 + shell 导航过滤 + access_denied 审计 + 登录消费 role（本轮攻方复核：**nav 级消费确凿**，action 级见 P2-N1） |

**核销结论：v4 债务曲线继续下行；唯一新增敞口全部来自九波增量（§3）。**

## 3. 增量面深审（W26–W34 新增 11 个生产模块）

架构评价（每条双源：源码 + 测试证据）：

1. **抽取链一致性（优）**：label/predict 两页五次抽取（workers×2/sam_session/batch_runner/video_super_actions）严格复刻既有模式（Qt-free worker + Mixin 槽名派发 + 页面保模块级绑定测试缝）；行为保持有 70+ predict/label 测试锚定（重验: W33/W34 门禁全绿记录）。
2. **permissions.py（优，带缺口）**：纯函数零 Qt（AST 守卫测试）、未知角色最小特权、登录页恒允许；缺陷见 P2-N1（action 面）。
3. **ocr_easyocr.py（优）**：「注册零依赖」宣称经毒化测试实跑验证成立（攻方攻 E 被驳倒）；缺库/缺权重诚实 raise 带离线指引；lite 内引擎照常注册、load 诚实报安装指引——可选件降级路径完整。
4. **amp_preflight.py（优）**：2 行 autocast 探针替代 SKolpha 黑盒资产；cpu/lite 静默跳过语义清晰；真机 cuda 端到端未验证（留 residual，声明）。
5. **打包链（优，带缺口）**：W26 三重守卫（spec AST/毒化/五方一致）在 W32 五方同步中实际生效；缺陷见 P2-N2（lite 依赖残留）。
6. **产物位置单源（优）**：batchPredict/autolabel/superres 三约定共享 `{root}/results/{name}_{ts}` + resolve_base_root 单源 + 「不污染被扫描目录」卫生（W28）。

## 4. 缺点清单（本轮新增：P0×0 / P1×0 / **P2×4** / P3×4）

**P2-N1 action_allowed 登记不消费：4 个动作注册、生产调用点 0 处**（已验证·攻方存活）
W29/W30/W33/W34 逐波向 `_ACTION_MATRIX` 登记 `label.batch_prelabel` / `predict.batch_infer` / `predict.video_super`（+W29 空集），但 `grep -rn action_allowed gui/ core/`（排除定义与测试）命中 **0**（重验: 两遍 grep 一致）——按钮 onClick 全部不经动作门控。对照计划文本自相矛盾处：「每波加『更新 permissions 面』行项」（登记，已做）vs「action 级在 W30/33/34 冻结动作集后逐波补」（消费，未启动）。**不升 P1 的依据**：nav 门控有效覆盖 operator 主暴露面（settings/project/train/deploy 不可见即不可达），engineer 全业务页可见是矩阵设计意图。定性：防纵深缺失 + 死数据（「登记≠消费」恰是 W29 立项要消灭的「角色存了不消费」的 action 级镜像）。修法：三按钮入口处 `action_allowed(role, action)` 检查 + denied 审计（复用 log_access_denied），约 0.5 人日。

**P2-N2 lite 残留 easyocr 独占依赖：3 包 + 运行库未随剪除，~15MB 占用挤压 2.4MB 余量**（已验证·攻方存活）
`pip show` 反查：python-bidi / pyclipper / shapely 的 `Required-by` 均为 **easyocr（唯一依赖方）**；`dist/AutoVisionAgent-lite/_internal/` 实测仍含 `bidi/ pyclipper/ shapely/ Shapely.libs`（easyocr 本体已剪）（重验: pip + ls 双源一致）。W32 只剪 easyocr 目录违背「推理-only 可选件不占 2GiB 预算」的 PRD 意图；lite 实测 **1.9977 GiB（余量 2.4MB）**（重验: du 两遍一致）——任何后续依赖波动即破线。修法：`make_lite_dist._prune_optional_packages` 列表加 4 项，重派生 + 守卫，约 0.5 人日（含重打包验证）。

**P2-N3 i18n 完整性无机械守卫：tr() 缺词条 27 处（九波新增 1 + 存量 26），en_US 模式漏翻；v4 S9「缺译 1 键」判定被推翻**（已验证·攻方存活）
机械对账（脚本扫描 `tr("字面量")` vs i18n 字典键）：当前 **26 处** + W31 新增 1 处（`AMP 预检失败，已回退 FP32`）；基线 f20f12b 同法扫描 = 26 处 → 存量漏翻非九波引入，但 v4 S9 判定「缺译 1 键（测试串）」**显著低估**（本轮推翻修正）。W31 缺失根因实证：词条添加 shell 命令 `grep '"混合精度"' && … || python-add` 的 `||` 短路——grep 锚错字符串使命中，添加脚本未执行（ch 中文回退源串直出掩盖漏翻，门禁不红）。分布：data_manage 10 / login 8 / shell 3 / main 2 / eval·label·train 各 1（重验: 两遍脚本一致）。W20「tr()+zh/en 同 commit」教义九波内无机械守卫支撑。修法：补 27 词条 + 把对账脚本固化为守卫测试（本轮脚本即原型），约 1 人日。

**P2-N4 UIA 12/12 空闲机取证累计拖欠（W26 起）**（已验证·流程债）
自 W26 起每波 state 文件均留「12/12 空闲机取证」residual，至今未执行；期间 predict 流在活跃机器上呈输入争抢型失败（症状跨运行漂移 + 96–147s 拖慢 3 倍 + 应用侧 0 ERROR + 摘除对照实验仍败——环境归因证据链完整，且 W28 那次「复跑不过」经对照实验证明是真回归并已修复，方法论有效）。发版前必须有一次空闲机全量 12/12 证据，否则打包态 UI 面处于「部分验证」状态。修法：空闲时段跑 `pytest tests/uia/`（约 10 分钟），0.5 人日。

**P3 观察（不编号立案）**
- batch_prelabel 的 LabelMe `imagePath` 写绝对路径（`batch_prelabel.py` save_labelme 调用）——标注目录整体迁移后断链（LabelMe 生态惯例相对路径）；单工位影响有限。
- 登录前宽容态：`set_role(None)` 全页可见（W29 PRD 声明的有意设计）——登录页被绕过的纵深缺失，桌面单机威胁模型下可接受。
- About「v2.0.0 (M2)」/ README「2.0.0」版本宣称在九波后陈旧——发版时统一切版本号（九波已具备 M3 量级变更）。
- `unused/` 空目录未清（v4 P3-8 + W26 卫生项双计漏执行，`rmdir` 一条命令）。

## 5. 实测指标表（命中阈值项即关键数字，含复核状态列）

| 指标 | 实测值 | 复核状态 | 阈值判定 |
|---|---|---|---|
| 生产代码总 LOC（12 包） | 17,766 | 重验: find+wc 两遍一致 | 正常 |
| 单文件最大 LOC | 792（data_manage/page.py） | 重验: 一致 | P2 档（300–1000）但守卫棘轮在（<800 硬线） |
| broad except 密度 | 2.81/千行（50 处） | 重验: grep 两遍一致 | 正常（v4 3.07 → 下降） |
| TODO/FIXME | 0 | 重验: 一致 | 正常 |
| 门禁用例 | 1,092 passed + 4 skipped | 重验: collect-only=1,096 两数自洽 | 正常（覆盖率 ≥92 地板，最近实测 96.32%） |
| lite 体积 | 1.9977 GiB / 余量 2.4 MB | 重验: du 两遍一致 | **P2-N2**（<2GiB 守卫过，但余量 <10MB 预警线） |
| i18n tr() 缺词条 | 27（26 存量 + 1 九波） | 重验: 脚本两遍 + 基线对照一致 | **P2-N3** |
| action_allowed 生产消费点 | 0 | 重验: grep 两遍一致 | **P2-N1** |
| 仓库瞬态产物 | 0 | 重验: 一致 | 正常（P2-1a 保持闭环） |
| 九波新增文件 | 47（11 生产模块 + 9 留档 + 10 文档 + 测试） | git name-status | 正常（全部有 PRD/state 留痕） |

## 6. 攻方复核台账（§11.2 面板伸缩：主会话反驳裁决）

| 攻击点 | 裁决 | 依据 |
|---|---|---|
| A. action_allowed 零消费 | **存活 → P2-N1** | grep 双遍 + 计划文本两段矛盾点分析 |
| B. lite 残留 easyocr 依赖 | **存活 → P2-N2** | pip Required-by 唯一依赖方 + lite 目录 ls 双源 |
| C. batch_runner 抽取致行为回归 | **被驳倒** | 70 项 predict 测试全绿（含 W18 取消/W28 卫生/W33 过滤语义锚） |
| D. W31 AMP 词条缺失 | **存活 → P2-N3 组成** | grep i18n=0 + 根因（shell 短路）实证复演 |
| E. ocr「注册零依赖」宣称不实 | **被驳倒** | 毒化测试（sys.modules easyocr=None）实跑注册成功 |
| F. v4 S9「缺译 1 键」 | **被推翻（v4 判定修正）** | 本轮机械对账 26 处基线即缺 |
| G. 关键数字 | 全部重验一致 | 见 §5 复核列 |

## 7. 改进路线（面向发版，按 ROI 排序）

### 🚑 第一波·发版前必做（约 1.5 人日，低风险）
| # | 动作 | 解决 | 做法 |
|---|---|---|---|
| 1 | lite 依赖剪除 | P2-N2 | prune 列表 +bidi/pyclipper/shapely/Shapely.libs → 重派生 + 守卫复跑（余量回收 ~15MB→~17MB+） |
| 2 | i18n 补 27 词条 + 对账守卫测试 | P2-N3 | 词条按 §4 分布补；守卫=本轮对账脚本固化为 `tests/test_w20_i18n_completeness.py`（tr 字面量 ∖ 字典键 = 空集） |
| 3 | UIA 空闲机 12/12 取证 | P2-N4 | 空闲时段全量跑 + 留档 |
| 4 | unused/ rmdir + 版本号统一 | P3 | 顺手 |

### 🔧 第二波·下一迭代（约 1 人日，中风险）
| # | 动作 | 解决 | 做法 |
|---|---|---|---|
| 5 | action_allowed 消费接线 | P2-N1 | 三个按钮入口检查 + denied 审计（复用 log_access_denied 通道）；顺带在计划模板补「登记≠消费」检查项 |
| 6 | batch_prelabel imagePath 相对化 | P3 | LabelMe 惯例（图与 JSON 同目录时相对路径） |

### 🚀 第三波·可选演进
7. W32 residual：真机 OCR 离线权重端到端 + cuda AMP 首跑验证（需目标硬件）；8. versioning 单趟 walk（P3-4 defer 触发时）。

## 8. 决策者建议

1. **架构判断：v4「债务清偿完毕、进入守恒守护」的结论在九波压力测试后依然成立**——但九波把债务从「骨架债」转向「一致性债」（登记/宣称与消费/实现的差距）。发版（对外分发 exe/lite）前清偿第一波 4 项即可达标；不清偿则在英文界面（漏翻 27 处）、lite 预算（2.4MB 余量）与 UI 面验证（UIA 拖欠）上带已知缺口出门。
2. **若只做一件事：动作 1（半小时）**——lite 余量 2.4MB 是唯一可能「静默破线」的项：任何一次 pip 版本漂移重打包即超 2GiB 守卫拒出库，届时排查成本远高于现在剪 4 个目录。
3. **守恒模式的新守卫建议**：i18n 对账守卫（动作 2）与 action 消费守卫（动作 5）补上后，「登记/宣称 vs 消费/实现」三类半收口（角色旧案、action 新案、i18n）全部有机械防线——这是本轮三条 P2 的共同根源模式。

## 9. 覆盖矩阵（18 视角 + 扩展；状态=已查 ✓ / 不适用）

| 视角 | 状态 | 已查 | 关键发现 |
|---|---|---|---|
| C1 架构合理性 | 必查 | ✓ | 抽取链模式一致（§3.1）；分层无新违例；permissions 纯函数层独立 |
| C2 可维护性 | 必查 | ✓ | Top3 全 <800 + 守卫三次实际拦截；47 新文件全留痕 |
| C3 可靠性 | 必查 | ✓ | broad except 2.81/千行降；W28 取消跳写/失败槽收口；无新吞异常面 |
| C4 可测试性 | 必查 | ✓ | 1,096 用例（+96）；纯函数 worker 模式扩面；UIA 12/12 拖欠（P2-N4） |
| C5 可运维性 | 必查 | ✓ | AVA_LOG_DIR 隔离保持闭环（pytest-of=0）；lite marker 留档扩至可选包剪除 |
| C6 安全性 | 必查 | ✓ | 凭据 gitignore 保持闭环；权限 nav 级落地、action 级缺口（P2-N1）；无新增硬编码密钥（grep=0） |
| S1 性能伸缩 | 适用 | ✓ | 无新热点（批量/视频超分为用户触发的长任务且有进度+取消）；N/A 深查（单机桌面） |
| S2 数据持久化 | 适用 | ✓ | 产物约定单源（§3.6）；LabelMe imagePath 绝对路径 P3 |
| S3 并发 | 适用 | ✓ | run_job 协作取消复用一致；无新共享态 |
| S4 API 契约 | 适用 | ✓ | proto 零改动（W32 OCR 仅加枚举字符串）；serving 未触 |
| S5 依赖健康 | 适用 | ✓ | lock 单 cv2 守卫新增；easyocr 钉版本在 lock；lite 残留（P2-N2） |
| S6 灾备 | 不适用 | 单机桌面；versioning 快照链 v4 已审 |
| S7 合规 | 不适用 | 无 PII/监管面 |
| S8 可观测性深化 | 不适用 | 单机；审计链 v4 已审且 W29 增 access_denied |
| S9 i18n/a11y | 适用 | ✓ | **P2-N3：27 处缺译 + 无守卫；v4 S9 判定修正** |
| S10 演进/ADR | 适用 | ✓ | ADR-0002 冻结决策补齐；九波各带 PRD/state 可追溯 |
| S11 构建链 | 适用 | ✓ | --clean 可重现；五方守卫 W32 实际拦截；CI 面本轮未跑（局限） |
| S12 资源泄漏/生命周期 | 适用 | ✓ | VideoCapture/VideoWriter try-finally release；QThread 生命周期沿用 W18 模式；未做长时间运行泄漏实测（局限） |
| 扩展视角（视觉域） | 适用 | ✓ | 见 §6.4.1 对照：像素格式（ imread_unicode 统一）/静默失败（W28 零检出反馈收口）/算法证据链（RED 用例九波全走）——无新命中；「结论深度」红线（显示类）本轮无渲染类对标结论 |
| 扩展视角 | — | — | 无新增领域视角（已评估：MES 域不适用——无工单/报工面） |

## 附录 E 完整性批判记录（§6.4 九问）

1. **最关键风险面覆盖？** 已覆盖：发版面四缺口（P2×4 即打包预算/UI 验证/i18n 完整性/权限纵深）；无已识别未审的最高风险面遗留。
2. **没打开过的子系统？** 抽样：九波触 11 新模块全读；serving/C# 面九波未触（git diff 证实零改动）→ 沿用 v4 结论，未重审（局限已声明）。
3. **外部边界错误路径？** 视频文件坏输入 raise（W34 测试锚）；OCR 缺权重诚实 raise；无新增网络边界。
4. **非功能默认成立？** lite 预算被 P2-N2 证伪（未默认成立）；性能未基准（v4 基线沿用）。
5. **运行产物异常信号？** logs/autovision.log 0 ERROR/0 污染已验；UIA 争拖慢现象归因证据链完整（§4 P2-N4）。
6. **只看主路径？** 边界经攻方 A–G 台账（§6）；取消/失败/权限拒绝路径均有测试锚。
7. **文档自相矛盾？** 计划文本「登记 vs 消费」矛盾已抓（P2-N1 根源）；本文无前后矛盾（自查）。
8. **单一证据源？** 全部 P2 双源（§5 复核列）；P3-3 双源（commit+源码）；P3-2 双源（ADR+Read）。
9. **该加的领域视角？** 视觉域对照已做（矩阵扩展行）；MES 域不适用已声明。

## 验证范围与局限

- **本轮未验证**：serving/gRPC/C# 子系统（九波零改动，沿用 v4 结论）；真实 cuda 环境行为（AMP 探针/OCR 权重）；CI 远端（本轮全部本地验证）；长时间运行内存泄漏实测；UIA 全量 12/12（机器被活跃使用，环境归因留档——正是 P2-N4 本身）。
- **测量口径**：生产代码 = 12 个 Python 包（gui/core/models/labeling/project/serving/inference/dataset/industrial_vision_platform + engines 所在 models 子包），排除 build/dist/.venv/__pycache__/tests；i18n 对账仅覆盖 `tr("纯字面量")` 形态（f-string/变量键不在内——漏翻计数为下界）。
- **基准时点**：全部测量于 2026-08-23 @ 4dec2cf 工作树（无未提交变更）。

---
*本文为回归轮 R2 产出；v4 的架构解析主体（分层图/机制剖析/启动链）未随九波漂移的部分继续有效。下一轮建议：发版后按增量轮继续。*
