---
name: sync-biz-record
description: 向业务需求记录追加阶段章节（REQ/PLAN/DESIGN/IMPL/VERIFY/RELEASE），无记录则按规范新建。当需求开发进入任一阶段、或需要补录需求过程时使用。
---

# sync-biz-record：追加一条业务记录

> 原子范围：一次只写一个阶段章节；append-only，禁止回头编辑历史章节。

## 步骤

1. **定位文件**：`.qoder/records/biz/{YYYY-MM}/{YYYYMMDD}_{需求名}.md`
   - 日期 = 需求发起日（固定不变）；文件不存在则新建，写文件头（标题、状态、发起日期）
2. **追加阶段章节**（按当前阶段选一个）：
   ```markdown
   ## [REQ] YYYY-MM-DD       <!-- 背景 + 验收标准 -->
   ## [PLAN] YYYY-MM-DD      <!-- 方案与取舍，被否方案一句话记原因 -->
   ## [DESIGN] YYYY-MM-DD    <!-- 接口/表结构/关键流程 -->
   ## [IMPL] YYYY-MM-DD      <!-- 涉及文件 + 使用的 skill -->
   ## [VERIFY] YYYY-MM-DD    <!-- 测试与红线检查结果 -->
   ## [RELEASE] YYYY-MM-DD   <!-- 发布信息 -->
   ```
3. **同阶段多次发生**（如 IMPL 分批）：追加 `## [IMPL] YYYY-MM-DD (2)`，不改旧章节
4. **状态流转**：完成更新文件头"状态"为`已发布`；废弃改`已废弃`，不删除文件

## 自检

- [ ] 文件名符合 R00（发起日期前缀）；历史章节未被修改
- [ ] REQ、IMPL 两阶段最终必须存在（R04）
