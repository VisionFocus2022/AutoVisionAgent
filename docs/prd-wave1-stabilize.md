# wave1-stabilize — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-16 | 档位: L2 | 四维: reversible/module/test_visible/low（见 state.json）
> 上游依据: docs/AutoVisionAgent-架构解析与优化方案.md §11.5 第一波止血（用户已批准实施）

## 1. 背景与目标

- **背景**：架构审查（2026-08-16）终版 4 P1 + 14 P2。第一波止血针对：无版本管理（P1-4）、运行环境流落兄弟树（P2-1）、dispatcher 并发竞态（P2-2）、中文路径读图缺陷×5（P2-5）、宣称与实况倒挂（P1-1 第一步）。
- **目标**：
  1. 建立 git 基线与可复现 venv 环境，为后续所有改动提供回滚与验证安全网；
  2. 消除 3 个已定位的代码级缺陷（dispatcher 竞态 / 中文路径 / 静默假结果）；
  3. GUI 任务下拉与引擎注册表实况对齐，假 loss 路径显式警告。

## 2. 功能需求 (FR)

- **FR-001**: git 基线 — 仓库初始化并产生基线提交，敏感文件（users.json/license.key）与产物目录被 .gitignore 排除 | P0
- **FR-002**: venv 归位与环境锁定 — 兄弟树 .venv 复制回原创建路径，PySide6/torch CUDA 可用，全测试链可收集，生成 requirements.lock.txt | P0
- **FR-003**: VisionModelDispatcher 线程安全 — _engines 的复合操作（check/move_to_end/get/驱逐）由锁保护，unload 释放移到锁外 | P1
- **FR-004**: 中文路径读图统一 — 新增 core/image_io.imread_unicode（np.fromfile+imdecode，PIL 兜底），替换 5 处裸 cv2.imread（label×2 / predict×2 / dataset×1） | P1
- **FR-005**: 宣称诚实化 — engines docstring 改为 6/9 实况；train 下拉列全 9 项并对未装引擎标注（首项保持 DET 兼容 UIA）；predict 下拉仅列已注册引擎；train 两条静默假 loss 路径与 eval GT 自比较回退均发出状态栏警告；test_gui.py 对齐当前主壳 API | P1

## 3. 验收标准 (AC)

- **AC-001**: `git log --oneline` 含基线提交，`git status --short` 干净（忽略产物） [FR-001]
- **AC-002**: `.venv/Scripts/python.exe -c "import PySide6, torch; torch.cuda.is_available()"` 成功且 cuda=True；`requirements.lock.txt` 存在且行数>50 [FR-002]
- **AC-003**: 压力测试（8 线程×50 轮 load/infer 混合，max_loaded=2）无未捕获异常；既有单线程语义回归全绿（LRU 驱逐顺序、未加载 infer 抛 RuntimeError） [FR-003]
- **AC-004**: 中文目录+中文文件名的 PNG：裸 cv2.imread 返回 None（对照证明缺陷存在），imread_unicode 返回正确尺寸数组；VisionDataset 在中文路径下返回非 None 图像 [FR-004]
- **AC-005**: `grep "9 任务全注册" models/supervised/engines/__init__.py` 无命中；train 页 cmb_task 共 9 项且首项 data==TaskType.DET，未装引擎项标签含标注 [FR-005]
- **AC-006**: predict 页 cmb_task 项数==注册表注册数（当前 6）且每项 currentData 在 registry.list() 中 [FR-005]
- **AC-007**: 引擎缺失时 _make_trainer 发出含"模拟"的状态警告；引擎无 train_epoch 时同样警告；eval GT 回退发出警告 [FR-005]
- **AC-008**: py312 可跑子集（182 项）除已知 7 项引擎矩阵红外全部通过；新增测试全绿 [FR-003/004/005]

## 4. 范围

- ✅ **In Scope**: 上述 FR-001..005；test_gui.py API 对齐（test-only，为恢复 GUI 回归网——记入偏差）
- ❌ **Out of Scope**: 移植 det/seg/abdet 引擎（第二波）；flaw_gen TypeError 修复（第二波）；主线程重活迁移（第二波）；覆盖率门禁迁移（第二波）；deploy 页下拉（现含 cls 不倒挂，不动）；UIA 测试实际运行（需真人桌面会话，验证留给用户）

## 5. 风险与假设

- **风险**: venv 复制后脚本内绝对路径失效 → 缓解：该 venv 原创建路径即本树，复制即归位，逐项验证；venv 体积 7.1G 复制耗时 → 后台执行。
- **风险**: dispatcher 加锁改变锁内行为 → 缓解：unload 保持在锁外（GPU 同步不持锁），先写回归测试锁既有单线程语义。
- **假设**: 并发竞态的窄窗口无法在测试中确定性复现（对抗复核已确认后果为 fail-request 级）→ 以压力测试+代码结构论证为证据，TDD 的 RED 以回归测试为准（记偏差）。
- **假设**: UIA 测试不读任务下拉（已核实 test_full_workflow.py 只点按钮）→ 下拉改造不破坏 UIA。

## 6. 实现思路

- **拟采用**: dispatcher 加 threading.RLock（与 registry.py 双检锁同款）；imread_unicode 走 np.fromfile+cv2.imdecode；下拉构建抽 gui/core/tasks_ui.py 统一 populate_task_combo(combo, only_available)。
- **复用**: models/supervised/registry.py 的 list()/has()；train 页既有 R5-3 警告文案与 _SimStrategy；test_gui.py 的 offscreen qapp 范式。
- **注意**: 下拉首项必须保持 DET（UIA 训练步用默认项）；register_all_engines 在页面构建期触发（惰性导入，无重依赖开销）；不触碰 era 文档。

---

## 自检（5 项）

- [x] 完整性: 每条需求有 FR 编号
- [x] 无歧义: grep -iE "快速|友好|高效|灵活|强大" 本文件命中 = 0
- [x] 可追溯: 每个 FR 有对应 AC
- [x] 范围清晰: In / Out Scope 已列
- [x] 指标可量化: AC 均可机械判定

## ✅ 门禁

- [x] G1：用户原话"你的建议很好，根据你的建议开始实施"（2026-08-16，批准 §11.5 第一波）→ 状态证据
- [x] G3：同上原话含"开始实施"（执行授权）→ 状态证据；完成后须 AC 全过并通过状态验证器
