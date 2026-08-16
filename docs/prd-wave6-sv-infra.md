# PRD — 第六波：InferenceSlicer/CompactMask 对标（wave6-sv-infra）

> 依据：用户 2026-08-16 指令"继续实施 InferenceSlicer 对标 tiling_inferencer（滑窗推理）、
> CompactMask RLE 压缩对标 serving 共享内存大掩码传输——都有现成对照物"
> （延续 W5 supervision 文章方法的落地，范围由用户逐项点名）。
> 基线：W5 终态 359 passed / 0 failed / 1 skipped，门禁 70.03%。

## 背景（实测）

- 本树 `inference/tiling_inferencer.tile_infer`：自研滑窗（compute_tiles + 逐瓦片
  engine.infer + 坐标回映 + 自研 NMS 合并）；sv 0.30 `InferenceSlicer` 同型能力
  （callback→sv.Detections、overlap_filter=NMS、thread_workers、compact_masks）。
- serving 大掩码传输：masks (N,H,W) bool 以原始字节写共享内存（_SHM_MIN_BYTES=64KiB
  起步）；sv `CompactMask` 为 run-length 压缩结构——实测其内部 rles/crop_shapes 为
  **私有字段**（dir 仅 offsets/shape/dtype 公开），不宜作跨语言线格式。

## FR-001 滑窗推理 sv 后端（tile_infer_sv）

- `inference/tiling_inferencer.tile_infer_sv(image, engine, slice_wh, overlap_wh,
  iou_threshold, threshold)`：sv.InferenceSlicer + 本树 sv_bridge 回调
  （切片→engine.infer→DetectionResult→sv.Detections），合并结果转回 DetectionResult。
- 与既有 `tile_infer` 同契约：小图直推、结果含跨瓦片 NMS 合并、extra 记录后端信息。
- 对照测试：合成大图 + 已知物体图（含跨瓦片物体），两后端都精确找回 N 物体、
  无重复；pytest-benchmark 做 A/B 延迟对比（同图同参）。

## FR-202 大掩码 shm 传输 RLE 压缩（对标 CompactMask，线格式自控）

- `serving/mask_codec.py`：自控线格式 `bool_rle`（int32 交替游程，False 起始，
  行主序展平；格式文档化）。encode/decode 纯函数。
- `SharedMemoryHandle` 增 `encoding` 字段（"raw"/"bool_rle"）；`SharedMemoryManager`
  增 `write_mask_compact`；`read_array` 识别 bool_rle 解码还原 (N,H,W) bool。
- `serialization._array_to_shm_or_skip` 支持环境变量 `AVA_SHM_MASK_RLE=1` 时对
  bool 掩码走压缩（**默认关**——.NET SharedMemoryReader 需先支持 bool_rle 才能
  默认开启，契约变更走显式开关，docstring 注明）。
- 对标基准：同掩码下本编码 vs sv CompactMask（from_dense footprint）压缩比同量级
  （测试记录断言），1080p 稀疏缺陷掩码压缩比 <10% 原始体积。

## 验收标准

- AC-001（FR-001）：tile_infer_sv 对照测试绿——合成 2400×1800 图（tile 640、
  overlap 96）两后端均找回全部 6 物体（含 2 个跨瓦片），零重复；A/B benchmark 跑通。
- AC-002（FR-202）：codec 往返（随机稀疏/全真/全假/单像素/N=3）逐位相等；
  write_mask_compact→read_array 往返相等；压缩比断言（1080p×2 稀疏 <10%）；
  AVA_SHM_MASK_RLE 开/关两态下 detection_result_to_proto 的 masks_shm.dtype 分别
  为 bool_rle/bool 且读回逐位相等；默认关（无环境变量时行为与 W5 完全一致）。
- AC-003：门禁全量 rc=0（fail-under=70 保持或升）；W5 全部测试无回归。
