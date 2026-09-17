# AutoVisionAgent 2.1.0 深度审查报告（v7 · 回归轮 R4）

> 版本: 1.0 | 日期: 2026-09-16 | 方法: architecture-review L2 回归轮——2 证据矿工（SAM/SAM3 标注子系统 + W40-W54 非标注面）+ 主会话反驳裁决 + 主门禁独立复跑
> 审查对象: HEAD=`34673c5`（2026-08-31）· 增量 `29298b8..HEAD`（25 提交，W38 清偿 + W39 护栏收口 + W40-W54 SAM/SAM3/极柱模型/UIA/ruff 棘轮）
> 与 v6 的关系: 回归轮 R4——不重审 v6 已覆盖模块，只核销 v6 台账 26 项、深审其后增量（275 文件 +10,812/-1,301）、攻方复核 W39/W45/W54 刚落地的整改宣称
> 证据标注约定: （已验证）= 本轮主会话亲读 file:line 或独立复跑; （已验证·双源）= 矿工采证 + diff/commit 记录交叉; （推断，依据：…）= 未直接复现。file:line 均来自实际读取。

## 1. 一句话总评

v6 台账 26 项中 21 项闭环且经本轮证据核销（W38/W39/W45 清偿基本兑现，ruff 棘轮与主门禁均独立复跑通过），但「W45 台账清零」宣称被三处证伪（FakeThread 收敛未删净、无登出从未排期、反向死键守卫未建）；W43-W54 新落的 SAM/SAM3 交互标注子系统方法面设计良好、测试断言强度高，但**换图会话治理缺失**构成数据完整性与可用性三缺口——形状跨图残留可误存（P1-1）、非 INTERACTIVE 模式换图后静默用旧图预测（P1-2）、点击推理在 GUI 线程同步执行每次冻 UI 1.4-1.5s（P1-3）；聚合门禁（ruff 棘轮/check-gate）真实归零但纯本地人工执行、未挂 CI。

## 2. v6 台账核销表（回归轮 R4，26 项）

| v6 编号 | 宣称 | 核销结论 | 本轮证据 |
|---|---|---|---|
| P1-1 i18n 转义键 | W38 清偿 | **闭环** | 运行时复验：`set_language('en_US')` 后 `tr('有正在进行的操作（训练/推理）。\n')` 返回英文（已验证）; 机械守卫 tests/test_w20_i18n_completeness.py:27-28 改严格源文本比对（已验证） |
| P1-2 版本元数据 | W38 清偿 | **闭环** | pyproject.toml:3 = 2.1.0 + tag v2.1.0 存在 + tests/test_w38_version_consistency.py（已验证） |
| P2-1 UIA 12/12 空闲机取证 | v5「发版前」 | **大体闭环** | W40 python 模式 12 用例全验证（73b6eb1）→ W46·C 打包 exe 15/15（cb7427c）→ W49 19/19（8627ebd，commit 留痕）; RELEASES.md:34 待办文案仍停在 8-23 未刷新 |
| P2-2 跨盘符整批静默失败 | W38 清偿 | **闭环** | batch_prelabel.py:112 `splitdrive` 判跨盘回退绝对路径 + manifest `relpath_fallback` 字段区分回退/坏图（:10, :92，已验证） |
| P2-3 未登录宽容态全放行 | W39 反转 | **闭环** | shell.py:200-205 未登录按 operator 页集; permissions.py:98-99 `check_action` 未登录按 operator 动作集（已验证·双源：矿工 diff + 主会话亲读） |
| P2-4 离线一键 admin | W39 降级 | **闭环** | login/page.py:538 `log_login(role=ROLE_OPERATOR)`、:541 `login_success.emit("offline", ROLE_OPERATOR)`（已验证） |
| P2-5 守卫单引号盲区+6 漏翻 | W38 清偿 | **闭环** | test_w20:60 双引号+单引号双正则、:87 单引号探针断言（已验证） |
| P2-6 data_manage 批量工具漏登记 | W39 入控 | **闭环** | 登记 permissions.py:57 `data_manage.batch_label_edit` + 三处消费 page.py:585/609/633（已验证） |
| P2-7 批量/单张标签语义分叉 | W39 统一 | **闭环** | workers.py:76 与 batch_prelabel.py:45 均逐框 `labels[i]`，注释留档分叉史（已验证） |
| P2-8 原子写三胞胎 | W39 单源 | **闭环** | labeling/batch_tools.py:27 `atomic_write_json` 单源; batch_prelabel.py:23、predict/workers.py:14 消费（已验证）; 批注: workers.py:14 re-export 中转层可再下沉 |
| P3-1 门控顺序三页三样 | W39 统一 | **闭环** | predict:393 / video_super:34 / data_manage:585 门控均置于按钮入口首行，W39 注释留档（已验证） |
| P3-2 审计 page 字段混载 | W39 审计三件 | **闭环** | permissions.py:121-124 action 字段加 `action:` 前缀区分（已验证·双源） |
| P3-3 审计失败路径+无界缓冲 | W39 清偿 | **闭环** | audit_logger.py:64-65 `_buffer_hard_max=1000` 丢最旧 + mkdir 移入 try（:118-126，已验证·双源） |
| P3-4 无登出+reset 死代码 | —（未排期） | **未闭环** | 全 gui/ 无 logout 实现、`reset_current_role/reset_current_user` 生产零消费（grep 实测）; W45「台账清零」从未含此项 |
| P3-5 permissions 模块头失实 | W39 修正 | **闭环** | 模块头 :1-5 W39·v6 P3-5 声明修正（已验证） |
| P3-6 未知角色回退矛盾 | W45 归一 | **闭环** | permissions.py:61 `_normalize_role` 统一 operator + test_w45:27-33 实断言（已验证） |
| P3-7 lite 剪除归属假设无守卫 | W45 守卫 | **闭环** | tests/test_w45_p3_cleanup.py 剪除包 import 守卫（已验证） |
| P3-8 save_dir 三胞胎 | — | **不拟收口（前提消失）** | 三函数仍分离（autolabel_save_dir: batch_prelabel.py:30 / superres_save_dir: video_super.py:19 / batch_save_dir: workers.py:53）但签名已分叉（batch_save_dir 多 scanned_dir 参），「逐字同构」不再成立（已验证） |
| P3-9 反向死 key 无守卫 | —（未排期） | **未闭环** | test_w20 无反向对账断言（grep 反向/死键/reverse 零命中）; W44 只做了变量键守卫（不同方向） |
| P3-10 接线子串断言弱 | W39 行为化 | **闭环** | test_w35 现为 monkeypatch+返回值行为断言，无 `in src` 子串断言（已验证） |
| P3-11 初始凭据明文 | W45 警示 | **闭环（机制演进）** | configs/ 无 initial_credentials.txt 落仓; login/page.py:77 `sweep_residual_initial_credentials` 残留清扫（已验证） |
| P3-12 「记住登录」死控件 | W39 删除 | **闭环** | login/page.py:295-296 注释留档已删（已验证） |
| P3-13 unused/ 空目录 | rmdir 一条命令 | **闭环** | `git ls-files unused/` 零跟踪（本地遗留空目录，cosmetic）（已验证） |
| P3-14 lite 余量无棘轮 | W45 棘轮 | **闭环** | test_w19_lite_dist.py 5MiB 硬棘轮 + 10MiB 预警（已验证） |
| P3-15 gui→serving 跨层 | W45 下沉 | **闭环** | core/mask_codec.py 落地、serving/mask_codec.py 变 re-export shim、workers.py:123 改 import core（已验证）; 批注: serving/serialization.py:154 仍走 shim |
| P3-16 FakeThread 逐字复制 | W39 单源收敛 | **宣称部分证伪** | tests/conftest.py:87+ 单源与「各文件本地副本已删」注释真建立，但 **17 个测试文件仍各自定义 `class FakeThread`**（grep 实测 18 处含 conftest），且形态漂移（本地 `_t/_a/_k` vs conftest `_target/_args/_kwargs`）; 抽样 3 文件创建于 2026-08-17（早于 W39）——存量未删净而非新增回潮（已验证） |

**核销计分**: 闭环 21 + 大体闭环 1 + 未闭环 2（P3-4/P3-9）+ 宣称证伪 1（P3-16）+ 前提消失 1（P3-8）= 26。**58c5d27「W45，v6 台账清零」宣称不成立**——三处与事实不符。

## 3. 增量面深审（`29298b8..HEAD`，25 提交）

### 3.1 SAM/SAM3 交互标注子系统（labeling/ 19 文件 + gui/pages/label/，W43-W54 共 9 提交）

**正面确认（防失衡清单）**：
- 同构方法面设计（Sam3Adapter 与 SamAdapter 方法对齐，transformers 5.12 无 point 提示时代偿盒降级有 docstring 源码实证依据）（已验证·双源）
- `_best_mask_near` 质心选例优雅零产出（空实例不崩、空掩码不产形状），W52 162 图实测决策 docstring 留档（已验证·双源）
- 掩码∩矩形硬约束两后端一致、代偿盒/外包盒边界夹取（sam3_adapter.py:196-199,238-244）（已验证·双源）
- W52/W53 半径/盒边距悬崖知识完整留档（predict_point_in_box docstring 记两轮证伪+回滚; router_diag 产物与 exp 脚本在仓）（已验证·双源）
- 撤销/重做快照栈与手动形状完全对称（canvas.py:73-108）（已验证·双源）
- UIA 真窗套件断言强度高（几何合法性逐点校验/状态机双通道计数/失败注入负例——抽样 5 文件）（已验证·双源）
- 加载失败诚实（伪权重→状态栏报错+主窗存活，UIA 实证）; 子系统无 bare except、无完全裸吞（已验证·双源）

**缺陷**：见 §4 P1-1/P1-2/P1-3、P2-1/P2-4/P2-5、P3 系列与会话态残留项。

### 3.2 非标注面（gui/core/serving/scripts/.qoder）

- **W54 typing 现代化占 gui 增量大头**：33 文件 `Optional→|`、`try/pass→contextlib.suppress`、isort——行为等价（diff 逐段核对）（已验证·双源）
- **W39 权限反转**三处（shell/permissions/data_manage）口径一致 + 行为化测试守护（已验证）
- **broad except 口径修正**（详见 §5 台账）：生产净增仅 3 处且全部留痕（brush_sam.py:84、region_sam.py:105 均 `# noqa: BLE001` + logger.exception; finetune_sam3.py:237 重试耗尽 raise）——「39→53 恶化」系 v6 基线口径不可复现所致（同口径复测基线为 50）（已验证·双源）
- **.qoder/**（28 文件入库）：纯流程资产——AGENTS/rules/skills/agents/records/skill-bank，生产包零引用、敏感信息正则扫描阴性; records 质量高（ruff 计数假红缺陷修复留档）（已验证·双源）; 批注: AGENTS.md L0 基线数字仍写 1153（实际已归零）
- **scripts/**：13 个取证/实验脚本硬编码 `E:/学习项目/...` 绝对路径（见 P2-3）; 9 个 exp_sam3_* 无 argparse; router_search 链式依赖 router_diag 产物; 仅 convert/finetune 两脚本纯函数被测试引用
- **W54 ruff 棘轮**：`scripts/ruff-baseline.txt` = `0`（2 字节）+ HEAD 实跑 `ruff check .` 0 违规——真实归零非纸面（已验证·双源）; 但 `check-gate.sh`/`check-naming.sh` 未挂 CI（见 P2-2）
- **conftest 内存预检**：落点 tests/uia/conftest.py:464-491（ctypes GlobalMemoryStatusEx，提交内存 <6GB 整组 skip + 逃生门）——诚实实现（已验证·双源）
- **6124e01 lite logs 豁免**：字节级对账真实（marker v2 total_bytes + 无 CUDA/`+cpu`/体积棘轮断言）; 豁免按路径段名 `logs` 匹配且守卫测试内联复制同一排除逻辑（双份手抄，见 P3-8）（已验证·双源）

### 3.3 依赖与运行产物

- requirements.lock.txt:200 锁 transformers==5.12.1; segment_anything/transformers 在 requirements.txt:39-40 均注释可选——基础安装无 SAM 后端、运行时诚实探测（已验证）
- logs/autovision.log（5.2MB，9-2）：114 条 ERROR 的 logger 分布（login 84 / predict 18 / uia.conftest 12）与 UIA LogAnchor 失败注入设计吻合——**测试注入痕迹非生产崩溃信号**（推断，依据：logger 分布 + W49 失败注入用例面 + 文件时间与 UIA 跑批期吻合; 未逐条核读）
- CI：ci.yml 全量门禁（windows-latest + offscreen Qt + dotnet job）已配置，gitee/github 双远程已接; ci.yml 头部「本仓当前无 git 远程」注释过时; CI 红/绿率本地不可验证

## 4. 新缺点清单（P1×3 / P2×5 / P3×10）

> 定级依据：数据完整性/静默失败类按 §6.4.1 机器视觉域红线 + v6 定级先例（跨盘整批静默失败有 manifest 留痕=P2; 本组 P1 均无留痕且直接产错数据/冻旗舰功能）; 规模类按 §7 阈值表。

**P1-1 换图不清画布形状 + save() 自动切下一张 = 跨图标注污染/误存通道**（🚑 一波）
`gui/pages/label/page.py:475-500` `_load_by_index` 无任何清形状调用（全文件仅 btn_clear :363 一处触发）; `labeling/canvas.py:57-64` `set_image_pixmap` 只换背景不清形状; `page.py:705-706` save 后 600ms 自动 `next_image`——上一图形状残留到下一图画布，继续绘制即混合两图形状，再保存即误存（保存走手动文件对话框，非全静默，但污染显示与后续绘制完全静默）。无任何测试/文档钉住「复制携带」为有意工作流（已验证·主会话亲读三处）。域定级：标注数据完整性红线（错误训练数据静默产生）。若属有意「同区域复制」工作流，须 ADR 显式化 + UI 确认门。

**P1-2 SAM 会话换图只重预热 INTERACTIVE——REGION_SAM/SAM_BRUSH/AUTO 换图后静默用旧图预测**（🚑 一波）
`page.py:497-500` 显式 `mode is AnnotationMode.INTERACTIVE` 才 `_warm_sam()`（W4-T3 注释自证该逻辑诞生时只有 INTERACTIVE 一种 SAM 模式; W43-W44 新增三模式未同步扩展）; `sam_session.py:190-193` attach 时图像定格，此后换图无人调 `set_image`——新图坐标进旧图模型，**静默产出错误掩码**（比 P1-1 更隐蔽：无视觉残留提示）。加重项：预热丢拍竞态 `sam_session.py:149-150`（busy 直接 return 无排队）——换图瞬间旧图预热完成后 `_sam_attach` 把旧图塞给 labeler，画布显示 B、预测用 A（已验证·亲读）。域定级：静默错误输出 + 无任何留痕（对照 v6 跨盘 P2 有 manifest 留痕，此处更重）。

**P1-3 SAM 点击推理在 GUI 线程同步执行——SAM3 每击冻 UI 1.4-1.5s、AMG 全图更久**（🔧 二波）
`labeling/modes/interactive.py:58-67` on_press 直接调 `adapter.predict_point`（mousePressEvent 调用链内，亲验）; 同型：region_sam.py:96-115（on_release）、brush_sam.py:66-95、auto.py:63-85（on_press→run() 全图 AMG，亲验）。根因协同：sam3_adapter.py:93-104 `set_image` 只缓存不编码（transformers SAM3 无独立 embedding API），`_warm_sam` 对 SAM3 空转——docstring「点击时命中缓存，UI 不冻结」（sam_session.py:148）对 SAM3 不成立。实测锚点：W46 真机 RTX3060 交互 1.4-1.5s/次（commit 29d95db）; AMG 全图时长无实测记录（推断，依据：全图多实例前向 + SAM3 单击 1.4s 量级外推）（亲验 interactive/auto 两处 + 矿工采证其余两处）。加载/预热已在 worker 线程（run_job + invoke_main），唯独点击推理留在 GUI 线程——同子系统内已有线程基建可复用。定级：旗舰交互功能可用性债务（W43-W54 投入 9+ 提交的功能面）。

**P2-1 SAM 模型无卸载/VRAM 释放通道**（🔧 二波）
`gui/pages/label/page.py:182` `_sam_adapter=None` 仅在 `__init__`; 页面无 closeEvent、全子系统无 unload/empty_cache 路径——SAM3 真机 VRAM 4.05GB（W46 实测）挂到进程退出; 页面级换后端（SAM1↔SAM3）亦无释放（已验证·双源）。S12 资源生命周期视角。

**P2-2 聚合门禁未挂 CI——ruff 棘轮/check-gate/check-naming 纯本地人工执行**（🔧 二波）
ci.yml 无任何对 `scripts/check-gate.sh`/`check-naming.sh`/ruff 基线的引用; 脚本硬编码 `.venv/Scripts/python.exe` Windows venv 路径（bash 语法）（已验证·双源）。W54 花大力气归零的棘轮在换机/他人提交场景无机器兜底——「基线只升不降」依赖自觉。S11 构建链视角。

**P2-3 13 个取证/实验脚本硬编码仓外绝对路径——回归标尺不可移植**（🧹 三波）
eval_sam3_accuracy.py:15,23、convert_labelme_to_yoloseg.py:156、eval_pole_seg.py:29、finetune_sam3.py:34 及 8 个 exp_sam3_*（如 exp_sam3_region_caliber.py:21,30、router_search.py:24）默认值指向 `E:/学习项目/...` 仓外路径; 另 router_search 输入依赖另一 exp 脚本产物（链式）、9 脚本无 argparse（已验证·双源）。W47 将 eval_sam3_accuracy.py 留档为「回归标尺」——不可移植的标尺在换机后失效，弱化 §6.4.1 算法证据链的可重演性。

**P2-4 SAM 推理异常有日志无操作员反馈; AUTO 失败与零检出在 UI 合流**（🚑 一波）
interactive.py:64-67 / auto.py:69-72 / region_sam.py:105 / brush_sam.py:84 均 `except Exception → logger.exception → return None/0`——留痕完整但状态栏零提示，操作员视角「点击没反应」; AUTO 通道检测器异常与真零检出同表现为空队列（对照：DET 批量预标注已区分零检出/失败并有专门文案 workers.py:80-85 + page.py:571-574——同仓同族能力不对称）（已验证·亲验 interactive/auto）。域定级：有日志留痕故未至 P1 档（§6.4.1 无 Trace 的 P0 型不适用），但交互工具的操作员感知缺口显著。

**P2-5 SAM 加载/预热/使用三处竞态**（🔧 二波）
① `_ensure_sam`（sam_session.py:51-64）顶部无 busy 守卫——加载在途再点模式按钮二次进入、后发 job 覆盖 `self._sam_adapter`（:131）; ② 点击路径不查 `_sam_busy`——与后台 warm worker 并发进同一 torch 模块（interactive.py:59 只查 adapter/image 非空）; ③ 丢拍竞态已并入 P1-2（已验证·亲读 ①②）。S3 并发视角; GIL 下 Python 层原子但 torch 前向非线程安全语义无保证（推断，依据：PyTorch 常识 + 代码无锁实证）。

**P3-1 恒真断言**：tests/test_w45_p3_cleanup.py:34 `assert action_allowed("intruder", "settings") is False or True`——`or True` 使断言恒真，守不住任何回归（已验证·亲读）。
**P3-2 FakeThread 收敛宣称与现实不符**：17 文件本地副本仍在且形态漂移（§2 P3-16）; conftest 注释「各文件本地副本已删」失实——双源维护，行为可分叉（已验证）。
**P3-3 核销宣称纪律缺口**：「W45 台账清零」三处证伪（P3-4/P3-9/P3-16）+ v6 broad except 基线 39 口径不可复现（同口径 50）——宣称应改为机械验证（守卫测试/grep 锚点）而非人工声明（已验证）。
**P3-4 iou_thresh 同名参数两后端语义分叉**：SAM3 默认 0.3（sam3_adapter.py:277-281）vs SAM1 默认 0.88（sam_adapter.py:214-219），无 [0,1] 校验、UI 不可达——未来暴露参数时是语义陷阱（已验证·双源）。
**P3-5 AVA_SAM3_DIR 通道校验不对称**：env 路径只查 `is_dir()`（sam_session.py:39-40），对话框路径双文件校验（:41-44）——env 指坏目录延迟一个加载周期才诚实报错（已验证·双源）。
**P3-6 SAM3 能力降级无用户感知**：负点击返回空（sam3_adapter.py:191-192，SAM3 无负点击精修 vs SAM1 有）、笔刷 logits 恒 None 仍缓存（brush_sam.py:94）、未加载完成时点击静默 no-op（interactive.py:59-60）——诚实降级实现正确但用户无感知通道（已验证·双源）。
**P3-7 模式会话态跨图残留**：RegionSam `_box`（region_sam.py:142-146）、BrushSam `_fg_points/_logits`（brush_sam.py:106-111）换图不清——P1-2 的表层姊妹项（已验证·双源）。
**P3-8 lite 豁免面双份手抄**：make_lite_dist.py:266-270 与 test_w19_lite_dist.py:357-365 各自维护同一排除逻辑，docstring 自认「两处必须人肉同步」（已验证·双源）。
**P3-9 文档指针滞后四面**：README.md:42 「权威版（v4）」链 v5（v6/v7 已存在）; RELEASES.md:34 UIA 待办停在 8-23（W40-W49 已做）; .qoder/AGENTS.md 基线 1153 已归零; ci.yml 头「无 git 远程」已过时（已验证）。
**P3-10 gui/pages/label/page.py 793 行距 800 守卫线 7 行**：W27 曾压至 695，SAM 会话接入后回涨 98（wc 实测; 守卫三次拦截史见 RELEASES）（已验证）。

## 5. 实测指标表（本轮 HEAD=34673c5）+ 攻方复核台账

### 5.1 指标表

| 指标 | v7 实测 | v6 对照 | 判定 | 复核状态 |
|---|---|---|---|---|
| 主门禁 | **1216 passed + 5 skipped / 150.52s / exit 0**（覆盖率 ≥92 棘轮随 addopts 生效） | 1106 | +110 用例 | （重验: 本轮独立全量复跑，一致） |
| 收集数（含 UIA） | 1243 | — | 1243-1216=27=UIA 套件（22 函数含参数化） | （重验: collect-only，一致） |
| 12 包生产 LOC | **19,867** | 18,695 | +6.3%（labeling 子系统为主） | （重验: wc 双遍，一致） |
| 单文件最大 | 795（data_manage/page.py） | 792 | 800 守卫未破（label/page.py 793 临界） | （重验: wc sort，一致） |
| broad except（12 包非测试） | **53**（同口径基线复测 50） | 39（口径不可复现） | 净增 3 且全留痕 | （重验: 矿工 diff 逐行 + 主会话抽验——v6 的 39 与本轮 50 为口径差） |
| bare except | 0 | — | 正常 | （重验: grep，一致） |
| TODO/FIXME 真实计数 | **0**（4 命中均为「初始密码: XXX」掩码注释误报） | 0 | 持平 | （重验: 逐条人工核读，修正初判） |
| ruff 违规 | **0**（baseline 文件=0 + 实跑 0） | （W54 宣称 1153→0） | 归零 | （重验: 实跑，一致） |
| 覆盖率精确值 | ≥92（exit 0 门禁生效; 精确值未单独重测） | 92+ | 达标 | （部分重验: 门禁生效性机械证明; 92.93% 维持 W54 宣称口径） |
| lite 体积 | 本轮未重打包（W46·C 记录余量 20.6MiB） | 1.9935GiB/余量 ~6.5MB | 棘轮 5/10MiB 已挂测试 | （未重验: 打包需空闲窗口; 棘轮测试在门禁内跑） |
| en_US 中文残留 | 双引号+单引号守卫均在门禁内（1216 绿含 test_w20） | ≥7 | 守卫口径闭环 | （重验: 守卫随门禁复跑） |
| P1/P2/P3 | **3/5/10** | 2/8/16 | 台账 24/26 闭环（含大体+前提消失） | — |

### 5.2 攻方复核台账（主会话反驳裁决）

| 候选发现 | 反驳过程 | 裁决 |
|---|---|---|
| broad except「39→53 恶化 +14」（主会话 Phase 1 初判） | 矿工 diff 逐行：+14 行中生产净增 3、格式重写 3、测试 8; 同口径基线复测 50 非 39 | **初判被证伪**：净增 3 且全留痕; v6 基线口径问题入 P3-3 |
| P1-1 形状跨图残留「可能是有意复制工作流」 | 查 save/换图全链 + 全部测试：无一处钉住携带意图; 600ms 自动切图与携带组合指向意外 | **存活 P1**（若有意须 ADR 化） |
| P1-2 旧图预测（矿工 A） | 主会话亲读 page.py:497-500 + sam_session.py:190-193; W4-T3 注释自证历史成因 | **存活 P1**（亲验） |
| P1-3 GUI 线程推理「AMG 数十秒」（矿工 A） | interactive/auto 两处亲验成立; AMG 时长无实测记录，1.4-1.5s 有 W46 实测锚点 | **存活 P1**; AMG 时长降为推断标注 |
| 「FakeThread 已单源收敛」（矿工 B 采信 conftest 注释） | 主会话 grep 实测 17 文件仍有定义; 抽样 3 文件建档于 W39 之前 | **宣称证伪**：存量未删净，入 P3-2/P3-3 |
| 恒真断言 test_w45:34（矿工 B） | 主会话亲读原文 | **坐实 P3-1** |
| logs 114 ERROR「生产异常信号？」 | logger 分布与 UIA 失败注入设计吻合; 未逐条核读 | **降为测试注入痕迹**（推断标注） |
| P3-16 v6「核销表宣称」对 W39 的回溯性质疑 | 抽样文件 2026-08-17 建档 < W39（8-23）——是未删净非回潮 | **定性修正**：W39 当期宣称失实（而非后来退化） |

## 6. 改进路线（按 ROI 排序）

### 🚑 第一波·标注数据完整性与感知止血（约 2 人日，低风险）
1. **P1-1**：`_load_by_index` 清形状（或显式「携带到新图？」确认门 + ADR）——0.3 人日
2. **P1-2**：换图会话治理统一——全 SAM 模式 re-warm/re-attach + busy 排队/取消语义——1 人日
3. **P2-4**：推理异常/AUTO 失败接状态栏反馈（复用 DET 零检出/失败区分文案）——0.3 人日
4. **P3-1**：恒真断言改为实断言——0.05 人日

### 🔧 第二波·线程与生命周期（约 2-2.5 人日，中风险）
5. **P1-3**：点击推理移 worker 线程（复用 run_job + invoke_main 基建; AMG 优先）——1-1.5 人日
6. **P2-5**：`_ensure_sam` busy 守卫 + 点击前 busy 检查——0.3 人日
7. **P2-1**：SAM 卸载通道（页面离开/closeEvent 释放 + empty_cache）——0.5 人日
8. **P2-2**：check-gate.sh 挂 CI（ci.yml 加 job + 去 venv 硬编码路径）——0.3 人日

### 🧹 第三波·卫生（约 1 人日，随时）
9. **P2-3**：13 脚本路径参数化（argparse + 仓相对默认）——0.5 人日
10. **P3-2**：FakeThread 17 副本收敛 + conftest 注释修正——0.3 人日
11. P3-3..P3-10（登出排期决策/反向死键守卫/iou_thresh 校验/env 对称校验/降级感知/会话态清理/lite 手抄合并/文档指针/793 行拆分）——0.5 人日

### 决策者建议
- **SAM 标注已是产品主打面**（W43-W54 投入 9+ 提交 + UIA 深度覆盖），其数据完整性三缺口（P1-1/P1-2/P2-4）应在下一次发版前收口——错误标注静默流入训练集的代价高于全部一波工作量。
- **「声称收口≠真收口」本轮三度上演**（FakeThread/台账清零/broad except 口径）——核销宣称应改为机械验证（守卫测试或 grep 锚点入 CI），人工「已清零」承诺不可复现。
- **聚合门禁上 CI（P2-2）是所有本地棘轮的前提性投资**——ruff 基线、lite 体积、命名规约目前全靠自觉。

## 7. 覆盖矩阵（18 视角 + 扩展，增量更新 v6）

| 视角 | 状态 | 本轮关键更新 |
|---|---|---|
| C1 架构 | 必查 ✓ | 分层无新违例（gui→serving 跨层已消; workers re-export/serialization shim 为残余批注）; SAM 适配器层同构方法面设计良好 |
| C2 可维护性 | 必查 ✓ | 793 行临界（P3-10）; ruff 真实归零; exp 脚本债务面（P2-3）; FakeThread 双源（P3-2） |
| C3 可靠性 | 必查 ✓ | **P1-1/P1-2 数据完整性静默缺口**; 推理异常留痕完整（正面） |
| C4 可测试性 | 必查 ✓ | 1216 绿独立复跑; UIA 断言强度高; 恒真断言 1 处（P3-1） |
| C5 可运维性 | 必查 ✓ | lite 棘轮测试化; RELEASES 待办滞后（P3-9） |
| C6 安全 | 必查 ✓ | v6 硬底线维持; 权限反转后旁路关闭（W39 三处一致）; 无登出（P3-4 承接） |
| S1 性能 | 适用 ✓ | **P1-3 GUI 线程推理冻结**（1.4-1.5s/击实测锚点） |
| S2 数据 | 适用 ✓ | **P1-1 跨图污染/误存**; manifest 区分回退/坏图（正面） |
| S3 并发 | 适用 ✓ | **P2-5 三处竞态**（加载双发/warm 并发/丢拍并入 P1-2） |
| S4 契约 | 适用 ✓ | proto 零实质变化（生成器版本头）; 版本五方守卫在门禁 |
| S5 依赖 | 适用 ✓ | lock 锁定; SAM 后端可选声明诚实; transformers 5.12 无 point 提示的代偿已留档 |
| S6 灾备 | 不适用 | 单机工作站（同 v6） |
| S7 合规 | 不适用 | 无 PII/监管面（同 v6） |
| S8 可观测深化 | 不适用 | 单机（同 v6）; 审计缓冲硬上限已修（正面） |
| S9 i18n | 适用 ✓ | 双引号守卫闭环 + 运行时验证; 反向死键守卫未建（P3-9 承接） |
| S10 演进/ADR | 适用 ✓ | ADR 实践存在（docs/adr 0001/0002）; .qoder records 留痕质量高; W52/W53 证伪知识 docstring 留档（正面）; 核销宣称纪律缺口（P3-3） |
| S11 构建链 | 适用 ✓ | **P2-2 聚合门禁未挂 CI**; ci.yml 配置在但红/绿率不可验证; 双远程已接 |
| S12 资源泄漏/生命周期 | 适用 ✓ | **P2-1 SAM 模型无卸载通道**（VRAM 4GB 挂进程）; 页面退出有全局 5s 有界停机兜底（正面） |
| E-机器视觉域（§6.4.1） | 扩展 ✓ | 像素格式/算子几何不适用（SAM 后端自封装）; 静默失败→P2-4; 证据链→P2-3（标尺不可移植）; 参数域悬崖知识留档充分（正面）; 资源生命周期→P2-1; **无扩展新增（已评估）** |
| E-MES 域 / E-运动控制域 | 不适用 | MES 关键词（工单/报工/条码/SN）全仓 0 命中; 运动控制关键词（LTDMC/dmc_/轴卡）0 命中——依赖面纯 torch/PySide6/cv2（已验证） |

## 8. 完整性批判记录（§6.4 九问）

1. **最关键风险面覆盖？** 已覆盖——标注数据完整性（P1-1/P1-2）与旗舰功能可用性（P1-3）为本轮核心产出。
2. **有无从未打开的子系统？** exporter/evaluation/benchmarks/dataset 包未逐文件深审（矿工 diff 证实本窗口仅 typing 清洗; v5 曾全量审）; models/supervised 各引擎内部未重读（同前）。已按增量面原则交代。
3. **外部边界？** gRPC serving 边界本窗口 proto 零实质变化（v5 已深审）; 无相机/硬件直连（文件交换型工具）。
4. **非功能默认成立？** UI 冻结有 W46 实测锚点; VRAM 4.05GB 实测; AMG 时长与并发竞态的实际发生率未实测（推断标注）。
5. **运行产物异常信号解释？** logs 114 ERROR 归类测试注入（推断标注）; 无 dump/崩溃文件。
6. **主路径 vs 错误路径？** 矿工专项即错误路径; 竞态场景（P2-5）识别但未运行时复现。
7. **文档自相矛盾？** broad except 基线 39 vs 50 已发现并定性（口径）; conftest「已删」vs 17 副本已证伪; 无其他。
8. **单一证据源？** P1 三条均主会话亲验; P2-1/P2-2/P2-3 矿工采证 + commit/diff 交叉（双源）; logs 归类单源（已降推断）。
9. **领域视角补全？** 机器视觉域表已应用（E-行）; MES/运动控制域以关键词 0 命中 + 依赖面证据判 N/A; 无新增领域视角（已评估）。

## 9. 验证范围与局限

- 审查期间 git status 保持 clean（仅 .claude/ 未跟踪）; 无并行会话干扰。
- 主门禁 1216 绿为本轮独立复跑（150.52s, exit 0, 覆盖率棘轮生效）; 覆盖率精确值未单独重测（92.93% 维持 W54 宣称）; UIA 真窗套件未执行（需桌面会话 + 打包 exe，历史绿记录 W49 19/19 / W53 3/3）; lite 体积未重打包复测。
- 矿工发现经主会话逐条裁决: P1 全部亲验 file:line; P2-1/P2-2/P2-3 双源（矿工 + commit/diff/实跑）; P3-6/P3-7 等矿工单源采信（结构一致性高，未逐行亲读）。
- AMG 全图推理时长、竞态实际发生率、CI 远端红/绿率为推断或不可验证项，均已就地标注。
- 上一轮（v6）的 broad except 基线 39 在同口径下不可复现（实测 50）——跨轮数字对比以本轮口径为准。
