# PRD：W32 OCR 可选引擎（L2 · 精简）

> v1.0 · 2026-08-22 · 上游：计划 W32 节（已批准）· 档位 🟡L2（新任务类型 × 打包面）
> 门禁代偿同前。探索三栏：【已知】easyocr==1.7.2 已装/单 cv2 源/五方守卫需同步；【假设】lite 剪除 easyocr 后预算内（实证 1.984GiB ✓）；【未知】无

## FR
- FR-1 TaskType.OCR（proto 零改动：task 值字符串 "ocr"）
- FR-2 ocr_easyocr.py：模块级零 easyocr 依赖（注册零成本）；load/infer 惰性导入；缺库/缺权重诚实 raise（fetch_ocr_weights 指引）；quad→xyxy/labels=识别串/scores=逐行置信度/threshold 过滤；离线目录模式 download_enabled=False
- FR-3 scripts/fetch_ocr_weights.py：craft_mlt_25k+语种识别器下载 + sha256 manifest（离线优先平台显式供给）
- FR-4 lock 单 cv2 provider 守卫（easyocr 元数据拉 headless 的 v1.x 血泪防复发）
- FR-5 GUI：TASK_LABELS+predict 自动在列（only_available）；训练页 exclude=(OCR,)（推理-only）；i18n
- FR-6 spec hiddenimports + engines 列表（五方守卫同步）；lite 派生剪除 easyocr（推理-only 可选件不占 2GiB，lite 内 load 诚实报指引）

## AC
注册零依赖 ✓ 缺库/缺权重诚实 raise ✓ 文本行映射+阈值过滤 ✓ lock 单源 ✓ 训练页排除+推理页在列 ✓ PYZ 含 easyocr（12456 模块/18 子模块）✓ lite 1.984GiB 无 easyocr ✓ 守卫 30/30 ✓
## 范围外：真机 OCR 端到端（需联网取权重——用户环境 fetch 后可用）；OCR 训练（明确不支持）
