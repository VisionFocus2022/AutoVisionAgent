# SKolpha 3.3.2 全功能反编译取证 — 任务列表 (tasks-lite)

> 版本: 1.0 | 日期: 2026-09-02 | 关联: docs/prd-skolpha-full-forensics.md（门禁 1/2 已过，连跑波1+波2 已裁决）
> 验证形态说明：本批为研究/取证批，任务验证=锚点可复核（exe 偏移/明文文件路径）+ 报告三态标注，无 pytest 门禁（N/A）。

## 波1 全景测绘（FR-001）

- [x] **W1-0 前置侦察**（探索期已完成）：目录结构/明文配置盘点/加密形态识别 ✅ 2026-09-02
- [ ] **W1-1 exe 模块表提取**：py_scan 特征确认 + `包.模块` 正则全量提取 → 业务包清单（工具：dotnet-decompile/scripts/py_scan.py；产物 %TEMP%/skolpha-forensics/modules.txt）｜验证：模块数≥百级且含业务包名（AC-001）
- [ ] **W1-2 明文资源解析**：languageFile.json（i18n 全量）、programFile.json、configFile*.json、configs/labelme 参数、TrainConfigs 九类模板逐类摘要｜验证：解析脚本产物落 %TEMP% 并摘要进报告（AC-002 素材）
- [ ] **W1-3 chm 手册解编译**：hh.exe -decompile + GBK→UTF-8｜验证：htm 文件数≥1 且可 grep 中文
- [ ] **W1-4 波1 报告**：docs/skolpha-forensics-wave1.md（功能全图：三源交叉+分层架构+九类训练任务矩阵+加密面）｜验证：AC-001/AC-002

## 波2 四大主线函数级深挖（FR-002/003/004）

- [ ] **W2-1 标注主线**：labelme 定制点（参数文件+常量）+ SAM 机制（前案结论并入）+ 标注数据落地格式｜验证：≥5 函数级锚点
- [ ] **W2-2 创建工程主线**：programFile.json 语义 + 工程目录结构 + 新建/保存/打开调用链｜验证：≥5 函数级锚点
- [ ] **W2-3 训练主线**：TrainConfigs 模板→数据管线→训练循环→产物结构（OpenMMLab 假设验证）｜验证：≥5 函数级锚点
- [ ] **W2-4 推理主线**：模型加载→预处理→推理→后处理→结果落地｜验证：≥5 函数级锚点
- [ ] **W2-5 Fernet 解密**：44 字符 base64 密钥形态特征在常量区全文搜→试解 default.yaml｜验证：AC-004（成功或诚实结论）
- [ ] **W2-6 定点动态核对**：≥2 处（日志/产物目录）实机核对静态推演｜验证：AC-006
- [ ] **W2-7 波2 报告+收尾**：docs/skolpha-forensics-wave2.md + 门禁 3 + 经验沉淀｜验证：AC-003/005 + 收尾确认

> ✅ 2026-09-02 批次完成：W1-1..W2-7 全部执行完毕（含 AC-004 提前达成于波1）；门禁 3 裁决=接受静态结论收尾、文档不提交留工作区。
