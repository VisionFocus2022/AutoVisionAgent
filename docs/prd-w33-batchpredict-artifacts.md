# PRD：W33 batchPredict 产物补齐（L2 · 精简）

> v1.0 · 2026-08-22 · 上游：计划 W33 节 · 档位 🟡L2 · 门禁代偿同前
> 三栏：【已知】DetectionResult.masks (N,H,W)/mask_codec RLE/sv_bridge 渲染器均在场；【假设】过滤作用于记录与产物两层（一致）；【未知】无

## FR
- FR-1 filter_result_by_labels：boxes/labels/scores/masks 协同过滤；空集透传（SKolpha 对象类型双参收尾）
- FR-2 save_batch_artifacts：masks RLE npz（decode 可恢复）+ overlay jpg；失败 WARNING 不炸批
- FR-3 页面：edit_label_filter/chk_overlay（objectName 无内联样式）+ _process 管线；批处理体抽 batch_runner（规模守卫 800/100 双线触发后 W27 式抽取）
- FR-4 permissions：predict.batch_infer 三角色
- FR-5 输出根可配置=设置页 workspace 单源（W28 已建，test_w28 留守卫——文档化不重复建设）

## AC：过滤对齐（含 masks 索引）✓ masks RLE 落盘可解码 ✓ 勾选 overlay 产出 ✓ 过滤接线到记录与 JSON ✓ action 登记 ✓ page 759 行/守卫绿 ✓
