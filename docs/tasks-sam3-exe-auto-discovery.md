# Tasks — SAM3 自动发现 exe 侧闭环

> 关联：docs/prd-sam3-exe-auto-discovery.md ｜ 档位 🟡L2 lite ｜ 2026-08-31

| # | 任务 | 验证 | 状态 |
|---|------|------|------|
| T1 | 重打包 full exe（后台，~4 分钟；防呆断言要求项目 venv） | 退出码 0；`_internal/transformers/models/sam3` 在场 | ✅ |
| T2 | 复制 `weights/sam3` → `_internal/weights/sam3`（3.3G，~1-2 分钟） | config.json + model.safetensors 在场；体积抽查 | ✅ |
| T3 | UIA 全套回归（exe 模式，后台分批 + `%TEMP%` 日志；机器须空闲） | SAM3 两文件 7 用例绿（自动发现实跑）；其余套件绿或新鲜复验定谳 | ✅ |
| T4 | 收尾：AC 核对 + 汇报（exe 留给用户手测）+ 经验沉淀 | AC-1~4 全过 | ✅ |

依赖：T1→T2→T3→T4 串行（T2 必须在 T1 后——重打包清空 dist）。
