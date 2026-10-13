# AutoVisionAgent 审查硬约束（AI 审查必读上下文）

> 本文件是 ai-review.sh 的固定前言，AI 代入以下项目硬约束后再审 diff。

- **运行环境**：Windows 优先（GBK 默认编码陷阱、文件句柄释放顺序影响 rmtree、260 字符长路径）；中文/空格仓库路径。
- **PySide6 主线程契约**：>100ms 耗时操作（推理/IO/训练）必须在 worker 线程；worker→UI 只能走信号/invoke_main 回投，禁止跨线程直接 setXxx；异步回调需校验陈旧结果（换图/切页后丢弃旧结果）；忙态拒收而非回落同步。
- **PyTorch 双产物约定**：CUDA 不可用必须可回退 CPU（禁裸 .cuda()/.to("cuda")，走统一 device 决策）；大模型卸载三步 `del model` + `torch.cuda.empty_cache()` + 引用置 None；推理包 no_grad/inference_mode；frozen（打包 exe）态 DataLoader workers=0 守卫不可破坏。
- **提交纪律**：feat+test 成对；测试 RED→GREEN（先证伪再实现）；删除功能时守护用例、__all__、i18n 键、行数守卫（page.py 800）同批更新。
- **单一真源**：pytest.ini（覆盖率门禁）、coverage_floors.py（per-package 地板）、ruff-baseline.txt（=0）、requirements.lock.txt（依赖）——审查中发现"开第二份配置"即报。
- **历史判例**（同类问题必查）：W55 SAM 同步推理冻 UI 1.4s；W58 卸载 SAM 释放 4GB 显存 + GBK PIPE 编码；W2-4 孤儿控件；W54 ruff 基线归零假红（"All checks passed!" 行计入 wc -l）；W64 dist 重建丢权重。
