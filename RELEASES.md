# AutoVisionAgent 发布说明（RELEASES）

> 发版产物：`dist/AutoVisionAgent/`（完整版，CUDA 支持）与 `dist/AutoVisionAgent-lite/`（CPU 版，<2GiB）。
> 升级建议：覆盖安装前备份 `configs/`（users.json / user_settings.json）与项目工作区。

## v2.2.0（工程审查清偿波）· 2026-10-06

自 v2.1.0（M3）以来的变更——两轮全面工程审查（core/serving/gui/training/dataset/inference，84 项发现）+ 六批修复 + 三项基建。

### ⚠️ 行为变更（升级必读）

- **Detect threshold 改 proto3 optional presence**：显式 `threshold=0.0`（工业低阈值/全召回）此前被 proto3 标量语义当"未设置"回退默认 0.5，现在正常生效。**C# 客户端**：`Detect*` 系列 threshold 参数升级 `float?`——传 `null` 表示不设置（服务端用引擎默认），显式值（含 0）正常传输；旧调用方零改动兼容
- **未知任务名 fail-closed（ADR-0006）**：Detect/LoadModel 收到未知 task 此前静默回退目标检测（fail-open），现在返回 `INVALID_ARGUMENT`（C# `MapTaskType` 抛 `ArgumentException`）。"vlm" 等 Python 侧不存在的任务名已从 C# 映射移除，sseg/sgan/super 已补
- **数据集导出默认 train/val 分层划分（8:2）**：`labelme_dir_to_yolo` 默认按类别分层划分到 `images/{train,val}` 子目录——**mAP 不再在训练集上计算**（此前 train=val 同目录，指标虚高）。`val_ratio=0` 保持旧单目录布局（兼容逃生门）。存量数据集重新导出后训练指标会**真实下降**，这是修正而非退化
- **损坏标注不再静默降级**：标注 JSON 损坏的样本此前降级为"无缺陷"负样本进训练（正样本被当背景教坏模型），现在跳过该样本并留痕
- **UnloadModel 元数据一致（ADR-0005）**：卸载后 `Ping.loaded_tasks`/`GetTaskInfo.loaded` 立即同步（此前恒报 loaded=True）
- **serving RPC 审计接入**：LoadModel/UnloadModel/Detect 成功失败均记 `serving_rpc` 审计事件（此前 gRPC 路径零审计）

### 安全加固

- **FetchRegion 任意文件读取封堵（S1）**：共享内存读取加白名单（shm 目录 + `ava_*.bin` 双条件），白名单外路径统一 NOT_FOUND（fail-closed 防路径探测）；`AVA_SHM_ALLOW_ANY_FILE=1` 逃生门
- **恶意 RLE OOM 防护（S2）**：掩码解码三道闸（元素上限 2^30 / 4 字节对齐 / 负游程拒绝 + int64 求和防回绕）；`AVA_MASK_RLE_MAX_ELEMENTS` 可调
- **LoadModel 权重路径白名单（H1）**：`AVA_MODEL_ROOTS` 环境变量（os.pathsep 分隔）配置允许根；未配置回退项目根/当前目录（开发态），生产部署应显式收紧

### 训练可信度（三部曲 + 收尾）

- train/val 分层划分（见行为变更）+ **真 resume**（ITrainStrategy.load_state 权重实际装载；策略不支持时明确告警"从随机权重续训"）+ 随机种子控制（TrainConfig.seed，统一 random/numpy/torch/cuda）
- resume 后 LR 调度器步数回放（Cosine 相位连续）；早停优先监控 val_loss（一次性适配器不再误触发）
- metrics.jsonl 逐 epoch 落盘（中断不丢历史）；checkpoint 原子写（.tmp + rename）
- 推理中禁止更换模型（use-after-unload 防护）；停止训练不再冻结 UI 5 秒；单张推理结果请求 ID 守卫

### 工程与质量

- 门禁 1102→**1346 用例**（+244）；全量 92% 覆盖率门禁通过；core 包 91.2%→93.6%
- **覆盖率棘轮地板**（scripts/coverage_floors.py，per-package 只升不降）+ proto 生成物对账（gen_proto.py --check）双双接入 CI
- 线程契约文档（docs/threading-contract.md：五条契约 + PR 审查检查单）
- 规模守卫三次真实拆分（labelme_dir_to_yolo / tile_infer / predict 页 ExportActionsMixin）；i18n 完整性保持（新词条全配 en_US）
- 共享内存 H 簇修复：部分写循环（防 SIGBUS）、TOCTOU 锁内拷贝、负 offset 校验、端口绑定失败显式报错（防假启动）
- image_io PIL 回退统一 BGR（消除同函数双通道语义根因）；批量产物 stem 哈希去重（跨目录同名不覆盖）

## v2.1.0（M3）· 2026-08-23

自 v2.0.0（M2）以来的变更——SKolpha 3.3.2 对标九波（W26–W34）+ 架构复审 v5 清偿波（W35/W36）。

### 新功能

- **角色权限**：admin/engineer/operator 三角色登录后按矩阵过滤导航可见性；被拒访问留审计痕；动作级门控（批量推理/批量预标注/视频超分）落地（操作护栏非安全边界）
- **推理阈值与对象过滤**：推理页阈值旋钮（单张+批量生效）+ 对象类型过滤（逗号分隔）——SKolpha「阈值+对象类型」双参对标完成
- **文件夹批量预标注**：目录→逐图 DET 推理→LabelMe JSON（imagePath 相对路径）；坏图跳过留痕、可取消、manifest 汇总
- **OCR 文字识别（可选任务）**：easyocr 引擎（ch_sim+en）；离线权重供给脚本 `scripts/fetch_ocr_weights.py`；lite 版不含（可安装后启用）
- **批量产物补齐**：分割 masks RLE 持久化（可解码恢复）+ 可选叠加结果图
- **逐帧视频超分**：VideoCapture→super 引擎→mp4v（帧数保持，分辨率随引擎倍数）
- **主页最近项目/检测历史**：登录后自动刷新（此前恒空）
- **AMP 混合精度预检**：训练前 cuda fp16 探针，失败自动回退 FP32 并警告

### 修复

- 打包态推理引擎加载必败（spec 误剔 matplotlib）——P0 级修复；PYZ 清场（pytest/pydub/web 栈误打包 -355 模块）
- AI 预标注冷启动诚实化：未加载权重明确提示（不再静默失败）；引擎失败与零检出区分反馈
- 批量推理落盘卫生：取消不再写空/截断 JSON（含显式取消反馈）；无项目时结果回退 workspace 不污染数据集
- flaw_gen 三处清理（过期横幅/死下拉/硬编码 CPU）
- i18n：补 22 处漏翻（en_US 零中文残留）+ 完整性机械守卫

### 工程与质量

- 门禁 996→1102 用例；页面规模守卫（≤800）三次拦截并抽取；五方打包一致性守卫
- lite 体积 1.9935GiB（剪除 easyocr 及独占依赖）；版本宣称与文档统一
- 架构复审 v5（回归轮）：v4 十二项核销 10 闭环；四条 P2 全部清偿或根治
- 已知待办：~~UIA 全量 12/12 空闲机取证~~（W40 python 模式 12/12 + W46·C 打包 exe 15/15 + W49 19/19 已补做，2026-08-24~30）；真机 cuda/OCR 离线权重端到端验证（需目标硬件）仍开放

## v2.0.0（M2）

初版双范式基线（详见仓库历史）。
