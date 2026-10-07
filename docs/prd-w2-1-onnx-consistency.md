# PRD-lite：W2-1 ONNX 一致性校验 + 模型卡随包

- **版本**: v1.0（2026-10-07）
- **档位声明**: 🟡L2 ｜ 确定性：高（ultralytics 原生支持 YOLO(onnx) 加载，双端同源后处理免手写 NMS）｜ 影响半径：中（部署导出链新增校验/落盘；不触数据/鉴权）｜ 规模：中（新模块 ~150 行+deploy 插桩 ~40+测试）｜ 可逆性：双向门
- **上游**: roadmap Wave2 W2-1；W1-2 历史记录字段复用；W1-4 线程纪律（校验=推理秒级，进 worker）
- **门禁**: 探索 ✅（用户指令"继续 W2-1"）｜ PRD ✅（S2 预裁决：roadmap DoD 锁定）｜ 收尾 ✅（2026-10-07：单测+集成 10 绿（含真链 训练→export_onnx→一致性≥0.95→卡片含 defect）；主门禁 1449 绿+ruff 0；exe 重打包）
- **并行批避让声明**：i18n.py / supervised_exporter.py 为并行会话在途文件——本行零触碰：新文案用字面量（该批收口后补键），导出调用面只读。

## 2. FR

- **FR-1 一致性校验模块**（新 `exporter/onnx_consistency.py`）：
  `compare_boxes(a,b,iou_t)` 纯函数（贪心 IoU 匹配）；
  `onnx_consistency_check(pt,onnx,images,min_match=0.95)`——
  YOLO(pt) vs YOLO(onnx) 同图同阈推理，框集逐图匹配率汇总；predictor
  可注入（测试缝）；任何异常→显式失败 dict（不静默）。
- **FR-2 模型卡随包**：`write_model_card(pt,onnx,task)`——train_history
  中按 weights_path 匹配记录（复用 W1-2 字段：classes/imgsz/metrics/
  backbone/轮数），无记录降级最小卡（task/时间/pt/onnx 路径）；
  落 `<onnx同目录>/<stem>_model_card.json`。
- **FR-3 部署页插桩**：export_onnx 成功后（worker 内，进度 80 段）跑
  校验+写卡；results 增 consistency/card；`_export_done_slot` 通过=
  绿状态含匹配率、失败=红字（"!"）含原因——**失败不静默**；样本图取
  历史记录 data_yaml 图像目录前 6 张，无则合成灰图并在 detail 注明。

## 3. AC

- AC-1 纯匹配：完美/部分/不相交三态匹配率正确。
- AC-2 校验：fake predictor 完美对→ok=True rate=1.0；onnx 漏检 1/3→
  rate<0.95 ok=False；坏 onnx 路径→显式失败 dict 不抛出。〔非 happy〕
- AC-3 卡片：有历史记录→classes/imgsz/metrics 入卡；无记录→最小卡
  不炸。〔非 happy〕
- AC-4 集成（真链）：2 图 det 真训练（floor=0，1 epoch）→ export_onnx
  → 校验 ok=True 且匹配率 ≥0.95 → 卡片与 onnx 同目录、classes 含 defect。
- AC-5 主门禁全绿+ruff 0+行数守卫（deploy 272→<400）。

## 4. 范围

新：exporter/onnx_consistency.py、tests/test_w2_1_onnx_consistency.py。
改：gui/pages/deploy/page.py。
Out of scope：int8 量化校准图接 GUI（并行批 X8 议题）、TRT 一致性、
i18n 键补录（并行批收口后）。

## 实施纪要（2026-10-07）——真链 DoD 逼出两个真缺陷（均已修）

1. **torch≥2.6 weights_only 拒载 ultralytics 检查点**：发布页 P3④ 的
   `torch.load(weights_only=True)` 对真训练权重直接 UnpicklingError
   （DetectionModel 不在 safe globals）——发布链对自产权重必炸。
   修 `safe_load_model`：解析报错中的 GLOBAL 名→import→
   add_safe_globals→重载的**收敛循环**（白名单仍限库自有类，非
   weights_only=False）；一并解包 ckpt dict（ema 优先于 model）。
   隐式返回 None 的循环耗尽陷阱已补显式抛错（64 轮上限）。
2. **AMP 训练权重=Half，ONNX fp32 导出类型必炸**：默认 AMP 训出的
   模型导出时 FloatTensor 输入撞 HalfTensor 权重。修在解包后
   `.float()`（exporter 为并行批在途文件，修复归口本模块避免碰它）。
- deploy 单测 4 例按新契约收敛（fake 一致性通过；断言"导出完成"
  前缀）；文案字面量=避让并行批 i18n.py（收口后补键）。
