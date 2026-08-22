# PRD：W31 AMP 预检（L2 · 精简）

> v1.0 · 2026-08-22 · 上游：计划 W31 节（已批准）· 档位 🟡L2（训练链路大影响）
> 门禁代偿同前（计划批准 + 用户连续执行指令）

## FR
- FR-1 models/supervised/amp_preflight.py 纯函数 amp_preflight(device)->(ok, reason)：cpu/非 cuda→(True,"skip") 静默跳过；cuda fp16 前向+反向全有限→(True,"ok")；异常/非有限→(False,原因)
- FR-2 训练页接线：amp 勾选时预检；失败→状态栏警告+chk_amp 取消+TrainConfig 回退 amp=False（dataclasses.replace）；通过→零扰动
- FR-3 不随包 checkamp.pt（SKolpha 资产方案弃用——2 行 autocast 等价）；i18n zh+en

## AC
cpu 跳过 ✓ cuda 异常 False+原因 ✓ 非有限 False ✓ 页面回退（配置/复选框/状态栏）✓ 通过零扰动 ✓

## 范围外：真实 GPU 端到端（本机无 cuda，探针路径经 mock 验证；真机首跑留验证项）
