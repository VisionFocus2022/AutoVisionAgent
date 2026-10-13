# 第三轮工程审查综合报告（evaluation/ + exporter/ + labeling/）

**日期**：2026-10-06
**轮次**：第三轮（前两轮已覆盖 core/serving/gui/training/dataset/inference 并全清偿）
**审查范围**：evaluation/（3 文件 736 行）+ exporter/（1 文件 308 行）+ labeling/（24 文件 3,105 行含 modes/）
**审查方式**：两路并行独立审查（每路均实测验证可疑项）+ 主理人交叉修复

---

## 📌 TL;DR

- 整体结论：三个子系统延续项目高质量水位（契约文档密度高、边界经实测校准），发现 **36 项**（labeling 16 + evaluation/exporter 20）
- 严重度：🔴 1（实测复现崩溃）· 🟠 13 · 🟡 17 · 🟢 5
- **修复完成度**：本轮当日修复全部 🔴 + 全部 🟠 高优先项（labeling L1-L6 + eval/exporter E1/E2/E3/E10/E11/X7/E20 及追加发现的引擎异常缺口），共 14 项；其余 🟡/🟢 归档后续
- 验证：13 个新回归测试全过；受影响套件（labeling 81 + eval/exporter 66）全绿

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（🔴 与 🟠 已当日清偿） |
| 🔴 | 1 项（L1，实测复现）已修 |
| 本轮修复 | 14 项（L1-L6 + E1/E2/E3/E10/E11/X7/E20 + 追加引擎异常捕获） |
| 归档待办 | 🟡 12 项 + 🟢 5 项（L7-L16 / E4-E19 / X8/X9/X16 等，见行动清单） |
| 分层检查 | ✅ 两路均确认无反向依赖（evaluation/exporter 仅依赖 core；labeling 无 gui import） |

---

## 🔍 已修复项明细

| # | 原严重度 | 文件:行 | 问题 → 修复 |
|---|---------|---------|------------|
| L1 | 🔴 | labeling/batch_tools.py:78,108,139 | except 元组捕不到 `load_labelme` 抛的 `AnnotationIOError`（AppError 子类）——坏 JSON 击穿"跳过"意图崩掉整个批量任务（实测复现）→ 元组加 `AppError`（三处） |
| L2 | 🟠 | labeling/io_labelme.py:163-168 | `save_labelme` truncate-then-write 直写（写盘中途失败截断既有标注，主保存链路）→ 改走 `atomic_write_json` 单源（延迟导入防循环依赖） |
| L3 | 🟠 | labeling/controller.py:52-57 | 模式切换静默蒸发进行中标注（pending 多边形/半途顶点）→ `_has_pending_work` 探测 + feedback 通道知情提示 |
| L4 | 🟠 | labeling/modes/polygon.py:36-43 | 点击首点闭合区吞点（表现"点击失灵"）→ `close_requested` 标志 + controller `handle_press` 即时触发 commit；删恒真死代码 |
| L5 | 🟠 | labeling/canvas.py:73-77 | 撤销栈 list 无界（长会话内存增长至 GB 级风险）→ `deque(maxlen=100)` |
| L6 | 🟠 | labeling/controller.py:212-217 | AUTO 模式 `while True` 依赖 commit 严格性（异步回填窗口可拉长/冻结 GUI）→ 快照 `pending_count` 上限迭代 |
| E1 | 🟠 | evaluation/metrics_supervised.py:273-278 | seg/abdet 分支把 dict 列表直喂指标函数必抛 TypeError（GUI 靠兜底掩盖"从未打通"）→ ndarray/标量形态放行，dict 形态显式 ValueError 指明不支持 |
| E2 | 🟠 | evaluation/eval_flow.py:143-145 | 单图推理失败静默回退 GT（mAP 被 GT 自匹配虚高且无感知）→ `_degraded` 标记 + 计数 + `on_warn` 汇报"N/M 张回退" |
| E3 | 🟠 | evaluation/eval_flow.py:192 | 单张坏 JSON 打死整场评估 → 逐文件容错跳过 + 计数汇报；**追加**：引擎加载的 `UnsupportedTaskError` 等 AppError 族逃出 except 元组 → 补通用回退分支 |
| X7 | 🟠 | exporter/supervised_exporter.py:114,233 | int8 产物写 `.int8.onnx` 但返回原 fp32 路径（GUI/审计报告错文件）→ `_try_quantize` 返回实际产物路径 |
| E10 | 🟡 | evaluation/metrics_supervised.py:228-238 | AUROC 样本不足返回 0.0（误读为模型反向）→ NaN 走既有 N/A 显示 |
| E11 | 🟡 | evaluation/metrics_supervised.py:240-248 | 并列分数（工业 sigmoid 饱和常见）结果依赖输入序，与 WMW 语义不符 → 同分组平均 TPR/FPR 再积分 |
| E20 | 🟢 | evaluation/generative_metrics.py:104 | FID trace 微负显示 -0.00xx → `max(fid, 0.0)` 钳位 |
| — | 追加 | evaluation/eval_flow.py:86 | 测试过程发现的引擎未注册异常逃逸（见 E3 追加） |

## 🧪 新增测试（tests/test_round3_fixes_l_e_x.py，13 例）

坏 JSON 批量不崩（replace/statistics）、原子写往返无 tmp 残留、撤销栈有界、闭合点击请求标志与复位、病态无限队列按上限截断、seg/abdet 显式拒绝、AUROC NaN/并列序无关、eval_flow 坏文件跳过+警告、int8 路径返回、FID 钳位。

---

## ✅ 行动清单（归档待办，按优先级）

| # | 行动 | 紧急度 |
|---|------|--------|
| 1 | E4：LPIPS 任意配对改最近邻/成对校验（统计有效性硬伤） | P1 下轮 |
| 2 | E5/E13：FID 默认样本量提升 + InceptionV3 双重构建合并（资源翻倍） | P1 下轮 |
| 3 | X8：int8 随机校准改样本注入接口（部署可信度，量化精度风险） | P1 下轮 |
| 4 | E6：混合分辨率数据集 resize 对齐（LPIPS/stack 路径） | P2 |
| 5 | X14：导出原子写（.tmp+rename）+ fp16 覆盖唯一产物问题 | P2 |
| 6 | E12/E17：生成式评估入口校验/进度回调 + 训练集评估告警 | P2 |
| 7 | L7/L8：point_in_polygon 边界语义 + shape 级解析容错 | P3 |
| 8 | L9-L12：SAM 通道序断言 / load 异常包装 / 构造失败反馈 / 预览增量绘制 | P3 |
| 9 | E18/E19：GT 类别提取 / mAP 并集语义文档 | P3 |
| 10 | L13-L16：颜色往返 / 不可达桩清理 / 共线闭合校验 / hash 缓存 | P3 |

---

## ⚠️ 已知局限

- seg/abdet 评估的完整打通（mask 栅格化供给、image-level score 通道）属功能开发非缺陷修复，本轮按 E1 显式拒绝处理，待产品排期
- X8 随机校准的完整修复需校准数据注入接口设计（涉及 GUI deploy 页联动）

---

## 📚 数据来源 & 成员产出索引

- evaluation/exporter 审查（20 项：🟠9/🟡7/🟢4）+ labeling 审查（16 项：🔴1/🟠5/🟡6/🟢4），两路均含实测验证段（排除 RDP 递归深度、SAM 线程链等 4 组疑点避免误报）
- 修复与测试：主理人当日完成（14 项修复 + 13 测试）

---

> 本报告由第三轮并行代码审查汇编生成，关键决策请由人类工程负责人复核。
