# PRD：SAM3 集成到标注（W46 · lite）

## 定档声明（Step 0）

- 档位：🟡 **L2**（自治会话，`AskUserQuestion` 不可用——门禁按 S1 用户显式指令 / S3 自主留痕降级，见 §7）
- 确定性：低→高（取证后收敛）——SAM3 运行时形态已实证：venv transformers 5.12.1 内置 `Sam3Model/Sam3Processor`（sdpa 注意力，无需 flash-attn，torch 2.5.1 兼容）
- 影响半径：小-中——纯加性（新 adapter + 会话装配分支），不动存量 SAM1 代码路径；回归红线 = 现有全量测试绿
- 规模：中（约 300-450 行 / 5-7 文件 + 3.5GB 权重下载，权重不入库）
- 可逆性：双向门（git 回滚代码；权重目录可删）
- 依据：低确定 × 小影响 → L2；用户 S1 指令锁定目标「下载 SAM3 权重并集成到标注」

## 1. 背景与目标

项目标注页现有 SAM 交互基于 2023 年 `segment-anything`（SAM v1，vit_b）。Meta 于 2025-11 发布 SAM 3（文本概念 + 几何提示的可提示分割基础模型）。用户指令：从 ModelScope 镜像 `facebook/sam3` 下载权重并集成到项目标注。

**目标**：SAM3 作为标注页可选后端——文本概念全图分割（SAM3 招牌能力）+ 盒提示分割，与现有 SAM1 后端并存可切换。

## 2. 需求（FR）

- **FR-1 权重下载**：`scripts/download_sam3.py` 从 ModelScope 拉取 transformers 格式文件（config/processor/tokenizer/model.safetensors ≈3.5GB），排除本项目不用的原始 `sam3.pt`；产物落 `weights/sam3/`，`.gitignore` 覆盖 `*.safetensors`。
- **FR-2 Sam3Adapter**：`labeling/sam3_adapter.py` 提供 SamAdapter 同构鸭子方法面（`load/loaded/set_image/predict_point/predict_box/predict_point_in_box/predict_points/build_amg_detector`），延迟导入 transformers；无权重/未加载时诚实报错（对齐 super_cv2 的「不返假数据」惯例）。
- **FR-3 提示映射**（transformers 5.12.1 无 point 提示的诚实降级）：点击 → 以点为中心的小盒提示；笔刷多点 → 笔划点外包盒提示（`mask_input` logits 迭代不支持，忽略并在 docstring 声明）；盒/区域 → 直接盒提示；`REGION_SAM` 保留 W43 掩码∩矩形硬约束。
- **FR-4 文本概念自动标注**：`build_amg_detector(label=)` 语义升级——SAM3 后端时 label 即概念文本提示，`post_process_instance_segmentation` 全实例 → ε 折点多边形 Shape 队列（复用现有 AUTO 模式通道，controller 零改动）；沿用 W44 护栏（面积过滤 + max_masks 截断告警）。
- **FR-5 会话装配**：`SamSessionMixin._ensure_sam` 支持选 SAM3——`AVA_SAM3_DIR` 环境变量优先（测试/幂等路径），其次文件对话框可选中 `config.json`（父目录即模型目录，过滤器加 `*.json` 分支），未选则回落存量 SAM1 `.pth` 流程（行为不变）。
- **FR-6 测试**：Fake 后端单测（提示映射/多边形产出/护栏/未加载报错）+ 装配分支单测 + `AVA_SAM3_DIR` opt-in 真权重冒烟（对齐 AVA_SAM_CKPT 既有模式）；全量门禁回归绿。

## 3. 验收标准（AC）

- AC-1：`weights/sam3/` 四件必需文件齐备且 `git status` 不出现 safetensors（忽略生效）。
- AC-2：AVA_SAM3_DIR 设置时，AUTO 模式以 label 文本为概念提示产出 ≥1 个多边形 Shape（真权重冒烟，RTX 3060）；未设权重时相关单测全绿且不依赖网络。
- AC-3：四个 SAM 模式（I/J/B/AUTO）在 SAM3 后端下方法面可调，点击/盒/笔刷各产出多边形（Fake 单测断言 + 真权重抽查）。
- AC-4：存量行为零回归：不设 AVA_SAM3_DIR、不选 json 时，`_ensure_sam` 走原 SAM1 流程（既有测试不动即证）。
- AC-5：全量 pytest 门禁绿（基线 1150 通过口径，允许 +新增用例数）。

## 4. 范围

**In**：labeling/sam3_adapter.py、sam_session 装配分支、.gitignore 一行、scripts/download_sam3.py、tests 新文件。
**Out**：SAM1 存量路径的任何行为修改；settings 页 UI 配置项（v1 用环境变量 + 对话框分支）；视频分割/训练；exe 重打包（留待用户验收后另行打包波次）。

## 5. 风险与假设（含 D1 三栏）

- 已知：transformers Sam3 无 point 提示（grep 实证）→ FR-3 降级方案；3.44GB 权重 fp32 于 12GB VRAM 推理可行（假设，冒烟验证；不足则 `.half()` 或文档标注）。
- 假设：ModelScope 镜像与 HF 仓库文件一致（sha256 由 modelscope 客户端校验）；点击延迟约 0.5-2s/次（无独立 embedding 缓存 API，每次前向全图编码——W21 快路径在 SAM3 后端退化为 ndarray 引用缓存，预热量级同推理）。
- 反目标（D3）：不破坏 1150 存量测试；不硬升 torch/transformers（零依赖变更）；权重不入 git；错误不静默（对齐「诚实回退」惯例）。
- 风险：i18n 新键漏配触发 W44 变量键守卫 → 新增状态文案同步入 zh_CN/en_US 词表；modelscope 装入 venv 造成 lock↔freeze 漂移（W19 教训）→ 若存在漂移守卫则同步补 lock 行。

## 6. 实现思路

后端鸭子类型替换（modes 层 `sam_adapter: Any` 均不感知后端差异）+ 会话装配点单分支选择。SAM3 推理封装为 `torch.inference_mode()` + `attn_implementation` 默认 sdpa。多边形产出复用 `simplify_polyline(ε=2.0)` + `cv2.findContours` 既有管线（与 SamAdapter 逐方法对齐）。

## 7. 门禁裁决（自治降级留痕 · S1/S3）

| 门禁 | 正常形态 | 本会话裁决 |
|---|---|---|
| 探索门禁 | AskUserQuestion 三栏确认 | **S1**：用户指令已锁定「下载+集成到标注」目标与数据源；三栏账见 §5，未知项已转研究动作并闭环（ModelScope 清单实证、transformers API 实证、point 缺失实证）→ 放行 |
| PRD 门禁 | AskUserQuestion 确认 PRD | **S3**：本文档即留痕；变体选择裁决=只下 transformers 格式（项目已有 transformers 5.12.1，零新运行时依赖；官方 sam3 包需 flash-attn 且 Windows 不支持） |
| 收尾门禁 | AskUserQuestion 收尾确认 | **S3**：AC 逐项核验 + 全量门禁结果于 tasks 文档回填；不自动 commit（执行铁律 7） |
