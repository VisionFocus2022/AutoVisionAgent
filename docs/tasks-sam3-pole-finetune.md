# Tasks：SAM3 极柱域微调（W48 · lite）

关联：[prd-sam3-pole-finetune.md](prd-sam3-pole-finetune.md)

| # | 任务 | 依赖 | 验证 | 状态 |
|---|------|------|------|------|
| T1 | `scripts/finetune_sam3.py`：数据集+损失+匹配纯函数 + 训练循环 + `--smoke` | — | TDD：tests/test_sam3_finetune_script.py 15 用例绿（v1.0→v1.1 两轮迭代） | ✅ |
| T2 | 真机 smoke：`--smoke` 跑通（loss 有限/val IoU/ckpt 存取+adapter 复载） | T1 | v1.1 smoke rc=0（val 0.529 健康） | ✅ |
| T3 | eval_sam3_accuracy.py 参数化 `--ckpt/--manifest/--n` | — | --n 3 实跑验证 + 默认口径复核 | ✅ |
| T4 | 全量训练后台（约 2h）→ 最优 ckpt | T2 | ⛔ **环境阻塞**：Qoder IDE 代理循环跑 pytest 且进程泄漏不退出（三只僵尸 31.8/39/14.7GB，杀后 10-20min 复生），训练三度被挤死；v1.1 代码已就绪（塌缩护栏+RAM 重试+objectness 弃用） |
| T5 | 验收：val 集 adapter 独立复测（AVA_SAM3_DIR=sam3-pole-ft）vs 基线 | T3+T4 | AC-2/AC-3 达标 | ☐ |
| T6 | 收官：主门禁 + 文档回填 + learning | T5 | **主门禁 1197/5/rc=0 已过**（+15 用例）；learning 已沉淀；文档收尾待 T5 | ◐ |
