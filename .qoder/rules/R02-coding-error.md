---
trigger: model_decision
description: 编码、错误处理与日志约束。编写或修改业务代码、异常、日志、审计、i18n 文案时必须遵守
---

# R02 编码与错误处理约束

> 覆盖域：编码与错误处理（域2）

## 1. 异常体系（L0/L1）

1. **[L1] 异常唯一字典**：所有自定义异常声明在 `core/exceptions.py`，继承 `AppError`，按模块分组，同步登记 `__all__`；带上下文的异常实现 `details` property（先例：`AnnotationIOError(path=)`、`InvalidShapeError(mode=)`）
2. **[L0] 异常不裸穿 UI**：Qt 槽/事件回调必须接住领域异常转用户可见提示——`InteractiveLabeler` 曾因 `save()` 的 except 元组漏 `InvalidShapeError` 致裸穿 Qt 槽崩窗口（W46 生产缺陷实证）
3. **[L1] 可预期失败不抛异常**：引擎未装/权重缺失/不支持的任务，走 `SupervisedEngineError`/`UnsupportedTaskError` 或返回明确错误态；fail-honest 拒绝优于静默落默认分支

## 2. 日志与审计（L0/L1）

1. **[L1] Logger 惯例**：模块级 `logger = logging.getLogger(__name__)`；文件日志由 `gui/main.setup_logging` 统一配置落 `logs/autovision.log`；测试态用 `AVA_LOG_DIR` 隔离（`core/audit_logger._resolve_audit_dir` 先例）
2. **[L1] 审计必打锚点**：登录/模型加载/训练/导出等关键操作必须走 `core.audit_logger.get_audit_logger()`——AUDIT 行即时进 autovision.log（jsonl 有 100 条缓冲不可锚，W49 结论）；新增关键操作时同步加审计测试锚点
3. **[L0] 不吞异常**：禁止 `except: pass` / 裸 except 静默吞；确需降级时 log warning + 明确返回值
4. **[L1] 日志不进守卫区**：跑批/长命令输出落 `%TEMP%` 或 `.workflow/`，永不落 `logs/`（W23 隔离守卫会红）

## 3. i18n（L1）

1. **[L1] zh/en 双键同步**：新增 UI 文案必须同时登记 zh/en 字典，键数守卫 `Strings_ZhEn_KeySets_PairUp_WithExpectedCount` 计数 +N 同步断言
2. **[L1] 变量键盲区自查**：经 `tr(label_key)` 变量传入的键（如模式标签）是字面量守卫的永久盲区——新键直接入字典并对齐 `_MODES` 字面量表（W43/W44 结论：源码级枚举优于白名单）

## 4. 通用编码（L2）

- **[L2]** 类型标注新代码用 PEP 604/585 现代形态（`X | None`、`list[int]`）——存量 UP 债见 ruff 棘轮基线，只许降不许升
- **[L2]** 顶层 import 保持排序（I001）；确需运行时导入注明原因

## 5. 自检清单

- [ ] 新异常入 `core/exceptions.py#__all__`；UI 回调接住领域异常
- [ ] 关键操作有审计锚点；无裸 except
- [ ] 新文案 zh/en 双键 + 计数断言同步
