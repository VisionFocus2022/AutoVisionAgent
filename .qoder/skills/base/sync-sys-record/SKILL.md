---
name: sync-sys-record
description: 为工程约束体系（.qoder/ 下规则、agent、skill、脚本等）的一次变更新建 sys 记录并同步 AGENTS.md 索引。当新增或修改任何体系资产时使用。
---

# sync-sys-record：新建一条体系记录

> 原子范围：一次变更一条记录；append-only，修正旧记录用新文件而不是编辑旧文件。

## 步骤

1. **新建记录**：`.qoder/records/sys/{YYYY-MM}/{YYYYMMDD}_{类型}_{主题}.md`
   - 类型 ∈ `rule / agent / skill / command / script / doc`（R00）
2. **固定六字段模板**：
   ```markdown
   # {变更标题}
   - 日期: YYYY-MM-DD
   - 类型: {type}
   - 执行者: {agent 或 主对话}
   - 等级: {L0/L1/L2}
   ## 变更内容
   ## 涉及文件
   ## 验证结果
   ```
3. **同步索引**：资产有新增/改名/删除时，更新 `.qoder/AGENTS.md` 第 3 节资产索引表（唯一事实源，R00）
4. **命名偏离**：若本次变更违反 R00 命名，必须在"验证结果"中书面说明原因

## 自检

- [ ] 记录文件名与六字段模板符合 R00
- [ ] AGENTS.md 索引表与磁盘实际资产一致
