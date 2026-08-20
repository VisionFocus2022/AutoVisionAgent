# AutoVisionAgent 2.0.0

工业视觉智能平台——面向工业质检场景的一站式视觉工作站：数据/标注管理、模型训练、评估、推理与部署，配套 PySide6 桌面 GUI（后端 PyTorch）。

## 环境要求

- Windows（下文命令均以 `.venv/Scripts/...` 为准；Linux/macOS 对应 `.venv/bin/...`）
- Python 3.10+（`pyproject.toml` 中 `requires-python = ">=3.10"`）
- 依赖以 `requirements.lock.txt` 锁定安装（首行 `--extra-index-url https://download.pytorch.org/whl/cu121` 指向 CUDA 121 版 PyTorch 轮子源）

## 最小启动路径

```bash
git clone <repo-url>
cd AutoVisionAgent
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock.txt
.venv/Scripts/python -m pytest
```

注意：全量 `pytest` 自带覆盖率门禁（`--cov-fail-under=92`，配置见 `pytest.ini`，分母含 core/gui 等 12 个包），覆盖率不足时整体失败。只跑单个测试文件时可用 `-o addopts=` 清掉覆盖率参数快跑：

```bash
.venv/Scripts/python -m pytest tests/test_xxx.py -o addopts= -q
```

## 桌面应用

```bash
.venv/Scripts/python -m gui.main
```

打包发布（PyInstaller exe）流程与检查单见 [docs/release-checklist.md](docs/release-checklist.md)。

## 测试

- 单元/集成测试位于 `tests/`（pytest，随全量门禁运行）。
- UIA 真窗自动化测试（需桌面会话 + 打包 exe，pytest 默认排除）方案与运行方式见 [docs/uia-test-plan-full-coverage.md](docs/uia-test-plan-full-coverage.md)。

## 架构文档

- 权威版（v4）：[docs/AutoVisionAgent-架构解析与优化方案-v4.md](docs/AutoVisionAgent-架构解析与优化方案-v4.md)
- 历史版（v3）：[docs/AutoVisionAgent-架构解析与优化方案-v3.md](docs/AutoVisionAgent-架构解析与优化方案-v3.md)
- 历史版（v2）：[docs/AutoVisionAgent-架构解析与优化方案-v2.md](docs/AutoVisionAgent-架构解析与优化方案-v2.md)
- 历史版（v1）：[docs/AutoVisionAgent-架构解析与优化方案.md](docs/AutoVisionAgent-架构解析与优化方案.md)
