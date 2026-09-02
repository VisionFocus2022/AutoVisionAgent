# SKolpha 能力复刻立项 — 需求规格说明书 (PRD)

> 版本: 1.0 | 日期: 2026-09-02 | 状态: 评审中（待用户门禁 4 裁决开工） | 档位: 🔴 L3 | 确定性: 低（三处能力仅符号级取证证据） | 影响半径: 大（标注枚举/TrainConfig/project schema/多页面联动；lite 2GiB 预算约束）
> **门禁偏差（自治留痕）**：本会话无 AskUserQuestion → 探索门禁=S1 用户显式指令（「把所有能力（如操作标注/切割线形态、批量预测线程模式）立项复刻进 AVA」）；PRD/Design 门禁=S3 自主留痕（本文档即出示物，docs 落盘可回滚）；**门禁 4（开始编码）=停点，不降级**——待用户裁决。
> 前置：SKolpha 3.3.2 全功能取证已完成闭环（docs/skolpha-forensics-wave1.md + wave2.md + prd/tasks-skolpha-full-forensics.md，Fernet 密钥已实证破解）。

---

## 1. 概述

### 1.1 项目背景

- 对标品 SKolpha 3.3.2（S-Sigma 三星定制版工业缺陷检测训练平台）已完成两波函数级取证：8 大任务模块×六步工作流、双训练引擎、Fernet 加密全破（密钥 `urlsafe_b64encode("SAMSUN"*5+"CN")`，default.yaml/TrainConfigs/.spro 工程文件均可解密）。
- AVA v2.0 现状核验（2026-09-02，代码级证据）：**任务引擎面已全覆盖**——`models/supervised/engines/` 注册 det_yolo/cls_torchvision/seg_yolo/pseg_yolo/pose_yolo/sseg_smp/abdet_anomalib/sgan_blend/super_cv2/ocr_easyocr 共 10 引擎；批量推理已有取消/进度/统计报表/JSON 原子落盘/RLE 产物（gui/pages/predict/page.py:452-508、workers.py:110）；项目系统有 FileSystemProjectStore+TaskCounter+versioning（gui/pages/project/page.py:50-58）。
- **真实差距**（逐项对照 wave1/wave2 功能全图后收敛为 8 项，见 §1.2 与 §6.0）：工业标注形态、任务级训练模板参数化、工程参数绑定、数据工具集、批量预测模式、API 推理路径、训练子进程隔离、超分训练。

### 1.2 目标

1. 补齐用户点名的工业标注形态：**切割线（cut_line_label 对标）+ 操作标注（operation_label 对标）**，与现有 5 形态并存成 7 形态。
2. 补齐**批量预测线程模式**（对标 batchPredictThread/batchPredictOnlyOne 双模式语义）。
3. 建立**任务级训练模板体系**（对标 TrainConfigs 30+ 参数模板，明文 YAML，不加密）。
4. 补齐**工程参数绑定**（对标 .spro schema 五段中 AVA 缺的三段语义）与 **S_Tools 数据工具集**。
5. 每波落地后主门禁 rc=0（fail-under 92 不动）、lite <2GiB、W24 规模守卫绿。

### 1.3 术语表

| 术语 | 定义 |
|------|------|
| SKolpha | S-Sigma 三星定制版工业缺陷检测训练平台（对标品，E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18） |
| 六步工作流 | 项目管理→数据管理→模型训练→模型评估→模型发布→模型预测（SKolpha chm 手册口径） |
| 切割线（cut_line） | SKolpha 标注 7 形态之一，推断为折线/切割路径形态〔🔎符号级证据 @0x3d52001-0x3d5205b，交互语义待实机核对〕 |
| 操作标注（operation） | SKolpha 标注 7 形态之一，推断为操作区域+操作名形态〔🔎同上〕 |
| 训练模板 | SKolpha TrainConfigs 按 9 任务码分文件、含 30+ `my_*` 前缀参数（img_scale/split=0.8/data_expansion/max_rotate/translate/flip 等）的参数化配置；AVA 侧复刻为明文 YAML |
| transferType | SKolpha 工程 dataInfo 字段，取值 Rect/Polygon，与标注形态联动 |

---

## 2. 角色与用户画像

### 2.1 目标用户

| 角色 | 描述 | 使用场景 | 技术水平 |
|------|------|----------|----------|
| 视觉工程师（用户本人） | AVA 维护者 | 按六步工作流打样工业项目；配置训练模板 | 高级 |
| 工厂标注员 | 最终使用者 | 用切割线/操作标注标注产线图像 | 初级 |

### 2.2 用户旅程（新增形态示例）

1. 标注员打开 label 页载入产线图 → 按 `C` 进入切割线模式 → 逐点绘制切割路径 → 右键提交。
2. 按 `O` 进入操作标注模式 → 框选操作区域并输入操作名 → 提交。
3. 保存 LabelMe JSON → 重开文件，两种形态与属性完整往返。

---

## 3. 功能需求 (Functional Requirements)

### 3.1 核心功能

**FR-001: 切割线标注形态**（对标 cut_line_label）| P0
- **描述**: 新增折线标注模式 CUT_LINE：左键逐点添加（≥2 点），右键/回车提交；支持 EDIT 模式顶点拖拽微调；画布渲染为醒目虚线（与多边形实线区分）。
- **输入**: 鼠标点击序列。
- **输出**: Shape(mode=CUT_LINE)；io_labelme 落盘为 labelme 原生 `linestrip` 形态（跨工具互操作，见 Design §4.1 决策）。
- **规则**: 快捷键 `C`；单点不构成有效折线；与既有 5 形态并存（共 7）。
- **关联**: FR-002（共用落地链路）。

**FR-002: 操作标注形态**（对标 operation_label）| P0
- **描述**: 新增操作区域标注模式 OPERATION：矩形拖拽或≥3 点多边形区域 + 操作名作为标签（复用现有标签输入框语义）。
- **输入**: 拖拽矩形 / 多点区域；操作名文本。
- **输出**: Shape(mode=OPERATION)；io_labelme 落盘（矩形/多边形原生形态 + `operation: true` 属性字段往返，见 Design §4.1）。
- **规则**: 快捷键 `O`；标签名即操作名。
- **关联**: FR-001。

**FR-003: 批量预测线程模式**（对标 batchPredictThread/batchPredictOnlyOne）| P0
- **描述**: 预测页批量推理增加模式选项：①「逐张即时」模式（对标 batchPredictOnlyOne——推理一张即入表即落盘，队列中途可增删）；②线程并发选项（默认串行=现状稳定口径，可选并行 N≤4）。
- **输入**: 模式选择控件 + 并发数。
- **输出**: 行为同现状（取消/进度/统计/JSON 语义不回归）；并行模式结果按完成序入表、batch_results.json 仍按文件名序原子落盘。
- **规则**: 默认串行；并行仅 IO+后处理并行时须保持线程安全（见 Design §4.2）。
- **关联**: —。

**FR-004: 任务级训练模板体系**（对标 TrainConfigs 模板参数化）| P1
- **描述**: 建立 `configs/train_templates/{task}_{variant}.yaml` 明文模板（不加密——SKolpha 加密为反面教材，wave1 §5）；模板含任务级默认骨干/输入尺寸/增强参数 30+ 项（以解密后的 TrainConfigs 为初始值字典）；训练页增加模板选择器，选中后回填表单，可被 UI 覆盖。
- **输入**: 模板文件 + 用户表单覆盖。
- **输出**: TrainConfig（含新增 augmentation 段：hflip/vflip/rotate_max/translate/crop_scale/mean/std/split_ratio/data_expansion）。
- **规则**: ≥9 任务码×≥1 变体（normal/small/large 对标）；未知字段诚实告警；模板缺失回退内置默认。
- **关联**: FR-005。

**FR-005: 工程参数绑定三段**（对标 .spro schema）| P1
- **描述**: 项目记录补三段语义：①`predictionParams{modelFile, threshold}`——项目打开后预测页可一键带出模型+阈值；②`transferType: Rect|Polygon`——联动 label 页默认标注形态；③`dataPath`——项目数据目录记忆。
- **输入**: 项目页/预测页/label 页写入。
- **输出**: project store 持久化；旧工程文件缺新段时兼容读取（缺段=空默认，不报错）。
- **规则**: 不做 Fernet 加密（明文 JSON）；不做 deploymentParams 的 endpoint/apiKey 持久化进工程文件——apiKey 走环境变量/凭据文件（安全约束，见 §4.3）。
- **关联**: FR-004/FR-007。

**FR-006: 数据工具集首批**（对标 S_Tools）| P1
- **描述**: data_manage 页新增工具菜单三项纯函数工具：①标签统计（扫描 LabelMe JSON 汇总各类别数量/尺寸分布）；②标签替换（旧名→新名批量重写 JSON）；③标签删除（按名批量移除 shape 并清理空文件警示）。
- **输入**: 数据目录 + 参数。
- **输出**: 统计报表/批量改写结果（原子写、失败逐文件报告）。
- **规则**: 只处理 LabelMe JSON；改写前自动备份原文件到同级 `.bak`（防误操作）。
- **关联**: —。

**FR-007: HTTP API 推理路径**（对标 deploymentParams{endpoint,apiKey} + 推理三路）| P1
- **描述**: 预测页增加「远端 API」推理源：输入 endpoint URL（POST 图像→JSON boxes 契约），apiKey 经环境变量 `AVA_API_KEY` 或凭据文件注入，不入日志不硬编码。
- **输入**: endpoint + 图像。
- **输出**: 结果进表格/预览（与本地引擎同 UI 语义）；超时/断网/非 200 均诚实报错。
- **规则**: 轻量实现（requests + 显式契约校验）；gRPC serving 主路径不动。
- **关联**: FR-005。

**FR-008: 数据工具集次批**（裁剪数据集/照片尾缀修改/数据清洗）| P2 ✅ 2026-09-02 W60 落地（裁剪补图像侧瓦片配对；尾缀/清洗新实现，坏件隔离 _trash 可逆）
**FR-009: 训练子进程隔离评估与实施**（对标 multiprocessing 子进程训练）| P2 ⏸️ 2026-09-02 W60 评估结论=**缓办**：全仓零引擎实现 train_epoch（grep 证据），训练全部走 _SimStrategy 模拟——子进程隔离无真实负载可隔离；待首个引擎接入真实逐轮训练时随其落地（本条即 PRD「评估后决定实施与否」的裁决记录）。
**FR-010: 超分训练**（对标 super 训练模板）| P2 ⏸️ 2026-09-02 W60 评估结论=**缓办**：AVA super_cv2 推理-only（预训练 EDSR pb 权重已覆盖工业用法）；真训练需 torch trainer+引擎加载+导出兼容三件套，零新依赖约束下性价比为负——SKolpha 该能力依赖 mm 系（PRD §7.2 已明确不复刻）。

### 3.2 交互需求

- label 页工具栏新增「切割线 (C)」「操作标注 (O)」两按钮，i18n 双语（zh_CN/en_US）。
- 训练页新增「训练模板」下拉（任务码×变体），选择后状态栏提示模板名。
- 预测页新增「批量模式」选项组（逐张即时/整批完成）与「并发数」微调（1-4，默认 1）。
- data_manage 页新增「数据工具」按钮组，各工具弹参数对话框 + 执行进度 + 结果摘要。
- 异常文案示例：「模板字段无法识别：my_xxx（已忽略）」「远端推理失败：HTTP 503（请检查 endpoint 与服务状态）」「标签替换完成：重写 12 个文件，跳过 2 个（非 LabelMe JSON）」。

### 3.3 数据需求

- 标注 JSON：labelme 兼容，新形态映射见 Design §5.1。
- 训练模板 YAML：`configs/train_templates/`，schema 见 Design §5.2；**新增落盘文件须配 .gitignore 策略审查**（W24 模板规则：凭据类不入库）。
- project store：现 schema 加可选三段（向后兼容）。

---

## 4. 非功能需求 (NFR)

### 4.1 NFR-001 性能
| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 并行批量推理吞吐 | ≥串行基线（不劣化） | 同集 50 图 A/B 计时 |
| 模板加载耗时 | <100ms | 计时断言 |
| 新标注模式交互延迟 | 与多边形模式同量级（<16ms/事件） | 手测+现有 canvas 性能口径 |

### 4.2 NFR-002 兼容性
- 旧标注 JSON（5 形态）/旧 project 记录/旧训练预设**读取零破坏**；`AutoVisionAgent-lite` <2GiB 硬预算（新增均为纯 Python，无重依赖，预期零增量——仍须实测）。
- exe spec hiddenimports 同步新模块（W55 datas/防呆同型核查）。

### 4.3 NFR-003 安全
- 不复刻 Fernet 硬编码密钥加密（wave1 §5 明示反面教材）；apiKey 仅经环境变量/凭据文件，凭据文件入 .gitignore（吸取 configs/initial_credentials.txt 漏配教训 W23/W24）；日志与异常文案零密钥明文。

### 4.4 NFR-004 可用性
- 新形态学习成本：与现有多边形/矩形同交互范式（逐点/拖拽+右键提交）；i18n 双语齐全，无死键。

### 4.5 NFR-005 可维护性
- 页面文件 ≤800 行（W24 守卫）——predict/data_manage 已 784/792 行，**新动作一律外置 Mixin/子模块**（先例：video_super_actions.py）；新函数 ≤100 行带类型标注；每波守卫测试增量生长（FB-016）。

---

## 5. 验收标准 (AC)

### 5.1 功能验收
- **AC-001**: `AnnotationMode` 成员=7（POLYGON/RECTANGLE/INTERACTIVE/REGION_SAM/EDIT/CUT_LINE/OPERATION）；label 页工具栏按钮=7；快捷键 Q/R/I/J/E/C/O 各就位〔FR-001/002〕
- **AC-002**: 切割线与操作标注可创建→EDIT 顶点微调→保存→重开，形态/属性完整往返（io_labelme roundtrip 测试）〔FR-001/002〕
- **AC-003**: 批量预测两模式可用；取消/进度/统计/JSON 落盘语义不回归（既有测试全绿）；并行模式 batch_results.json 文件名序稳定〔FR-003〕
- **AC-004**: `configs/train_templates/` ≥9 任务码×≥1 变体；UI 选模板→表单回填→TrainConfig 反映 augmentation 段；模板为明文 YAML（grep 无 gAAAAA 密文形态）〔FR-004〕
- **AC-005**: 项目打开→预测页一键带出 modelFile/threshold；transferType 联动 label 默认形态；旧工程缺新段兼容读取（fixture：无新段旧工程）〔FR-005〕
- **AC-006**: 三数据工具 fixture 验证：统计数字正确/替换往返一致/删除后空文件有警示；改写有 .bak 备份〔FR-006〕
- **AC-007**: API 推理：mock server 契约通过→结果入表；超时/非 200/断网三分支诚实报错；日志与代码 grep 无 apiKey 硬编码〔FR-007〕
- **AC-008**: 主门禁全量绿（rc=0，fail-under=92）；W24 规模守卫绿；lite 派生绿且 <2GiB〔全局〕
- **AC-009**: i18n 双语键齐（无死键）；spec hiddenimports 含新模块；动态导入守卫绿〔全局〕
- **AC-010**: 动态核对 ≥2 处（SKolpha 实机：切割线/操作标注交互语义、批量预测模式语义）——用户配合项，静态先行不阻塞〔全局〕

### 5.2 质量验收
- [ ] ruff check 0 error；主门禁覆盖率 ≥92（fail-under 门禁）；80% 质量线以上（现基线 92.5%+，新模块应≥80%）
- [ ] 无 CRITICAL/HIGH 代码审查问题（code-reviewer 复核）
- [ ] 性能满足 §4.1（并行不劣化为硬门，其余记录健康度）

### 5.3 用户体验验收
- [ ] 中文界面表述清晰；错误提示含原因+下一步；新形态操作 ≤3 步上手

---

## 6. 约束与假设

### 6.0 需求探索三栏账（Phase 0 产出，自治留痕=S1 指令+S3 出示）

**真实任务**: 当按 SKolpha 六步工作流打样工业项目时，用户想要 AVA 补齐能力面缺口（工业标注形态/训练模板/工具集），以便自研工具完全替代对标品。
**反目标**: 本次明确不做——Fernet 加密复刻、PyQt5/labelme fork/S_Label 双标注器、mmcv/mmseg/mmdeploy/nncf 重依赖引入、StyleGAN3 训练（待裁决 D-2）、一次性全量 8 差距齐做。

| 已知（确证事实·带锚点） | 假设（待验证 · 不成立则…） | 未知（→待裁决/待查） |
|------------------|----------------------------|---------------------------|
| AVA 引擎 10 个全注册（`models/supervised/engines/` 目录：det/cls/seg/pseg/pose/sseg_smp/abdet_anomalib/sgan_blend/super_cv2/ocr_easyocr） | 切割线=折线、操作标注=区域+操作名〔仅有形态名锚点 @0x3d52001-0x3d5205b〕→ 若实机核对推翻，按新语义修订 FR-001/002 与 Design §4.1 | **D-1**「所有能力」复刻分级表（§3.1/§7.2）整体确认 |
| AVA 标注现 5 形态（docs/prd-labeling-mode-prune.md AC-001，2026-09-01 裁剪） | 批量线程模式差距=逐张即时+并发选项〔仅符号名 batchPredictThread/batchPredictOnlyOne @0x3cf05b0/0x3cf0503〕→ 若核对后 AVA 已等价，FR-003 降级为并发选项单点 | **D-2** StyleGAN3 生成式训练是否立项（建议：不立，sgan_blend 贴图融合已覆盖工业形态+FID/LPIPS 评估已有） |
| 批量预测已有取消/进度/统计/JSON/RLE 产物（gui/pages/predict/page.py:452-508、workers.py:110、batch_runner.py） | sseg_smp/abdet_anomalib 具备 train_epoch 真训练能力 → 若缺，FR-004 模板对应任务标注「推理-only」 | **D-3** 训练子进程隔离（FR-009）优先级（建议 P2 波次前置评估） |
| 训练预设仅 4 参数×4 档页面级（gui/pages/train/page.py:38-56 `_TRAIN_PRESETS`），无 augmentation 参数面 | TrainConfig 扩展段向后兼容（新增带默认值） → 若消费者破坏则五方消费方清单兜底（FB-005） | **D-4** 批量线程模式语义实机核对（AC-010 用户配合项） |
| SKolpha 侧 7 形态/schema 五段/21 训练函数/推理锚点全带 exe 偏移（wave1 §4-6、wave2 §1-4）；Fernet 密钥实证（wave1 §5） | lite 零增量 → 若实测超预算（新纯 Python 模块极小概率），走裁剪清单 | （未知栏剩余项均已有处置路径：D-1..D-4 + AC-010） |

### 6.1 技术约束
- Python 3.12 / PySide6；测试 pytest+coverage（fail-under=92）；lite 2GiB 硬预算（现余量 ~20MiB——**新增必须零重依赖**）。
- 禁止引入：mmcv/mmseg/mmdeploy/nncf/stylegan3（已有等价技术选型）；不引入新第三方包（FR-007 用既有 requests）。

### 6.2 业务约束
- 兼容既有：5 形态标注 JSON、project 记录、_TRAIN_PRESETS、UIA 12 用例、gRPC serving 与 C# 客户端契约。
- 波次节奏沿用 W 编号（下一波 W56 起）；每波结束主门禁绿才准入下一波。

### 6.3 假设条件
- 假设 SKolpha TrainConfigs 解密产物可作模板初值（已证可解密，wave1 §5）；否则内置文献值。
- 假设用户可配合 ≥1 次 SKolpha 实机动态核对（AC-010）；否则三处符号级语义维持推断级并留档。

---

## 7. 范围定义

### 7.1 本次范围 (In Scope)
- ✅ FR-001..007（P0×3 + P1×4）；FR-008/009/010 列入后续波次（P2）

### 7.2 明确排除 (Out of Scope)
- ❌ Fernet 加密及其任何形式复刻（反面教材）；PyQt5/Nuitka/labelme fork/S_Label/chm 体系；mm 系与 nncf 依赖栈（技术选型已定）；StyleGAN3 训练（待裁决 D-2，默认不立）；.spro 文件格式兼容/导入（不做跨工程文件迁移）；S_Tools 之「生成缺陷」（flaw_gen 页已有）与「缺陷样品分类」（createFlaw 待需求）

### 7.3 后续迭代 (Future Consideration)
- 🔮 SKolpha 工程文件 (.spro) 只读导入器（利用已破密钥，若用户需要迁移历史工程）；缺陷样品分类工具；超分训练

---

## 8. 依赖与风险

### 8.1 外部依赖
| 依赖项 | 类型 | 版本 | 影响 | 替代方案 |
|--------|------|------|------|----------|
| requests（既有） | 库 | lock 内版本 | FR-007 唯一新用到（已在依赖树） | 无需新增 |
| SKolpha 实机 | 本地软件 | 3.3.2 | AC-010 动态核对 | 静态推断级留档 |

### 8.2 风险评估
| 风险 | 可能性 | 影响 | 风险等级 | 缓解策略 |
|------|--------|------|----------|----------|
| 形态语义推断与原品不符 | 中 | 中 | 🟡 | AC-010 实机核对前置到 W56 验收；labelme linestrip 原生形态兜底跨工具互操作 |
| predict/data_manage 页面超 800 行守卫 | 高 | 低 | 🟡 | 新动作外置 Mixin/子模块（Design §4.2/4.5 硬约束） |
| 并行批量推理引入竞态（JSON 落盘/表格更新） | 中 | 高 | 🔴 | 默认串行；并行仅后处理层；原子写既有 temp+os.replace 复用；A/B 回归测试 |
| TrainConfig 扩展破坏五方消费方 | 低 | 中 | 🟡 | FB-005 五方清单核查（生产/单测/UIA/脚本/守卫）先行 |
| lite 体积预算超线 | 低 | 中 | 🟡 | 零重依赖约束+派生实测守卫（14 用例） |

### 8.3 对现有系统的影响
- 标注枚举扩展（非破坏性新增成员——与昨日裁剪方向相反但机制同链路，spec/i18n/守卫全同步）；训练页/预测页/数据页 UI 增量；project store 向后兼容读旧。

---

## 9. 需求追溯矩阵

| 需求编号 | 用户故事 | 验收标准 | 优先级 | 状态 |
|----------|----------|----------|--------|------|
| FR-001 | US-001 切割线标注 | AC-001/002/008/009/010 | P0 | 待实现 |
| FR-002 | US-002 操作标注 | AC-001/002/008/009/010 | P0 | 待实现 |
| FR-003 | US-003 批量预测模式 | AC-003/008 | P0 | 待实现 |
| FR-004 | US-004 训练模板 | AC-004/008/009 | P1 | 待实现 |
| FR-005 | US-005 工程绑定 | AC-005/008 | P1 | 待实现 |
| FR-006 | US-006 数据工具 | AC-006/008 | P1 | 待实现 |
| FR-007 | US-007 API 推理 | AC-007/008 | P1 | 待实现 |
| FR-008/009/010 | — | AC-008 | P2 | 后续波次 |
| NFR-001..005 | — | §5.2/AC-008 | P0/P1 | 待实现 |

---

## 10. 审批记录

| 角色 | 日期 | 决定 | 备注 |
|------|------|------|------|
| 用户 | 2026-09-02 | 探索方向已授权（S1 指令）；PRD 整体待门禁 4 一并裁决 | 待裁决项 D-1..D-4 见 §6.0 |

---

## 附录

### A. 参考资料
- docs/skolpha-forensics-wave1.md（功能全图+加密体系）；docs/skolpha-forensics-wave2.md（四主线函数级重建+复刻映射建议 §6）
- docs/prd-labeling-mode-prune.md（5 形态基线）；docs/prd-skolpha-full-forensics.md（取证闭环）

### B. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 1.0 | 2026-09-02 | 初始版本（L3 立项） | Claude |

---

## 自检（9 项）

- [x] **完整性**: 用户点名能力（操作标注/切割线/批量预测线程模式）→ FR-001/002/003 全挂编号；「所有能力」经 D1 剥假设后以差距矩阵 FR-001..010 收敛，逐条核对 §3
- [x] **无歧义**: 全文无「快速/友好/高效/灵活/强大」（grep 口径自检）
- [x] **可追溯**: FR↔AC 全挂（§9 矩阵）
- [x] **范围清晰**: §7 In/Out/Future 三列
- [x] **风险已识别**: §8.2 含技术（语义推断/竞态）、依赖（实机）、兼容（守卫/消费方）三类
- [x] **指标可量化**: §4.1 数值目标 + AC 均可判定（按钮数/grep/rc/lite 字节）
- [x] **假设已声明**: §6.0/§6.3 显式
- [x] **编号连续**: FR-001..010、AC-001..010、NFR-001..005 无跳号
- [x] **语言一致**: 中文

## ✅ 门禁（Phase 1 · 自治降级留痕）
- [x] 探索门禁 → S1 用户显式指令（立项+点名例证）；三栏账随本 PRD 落盘出示（§6.0），未知栏 4 项全部有处置路径（D-1..D-4 待裁决+AC-010 待核对，**未自行拍板**）
- [ ] PRD 门禁 → S3 自主留痕替代（本文档即出示物）；**用户复核翻案权保留**——与门禁 4（tasks 后开工裁决）合并披露
