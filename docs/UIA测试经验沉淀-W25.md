# UIA 全面深入测试（W25）经验沉淀——面向 UIA 测试技能优化

> 日期: 2026-08-21 | 波次: W25（structured-dev-workflow L2，state.json 验证器 rc=0）
> 档案: `.workflow/uia-deep-w25/` | PRD: `docs/prd-uia-deep-w25.md` | 用例: `tests/uia/` 12 条
> 用途: 后续编辑优化 uia-autofix-loop（及其 Phase 0 方案创建/分类闸）的实战场输入。所有条目均带证据指针（file:line / evidence log），非叙事回忆。

---

## 0. 结果速览

| 维度 | 数据 |
|---|---|
| 用例规模 | 6 → 12（+predict×2 / eval×1 / 改密×1 / move×1 / i18n×1） |
| 终验 | UIA 全套 12 用例：11 绿 + 1 strict xfail；主门禁 996/4 零回归 |
| 擒获生产缺陷 | 1 个（exe 打包态 predict 引擎必败，历版潜伏） |
| 踩中测试基建缺陷 | 3 个（fixture 序 / 僵尸进程 / 子串匹配陷阱） |
| 环境归因 flaky | 2 起（W16/21/22 同族，R1→R2 单测复跑即绿） |
| 耗时基准 | 全套 12 用例 427s；单用例冷启动 ~20s + 流程 2~90s |

**对技能的核心标定**：W25 的 6 次失败恰好均匀落在 uia-autofix-loop 分类闸的三路由上——生产缺陷（应修生产码）、testWrong（应修测试基建）、flaky/环境（复跑+归因，绝不改代码凑绿）。这是该分类策略难得的一次全三类实证。

---

## 1. 方法论层（可编入技能流程的经验）

### 1.1 前置调查先行，不直接写测试

扩面前用 3 个并行调查员（348k tokens，~8 分钟）产出四件套，四组用例全部一次写对骨架：

1. **UIA 流草稿**：导航路径/控件定位/等待点/断言锚（文案从 page.py 源码逐字摘出，不猜）；
2. **fixtures 清单**：前置文件怎么造、复用哪些既有 fixture；
3. **副作用与还原配方**：测试会动哪些持久态、teardown 怎么还原；
4. **风险清单**：锁账户/竞态/路径分叉等可达性陷阱。

关键产出示例：调查发现**训练链是 `_SimStrategy` 模拟训练、`save()` 为 no-op、零 .pt 落盘**（类定义于 `gui/pages/train/page.py:356-372`、经构造注入 `GenericTrainer`；dist/outputs/checkpoints 只有 .meta.json 铁证）——"复用链上训练产物"这条直觉路径被证据否决，改为离线构造权重（见 §5.1）。**没有这一步，四组用例会在权重来源上各踩一遍坑。**

### 1.2 覆盖新增型测试的 TDD 变体

纯覆盖新增（验证既有行为）没有可先失败的红断言；W25 的实操形态是**让失败成为真实信号**：全程 6 次失败无一假红——新用例调试期 4 次（predict 1 生产缺陷 + 改密用例 3 轮独立基建失败：fixture 序/僵尸清场/子串陷阱），另 2 起环境 flaky（复跑验收 R1 与套件终验 R1，见 §6，均 R2 单测复跑即绿）。判别标准：失败信息里必须能读到"应用侧到底发生了什么"（见 §4.4 诊断内嵌模式）。

### 1.3 验收口径：R1 套件 + R2 单测补跑 + 断言零修改

非空闲机器上单轮 12/12 不稳定，验收口径定为：

- R1 全套跑（记录跑前进程快照）；
- 失败用例**单测复跑一次**，绿即计入达成（R2）；
- 硬判据：**断言零修改**——复跑转绿不允许动断言；再配三件套归因（§6）。

W25 两轮验收（复跑验收 + 套件终验）各出现 1 起此形态失败，R2 均一次转绿（57.17s / 24.29s）。

---

## 2. 控件定位手册（PySide6/Qt 的 UIA 暴露特性）

技能写 UIA 测试时最容易翻车的就是控件暴露形态，逐条实证（含反例）：

| 控件 | UIA 暴露 | 定位法 | 证据/陷阱 |
|---|---|---|---|
| QPushButton | ButtonControl，Name=文本 | 子串匹配可用 | `click_button` 同时匹配 Button+CheckBox |
| setCheckable 的 QPushButton | **CheckBoxControl** | 同上 | 侧边栏导航按钮全是这类（`gui/core/shell.py:189`） |
| 复选框 QCheckBox | CheckBoxControl | ⚠️ 与按钮同匹配集 | **子串陷阱见 §4.3** |
| QLineEdit | EditControl，**Name 不保证等于占位文本/表单标签**（无 setObjectName 时） | **按 BoundingRectangle.top 升序排序分配**（登录页 [0]用户名 [1]密码；改密框 [0]旧 [1]新 [2]确认） | W25 改密用例全按坐标序 |
| QComboBox | **Name 为空**（探针实证） | **按 find_combo_controls 布局序**（数据页 [0]划分模式 [1]导出格式；设置页 [0]主题 [1]语言 [2]设备 [3]精度——构建顺序保证）；`Select("移动")` 可能抛 COM 错 0x80040201 → **键盘回退 SetFocus+VK_DOWN+RETURN**（相邻项一步可达） | `tests/uia/test_datamanage_move_i18n.py` `_combo_select` |
| QListWidget item | **ListItemControl，Name=项文本原样**（含 NoItemFlags 的提示项也照样暴露） | `find_control_by_name(win, "train/")` 直接命中分组项 | T2c 探针实证 |
| QTableWidget 单元格 | Name=单元格文本，无 objectName | 按文本找单元格 | predict 结果表 `img_001.png` |
| QLabel（占位文案） | TextControl，Name=文本 | 文案消失=状态变化断言（预览被 pixmap 替换 → "选择图像进行推理"消失） | `test_predict_flow.py` 步骤 5 |
| 状态栏 | statusText + statusAccent 两个 QLabel 合并读取 | `read_status_text` / `wait_status` 轮询 | 主要等待锚，全部断言优先走状态栏 |
| 原生文件/目录对话框 | class **#32770，作为父窗口的子窗口出现而非顶层** | `enter_path_in_open_dialog`（`uia_helpers.py:423`）；`_wait_dialog` 三策略查找（顶层→主窗子窗→遍历兜底） | QFileDialog 用原生 IFileDialog |
| 模态自定义对话框（QDialog.exec） | 顶层 WindowControl | `_wait_dialog("标题子串")` + `_wait_dialog_gone` | 改密框"首次登录——请修改密码" |

**文案锚纪律**：断言文案一律从 page.py 源码摘（如 `分数: {score:.3f}`、`划分完成 T6/V0/T2`、`密码错误 (4 次剩余)`），不凭记忆写；数字类锚用正则不锚精确值（随机权重零检出恒 0.000，但"分数: X.XXX"格式恒在）。

---

## 3. 三大测试基建陷阱（症状 → 诊断 → 修法）

这是 W25 最有复用价值的部分——三个陷阱的症状都不指向真因，各需一次取证才破案。

### 3.1 陷阱一：fixture 实例化序 = 参数序（删状态的 fixture 必须排前）

- **症状**：改密用例 R1 失败——`initial_credentials.txt 未生成`。日志显示 04:44 的旧 sweep 记录（应用启动时文件还在），删除动作被应用启动"看到"了旧状态。
- **诊断**：pytest fixture 按参数声明序实例化；签名 `(ava_app, first_run_cfg)` 使应用先启动（`_ensure_default_admin` 读到旧 users.json 走非空库分支、不重建凭据），删除晚于启动=无效。
- **修法**：参数序改 `(first_run_cfg, ava_app)`。**通用规则：任何"清场/预置状态"的 fixture 必须声明在被测进程 fixture 之前。**

### 3.2 陷阱二：残留僵尸进程 + QLockFile 单实例锁

- **症状**：R2 失败点漂移；应用日志出现无法归属的时间线（删除在启动前，但启动时 sweep 却看到旧文件）。
- **诊断**：上一用例的 exe 未死透 → 残留进程持 `%TEMP%` QLockFile → 新实例弹"已在运行"早退 → `find_main_window` 错绑到僵尸窗口，后续全在错误窗口里操作。
- **修法**：清场 fixture 的 setup 与 teardown 都先 `taskkill /IM AutoVisionAgent.exe /F` 再动文件；测试内自启的第二进程必须 finally 里 terminate→wait→kill 三段收尾。配套：`find_main_window` 钉住 `ClassName=MainWindow`（W21 已修，防同名文件夹窗错绑）。

### 3.3 陷阱三：click_button 子串匹配命中复选框（本波最隐蔽）

- **症状**：改密用例 R3 失败——点击"登录"后状态栏恒为初始**"就绪"**，应用侧零痕迹（无 AUDIT、无错误日志）。既非密码错也非放行 → 槽函数根本没触发。
- **诊断**：登录页有复选框**"记住登录状态"**（CheckBoxControl，在 click_button 的 Button+CheckBox 匹配集内），其文本包含子串"登录"，且树遍历序在真按钮前 → **点的是复选框不是登录按钮**（勾选不落任何状态，症状完美吻合"点了但什么都没发生"）。
- **修法**：精确匹配 helper——类型与 Name 双条件：`type(c).__name__ == "ButtonControl" and (c.Name or "").strip() == "登录"`（`test_user_mgmt_flow.py` `_click_login_button`）。
- **通用规则**：`click_button(win, "X")` 在有含"X"子串的其他控件（复选框/标签页/菜单项）在场时不可靠；关键动作按钮应精确匹配。**技能可内置：click 失败/无响应时先枚举匹配集 dump 出来看命中了谁。**

### 3.4 配套：诊断信息内嵌失败消息

R3 破案靠的是把状态栏文本写进断言失败消息：

```python
pytest.fail(f"...15s 未见；状态栏: {read_status_text(win)!r}")
```

一行"就绪"直接排除密码错误分支、锁定"点击未达"。**规则：每个 wait 类断言失败时，失败消息必须携带当时可观测的 UI 状态（状态栏文本/最后匹配控件），否则取证要多跑一轮。**

---

## 4. 副作用管理与还原配方

### 4.1 改密用例：删两文件自愈 > 快照恢复

改密会改 `users.json`（must_change→False+新哈希）并删 `initial_credentials.txt`。还原选**"删两文件，下次启动走空库首启分支自动重建全新随机密码"**而非快照恢复，理由：

- 快照恢复会把旧随机密码固化携带；且无法自愈**毒状态**（上轮 teardown 未跑 → must_change=False+凭据文件缺失+密码不可知 → 下轮必挂）；always-first-run 的 setup 删除使用例完全不依赖上一轮残留。
- **初始密码每轮从新生成的文件解析**（`re.search(r"^初始密码:\s*(\S+)\s*$", txt, re.M)`），绝不硬编码。

### 4.2 锁账户红线

连续 5 次错密码锁账户 300s 且持久化进 users.json——**"旧密码被拒"断言只做一次，绝不重试点击登录**。

### 4.3 i18n 用例：还原是硬要求，双层配方

语言是全局持久态（`user_settings.json` 的 language 键，仅点"保存设置"时写盘、closeEvent 不写）：

- **层1 UI 还原**：切回"中文 (简体)"→保存→`wait_status("设置已保存")`（保存流程 set_language 先于 emit，锚恒中文）→轮询确认文件落 ch_CN；
- **层2 文件兜底**：finally 里若文件 language≠ch_CN 则覆写 known-good 快照（app 已关/将关时无写盘竞态）。

残留 en_US 的爆炸半径：同 run 内后续所有 function 级冷启动整窗英文，既有用例全部中文锚（"数据管理"/"选择目录"/"导入完成"/"确认划分"弹窗标题…）确定性全红。**技能应把"全局持久态型副作用"（语言/主题/设备）列为高优先还原项。**

i18n 两个机理点（断言设计前必知）：设置页保存**不触发 retranslate**（不发 language_changed，已建控件文本不变）；侧栏"中文/EN"按钮触发全量 retranslate 但**不写盘**。切语言后断言"按钮变英文"必须先点 shell toggle 或重启，单走设置页保存只能断言新 tr() 信号（状态"Settings saved"）。

### 4.4 模式分叉：python 模式会写仓库工作树

CONFIG_DIR 分叉（exe=`dist/.../_internal/configs/`，python=仓库 `configs/`）。改密用例在 python 模式下首启会把**明文随机凭据写进仓库 configs/**——用 `pytest.mark.skipif(AVA_UIA_SOURCE != exe)` 钉死。**通用规则：动 configs/持久态的用例要审计两种模式各自的落盘位置，写仓库树的必须钉模式。**

### 4.5 move 划分：只能对 pytest tmp 操作

move 是真移动文件。fixture 先 copy2 到 tmp（`pole_subset_dir` session 级），workspace 同在 pytest tmp 根下 → move 为同卷 rename 亚秒级。绝不可把真实数据集目录当"选择目录"目标。

---

## 5. 可复用 fixtures 与确定性断言技法

### 5.1 离线构造可加载权重（tiny_det_model_path）

```python
m = YOLO("yolov8n.yaml")   # YAML 构造，零下载零网络
torch.save({"model": m.model, "train_args": {}, "train_metrics": {},
            "epoch": -1, "date": time.time(), "version": "8.4.81"}, pt)
```

12.8MB / 0.1s；exe 内 ultralytics 8.4.81 与 .venv 同版 → 反序列化兼容（实证 `DetYoloEngine.load→infer→run_eval_task` 全链绿）；随机权重对合成平图 conf=0.5 零检出 → 状态恒"分数: 0.000"（不锚精确值）。`AVA_UIA_MODEL` 指向真权重时优先复用。

### 5.2 确定性断言：从机制推出恒定值

8 张 × 0.8/0.1/0.1 的 **int 截断** → 划分恒 (6,0,2)，与 random.shuffle 无关 → 可强断言 `"T6/V0/T2" in status`。同页配套断言：磁盘铁证（顶层 0/train 6/val 0/test 2）+ UIA 分组项（"train/" 前缀）+ 反向锚（copy 态才有的"已隐藏子目录图像"提示行**不在场**）。**分层断言（磁盘/状态栏/UIA 控件三层互证）是抗 flaky 的最好结构。**

### 5.3 xfail 拆分：已知缺陷下保住可达覆盖

生产缺陷（见 §7）阻断 predict 主链时，把**不依赖引擎加载的负向探针**（"请先加载模型"）拆成独立可绿用例，主链挂 `@pytest.mark.xfail(strict=True)`——修复重打包后 XPASS 立即报出、强制去标记。**技能规则：xfail 不吞整条用例，先拆出缺陷盲区外的可绿部分。**

---

## 6. 环境归因协议（W16/21/22/25 四波校准）

UIA 真窗测试与机器空闲强相关。签名与处置已稳定成惯例：

- **跑前快照**：`tasklist | grep -iE "Weixin|WeChat|ToDesk|..."` 计数写进 evidence（终验轮跑前 16 个用户进程；复跑验收轮 R1 跑前快照列出 5 个（ToDesk×2/微信系×3）——两轮失败时均为非空闲状态）；
- **失败签名**：失败点跨用例/跨轮**漂移**（T1 轮挂"选择目录"find-timeout、终验轮挂"导入图像"点击未达——同族不同点）；
- **三件套归因**：①应用侧审计在场（AUDIT login / 状态推进日志）②日志无未解释 ERROR ③断言零修改；三件成立 → 环境归因（用户活跃进程与 UIA 坐标点击争抢输入）；
- **处置**：单测复跑取绿，不修改断言不强求单轮全绿；机器空闲时复跑可取单轮 12/12。

**技能可内置**：跑前进程快照 + 失败时自动比对"失败点是否漂移"作为 flaky 分类的硬证据。

---

## 7. 真生产缺陷擒获案例：打包态 vs 开发态差异

**W25 最高价值发现**——predict 页 UIA 首条覆盖即擒获历版 exe 潜伏缺陷：

- **根因链**：`autovisionagent.spec` excludes 剔除 matplotlib（W19 瘦身，spec :63）→ ultralytics 导入链硬依赖（第三方包内 `ultralytics/models/yolo/semantic/train.py:8` `import matplotlib.pyplot`）→ **打包态 predict 引擎加载必败**；
- **为什么一直没发现**：.venv 装了 matplotlib → 单测层永远绿；历版 exe 从未跑过 predict 页 UIA；
- **为什么 UIA 状态无变化**：`_pickle`/ModuleNotFoundError **逃出 predict 页 except 元组 `(RuntimeError, OSError, ValueError)`** → 无状态/标签变化（对照：eval_flow 的 except 元组能收 ImportError → ERROR 日志+GT 自比较降级，评估照常出指标）。同一根因、两个捕获面、两种表现——**except 元组宽度是打包态异常的生死线**；
- **处置范式**：strict xfail 留档 + 单独立卡（用户拍板）；修复须 spec 去 matplotlib + 重打包（连带 lite 体积规划，距 2GiB 仅余 30.8MiB）。

**技能结论**：UIA-on-打包产物的不可替代价值 = 捕获"开发态遮蔽"缺陷（依赖集差异/路径分叉/frozen 资源解析）。分类闸应把"仅打包态可复现"标记为高价值确定性缺陷。

---

## 8. 时长与超时经验值表（可直接抄进技能默认值）

| 环节 | 实测 | 建议超时 |
|---|---|---|
| exe 冷启动到主窗口 | ~20s | find_main_window 40s |
| 离线登录（offline 模式） | ~4s（含 AUDIT） | 20s |
| PBKDF2 验证（600k 迭代） | 0.13s | — |
| 登录→改密弹窗出现 | <2s | 15s |
| 引擎冷加载（exe 内首次 import ultralytics，UI 冻结属预期，外部轮询不受影响） | 5-15s | 60s |
| 单张推理（合成图） | ~1s 热态 | 60s |
| eval 单 GT JSON | 热态 <1s / 冷态 10-20s | 120s |
| 导入 8 张真实 bmp（2.56MB/张） | 秒级 | 60s |
| move 划分（同卷 rename） | 亚秒 | 90s（copy 模式同值） |
| 全套 12 用例串行 | 427s | — |

注意：exe 冷加载引擎时 **UI 线程冻结是预期行为**（同步 import 在 UI 线程），UIA 外部轮询不受影响——不要把"窗口无响应"当死锁杀进程。

---

## 9. 对 uia-autofix-loop 技能的改进建议清单

按落地优先级排（P0=分类闸正确性，P1=方案创建质量，P2=效率）：

**P0-1 分类闸实战场标定**：W25 六次失败的三类分布——生产缺陷（matplotlib，确定性，仅打包态可复现）/ testWrong（fixture 序、子串陷阱，确定性，修测试基建）/ flaky（点击丢失，失败点漂移+复跑即绿）。建议把三个案例编入分类闸的判定样例：①失败消息含应用侧状态且复跑稳定复现 → deterministic；②点击返回成功但应用侧零痕迹 → 先查匹配集命中了谁（§3.3），大概率 testWrong；③失败点跨轮漂移+跑前进程快照拥挤 → flaky 路由。

**P0-2 失败诊断信息强制内嵌**：wait 类断言超时必须携带 read_status_text 最后一值+最后匹配控件（§3.4）。R3 案例：无此诊断要多跑一轮取证。

**P1-3 Phase 0 方案创建吸收"调查四件套"**：UIA 流草稿（文案从源码摘）/fixtures 清单/副作用与还原配方/风险清单（§1.1）。特别是"副作用还原配方"应成为方案模板必填栏——i18n 毒状态残留会级联炸掉同 run 后续全部用例。

**P1-4 控件定位手册内置**（§2 表）：PySide6 暴露形态+三个陷阱（QLineEdit 坐标序/QComboBox 空 Name+键盘回退/复选框子串）应写进 detect-uia-stack 之后的定位策略层，避免每个 worker 重新踩。

**P1-5 精确点击 helper 进共享库**：`click_exact(win, "登录")`（类型+Name 双条件）作为 click_button 的补位 API；click 后无状态变化时自动 dump 匹配集。

**P2-6 时长表进默认超时**（§8）；exe 冷加载 UI 冻结不算死锁的说明。

**P2-7 xfail 拆分策略**（§5.3）：已知生产缺陷阻断主链时，先拆盲区外可绿部分再 xfail，strict 保证修复日 XPASS 报警。

**P2-8 打包态专属价值标注**：仅打包态可复现的失败标记高价值（开发态依赖遮蔽类缺陷，§7），修复建议联动 spec/打包配置而非运行时代码。

---

## 附：本波沉淀的代码资产索引

- `tests/uia/conftest.py`：`tiny_det_model_path`（session，离线权重）/ `eval_gt_dir`（LabelMe 真值）
- `tests/uia/test_predict_flow.py`：负向探针 + strict xfail 主链（缺陷细节在 xfail reason）
- `tests/uia/test_eval_flow.py`：直填双路径框（绕同名"浏览"按钮配对）
- `tests/uia/test_user_mgmt_flow.py`：`_click_login_button` 精确匹配 / `_sort_edits` 坐标序 / always-first-run 还原 / 两段式重启验证
- `tests/uia/test_datamanage_move_i18n.py`：`_combo_select`（Select+键盘回退）/ i18n 双层还原
- `.workflow/uia-deep-w25/evidence/*.log`：全部轮次原始输出（含跑前进程快照）
