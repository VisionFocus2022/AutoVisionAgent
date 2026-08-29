# PRD：W46·B 遗留三项清偿（lite）

## 定档声明

- 档位：🟡 **L2**（自治会话，S1 用户指令「继续实施 遗留三项」+ S3 留痕）
- 确定性：高 — 三项修法已在 [tasks-uia-sam-labeling.md](tasks-uia-sam-labeling.md) 留档实证
- 影响半径：中 — ①6 文件夹具排序 ②共享 helper 语义（全体 UIA 消费）③spec+重打包（产物级）；不触硬触发器
- 规模：中（~150-250 行 / 10+ 文件 + 一次重打包）；可逆性：双向门
- 覆盖留痕：执行结束不自动 commit（本次指令未授权提交）

## 1. 背景与目标

W46·B 收官时留档三项：①usefixtures 抢跑陷阱的存量扩散面（6 文件 11 处）②`enter_path_in_open_dialog` 假 True 语义 ③exe 未打包 SAM3 栈致 UIA 模块级 skip。取证新发现：**full exe 已含 transformers/sam3/clip/tokenizers 源码树（41M，历史依赖链捎带），lite 同样在预算内含全栈** → 第三项收敛为「补 1 个 hiddenimport + 重打包」。

## 2. 需求（FR）

- **FR-1**：6 个既有 UIA 文件移除「签名已含 ava_app」的冗余 `usefixtures("ava_app")` 标记（AST 核实 11 处全部此型，无「仅标记」型须保留）——签名顺序接管实例化序。
- **FR-2**：`enter_path_in_open_dialog` 语义收紧——True 仅当「对话框确认且已消失」（最终 `_wait_dialog_gone` 结果不再丢弃）；文档字符串声明契约；调用方（4 文件 11 处，全以 assert 消费）无需改动。
- **FR-3**：spec hiddenimports 补 `labeling.sam3_adapter`；全量重打包 + lite 重派生；`test_sam3_labeling.py` 模块级 skip 改为「exe 缺 sam3 栈才 skip」（探测 `_internal/transformers/models/sam3`）；配套 PYZ/打包守卫若计数硬编码则同步。
- **FR-4**：验证——主门禁全绿 + 全量 UIA（exe 模式，15 用例）跑通。

## 3. 验收标准（AC）

- AC-1：`grep usefixtures("ava_app") tests/uia/test_*.py` 仅余 sam3/user_mgmt 的 0 处（11 处全清）。
- AC-2：假 True 语义收紧后既有套件不因语义变化误红（对话框真卡时以清晰早败替代下游混淆）。
- AC-3：exe 模式下 SAM3 三用例可运行（T3 伪权重 → 「SAM 加载失败」即证 `labeling.sam3_adapter` 已入 PYZ）；lite 重派生守卫绿。
- AC-4：主门禁 1182+ 绿；全量 UIA exe 模式零回归（既有 12 用例 + sam3 3 用例）。

## 4. 范围

**In**：上述三文件域 + spec + 守卫计数 + 文档。**Out**：transformers 版本管理、lite 剪枝（不需要——现预算已含）、权重分发机制（AVA_SAM3_DIR 契约不变）。

## 5. 风险与假设（三栏）

- 已知：transformers/sam3/tokenizers/safetensors 已在 full+lite 包内（du 实证）；exe 分支 env 透传（conftest 实证）；构建仅 ~3.3 分钟（build_w46.log 实证）。
- 假设：移除标记后无既有用例依赖旧序（若有即暴露潜伏排序 bug，按发现处理）；PYZ 守卫计数可同步。
- 反目标：不弱化任何断言；lite 不超 2GiB 预算；重打包失败即回滚 spec 改动并汇报。

## 6. 实现思路

T1 纯删标记（AST 已核型）；T2 单点改 uia_helpers 返回契约；T3 spec 一行 + `pyinstaller autovisionagent.spec --noconfirm` + `make_lite_dist.py` + skip 探测器；最后 exe 模式全量 UIA 一次收官。

## 7. 门禁裁决（S1/S3 留痕）

| 门禁 | 裁决 |
|---|---|
| 探索 | **S1**：用户指令锁定三项；三栏未知项已全部转取证并闭环（tokenizers/lite/env/构建时长四路实证） |
| PRD | **S3**：本文档即留痕 |
| 收尾 | **S3**：AC 回填 + 全量门禁结果；不自动 commit |
