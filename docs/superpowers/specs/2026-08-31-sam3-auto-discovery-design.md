# SAM3 权重约定目录自动发现（设计）

- 日期：2026-08-31
- 状态：已获用户批准（方案 A）
- 来源：用户实测反馈——标注页 SAM 模式弹"选择 SAM 权重"窗，虽仓库
  `weights/sam3/` 已有完整权重仍需手动导航

## 1. 问题

`sam_session._ensure_sam` 仅认 `AVA_SAM3_DIR` 环境变量；未设时直接弹权重
选择对话框。普通用户不设环境变量，`weights/sam3/`（config.json +
model.safetensors 完整）形同虚设。

## 2. 目标行为

优先级（高→低）：

1. `AVA_SAM3_DIR` 指向有效目录 → 加载之（语义不变；可指向 sam3-pole-ft
   等任意微调目录）
2. **约定目录 `WEIGHTS_DIR / "sam3"`**（源码=仓库根/weights，exe=
   _internal/weights）含 config.json + model.safetensors → **静默加载**
3. 均无 → 现有弹窗（可选 .pth 走 SAM1 / config.json 走 SAM3，兜底不变）

明确不做（YAGNI）：
- 不扫描通配子目录（sam3-pole-ft 等微调版经 env 显式指定）
- 不自动下载、不内置算法回退
- SAM1 .pth 无约定发现（weights/ 无 .pth 事实）
- UI 状态文案不变（"交互式标注就绪"等，不破坏既有 UIA 断言）

## 3. 变更清单

| 文件 | 变更 |
|------|------|
| `core/constants.py` | 加公开常量 `WEIGHTS_DIR = _PROJECT_ROOT / "weights"`（含 __all__ 登记） |
| `gui/pages/label/sam_session.py` | `resolve_sam3_model_dir` 增第三参 `conventional_dir: str \| Path \| None = None`；**判断顺序 env → conventional → picked**（参数序保持 env/picked 原位不动，避免破坏既有调用可读性；conventional 逻辑插在两判断之间）；`_ensure_sam` 两处调用传入 `WEIGHTS_DIR / "sam3"`，并在自动命中时 `logger.info` 来源 |
| `tests/test_sam_wiring.py`（或同族） | 单测：三级优先级、conventional 缺 config.json/缺 safetensors → 跳过、env 覆盖 conventional |
| `tests/uia/test_sam3_labeling_deep.py` | 新用例 `test_sam3_auto_discovery_no_env`：unset AVA_SAM3_DIR → 点交互式 → 直接"交互式标注就绪"（用户实测场景的真窗铁证） |

## 4. 关键设计点

- **纯函数扩展**：发现逻辑收在 `resolve_sam3_model_dir`（W46 起即纯函数，
  可单测）；UI 层只传参。
- **有效性判定复用**：conventional 命中条件 = `Path(dir).is_dir()` 且
  config.json + model.safetensors 在场（与 picked 分支同款），判定代码
  提取私有 helper `_is_sam3_dir(p)` 避免三处复制。
- **exe 路径天然正确**：`_PROJECT_ROOT` 在 frozen 下指向 `_internal`，
  与 CONFIG_DIR 同基准；将来权重随包分发（_internal/weights/sam3）即被
  发现，无需再改。
- **诚实日志**：自动命中记 `logger.info("SAM3 权重自动发现: %s", dir)`；
  状态栏不加新文案（保持 UIA 断言面稳定）。

## 5. 测试与验收

- 单测（快速）：`resolve_sam3_model_dir` 三优先级矩阵（env×conv×picked
  的有效/无效组合，≥6 例）
- UIA 新用例：unset env + 真 weights/sam3 在场 → 交互式直接就绪 + 点击
  提交产 polygon（复用 deep 文件既有原语）
- 回归：既有 `test_sam3_labeling.py` 3 用例（env 注入路径）不红；
  主门禁全绿

## 6. 风险

- 多候选歧义已排除（只认精确名 `sam3`）
- exe 模式 _internal/weights 当前不存在 → 自然落弹窗，行为与今天一致
  （无回归风险）

---
*未 commit（待用户指示）。实施计划转 writing-plans。*
