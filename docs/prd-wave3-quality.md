# PRD — 第三波：标注语义恢复 + sseg 真化 + 主线程迁移 + 覆盖率门禁（wave3-quality）

> 依据：`docs/AutoVisionAgent-架构解析与优化方案.md` §11.5（第二波第 8/9 项遗留 + 路线延续）；
> 用户指定四项及顺序（2026-08-16 原话见 .workflow 状态 evidence）。
> 基线：wave2 终态 273 passed / 0 failed / 1 skipped / 8 xfailed（排 uia）。

## FR-001 labeling era-2 语义恢复（8 个 strict xfail 绊线转绿）

现状：8 个 xfail（tests/test_labeling.py ×7 + tests/test_gui.py ×1）记录 era-2 标注语义缺口：
- 矩形误触小形状丢弃（labeling/modes/rectangle.py 无尺寸阈值）
- 多边形 commit() 自动闭合（首尾相接）+ 吸附首点后提交 + 提交后状态清空（`labeler.points` 属性缺失）
- 画笔完全共线笔触（简化后 <3 点）应丢弃，不产出退化形状
- canvas.add_shape 接受 Shape 实例（era-2 契约）；undo/redo 快照须为浅拷贝以保持对象引用身份（现 deepcopy）
- canvas.replace_all(shapes) 可撤销整体替换（方法缺失）
- 控制器/label 页 handle_commit 产出闭合多边形

要求：移除全部 8 个 xfail 标记后测试全绿；既有 15+ 个 labeling 已绿测试语义不变。

## FR-002 sseg 真化（sseg_mmseg 桩 → sseg_smp 移植）

现状：models/supervised/engines/sseg_mmseg.py 在 ImportError 时回退 `_safe_torch_load` 测试桩路径
（架构审查 §7.2 定性降级路径存疑）；mmseg 未装于本树 venv。
兄弟树有现成真实现 `sseg_smp.py`（segmentation_models_pytorch DeepLabV3+，缺库诚实 raise）
与配套功能测试 `test_engine_sseg.py`（动态小模型真 load→infer）；本树 venv 已装
segmentation_models_pytorch==0.5.0（requirements.lock.txt 实证）。

要求：移植 sseg_smp.py 替换并删除 sseg_mmseg.py；矩阵/契约测试、spec hiddenimports、
run_m3_verification.py COMPILE_TARGETS 同步；全仓无 SsegMmseg/sseg_mmseg 残留引用。

## FR-003 主线程重活迁移（架构审查 P1-3）

现状（审查实证行号）：data_manage 页导入/划分/批量标注工具（data_manage/page.py:249-272、274-352、
425-533）、label 页 AI 预标注（label/page.py:449-541）、predict 页单张推理（predict/page.py:255-302）
均在 UI 线程同步执行；数千张工业图导入 = 分钟级"未响应"。

要求：上述五处迁移至 worker 线程，采用本树既有惯用法（threading.Thread + gui.core.thread_bridge.invoke_main
回调，与 flaw_gen/predict 批量一致）；执行期间触发控件禁用、结束/失败主线程回调恢复；
既有页面级测试保持全绿（纯工作逻辑抽为可同步调用的函数）。

## FR-004 覆盖率门禁回归 + serving 补测（架构审查 P2-4）

现状：pyproject [tool.pytest.ini_options] 无 cov；serving 0% 覆盖（审查 §11.1 实测）；
兄弟树 pytest.ini 门禁（棘轮 fail-under）未随迁。

要求：
- 为 serving/serialization.py 与 serving/shared_memory.py 补纯逻辑单测（往返、句柄契约、释放），目标两模块覆盖率 ≥60%
- 移植 pytest.ini 并适配本树：包集合按本树发布包、uia 默认排除（-m "not uia"）、--strict-markers
- fail-under = 全量实测地板（棘轮，测量后设定并留痕）
- pytest 配置收敛单一真源（pytest.ini 优先，pyproject 冲突段移除）

## 验收标准

- AC-001（FR-001）：移除 8 个 xfail 后 `pytest tests/ --ignore=tests/uia` 0 failed 且 0 xfailed
- AC-002（FR-002）：test_m2_matrix SSEG 期望=SsegSmpEngine 通过；全仓 grep 无 sseg_mmseg/SsegMmseg 残留；移植的功能测试真 load→infer 通过
- AC-003（FR-003）：五处重活确不在 UI 线程同步执行（代码复核 + 全部页面测试绿）
- AC-004（FR-004）：`pytest tests/`（pytest.ini 生效、默认排 uia）rc=0；serving 两模块覆盖 ≥60%；fail-under=实测地板有命令留痕
