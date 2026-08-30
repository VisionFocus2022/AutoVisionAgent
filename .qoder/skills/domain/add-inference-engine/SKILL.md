---
name: add-inference-engine
description: 新增或更换推理引擎/检测后端（YOLO/SAM/自研模型接入）。当需求要接入新模型后端做推理或标注辅助时使用。
---

# add-inference-engine：新增推理引擎

> 原子范围：一个引擎后端，从注册到 GUI 接线到引擎族测试。

## 标准动线（按序执行，引用先例）

1. **能力边界先取证**：接入新后端先 grep 本地 site-packages 的 processor/model 签名定能力（W46：transformers SAM3 无 point 提示→点转小盒代偿）；别信 README 印象
2. **可选依赖门控**：try-import + 诚实报"未安装"（R01 §1.3）；依赖入 requirements 双文件
3. **契约缝注入**：优先走既有缝——标注辅助走 `AutoLabeler.set_detector`（W44 AMG 先例）；推理走 `inference/` 引擎注册表 + `training/` 训练侧；不新建平行管线
4. **引擎族测试**：对齐 `tests/test_engines_family_deep.py`/`test_engine_*` 族契约；未装依赖的门控路径测"诚实拒绝"
5. **GUI 接线**：predict 页设备/精度解析读 user_settings（R03 §2）；`AVA_UIA_MODEL` 可指权重
6. **权重与配置**：权重文件 gitignore（`*.pt/*.pth/*.safetensors`）；下载脚本入 `scripts/`（先例 `download_sam3.py`，ModelScope 免 gate 直查文件清单）
7. **门禁**：`bash scripts/check-gate.sh`；真机推理跑 `scripts/eval_*.py` 留数字

## 已知陷阱

- 概念词贴域：物理特征词 > 物体名 > 抽象词；分数阈值 0.3 起步再用 GT 对照校准（W46/W47：高分实例≠GT 命中）
- 推理分辨率=训练分辨率（W50：1280 训练 1600 推理反降）
- 训练类引擎先查"推理选实例用哪个分数"再动损失头（W48 objectness 压塌负结果）

## 自检

- [ ] 未装依赖路径诚实拒绝（有测试）
- [ ] 引擎族契约测试绿；权重不入库
- [ ] GT 对照或标注口径验收数字留档
