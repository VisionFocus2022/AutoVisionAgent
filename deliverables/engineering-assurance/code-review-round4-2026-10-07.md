# 第四轮工程审查综合报告（models/project/benchmarks + 昨夜四批次新代码）

**日期**：2026-10-07
**状态更新（2026-10-07 晚）**：🔴2/🟠11 已**全部当日修复**（三批实施），关键 Nit（N-1/N-14）与测试质量 4 项一并清偿；全量门禁 1485 passed + ruff 全绿。修复明细见文末「修复回执」。
**轮次**：第四轮（一至三轮已覆盖 core/serving/gui/training/dataset/inference/evaluation/exporter/labeling，130 项全清偿）
**审查范围**：① 从未审查模块：models/supervised/engines/ 全 11 文件 + registry/amp_preflight/device + project/ 全 6 文件 + benchmarks/ 全 6 文件；② 昨夜 Bug 治理四批次新代码（评估数学/导出链路/评估入口/几何标注 + 4 个测试文件）
**审查方式**：两路并行独立审查（均含 venv 实测复现）+ 主理人交叉验证（7 项独立实测）

---

## 📌 TL;DR

- **34 项发现：🔴2 · 🟠11 · 🟡21**（另含测试质量问题 4 项）
- **两处 Blocker 均在 YOLO 训练通道且同根**：引擎实例被 registry 永久缓存 → 一次性训练状态（`_train_model` 缓存 + `_stop_requested` 标志）跨训练残留 → **第二次训练要么秒完返回旧结果（B-1），要么 1 轮即停（B-2）**——症状与 W69 修复前的"假曲线"完全一致，等于在连续训练场景下重新打开
- 昨夜四批次新代码：核心算法全对（缓存语义/原子写/射线法/校准三分支），但 **L2 回退默认路径存在实测必崩的广播 bug**（fresh-1）与 int8 校准分辨率错配（fresh-3）
- benchmarks 确认未误入生产链（spec datas 仅 3 个 .pt，无生产 import）✔

---

## 🔴 Blocker（必须修）

### B-1 训练一次性缓存跨训练残留——第二次训练完全不执行
`models/supervised/engines/_yolo_seg_base.py:254-255,317`
- **现象**：`train_epoch` 开头 `if self._train_model is not None: return dict(self._train_metrics)`。训练页经 `registry.get(task)` 取引擎，registry 实例缓存使 det/seg 引擎跨训练是**同一实例**。
- **为什么重要**：用户换数据集/换参数再训同任务 → 第二次直接返回第一次的 metrics，GenericTrainer 循环秒完、曲线是旧值、`save()` 拷旧 best.pt。无任何告警。
- **改法**：训练指纹守卫——
```python
sig = (getattr(cfg, "data_yaml", ""), cfg.backbone, cfg.epochs, cfg.img_size)
if self._train_model is not None and sig == getattr(self, "_train_sig", None):
    return dict(self._train_metrics)
# ... 训练完成后：
self._train_sig = sig
```

### B-2 停止标志永不复位——停止过的引擎下次训练 1 轮即停
`models/supervised/engines/_yolo_seg_base.py:97-98,204-215`
- **现象**：`request_stop()` 置 `_stop_requested=True` 后无任何复位点；回调在第一个 epoch 结束就置 `trainer.stop=True`。
- **为什么重要**：第一次训练点过"停止"→ 同引擎第二次训练只跑 1 轮就"完成"，best.pt 是 1-epoch 产物，进度条正常走完，用户极难察觉。
- **改法**：`train_epoch` 入口 `self._stop_requested = False`（停止请求只在当次训练生命周期内有效；训练中停止不受影响——ultralytics train() 一次性整跑，request_stop 发生在入口返回后）。

> B-1/B-2 同根（实例状态生命周期），一次修复；配套回归测试：同引擎连续两次 train_epoch 断言第二次真实执行。

---

## 🟠 Should-Fix（11 项）

### 昨夜新代码（4 项，round4-fresh 实测复现）

| # | 位置 | 问题 | 改法 |
|---|------|------|------|
| F-1 | generative_metrics.py:253-256 | **L2 回退（生产默认路径，环境未装 lpips）nearest 配对下 gen≠real 张数必崩**——实测 `ValueError: broadcast (2,...) (3,...)`；既有测试两侧等长恰好遮蔽 | 回退路径改逐 gen 最近邻 MSE：`losses=[min(mean((tgt_arr-g)**2, axis=(1,2,3))) for g in gen_arr]`；补 gen≠real 用例 |
| F-2 | supervised_exporter.py:374-381 | int8 静态量化回退 `except Exception` **零日志**——用户提供的校准图全坏被静默换成动态量化（精度更差），无从排障 | 回退分支加 `logger.exception(...)`，calib_images 场景附"校准样本未生效！" |
| F-3 | supervised_exporter.py:132,146,349 | **auto input_shape 未回传**：cls 导出 224 模型但校准 reader 兜底 640——激活统计建立在错误分辨率分布上，量化精度静默劣化（det 双默认 640 才没暴露） | `_export_base_onnx` 返回 `(out_path, input_shape)` 元组；补 cls+int8 不传 shape 用例 |
| F-4 | generative_metrics.py:274-283 | nearest 全配对 **batch=1 逐次前向**：200×200=4 万次，CPU 约 7-30 分钟（主理人实测编排 2.2s+4 万次真前向），GUI 卡 10%→70% 无响应；LPIPS 支持批处理，现状慢约两个数量级 | tgt 堆叠一次，每 gen `expand` 后批量前向取 `.min()`（lead 已验证方案可行） |

### 从未审查模块（7 项，round4-uncovered）

| # | 位置 | 问题 | 改法 |
|---|------|------|------|
| S-1 | det_yolo.py:37 / pseg_yolo.py:34 / pose_yolo.py:33 / _yolo_seg_base.py:227 | `load(device=...)` 归一结果**从未作用于推理**——infer 不传 device，ultralytics 自动选设备；用户显式选 CPU（训练占显存时）被静默忽略 | load 末尾 `self._model.overrides["device"] = device` |
| S-2 | sseg_smp.py:64,84 | `strict=False` 静默加载 + **空 state_dict 的 falsy 回退**（`{} or raw.get("model") or raw` 错拿整 checkpoint）→ 权重与架构不匹配输出全错 mask 无告警，比崩溃危险 | 显式区分空 dict；missing/unexpected keys 非空时 warning |
| S-3 | cls_torchvision.py:33-48 / sseg_smp.py:57-93 | load 失败停在半初始化态：`self._model` 先赋值后 `.to(device)`/transform 构建失败 → info() 谎报 loaded=True，报错点远离根因 | 局部变量暂存，全部成功后才落位 `self._model` |
| S-4 | counter.py:55-63 + recent.py:39-44 + store.py:51-52 | project/ 三处 JSON **非原子写** + 损坏静默清零 → 计数重置 → 同名项目 seq 相同 → `makedirs(exist_ok=True)` 静默合并新旧数据（lead 实测跨实例并发 60 ID 重复 40 个同此根因）。versioning/_common 已有原子写惯例，唯独此处漏网 | mkstemp+os.replace 对齐仓库惯例；_load 损坏补 warning |
| S-5 | project/models.py:33-35 + store.py:34-47 | 项目名**零净化**：`name="../..evil"` 路径穿越逃逸 workspace 边界；Windows 非法字符直接 OSError 截断信息 | 入口 `re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,64}")` 校验 |
| S-6 | versioning.py:159-170 | 快照**双遍遍历一致性窗口**：manifest 哈希源文件（第一遍）与硬链（第二遍）之间被修改 → 快照内文件与 manifest 必然对不上 → verify 拒绝恢复，快照自毁无自愈 | 单遍遍历、对快照侧文件哈希（自洽性天然保证） |
| S-7 | abdet_anomalib.py:73-81 | anomaly_map **未 detach().cpu()**——带计算图的 GPU tensor 进 extra，长批量跑逐帧累积显存 | `anomaly_map.detach().cpu()`（与其余引擎 masks 处理对齐） |

---

## 🟡 Nit / 低优先（21 项，表格式归档）

| # | 位置 | 摘要 |
|---|------|------|
| N-1 | sam_adapter.py:106 | `shape[2] < 3` 放行 **RGBA 4 通道**（lead 实测穿透到 predictor；OpenCV IMREAD_UNCHANGED 恰产出此形态）→ 改 `!= 3` + 补 4 维用例 |
| N-2 | generative_metrics.py:29-31 | `[0,1]/[0,255]` 启发式误判 **16 位图**（/255 后值域 257）；空数组 `arr.max()` 直接 ValueError |
| N-3 | generative_metrics.py:142 | 极小样本（n=1）FID 产出伪值——E5 修了帽没修地板，eval_flow 补 <2 张 N/A 行 |
| N-4 | supervised_exporter.py:189 | Windows 固定名 tmp 并发导出同目标互踩（单进程残留已核实无碍）→ 加 pid 后缀 |
| N-5 | generative_metrics.py:283-284 | 空序列返回 0.0 被解读为"完美相似" → 改抛 ValueError |
| N-6 | geometry.py:197-202 | close_polygon 两瑕疵：已闭合+共线绕过校验；绝对阈值 1e-9 不随坐标尺度缩放 |
| N-7 | eval_flow.py:295 | model 为单文件但非图像（误选 .pt）→ E12 校验放行，PIL 打开才炸 → 补后缀校验 N/A 行 |
| N-8 | io_labelme.py:67 | L13 写出 description 但读回永不恢复——官方 LabelMe 填的描述经本工具往返即丢（docstring 至少声明） |
| N-9 | eval_flow.py:309,314 | fid/lpips 恒 device="cpu"，有 CUDA 也不用（200 张 CPU 前向数分钟） |
| N-10 | RELEASES.md | E6 混合尺寸静默 resize 未入行为变更声明（fid_score docstring 同步注明） |
| N-11 | sgan_blend.py:109 / super_cv2.py:113 | `imread_unicode` 失败返回 None 零防御 → `AttributeError: 'NoneType'` 远离根因 |
| N-12 | abdet:103 / sseg:111 | 灰度 2 维 numpy 输入 permute 崩；abdet `arr[..., :3]` 切的是宽度前 3 列（隐蔽） |
| N-13 | pose_yolo.py:49,60-66 | 理论路径 keypoints N 与 boxes=() 失配边角；回退标签用实例索引而非类别 id |
| N-14 | engines/__init__.py:38 | ImportError 只 warning 模块名无 exc_info——循环导入被吞成一行，排查靠盲猜 |
| N-15 | det_yolo.py:27-39 | load 与基类逐行相同（纯冗余覆写），删除零行为变化 |
| N-16 | versioning.py:241 | restore 覆盖前无"当前态"预快照，误恢复丢工作成果 → 开头 create_snapshot("pre-restore") |
| N-17 | versioning.py:262 | restore 双遍全量哈希 = 大项目 3 倍 IO（10GB→30GB），docstring 标注成本或 GUI 进度 |
| N-18 | cls_torchvision.py:76 | infer_batch 无 batch 上限，数千张低显存机器 OOM → 32/批分片 |
| N-19 | ocr_easyocr.py:79 | readtext 期待 RGB 而本仓读取契约恒 BGR——ndarray 直传路径识别率隐性下降 |
| N-20（lead） | generative_metrics.py:60 | **E13 缓存无生产释放通道**：cuda InceptionV3/LPIPS 在 GUI 长会话永久驻留 ~100MB VRAM（_reset_inception_cache 仅测试调用，git grep 已核实） |
| N-21（lead） | registry.py:56 | get() 无锁快路径与 clear_cache 竞争可返回已 unload 引用（use-after-unload 窗口；serving 层 H8 锁不覆盖 in-flight infer，属已知设计边界，记录在案） |

---

## 测试质量问题（4 项）

1. test_generative_metrics_stubs.py:395-412：L2 回退用例两侧等长，**恰好遮蔽 F-1**——修后补 gen≠real 用例
2. test_generative_metrics_stubs.py:324：`test_extract_features_reuses_model_within_fid` 名不副实（从未走 fid_score 编排）→ 改名或真走编排
3. test_x8_x14_exporter.py：无 auto-shape + int8 组合用例（F-3 盲区）→ 补 cls 不传 shape 断言校准 224
4. test_batch4_geometry_gt_labelme.py:40：水平边用例仅 `isinstance(bool)` 弱断言 → 用审查员实测的"底边水平凹槽"多点数值断言替掉

---

## 已核实无问题项（双路回执合并）

- benchmarks 不在生产 import 链；_DummyCalibReader 提级无残留引用；X14 tmp 覆盖/清理语义（lead 实测）；_to_numpy 量化损失 ≤1/255；_FileCalibReader with 释放与内存峰值（lead 实测 39MB）；E12 分支矩阵（lead 实测三项全过）；point_in_polygon 射线法（lead 凹多边形 5 点 + 审查员凹槽数值全对）；sam load 包装未吞 traceback；E17 生成式不提示（分布对分布无泄漏语义，正确）；scan_images sorted 无调用方破坏；versioning restore 语义正确（PRD 符合）；_safe_torch_load 白名单体系是安全亮点。

## 七维小结

| 维度 | 一句话 |
|------|--------|
| 正确性 | 两 Blocker 均为训练通道状态生命周期；F-1/F-3 是昨夜新代码的真实缺陷 |
| 错误处理 | sseg 静默错配最危险；int8 回退吞因；imread None 无防御 |
| 并发时序 | project/ 非原子写是数据完整性主险；快照双遍窗口；registry 快路径属边界 |
| 资源生命周期 | abdet GPU tensor 滞留 + E13 缓存无释放；cls/sseg 半初始化 |
| 性能 | nearest 4 万次前向 + 恒 CPU；infer_batch 无上限；restore 三倍哈希 |
| 安全 | 项目名穿越（S-5）是唯一新攻击面；其余无回归 |
| 可维护性 | 注释与决策留痕极好；det 冗余 load、弱断言测试是小毛刺 |

## 修复优先级建议

1. **第一批（Blocker+生产必崩）**：B-1+B-2（同根一次修）+ F-1 + F-3——训练通道正确性与生产默认路径崩溃
2. **第二批（数据完整性）**：S-4+S-5+S-6（project/ 一组）+ S-7
3. **第三批（性能+其余 Should）**：F-4（批处理+device）+ F-2 + S-1/S-2/S-3
4. Nit 与测试质量随批携带

---

> 本报告由第四轮双路并行审查 + 主理人 7 项实测汇编；关键结论请工程负责人复核。

---

## ✅ 修复回执（2026-10-07 晚，三批实施完毕）

| 项 | 修复 | 验证 |
|---|------|------|
| B-1 | `_train_signature(cfg)` 四元组指纹 + 同指纹才命中一次性缓存 | test_b1_same/different_signature（2 例） |
| B-2 | `train_epoch` 入口复位 `_stop_requested` | test_b2_stop_flag_reset（复位+零回调干扰断言） |
| F-1 | L2 回退 nearest 改逐 gen 最近邻 MSE（语义与主路径一致） | test_f1_l2_fallback_uneven（2v3 张不崩+语义值断言） |
| F-2 | int8 静态回退 `logger.exception` + calib 场景附"未生效"警示 | 源码级（回退路径日志） |
| F-3 | `_export_base_onnx` 返回 `(path, 有效shape)` 元组，量化链路吃到 auto shape | test_f3 2 例（224/512/256 全任务矩阵+集成 spy） |
| F-4 | `_lpips_pair_losses` 拆分：tgt 堆叠 + 每 gen 单次批量前向（4万次→200次） | test_f4（前向计数 2 + 批形状 + 语义不漂移） |
| S-1 | 四 YOLO 引擎 load 后 `overrides["device"]=device`（getattr 容错替身） | test_s1 |
| S-2 | sseg 空 state_dict 三分支 + missing/unexpected 告警（tuple 返回兼容） | device_guard 套件回归 |
| S-3 | cls/sseg load 局部暂存全链后落位（半初始化消除） | 既有套件回归 |
| S-4 | counter/recent/store 三处 `_atomic_write_json`（mkstemp+replace）+ 损坏告警 | test_s4 3 例 |
| S-5 | 项目名正则校验（防穿越/保留字符） | test_s5 2 例（6 恶意名拒绝+3 合法名放行） |
| S-6 | create_snapshot 单遍遍历+哈希快照侧文件（自洽） | test_s6 2 例（含并发改写模拟） |
| S-7 | anomaly_map `detach().cpu()` | test_s7（行为+源码静态断言双保险） |
| N-1 | set_image `shape[2] != 3`（RGBA 拒绝） | test_n1 |
| N-14 | 引擎 ImportError warning 加 exc_info | 源码级 |
| 测试质量 4 项 | stubs 批量断言修正（F-4 对齐）/ 名不副实用例改造 / auto-shape+int8 用例补齐（F-3 集成）/ 水平边数值断言（S-6 同批） | 全部随批落地 |
| W24 连带 | train_epoch 115→<100（`_train_signature`+`_extract_final_loss` 拆分）；perceptual_loss 101→<100（`_lpips_pair_losses` 拆分） | scale_guards 全绿 |

**新增测试 17 例**（test_round4_batch1_b_f.py 10 + test_round4_batch2_s.py 8，含 1 例改造）；适配既有断言 6 处。
**终态：ruff All checks passed + pytest 1485 passed / 7 skipped（2m06s）。**

