---
name: add-gui-page
description: 新增 GUI 页面（gui/pages/ 同构四件套）。当需求要加一个桌面功能页/页签时使用。
---

# add-gui-page：新增 GUI 页面

> 原子范围：一个页面四件套（page/workers/导航/测试），同构既有页面接线。

## 标准动线（按序执行，引用先例）

1. **选同构母本**：从 `gui/pages/` 选最接近的既有页做模板（label=画布+工具栏复杂页；predict=train/worker 后台任务页；settings=表单页）
2. **四件套**：`gui/pages/<name>/page.py`（≤800 行，预判抽取 worker）+ `workers.py`（QThreadPool 后台任务）+ 壳导航注册 + `gui/core/` 需要的访问器
3. **导航契约**：菜单项构造形态 `f"  {title}"` 两空格前缀 + `setCheckable(True)`（UIA 选择器契约锚定源码构造形态，W49）；`setCheckable` 在 UIA 树=CheckBoxControl 双类型
4. **权限与角色**：页面门控走角色权限体系（operator/engineer/admin）；离线模式语义=单工位非裁剪，勿误伤
5. **i18n 双键**：全部 UI 文案 zh/en（R02 §3）；变量键对齐字面量表
6. **测试三层**：离屏单测（QT_QPA_PLATFORM=offscreen，conftest 兜底）→ 页面契约/绑定测试 → UIA 真窗（触及装配链时）
7. **门禁**：`bash scripts/check-gate.sh`

## 已知陷阱

- 规模守卫第三次拦截 page.py 后抽 frozenset/worker 是既定动作，不是意外（W44）
- 模态窗/懒加载页签：未选中 TabItem 不进 UIA 视觉树，页对象先 Select 再断言
- 长等待后坐标点击前强制窗口激活；键盘捷径优先鼠标路径等价物（UIA 稳定性）

## 自检

- [ ] page.py ≤800 行；worker 后台任务不阻塞 UI 线程
- [ ] 导航可达（角色门控语义核过）+ i18n 双键
- [ ] 离屏单测绿；触及装配链补 UIA
