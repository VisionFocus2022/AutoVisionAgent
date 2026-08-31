# spec 打包环境机械防呆（架构审查 AVA-R1 / remediation P1-1 落地）
- 日期: 2026-08-31
- 类型: rule
- 执行者: 主对话（architecture-visualization:risk-quality-reviewer 审查 → remediation-plan P1-1 实施）
- 等级: L1

## 变更内容

`autovisionagent.spec` 头部新增构建期双断言，把 R01 §2"打包唯一入口"从文档约束升级为机械强制：

1. **解释器断言**：`sys.prefix`（resolve 后）必须等于 `SPECPATH/.venv`；不匹配立即 `SystemExit`，错误信息含 current/expected 路径与 R01 正确入口命令。
2. **核心依赖探针**：torch / torchvision / numpy / cv2 / PySide6 逐个 `__import__`，任一 ImportError 即中止（防 .venv 被裁剪或依赖未装全的环境漂移）。

**动机（AVA-R1）**：2026-08 架构审查实证——错误 venv（缺 torch 重依赖）仍能打出"GUI 可启动、推理训练全不可用"的残废 exe（3.5MB 假产物），且因 GUI 正常而晚发现。本次为根因性防呆，非个案修复。

同步修改：
- spec docstring 的构建命令更正为 R01 唯一入口（原 `pyinstaller autovisionagent.spec` 正是误导源之一）。
- `.qoder/rules/R01-module-build.md` §2 表下方登记防呆说明。

## 涉及文件

- `autovisionagent.spec`（断言块 + docstring）
- `.qoder/rules/R01-module-build.md`（§2 登记）
- `docs/architecture-review/remediation-plan.md`（P1-1 验收勾选，随验证完成同步）

## 验证结果

- **负向（错误解释器）**：`python -m PyInstaller autovisionagent.spec --noconfirm`（系统 Python39）→ ~0.2s 内 `[BUILD-ABORT] interpreter is not project venv`，退出码 1，未进入 Analysis ✅
- **spec AST 守卫不受影响**：`tests/test_w26_spec_packaging.py tests/test_dynamic_import_guard.py` → 14 passed ✅（守卫仅 AST 解析不 exec，CI setup-python 场景同理安全）
- **正向（.venv 全量重打包）**：`.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm` → 断言放行，PYZ→PKG→EXE→COLLECT 全链路成功（~5.9min），exe 84.3MB（符合 ~80MB 基线）、dist 6.36GiB ✅
- 命名合规：本记录 `20260831_rule_spec-build-env-guard.md` 符合 R00 `{YYYYMMDD}_{类型}_{主题}` 模式；无资产新增/改名/删除，AGENTS.md §3 索引表无需变更
- 命名偏离说明：编辑工具按小写路径写入，曾致盘上 `R01-module-build.md` 变为 `r01-module-build.md`（Windows 大小写不敏感，git 照常显示 M），check-naming 段红灯擒获；已两步改名恢复大写并复跑 `[PASS]`。教训：编辑 .qoder 资产后若有大小写疑义，跑 `bash scripts/check-naming.sh` 兜底
