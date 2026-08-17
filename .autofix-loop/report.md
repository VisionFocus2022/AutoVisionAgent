# UIA autofix-loop · VERIFICATION REPORT

- **状态：GREEN**（基线即零失败，无 worker 轮次；按协议 `failCount==0 && parseError===false` 直接终态；**复确认：第二次全量整跑再次 6/6 全绿**，连续双绿）
- 轮次：0 ｜ 墙钟（基线整跑）：~9 分钟 ｜ baseline→最终 failCount：**0 → 0**（6 passed / 0 skipped / 0 failed）
- failCountHistory（驱动器侧基建迭代期，非 loop 轮次）：基线#1 5/6 → #2（用户指示重跑）1/6 → #3（每用例独立 app）1/6 → **#4 0 失败**
- touchedFiles（loop 内生产代码修改）：**[]** —— 生产代码零修改；recoveredSet：[]

## 分类汇总

| 类别 | 数量 | 说明 |
|---|---|---|
| deterministic（loop 自动修） | 0 | 无需修——应用日志全程零异常，四轮翻车均为测试基建问题 |
| visual（testWrong 路由） | 0 | 套件无像素断言（方案层禁用） |
| flaky（testWrong 路由） | 0 | 基线终态零失败；基建修复消除了时序翻车源 |

## 到达 GREEN 的四轮测试基建修复（驱动器侧，全部为等待/前台化/生命周期策略，无断言放宽）

1. **#1→#2 检出**：新用例断言设计缺陷——矩形重试累计计数（状态栏实为"矩形 4 标注数"）而死等字面 "1"；改为基线计数 + 增量检测（任何一次未增即重试、终态硬失败，判定更严）。
2. **#2 检出（用户"再试一次"）**：会话级复用单个 app 实例在 6 用例下渐进失稳（UIA 树随 11 页内容膨胀 + 原生对话框级联残留）；改为**每用例独立启动被测应用**（plan-phase 生命周期纪律），对话框等待 10→22s、确认后等对话框消失、残留 #32770 清扫。
3. **#3 钉死根因**：第 2+ 个 app 实例 `win.SetFocus()` 只设键盘焦点不抬 z 序 → 坐标点击落到其他窗口；且 UIA 树可见隐藏页控件使导航点击"假成功"，连锁迷失成各页 find timeout。修复：`find_main_window` 用 **`SetActive()` 真前台化**；登录完成硬校验（离线模式按钮必须从树中消失 + 两轮重试，失败明确报"仍在登录页"而非连锁迷失）。
4. **#4 验证**：6/6 全绿（含既有 full_workflow 全流程 + 极柱 5 用例）。

## 运行接线（复现用）

```bash
export AUTOFIX_LOOP_CONFIG="C:/Users/888/.claude/skills/uia-autofix-loop/config.json"
export PATH="/e/学习项目/视觉大模型/.venv/Scripts:$PATH"
export PYTEST_ADDOPTS="tests/uia -o addopts= --timeout=300 --timeout-method=thread"
node "C:/Users/888/.claude/skills/uia-autofix-loop/scripts/baseline-uia.mjs"
```

（PYTEST_ADDOPTS 适配原因：内置 uia-windows 调用是裸 `python -m pytest`，不覆写会吃 pytest.ini 的 coverage addopts 且被 `--ignore=tests/uia` 排除。）

## 被测物

dist/AutoVisionAgent/AutoVisionAgent.exe（2026-08-17 10:00 重打包，含 W8-W10 全部 13 个修复）——**首次在本包上完成 6 用例真窗全绿**；此前 exe 为 W7 时代旧包，UIA 仅验证过单用例。
