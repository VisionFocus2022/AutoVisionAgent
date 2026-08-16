# wave2-engines — 精简 PRD (L2)

> 版本: 1.0 | 日期: 2026-08-16 | 档位: L2 | 四维: reversible/module/test_visible/medium（见 state.json）
> 上游依据: docs/AutoVisionAgent-架构解析与优化方案.md §11.5 第二波 #6/#7（用户指定本三件套）

## 1. 背景与目标

- **背景**：第一波后终态 240/10/8——10 个红全部因 det/seg/abdet 引擎缺失（v2.0 重建未迁移）；sgan/super 仍是 mmedit 桩（缺库时 score=1.0 假结果）；flaw_gen 页真引擎路径 TypeError 必崩（`SganMmeditEngine(TaskType.SGAN)` 构造参数错 + except 元组不含 TypeError）。兄弟树 `E:\计算机视觉\视觉大模型` 有全部真实现（era-4 "Option A 真化"产物）。
- **目标**：
  1. 移植 3 引擎使 10 红变绿（注册矩阵 9/9 真实成立）；
  2. sgan/super 以 sgan_blend（seamlessClone Poisson 融合）/super_cv2（dnn_superres）真化替换 mmedit 桩，诚实回退（缺库 raise，不返假数据）；
  3. flaw_gen 页经注册表正确接线，删除"复制占位图"假回退。

## 2. 功能需求 (FR)

- **FR-001**: 移植 det_yolo（ultralytics YOLOv8 检测）及其真实测试 test_engine_det_real | P0
- **FR-002**: 移植 _yolo_seg_base + seg_yolo（YOLOv8-Seg 实例分割共享基类）| P0
- **FR-003**: 移植 abdet_anomalib（Patchcore），适配本树 DetectionResult（anomaly_map → extra；score None→0.0）及其真实测试 | P0
- **FR-004**: 移植 core/path_io.ascii_path_copy + sgan_blend + super_cv2，替换 sgan_mmedit/super_mmedit（删除旧桩文件、注册表换名、契约测试导入同步）；两引擎 _to_numpy 接 imread_unicode（本树根即中文路径） | P0
- **FR-005**: flaw_gen 页重写引擎段：经 get_engine(TaskType.SGAN) 取引擎 + load(flaw_database=) + infer(ok图) + imwrite_unicode 落盘；显式捕获 SupervisedEngineError 走失败提示；删除 copy2 占位假回退 | P1
- **FR-006**: 跟进项：engines docstring 6/9→9/9、autovisionagent.spec hiddenimports 补齐 9 引擎 | P1

## 3. 验收标准 (AC)

- **AC-001**: `pytest tests/test_m2_matrix.py tests/test_m2_e2e.py` 中原 10 个引擎红全部转绿 [FR-001/002/003]
- **AC-002**: 移植的引擎测试全绿（det_real / abdet_real / sgan_blend / super 契约）[FR-001/003/004]
- **AC-003**: 全量套件（排 uia）**0 failed**（8 xfail 保留）[FR-001..006]
- **AC-004**: 诚实回退：sgan 缺缺陷库 → SupervisedEngineError；super 缺权重文件 → SupervisedEngineError；全仓 `grep "score=1.0"` 于 sgan/super 引擎无假结果路径 [FR-004]
- **AC-005**: flaw_gen 真引擎路径无 TypeError：注册表取 SGAN 引擎且 load 签名匹配（注册测试断言 get_engine(SGAN) 返回 SganBlendEngine）[FR-005]
- **AC-006**: spec hiddenimports 与磁盘 9 引擎一致；engines docstring 为 9/9 [FR-006]

## 4. 范围

- ✅ In Scope: 上述 6 项 FR；本树 pseg_yolo 不重构（兄弟树 TD-01 去重不移植）
- ❌ Out of Scope: sses_smp（sseg 真化，兄弟树有但用户未点名）；labeling era-2 语义恢复（8 xfail 项）；主线程重活迁移；覆盖率门禁；UIA 运行

## 5. 风险与假设

- **风险**: 兄弟树接口演进差异（已发现 abdet 的 anomaly_map 字段）→ 缓解：逐文件适配本树契约，测试先行。
- **风险**: ultralytics/anomalib 导入慢或 GPU 依赖 → 缓解：venv 实测 8.4.81/2.5.0 在位；测试全部离线设计（兄弟树已验证）。
- **假设**: 删除 sgan_mmedit/super_mmedit 无其他调用方（已 grep：仅 m2_contracts 测试与 flaw_gen 页，两者本次同步改）。
- **假设**: FlawGenPage 构造级测试受 PySide6 环境支持（venv 在位）。

## 6. 实现思路

- **拟采用**: 逐文件移植 + 本树契约适配（DetectionResult.extra / imread_unicode）；注册清单同步换名；先跑红→移植→绿。
- **复用**: 本树 core/image_io.imread_unicode（新增 imwrite_unicode）；兄弟树 4 份引擎测试。
- **注意**: sgan_blend 的 random 用种子测试需确定性（兄弟测试已处理）；except 元组补 SupervisedEngineError。

---

## 自检（5 项）

- [x] 完整性 / [x] 无歧义（无"快速|友好|高效|灵活|强大"）/ [x] 可追溯 / [x] 范围清晰 / [x] 指标可量化

## ✅ 门禁

- [x] G1：用户原话"根据你建议，实施第二波从兄弟树移植 det_yolo/seg_yolo/abdet_anomalib（10 红变绿）+ sgan_blend/super_cv2 真化 + flaw_gen TypeError 修复"
- [x] G3：同上（"实施"即执行授权）；完成后须 AC 全过 + 验证器 0
