---
trigger: glob
glob: "{pyproject.toml,requirements*.txt,autovisionagent.spec,.github/workflows/*,scripts/make_lite_dist.py}"
description: 模块依赖与构建发布约束。修改依赖文件、PyInstaller spec、CI 工作流、打包脚本时必须遵守
---

# R01 模块与构建发布约束

> 覆盖域：模块与依赖（域1）+ 构建与发布（域7）

## 1. 模块依赖（L0/L1）

1. **[L0] 依赖方向单向不可逆**：`gui → labeling/training/inference/exporter/evaluation → core`；`serving` 为独立对外层，只经 proto 契约消费 core；禁止任何反向或跨层依赖（grep 实证现状：gui 5 文件 import labeling、labeling/training import core）
2. **[L1] 依赖双文件制**：新增依赖先入 `requirements.txt`（带用途注释，可选项注释声明），再以钉死版本刷入 `requirements.lock.txt`；安装一律 `pip install -r requirements.lock.txt`（首行含 cu121 索引）
3. **[L1] 可选引擎 ImportError 门控**：ultralytics/transformers/anomalib/segment_anything 等可选依赖，引入处必须 try-import + 诚实报"未安装"（`core/config.py` 同款 fail-honest 语义），禁止裸 import 崩进程
4. **[L1] 新模块五方注册**：新增 python 包/子模块时检查连锁面——pytest.ini `--cov` 分母、`pyproject.toml` isort known-first-party、`autovisionagent.spec` hiddenimports、pyproject/mypy exclude、测试 import 面（W43 五方守卫连锁实证）

## 2. 构建命令（L1）

| 动作 | 唯一入口 | 禁止 |
|---|---|---|
| 主门禁 | `.venv/Scripts/python.exe -m pytest` | 手拼绕过覆盖率参数的"等价"命令 |
| L0 聚合门禁 | `bash scripts/check-gate.sh` | 只跑 ruff 不跑 pytest 就宣称完成 |
| 单测快跑 | `.venv/Scripts/python.exe -m pytest tests/test_x.py -o addopts= -q` | 用快跑结论冒充门禁结论 |
| 打包 | `.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm` | 改用裸 pyinstaller CLI 参数拼装 |
| lite 派生 | `.venv/Scripts/python.exe scripts/make_lite_dist.py` | 手工删 dist 内 DLL 造 lite |
| C# 客户端 | `dotnet test serving/dotnet_client` | 跳过（CI 有独立 job） |

> **打包环境机械防呆（2026-08 架构审查 AVA-R1 / P1-1）**：`autovisionagent.spec` 头部内建双断言——① 解释器必须是 spec 同级 `.venv`；② torch/torchvision/numpy/cv2/PySide6 可导入。错误环境立即 `[BUILD-ABORT]` 退出（退出码 1）。上表"打包"行的文档约束由此升级为机械强制；守卫测试（test_w26/test_dynamic_import_guard）对 spec 仅 AST 解析不受影响。

## 3. 打包与发布（L0/L1）

1. **[L0] lite 体积棘轮**：`dist-lite` 产物 <2GiB（`tests/test_w19_lite_dist.py` 守卫）；只升不降，升线前先减重
2. **[L1] spec 变更走守卫**：改 `autovisionagent.spec` hiddenimports 后必须全量重打包 + UIA 抽验（发版检查单 `docs/release-checklist.md`）
3. **[L1] 双远端**：gitee + github 两个 remote，推送须双发（github 443 间歇阻断时先落 gitee 并留档待追平）
4. **[L2] 发版宣称核销**：RELEASES.md 的宣称逐条三态核销（兑现/部分/证伪），W37 教训

## 4. 自检清单

- [ ] `bash scripts/check-gate.sh` 通过（命名 + ruff 棘轮 + 主门禁）
- [ ] 新依赖已双文件登记且可选依赖有门控
- [ ] 新模块五方注册齐备
