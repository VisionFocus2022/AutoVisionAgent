# AutoVisionAgent v7 审查整改实施规划（③ · 实施规划文档）

> 来源: [AutoVisionAgent-架构解析与优化方案-v7.md](AutoVisionAgent-架构解析与优化方案-v7.md)（回归轮 R4，2026-09-16）
> 覆盖: v7 全部新缺点 P1×3 / P2×5 / P3×10 的整改动作 11 条，三波（建议挂 W55/W56/W57，沿用仓内波次编号）
> 约定: 每条动作可独立提交/回滚；DoD 全部机械可判（单测断言 / grep 计数 / 门禁绿）；改动文件路径均经 v7 审查期间 ls/grep/Read 确认真实。
> 本文档可按仓内惯例移植为 `prd-w55-*.md` + `tasks-w55-*.md`（动作→AC→任务的一一映射已就绪）。

## 0. 方案总览

| 波次 | 动作 | 回引缺点 | 工时 | 风险 |
|---|---|---|---|---|
| 🚑 W55 一波·数据完整性与感知止血 | 1 换图硬清空画布会话 | P1-1 | 0.3 人日 | 低 |
| | 2 换图 SAM 会话同步（全模式） | P1-2 + P3-7 | 1 人日 | 低-中 |
| | 3 推理异常/AUTO 失败操作员反馈 | P2-4 | 0.3 人日 | 低 |
| | 4 恒真断言修正 | P3-1 | 0.05 人日 | 低 |
| 🔧 W56 二波·线程与生命周期 | 5 SAM 推理移 worker 线程 | P1-3 | 1-1.5 人日 | 中 |
| | 6 SAM 状态机串行化（busy 守卫） | P2-5 | 0.3 人日 | 低 |
| | 7 SAM 卸载通道 | P2-1 | 0.5 人日 | 低-中 |
| | 8 聚合门禁挂 CI | P2-2 | 0.3 人日 | 低 |
| 🧹 W57 三波·卫生与可移植性 | 9 脚本路径参数化 | P2-3 | 0.5 人日 | 低 |
| | 10 FakeThread 收敛 | P3-2 | 0.3 人日 | 低 |
| | 11 小项批量清偿（a-h） | P3-3/4/5/6/8/9/10 | 0.5-0.7 人日 | 低 |

**合计 ≈ 6 人日**。里程碑：W55 末发版前完成动作 1-4（数据完整性止血）→ W56 末动作 5-8 → W57 末动作 9-11 + v7 台账终核。

### 依赖关系图

```
动作1(硬清空) ──→ 动作2(会话同步) ──→ 动作3(异常反馈)
                       │
                       └──→ 动作6(状态机) ──→ 动作5(异步化) ──→ 动作7(卸载)

独立轨道（任意时点并行）:
  动作4(断言)   动作8(CI)   动作9(脚本)   动作10(FakeThread)   动作11a-h
```

- 动作 2 依赖动作 1：同为 `_load_by_index` 区段，先定清空语义再接会话同步，减少冲突。
- 动作 5 强依赖动作 6：异步化前必须先有串行化守卫（torch 前向非线程安全语义）。
- 动作 7 建议在动作 5 后：unload 须感知 PREDICTING 状态，避免与在途推理竞态（若提前做，unload 前必须查 busy）。
- 动作 3 建议在动作 2 后（同文件区段，回调注入面一次定形）；亦可提前独立做。

## 1. 风险登记册

| # | 风险 | 概率 | 影响 | 缓解 | 触发信号 |
|---|---|---|---|---|---|
| R1 | 换图清空改变现场「残留形状当模板」习惯 | 中 | 中 | Ctrl+C/Ctrl+V 显式携带通道已存在（page.py:388,734），发布说明注明 | 现场反馈「换图后标注丢失」 |
| R2 | ILabeler 契约变更（同步→请求-回调）波及 4 个 SAM 模式 + UIA 时序 | 中 | 中 | ADR 先行定契约；分步迁移（AUTO 先）；每步主门禁 + UIA label 套件 | UIA 假红/超时 |
| R3 | 异步化后 torch 并发前向 | 低 | 高 | 动作 6 全局 `_sam_state` 状态机先行（IDLE/LOADING/WARMING/PREDICTING 串行） | 推理偶发异常 / CUDA error |
| R4 | unload 与在途推理竞态 | 低 | 中 | unload 前置 PREDICTING 检查（动作 7 DoD ③） | 卸载时崩溃 |
| R5 | CI 挂载首次红（命名规约存量违例等） | 低 | 低 | 推送前本地预跑 check-naming.sh + ruff | CI 红 |
| R6 | FakeThread 17 文件批量替换引入行为差 | 低 | 低 | 本地副本与 conftest 版逐字比对（`_t/_a/_k` 与 `_target/_args/_kwargs` 仅属性名差、同步执行语义相同）；分目录分批提交 | 测试假绿 |
| R7 | 整改宣称与事实再次脱节（v7 P3-3 教训） | 中 | 中 | 本规划所有 DoD 均含机械断言，完成即机器可验，不依赖人工「已清零」声明 | 下轮回归核销 |

## 2. 逐条动作

### 动作 1：换图硬清空画布会话（P1-1）

- **背景动机**: v7 P1-1——`_load_by_index`（gui/pages/label/page.py:475-500）换图不清形状，`canvas.set_image_pixmap`（labeling/canvas.py:57-64）只换背景；save() 后 600ms 自动切下一张（page.py:705-706），上一图形状静默残留 → 跨图污染与误存。且 `clear_shapes`（canvas.py:157-163）先 `_save_state()` 再清——直接复用会留撤销复活通道。
- **DoD（验收标准）**:
  1. 换图后 `canvas.shapes == []`，且 `_undo_stack`/`_redo_stack` 均为空（换图后 Ctrl+Z 无形状复活）——新增单测 2 个断言；
  2. Ctrl+C → 换图 → Ctrl+V 显式携带路径仍可用（既有剪贴板功能回归用例绿）；
  3. 主门禁 1216+ 全绿。
- **改动范围**: `labeling/canvas.py`（新增 `reset_session()`：清形状 + 清双栈 + `_redraw()` + `shapes_changed.emit`，**不走** `_save_state`）；`gui/pages/label/page.py:486` 附近（`set_image_pixmap` 后接 `self.canvas.reset_session()`）；新建 `tests/test_w55_image_switch_session.py`。
- **分步骤**: ① canvas 加 `reset_session()` + 单测（隔离提交）② page 接线 + 换图单测 ③ 全量门禁 + `tests/uia/test_sam3_labeling*.py` 抽跑（UIA 换图用例不回归）。
- **风险与回滚**: R1（现场习惯）；单 commit revert 即回滚。
- **依赖**: 无（一波首个）。
- **工时**: 0.3 人日。
- **验证方式**: pytest targeted → 全量门禁 → UIA label 套件（发版检查单口径：桌面会话 + 打包 exe）。

### 动作 2：换图 SAM 会话同步——全模式 re-warm + 防丢拍 + 模式会话态重置（P1-2 + P3-7）

- **背景动机**: v7 P1-2——page.py:497-500 显式 `mode is INTERACTIVE` 才 `_warm_sam()`（W4-T3 注释自证历史成因，W43-W44 新增三模式未扩展）；`_sam_attach`（sam_session.py:190-193）attach 时图像定格，此后无人调 `set_image`——REGION_SAM/SAM_BRUSH/AUTO 换图后新图坐标进旧图模型静默错标。加重项：`_warm_sam` 见 busy 直接 return（:149-150），换图瞬间旧 warm 完成后把旧图 attach 给新画布（丢拍）。
- **DoD**:
  1. 换图时任一 SAM 模式（INTERACTIVE/REGION_SAM/SAM_BRUSH/AUTO），labeler 收到新图——单测用 FakeAdapter 记录 `set_image`/`predict` 收到的图像对象，换图后断言为新对象；
  2. warm 在途换图：旧 warm 完成后**不 attach 旧图**、自动对当前图重发 warm（FakeThread 同步化确定性单测）；
  3. `RegionSam._box`（region_sam.py:142-146）、`BrushSam._fg_points/_logits`（brush_sam.py:106-111）换图清空（经 `controller.cancel()` 或等价 reset）；
  4. 主门禁全绿。
- **改动范围**: `gui/pages/label/page.py:497-500`（INTERACTIVE-only 分支改全模式 `_sync_sam_session()`）；`gui/pages/label/sam_session.py`（`_warm_sam` 捕获 `image_path`、经 `invoke_main` 载荷传入 `_sam_attach(warmed_path)`——**注意确认 thread_bridge 多参载荷能力，必要时单参打包**；`warmed_path != self._image_path` 时不 attach、重发 warm；新增 `_sync_sam_session`：先同步更新 labeler 图像引用（ndarray 引用换绑，零成本）再异步 re-warm）；`labeling/controller.py`（新增 `update_image(image)` → `self._labeler.set_image(...)`——四 labeler 均已有 `set_image`：interactive.py:53 / region_sam.py:64 / brush_sam.py:53 / auto.py:58）；`labeling/modes/region_sam.py`、`brush_sam.py`（会话态 reset 钩子）；`tests/`。
- **分步骤**: ① controller.`update_image` + 单测 ② `_sam_attach` 带 warmed_path 校验 + 丢拍单测 ③ page 接线全模式同步 + 模式会话态重置 + 单测 ④ 全量门禁。
- **风险与回滚**: `_sam_attach` 槽签名变化（现调用点仅 sam_session.py:170 一处）; 单 commit revert。
- **依赖**: 动作 1 之后（同区段）。
- **工时**: 1 人日。
- **验证方式**: 单测（FakeAdapter 调用记录）+ UIA 换图重预热用例（957f697 已有用例面）。

### 动作 3：推理异常与 AUTO 失败的操作员反馈（P2-4）

- **背景动机**: v7 P2-4——interactive.py:64-67 / auto.py:69-72 / region_sam.py:105 / brush_sam.py:84 均 `except Exception → logger.exception → return None/0`，操作员视角「点击没反应」; AUTO 检测器异常与真零检出在 UI 合流（对照 DET 批量预标注已区分零检出/失败：workers.py:80-85 + page.py:571-574——同仓同族能力不对称）。
- **DoD**:
  1. 四模式推理异常 → 状态栏 ERROR 消息（monkeypatch adapter 抛异常的单测断言消息收到）;
  2. AUTO 异常文案「自动检测失败」与零检出文案「未检出目标」可区分（`run()` 异常返回哨兵 -1 或经回调上报，页面按结果分发）;
  3. SAM 模式下模型未就绪时点击 → 状态栏「SAM 未就绪」一次性提示（interactive.py:59-60 的静默 no-op 分支）;
  4. 主门禁全绿。
- **改动范围**: `labeling/modes/{interactive,region_sam,brush_sam,auto}.py`（labeler 增可选 `on_error` 回调）; `labeling/controller.py`（labeler 构造时注入回调，回调由 page 提供）; `gui/pages/label/page.py`（回调 → `status_changed.emit`）; `tests/`。
- **分步骤**: ① 回调注入面 + interactive 单测 ② 其余三模式 + AUTO 哨兵区分 ③ 未就绪提示 ④ 全量门禁。
- **风险与回滚**: 低; 单 commit revert。
- **依赖**: 建议动作 2 后（注入面一次定形）。
- **工时**: 0.3 人日。
- **验证方式**: 单测 + UIA 真窗失败注入用例（W49 flaw_gen 三段诚实失败先例可复用）。

### 动作 4：恒真断言修正（P3-1）

- **背景动机**: v7 P3-1——tests/test_w45_p3_cleanup.py:34 `assert action_allowed("intruder", "settings") is False or True` 恒真。
- **DoD**: 改为 `assert action_allowed("intruder", "settings") is False`（"settings" 非登记动作 → `_ACTION_MATRIX` 无键 → 全角色拒绝，语义断言）; 注释说明「未登记动作键全角色拒绝」; targeted 套件绿。
- **改动范围**: 仅该文件 1 行 + 注释。
- **工时**: 0.05 人日。**验证**: `pytest tests/test_w45_p3_cleanup.py -o addopts= -q`。

### 动作 5：SAM 推理移 worker 线程（P1-3，AMG 优先分两步）

- **背景动机**: v7 P1-3——点击推理在 GUI 线程同步执行（interactive.py:58-67、region_sam.py:96-115、brush_sam.py:66-95、auto.py:63-85）; SAM3 无独立 embedding API（sam3_adapter.py:93-104 set_image 只缓存），每击完整前向，真机实测 1.4-1.5s 冻 UI（W46 commit 29d95db）; AMG 全图更久。加载/预热已在 worker（run_job + invoke_main），唯独推理留在 GUI 线程。
- **设计**: ILabeler 的 SAM 模式从「on_press 内同步推理返回」改为「请求-回调」——labeler 只记录 pending 点并经回调发起请求; `sam_session` 统一经 `run_job` 执行 adapter 调用、`invoke_main` 回主线程 commit 形状; 全程 `_sam_state` 状态机（动作 6）串行。
- **DoD**:
  1. 单测断言 predict 执行线程 ≠ GUI 线程（worker 内 `threading.current_thread()` 与主线程比对）;
  2. FakeAdapter 注入 1.0s 延迟模拟慢前向：点击后 200ms 内状态栏出现「推理中」且 Qt 事件循环可继续处理事件（processEvents 探针单测）;
  3. AMG（AUTO 模式）异步 + 状态栏「自动分割中…」+ 可取消;
  4. 主门禁全绿 + UIA label 套件绿（时序断言改等状态栏终态）。
- **改动范围**: `gui/pages/label/sam_session.py`、`gui/pages/label/page.py`、`labeling/controller.py`、`labeling/modes/{interactive,region_sam,brush_sam,auto}.py`、`gui/core/jobs.py`（如需取消语义扩展）、`tests/` 新契约单测、`tests/uia/` 时序适配。
- **分步骤**: ① 一页 ADR 定契约（on_press 同步返回 → 异步 commit; 非 SAM 模式零影响）② AUTO 异步化（消除最大冻结面）③ interactive/region_sam/brush_sam 逐个迁移 ④ UIA 适配。每步独立提交过门禁。
- **风险与回滚**: R2/R3; 分步 revert。
- **依赖**: 动作 6 之后（串行化先行）; 动作 2 之后（会话同步定形，避免异步化叠加旧图问题）。
- **工时**: 1-1.5 人日。
- **验证方式**: 单测 + 全量门禁 + UIA 真窗（发版检查单口径）。

### 动作 6：SAM 状态机串行化（P2-5）

- **背景动机**: v7 P2-5——`_ensure_sam`（sam_session.py:51-64）顶部无 busy 守卫，加载在途再触发则二次加载覆盖 `self._sam_adapter`（:131）; 点击路径不查 `_sam_busy`（interactive.py:59 只查 adapter/image 非空），与后台 warm 并发进同一 torch 模块。
- **DoD**:
  1. `_sam_state`（IDLE/LOADING/WARMING/PREDICTING）单一状态机，`_ensure_sam` 顶部非 IDLE 即拒 + 状态栏「加载中…」;
  2. 推理请求在非 IDLE 时拒绝并提示（或排队最后一个——实现取拒绝，简单诚实）;
  3. 单测：FakeThread 计数断言双击模式按钮只产生 1 个加载 job; 并发点击不进 predict;
  4. 主门禁全绿。
- **改动范围**: `gui/pages/label/sam_session.py`（状态机 + 守卫）; `tests/`。
- **分步骤**: ① 状态机替换 `_sam_busy` 布尔（兼容既有槽位复位语义——`_sam_failed` 复位点同步改）② 点击侧守卫 ③ 单测 + 门禁。
- **风险与回滚**: 既有 `_sam_busy` 消费点（:57,:149-153,:202）同批迁移防漏; 单 commit revert。
- **依赖**: 动作 2 后、动作 5 前。
- **工时**: 0.3 人日。

### 动作 7：SAM 卸载通道（P2-1）

- **背景动机**: v7 P2-1——`_sam_adapter` 仅 `__init__` 置 None（page.py:182），无 closeEvent、无 unload/empty_cache 路径; SAM3 真机 VRAM 4.05GB（W46 实测）挂到进程退出; 换后端亦无释放。
- **DoD**:
  1. 两 adapter 新增 `unload()`：释放模型引用 + `torch.cuda.empty_cache()`（cuda 可用时）+ `loaded=False`;
  2. 标注页工具栏/菜单增「卸载 SAM（释放显存）」动作; 页面 `closeEvent` 时自动卸载;
  3. 卸载前置条件：`_sam_state` 为 IDLE（防 R4 竞态）;
  4. 单测：unload 后 `loaded is False` → 再次 `_ensure_sam` 可完整重载（python 单测）; 真机 VRAM 回收验证项写入发版检查单（nvidia-smi 前后对比，4.05GB 基线）;
  5. 主门禁全绿。
- **改动范围**: `labeling/sam_adapter.py`、`labeling/sam3_adapter.py`（unload）; `gui/pages/label/page.py`、`gui/pages/label/sam_session.py`（接线 + closeEvent）; `docs/release-checklist.md`（真机验证项）; `tests/`。
- **风险与回滚**: R4; 单 commit revert。
- **依赖**: 动作 5 后（状态机就绪）; 亦可提前但须自备 busy 检查。
- **工时**: 0.5 人日。

### 动作 8：聚合门禁挂 CI（P2-2）

- **背景动机**: v7 P2-2——`scripts/check-gate.sh`（三段聚合：naming → ruff 棘轮 → pytest）与 `check-naming.sh` 未被 `.github/workflows/ci.yml` 引用，且硬编码 `.venv/Scripts/python.exe`; W54 归零的棘轮在换机/他人提交场景无机器兜底。
- **DoD**:
  1. `check-gate.sh`/`check-naming.sh` 解释器路径参数化：`PYTHON="${PYTHON:-.venv/Scripts/python.exe}"`;
  2. ci.yml 增加 ruff job（`pip install ruff && ruff check .`——baseline=0 时 exit code 即门禁）与 .qoder 命名校验步骤;
  3. 推送后 CI 新增 job 绿（需远程写权限，用户侧动作）;
  4. 本地 `bash scripts/check-gate.sh` 三段绿（口径与 CI 一致，注释声明单一真源）。
- **改动范围**: `.github/workflows/ci.yml`、`scripts/check-gate.sh`、`scripts/check-naming.sh`。
- **风险与回滚**: R5; revert 即回滚。
- **依赖**: 无（独立轨道，随时可做——越早越好，保护后续所有动作）。
- **工时**: 0.3 人日。

### 动作 9：脚本路径参数化（P2-3）

- **背景动机**: v7 P2-3——13 个脚本硬编码 `E:/学习项目/...` 仓外绝对路径（eval_sam3_accuracy.py:15,23、convert_labelme_to_yoloseg.py:156、eval_pole_seg.py:29、finetune_sam3.py:34、8 个 exp_sam3_*）; W47 留档的「回归标尺」换机即失效。
- **DoD**:
  1. 13 脚本 argparse 化（`--data/--weights/--out`，默认仓相对路径或必填）;
  2. `grep -rn "E:/学习项目" scripts/` 计数 = 0;
  3. 权重路径与 34673c5 已落档的「SAM3 权重约定目录自动发现」spec 对齐（自动发现优先、显式参数兜底）;
  4. 既有纯函数测试（test_convert_yoloseg.py、test_sam3_finetune_script.py）不回归; 每脚本 `--help` 可跑。
- **改动范围**: `scripts/` 下 13 个文件。
- **风险与回滚**: 低（默认行为变化仅影响实验脚本）; 分文件提交。
- **依赖**: 无。
- **工时**: 0.5 人日。

### 动作 10：FakeThread 收敛（P3-2）

- **背景动机**: v7 P3-2——tests/conftest.py:87+ 已有单源（W39「各文件本地副本已删」注释），但 17 个测试文件仍有本地 `class FakeThread` 定义且形态漂移（`_t/_a/_k` vs `_target/_args/_kwargs`）。
- **DoD**:
  1. `grep -rln "class FakeThread" tests/` 计数 = 1（仅 conftest.py）;
  2. 17 文件改用 conftest 的 `fake_threads` fixture（替换前逐文件核对本地图与单源行为等价：均为同步执行 target，仅属性名差）;
  3. conftest 注释修正为「唯一定义（W39 收敛 + W57 清偿 17 处存量）」;
  4. 主门禁全绿。
- **改动范围**: `tests/conftest.py`（注释）+ 17 个测试文件（清单以 grep 输出为准）。
- **风险与回滚**: R6; 分目录分批提交。
- **依赖**: 无（避开动作 5 的同文件期同步开发即可）。
- **工时**: 0.3 人日。

### 动作 11：小项批量清偿（P3-3/4/5/6/8/9/10，每子项独立提交）

| 子项 | 缺点 | 内容 | DoD（机械可判） | 工时 |
|---|---|---|---|---|
| 11a | P3-4 | 登出最小实现：菜单「锁定/回登录」→ `reset_current_user/reset_current_role`（终获生产消费者）+ 回登录页；**或** ADR 声明单会话工作站不做（二选一，需产品决策） | 实现路径: UIA 断言登出后导航回 operator 集; ADR 路径: docs/adr/0003 落档 | 0.2 人日 |
| 11b | P3-9 | test_w20 加反向死键守卫 | 断言: 字典键 ∖（双+单引号字面量 ∪ 动态链豁免清单）= 空; 豁免清单显式维护 | 0.1 人日 |
| 11c | P3-4(iou) | 两 adapter 构造参数 clamp + 语义 docstring | `iou_thresh` 超 [0,1] 抛 ValueError 的单测 ×2; docstring 注记 SAM3 0.3 / SAM1 0.88 分叉 | 0.05 人日 |
| 11d | P3-5 | `resolve_sam3_model_dir` env 分支补 config.json 存在性检查 | env 指向无 config.json 目录 → 立即回落 SAM1 + 状态栏提示（单测）; 与对话框分支口径一致 | 0.05 人日 |
| 11e | P3-6 | 进 SAM3 模式状态栏一次性能力降级提示 | 进模式后状态栏出现「此后端不支持负点击/笔刷迭代精修」（UIA 断言） | 0.05 人日 |
| 11f | P3-8 | lite 豁免面单源化 | make_lite_dist.py 模块级常量/函数，test_w19_lite_dist.py import 同源; 双份手抄消除 | 0.05 人日 |
| 11g | P3-9 | 文档指针四处刷新 | README 权威版→v7; RELEASES UIA 待办按 W40-W49 实况刷新; .qoder/AGENTS.md 基线数字→0; ci.yml「无远程」注释删 | 0.1 人日 |
| 11h | P3-10 | gui/pages/label/page.py 793 行 | 不独立拆分——挂为动作 2/5 重构验收注记（sam_session mixin 继续吸收, 目标 ≤700） | — |

**P3-3（核销宣称纪律）的整改即本规划本身**: 所有 DoD 含机械断言 + 动作 8 上 CI 后由机器持续验证，不再依赖人工「已清零」声明。

## 3. 里程碑时间线

| 里程碑 | 内容 | 累计工时 | 出口条件 |
|---|---|---|---|
| M1（W55 末） | 动作 1-4：数据完整性止血 | ≈2 人日 | 全部 DoD 机械断言绿 + 主门禁绿 + UIA label 套件绿 → **可发版** |
| M2（W56 末） | 动作 5-8：线程/生命周期/CI | ≈4.5 人日 | UI 冻结消除（DoD 探针）+ CI 新 job 绿 |
| M3（W57 末） | 动作 9-11：卫生清偿 | ≈6 人日 | grep 锚点全零（FakeThread=1、E:/学习项目=0）+ v7 台账终核（26+18 项全闭环或 ADR 显式豁免） |

## 4. Gate 6 自检

- [x] 改动文件路径全部经 v7 审查期间 ls/grep/Read 确认真实（page.py/sam_session.py/canvas.py/controller.py/四 modes/conftest.py/ci.yml/check-gate.sh/13 脚本清单）
- [x] 每条动作验收标准客观可判（单测断言 / grep 计数 / 门禁退出码），无「评估一下」「适当优化」类模糊词
- [x] 每条动作回引 v7 缺点编号（P1-1..P3-10 全覆盖: P1×3→动作1/2/5, P2×5→动作7/8/9/3/6, P3-1→动作4, P3-2→动作10, P3-3→规划本身, P3-4/5/6/8/9→动作11, P3-7→动作2, P3-10→动作11h）
- [x] 依赖图/风险登记册/里程碑齐备; 关键设计风险（R2 契约变更、R3 并发）有前置动作（ADR + 状态机先行）
