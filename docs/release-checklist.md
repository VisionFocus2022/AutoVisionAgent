# AutoVisionAgent 发版检查单

> 适用：打包发布 dist/ 前的人工验证流程（W4-T4 建立，P2-1 收尾）。
> 常规开发验证不需要本单——`pytest`（门禁覆盖率见 pytest.ini fail-under + uia 默认排除）即可。

## 1. 门禁全量（必须 rc=0）

```bash
.venv/Scripts/python.exe -m pytest
```

预期：全绿，覆盖率 ≥ fail-under（**以 pytest.ini 的 --cov-fail-under 为单一真源**，W14 起为 92；本单不写死数字以免与棘轮脱节——W11 审查曾发现此处滞留旧值 64%、v3 审查发现滞留 89）。

## 2. 打包

```bash
.venv/Scripts/python.exe -m PyInstaller autovisionagent.spec --noconfirm
```

确认 `dist/AutoVisionAgent/AutoVisionAgent.exe` 生成且时间戳更新。

可选：派生 CPU-only lite 产物（W19 双产物方案——复制全量产物并裁剪
`_internal/torch/lib` 内 CUDA DLL 栈，目标 <2GiB；引擎侧已做 cuda 不可用
→ cpu 回退，蒸馏冒烟见 `scripts/make_lite_dist.py` 与
`tests/test_w19_lite_dist.py` 守卫）：

```bash
.venv/Scripts/python.exe scripts/make_lite_dist.py
```

## 3. UIA 真窗端到端（需桌面会话 + 打包 exe，手动执行）

```bash
.venv/Scripts/python.exe -m pytest tests/uia -o addopts=
```

前提：
- 交互桌面会话（无头环境 conftest 会自动 skip 而非报错）；
- 目标 exe 未在运行（同名单实例会找不到窗口）；
- 无需预创建 `configs/license.key`：点"离线模式"在确认框选"是"即可进入（单工位模式，无许可证校验）；预创建空文件可跳过确认框直入。

## 4. 冒烟（人工，~2 分钟）

- [ ] 启动 exe → 登录页 → 离线模式进入主页
- [ ] 标注页：画矩形/多边形（闭合）/画笔，撤销-重做，保存 JSON
- [ ] 数据管理页：选目录 → 导入 → 划分（copy 模式）
- [ ] 训练页：任务下拉按注册表实况展示；模拟训练路径有"（模拟）"警告
- [ ] 推理页：批量推理出结果表、导出 CSV
- [ ] 设置页：主题 夜/日/自动（auto 随系统）、语言切换即时生效

## 5. 归档

- [ ] `git log --oneline` 确认本版提交链完整
- [ ] 版本号（pyproject version）与 tag 一致
