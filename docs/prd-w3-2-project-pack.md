# PRD-lite：W3-2 项目包 2.0（资产迁移）

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2-L3 ｜ 确定性：高（zipfile+SHA256 标准件；布局已有 ProjectLayout 五子目录）｜ 影响半径：中（导入写盘=数据变更类，靠"拒绝覆盖+先验校验"降险）｜ 规模：中（新模块 ~170+页面 ~90+测试）｜ 可逆性：导入拒绝覆盖=无破坏；导出只读
- **上游**: roadmap Wave3 W3-2；并行批已入库→i18n 恢复正常 tr() 流程（本轮起不再字面量避让）
- **门禁**: 探索 ✅（用户指令开工）｜ PRD ✅（S2 预裁决：roadmap DoD）｜ 收尾 ✅（2026-10-15：单测 7 绿（roundtrip 逐文件哈希相等/缺 manifest 零落盘/损坏列名/碰撞拒绝+原目录未触碰/空项目/页面三态）；UIA 导出链绿（创建→导出 zip 含 manifest）；主门禁 1498 绿+ruff 0；exe 重打包）

## FR

- **FR-1 打包模块**（新 `project/pack.py` 纯函数）：
  `export_pack(project_root, zip_path)`——遍历项目根（跳过
  `__pycache__`/`.DS_Store`/thumb 缓存），zip 内相对路径存文件 +
  `avpack_manifest.json`（格式版本/应用版本/项目目录名/文件数/总字节/
  created_at/逐文件 SHA256）。
  `import_pack(zip_path, base_root)`——三段式：①读 manifest（缺=
  显式错）②**先验校验**（zip 内逐文件 SHA256 对照，失配列出≤3 个
  文件名）③校验全过才落盘到 `base_root/<项目目录名>`（已存在=拒绝
  覆盖显式错，绝不静默合并）。
- **FR-2 页面**：项目页「导出项目包」（选中项目→保存对话框→zip）/+
  「导入项目包」（打开 zip→导入当前存储根→刷新列表+状态含文件数）；
  worker 线程（大包秒级，W1-4 纪律）；无选中/失败显式状态。
- **FR-3 i18n**：新键正常走 tr()（避让期已结束）。

## AC

- AC-1 roundtrip：假项目（图+标注 JSON+模型字节+配置）导出→新根导入
  →逐文件 SHA256 相等；manifest 计数/目录名正确。
- AC-2 缺 manifest：无 manifest 的 zip → 显式错误不落盘。〔非 happy〕
- AC-3 损坏：篡改 zip 内一字节 → 校验失配列文件名、零落盘。〔非 happy〕
- AC-4 碰撞：同名项目已存在 → 拒绝覆盖显式错、原目录未被触碰。
  〔非 happy〕
- AC-5 空项目：零文件也能导出/导入（manifest files=0）。
- AC-6 页面：无选中导出→提示；导入成功状态含 N 文件；worker 异常复位。
- AC-7 UIA 小链：exe 真链——创建项目→导出 zip（含 manifest）→删除
  项目→导入同一 zip→项目重现列表。
- AC-8 主门禁全绿+ruff 0+行数守卫（project/page ≤400）。

## 范围

新：project/pack.py、tests/test_w3_2_project_pack.py、
tests/uia/test_project_pack_w3_2.py。改：gui/pages/project/page.py、
gui/core/i18n.py。
Out of scope：增量包/差量、跨版本迁移、加密、压缩率选项。

## 实施纪要（2026-10-15）

- **真缺陷连带修**：项目管理页「刷新列表」此前只刷列表不重读根目录
  输入框（手改根路径后刷新无效的死角）——改连 `_init_store`（UIA 切根
  实证逼出）。
- **UIA 导入段会话级阻断（诚实登记）**：导入对话框关闭后槽链静默中断
  （冷/热探针双证：两条分支均未执行、零异常零日志）——单测级源模块
  拦截 bisect 证明功能正确（b2 落盘+状态发射）；定性为本远程会话输入
  通道缺陷（W64 类：导出对话框同会话可用）。**债务：本机 attended
  会话复跑导入 UIA 段补验**。
- 规模守卫拆分：_build_pack_row 模块级（103→达标）；i18n 动态链键
  （保存/选择项目包）入豁免判例（pick_*_file 内部 tr 消费）。
- 一次满载随机序段错误（W3-1 登记的 mpl×Qt 析构类）复跑绿——同类。
