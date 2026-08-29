# PRD：SAM 标注 UIA 自动化测试方案（W46·B · lite）

## 定档声明（Step 0）

- 档位：🟡 **L2**（自治会话延续，门禁 S1/S3 降级留痕，见 §7）
- 确定性：中→高——UIA 基建（tests/uia 12 用例 + uia_helpers 881 行 + 陷阱对策全在档）与 SAM 装配缝（AVA_SAM3_DIR 环境变量直载，绕开 #32770 对话框）均已取证
- 影响半径：小-中——测试文件纯加性；**唯一生产改动 = 补 AUTO 模式工具栏按钮**（见 §2 偏差），既有 exe 不受影响（未重打包，旧 exe 里无此按钮）
- 规模：中（测试 ~350 行 / 生产 ~3 行 / 2 docs）
- 可逆性：双向门（git）
- 依据：低确定×小影响 → L2；用户 S1 指令「创建 UIA 自动化测试方案，测试 SAM 标注」

## 1. 背景与目标

W46·A 已集成 SAM3 后端（weights/sam3 + Sam3Adapter + AVA_SAM3_DIR 装配）。现有 UIA 套件（12 用例）未覆盖任何 SAM 标注流。目标：以**源码模式**（exe 未打包 transformers，重打包留待后续波次）UIA 真窗驱动，验证 SAM 标注端到端链路：装配→预热→交互产出多边形→落盘铁证→失败诚实路径。

## 2. 需求（FR）

- **FR-1（生产补口·偏差项）**：`_MODES` 补 AUTO 工具栏按钮（文本「SAM 全图」快捷键 G）——取证发现 W44 的 AUTO/AMG 通道在 GUI 零入口（`_SAM_MODES` 含 AUTO 但无按钮，`_sam_attach` AUTO 分支 UI 不可达），补齐是测试概念分割的前置。i18n 补 1 键。
- **FR-2 环境注入夹具**：`sam3_weights_env`（指向 weights/sam3，缺权重 skip）/`sam3_fake_env`（tmp 伪权重目录）——**参数序先于 ava_app**（W25 实例化序教训）；python 源码模式继承 pytest env 直通子进程。exe 模式整模块 skip（exe 无 SAM3 栈，走 ImportError 分支非本方案目标）。
- **FR-3 用例 T1 三模式一图流**：「交互式」点击→多边形提交；「SAM 区域」拖矩形+区域内点击→多边形提交；「SAM 笔刷」拖划→多边形提交；保存 LabelMe JSON 铁证（≥3 polygon、label=预设值、imagePath 为真 bmp）。
- **FR-4 用例 T2 概念分割**：label 输入框填概念词（极柱域实测有效的 `hole`）→「SAM 全图」→等「自动标注就绪」→点击画布→回车 drain→保存 JSON：shapes≥1、shape_type=polygon、label=="hole"。
- **FR-5 用例 T3 诚实失败路径**：伪权重目录 env→「交互式」→状态栏「SAM 加载失败」+窗口存活（无对话框、无崩溃）。
- **FR-6 断言口径**：沿用项目规约——状态栏文本+磁盘 JSON 铁证+UIA 树属性；控件未找到类失败消息含英文 "timeout"（flaky 路由）；等待量 generous（SAM3 冷加载实测 9.8-23s，取 120s）。

## 3. 验收标准（AC）

- AC-1：T1-T3 在源码模式（AVA_UIA_SOURCE=python）全绿；单跑命令留档 tasks 文档。
- AC-2：T1 JSON 铁证含三种 SAM 模式产出的 polygon（≥3 shapes、label 正确、imagePath 为极柱真 bmp）。
- AC-3：T2 JSON shapes≥1 且 label=="hole"（概念=极柱域真机实测有效词）。
- AC-4：T3 状态栏出现「SAM 加载失败」且主窗口仍存活。
- AC-5：全量主门禁零回归（1178 通过口径；AUTO 按钮新增不影响既有单测/UIA——旧 exe 不含该按钮，默认 exe 模式 UIA 套件不受影响）。

## 4. 范围

**In**：tests/uia/test_sam3_labeling.py（3 用例）、page.py `_MODES`+1 行、i18n +1 键、AUTO 入口单测（TDD RED 先行）、2 docs。
**Out**：exe 重打包与 exe 模式 SAM3 UIA（待打包波次）；SAM1(vit_b) 后端 UIA（本地无 vit_b 权重）；画布像素级断言（项目规约禁 screenshot 断言）。

## 5. 风险与假设（D1 三栏）

- 已知：AUTO 无 UI 入口（取证）→ FR-1 补口；交互预测在 UI 线程同步阻塞 ~1.5s/次（W46·A 实测）→ 点击后固定等待；机器负载 22 个用户态进程（微信/浏览器族）在档为 UIA 输入争抢风险带 → 等待加宽+失败按 flaky 分类路由不改断言。
- 假设：AUTO 点击后需回车 drain 队列（controller handle_commit 逐个取）；「添加标签」非 JSON 落盘前置（按极柱用例既有顺序照做，不依赖其语义）。
- 反目标：不改生产标注逻辑（仅加按钮）；不断言 SAM 掩码几何质量（单元测试已覆盖）；flaky 不许改断言硬凑绿。

## 6. 实现思路

复用 ava_app/pole_subset_dir/label 页既有驱动模式（打开文件夹→模式按钮→ctypes 鼠标流→_shape_count 增量→保存对话框→JSON 断言）；SAM 差异点仅三处：env 夹具先行、等待「SAM 已加载/自动标注就绪」、点击后留推理窗口。

## 7. 门禁裁决（自治降级留痕 · S1/S3）

| 门禁 | 裁决 |
|---|---|
| 探索门禁 | **S1**：用户指令锁定目标；三栏账见 §5，未知项（AUTO 入口缺失/机器负载）已转取证并闭环 |
| PRD 门禁 | **S3**：本文档留痕；**偏差裁决=FR-1 生产补口**（AUTO 按钮是 W44 意图的补全且为 FR-4 前置，加性可回退，exe 零影响）|
| 收尾门禁 | **S3**：AC 逐项回填 tasks + 主门禁结果；不自动 commit |
