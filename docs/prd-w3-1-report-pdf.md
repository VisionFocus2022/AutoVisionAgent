# PRD-lite：W3-1 检测报告 PDF

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2 ｜ 确定性：高（matplotlib PdfPages 在包内；CJK 用 Windows 系统字体回退）｜ 影响半径：小（推理页新增导出动作，纯增量）｜ 规模：中（新模块 ~200 行+页插桩 ~50+测试）｜ 可逆性：双向门
- **上游**: roadmap Wave3 W3-1；W2-1 模型卡/统计表口径复用
- **门禁**: 探索 ✅（用户指令）｜ PRD ✅（S2 预裁决：roadmap DoD）｜ 收尾 ✅（2026-10-07：单测 6 绿（pypdf 锚点：页数≥2/metadata"检测报告"/统计值"3"+"66.7%"可提取/字体回退/中文路径/空检出单页）；主门禁 1491 绿+ruff 0；exe 重打包）
- **并行批避让**：i18n.py 在途——新文案字面量（同 W2 惯例）

## FR

- **FR-1 报告生成模块**（新 `exporter/report_pdf.py`，纯后端无 Qt）：
  `build_detection_report(results, out_path, params, sample_limit=6)`——
  matplotlib PdfPages 多页：
  ① 首页：标题/时间戳/参数（任务/模型/阈值/设备）+ 统计表（总图像/
  总检测/缺陷图像/缺陷率/类别分布——统计口径复用 W2-1 模型卡字段源）；
  ② 样本页：前 N 张有检出的原图+检测框叠加（每页 2 张，含文件名与
  检出数标注）；
  ③ PDF metadata title（"AutoVisionAgent 检测报告"）——可机读锚点。
- **FR-2 CJK 字体**：优先注册 `C:\Windows\Fonts\simhei.ttf`（msyh.ttc
  次之）；均缺失回退 DejaVu+英文标签（不产豆腐块），报告 metadata
  不受字体影响。
- **FR-3 中文路径安全**：out_path 全程 str 直写（matplotlib 原生
  支持），不经过临时 ASCII 中转。
- **FR-4 推理页「导出报告」**：批量结果非空时可用（对齐 CSV/JSON
  导出组）；worker 线程渲染（W1-4 纪律）；完成状态含路径与页数；
  保存对话框缺省名 `detection_report_<ts>.pdf`。

## AC

- AC-1 报告：3 结果（2 缺陷+1 净）+2 样本图 → 文件存在 >1KB；
  pypdf 读 metadata title 含"检测报告"；页数 ≥2；extract_text 含
  统计值锚点（"3"与"66.7%"）。
- AC-2 字体回退非 happy：字体路径全部缺失（monkeypatch）→ 仍产出，
  metadata 锚点不变。
- AC-3 中文路径：输出到含中文目录 → 成功且可被 pypdf 读取。
- AC-4 空样本：results 全净（无检出）→ 首页统计全 0 + 无样本页，
  不炸。
- AC-5 页面：_results 空时按钮禁用语义（状态提示"无数据可导出"）；
  worker 异常显式失败复位。
- AC-6 主门禁全绿+ruff 0+行数守卫（predict/export_actions 限内）。

## 范围

新：exporter/report_pdf.py、tests/test_w3_1_report_pdf.py。
改：gui/pages/predict/page.py（按钮+worker 槽）、
gui/pages/predict/export_actions.py（_export_report 动作）。
测试依赖：pypdf（仅测试侧读取校验，不入 exe）。
Out of scope：按类别分节、检测框置信度过滤、HTML 报告、盖章签名。

## 实施纪要（2026-10-07）

- matplotlib 细节二坑即修：Figure 无 .table（须 add_axes 后 ax.table）；
  字体注册在 rcParams 层全局生效（跨测试顺序共享——回退测试 monkeypatch
  候选清单而非 rcParams，避免污染顺序敏感）。
- 一次全量随机序段错误（matplotlib PDF 后端 × Qt 卸载顺序），确定性
  与复跑均 1491 全绿——与 W2-4 flaky 同批登记（候选根因：套件收尾时
  matplotlib/Qt 析构顺序，稳定化批）。
- pypdf 仅测试侧依赖（exe 不入包）；新增测试文件漏 pytestmark 被
  check-gate 新文件标记守卫拦下——守卫网再次自证。
