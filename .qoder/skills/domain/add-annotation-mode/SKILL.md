---
name: add-annotation-mode
description: 新增一种标注模式（矩形区域SAM/笔刷/多边形族新形态等）。当需求要在标注画布上加新交互模式时使用。
---

# add-annotation-mode：新增标注模式

> 原子范围：一种新交互模式，走完 modes→controller→导出→i18n→spec→测试全链。

## 标准动线（按序执行，引用先例）

1. **Labeler 实现**：`labeling/modes/` 新建 labeler，遵循 `labeling/base.py` 的 `AnnotationMode`/`Shape` 契约（先例：矩形区域 SAM=W43，笔刷精修=W44）
2. **模式注册**：`labeling/controller.py` 模式集合（模块级 frozenset 常量）+ `make_labeler` 分发；`_MODES` 字面量表与 i18n 标签对齐（变量键盲区，见 R02 §3）
3. **注入缝核白名单**：走 `attach_interactive`/`set_detector` 契约缝时核对接入点模式白名单——漏一个模式=GUI 死路（W46 实证）
4. **导出兼容**：`labeling/io_labelme.py` 确认 LabelMe JSON 可序列化；提交的 Shape 必须带正确工具模式（带错=LabelMe 拒收，W46 生产缺陷）
5. **五方注册**：spec hiddenimports（新子模块时）+ i18n zh/en 双键 + 快捷键 + `pyproject` isort
6. **测试四层**：labeler 单测（离屏）→ controller 分发单测 → io_labelme 序列化往返 → UIA 真窗装配链（模式切换→注入→交互→提交→保存，见 R04 §1.4）
7. **门禁**：`bash scripts/check-gate.sh`

## 已知陷阱

- 盒提示类参数悬崖：紧贴目标=最强提示，松量 8px 即砍半（W53 m=0/8/16/64=0.755/0.486/0.275/0.136）——交互设计引导紧框
- 掩码∩矩形硬约束是隐形增益器（+0.21 IoU），语义保障代码值得消融验证

## 自检

- [ ] 模式经 controller 注册且 GUI 入口可达（白名单已核）
- [ ] 提交/保存端到端过（UIA 或手动）
- [ ] i18n 双键 + 计数断言同步
