# AutoVisionAgent 发布说明（RELEASES）

> 发版产物：`dist/AutoVisionAgent/`（完整版，CUDA 支持）与 `dist/AutoVisionAgent-lite/`（CPU 版，<2GiB）。
> 升级建议：覆盖安装前备份 `configs/`（users.json / user_settings.json）与项目工作区。

## v2.2.0 · 2026-09-02

自 v2.1.0 以来的变更——SAM3 深水区（W37-W55 概览，详见 git 历史）+ **SKolpha 3.3.2 复刻程序全量落地（W56-W60）** + 发版窗收尾（W61）。

### SKolpha 复刻程序（W56-W60，L3 立项 docs/prd-skolpha-replication.md）

- **标注工业两形态**：切割线（C 键，开放折线≥2 点、虚线渲染、labelme linestrip 跨工具互操作）+ 操作标注（O 键，矩形区域+操作名）；枚举 5→7，EDIT 顶点编辑面同步扩展（折线拖点/矩形角点改尺寸）
- **批量预测双模式**：整批完成（W28 取消跳写语义不变）+ 逐张即时（每张入表、每 10 张或 2s 滚动原子落盘、运行中重扫目录支持中途增删文件、取消保留已落盘）；并发选项 1-4 仅后处理层并行（引擎前向恒串行，基线 0.96x 不劣化）
- **任务级训练模板**：configs/train_templates/ 11 份明文 YAML（初值取自 SKolpha 解密产物换算）+ 容错 loader + TrainConfig.augmentation 段 + 训练页模板回填/增强面板/「当前引擎忽略增强参数」诚实提示
- **工程参数绑定**：project/binding.py（.spro 三段明文对标：modelFile/threshold/transferType/dataPath）；创建项目即写默认绑定（分割系 Polygon）；预测页「从项目带入/保存绑定」；标注页 transferType 联动默认形态
- **S_Tools 数据工具**：存量三件补缺（.bak 改写备份/删除致空警示/统计含面积分布）+ 次批三件（裁剪数据集图+标注配对瓦片/照片尾缀批量修改/数据清洗可逆隔离 _trash）
- **HTTP API 推理源**：endpoint+Bearer 密钥（env AVA_API_KEY > configs/api_key.txt，零日志回显，gitignore 防呆）；四分支诚实报错；完成链复用单张推理
- **明确不复刻**：Fernet 硬编码密钥加密（反面教材）、mm 系/nncf 重依赖、PyQt5/labelme fork、StyleGAN3 训练；FR-009 子进程隔离/FR-010 超分训练评估缓办（全仓零引擎实现 train_epoch，PRD §3.1 裁决记录）
- 复核修复轮（1H+4M+3L）：模板 loader 启动链收口/API 契约收口/模板增强段断链接通/旧 keypoint JSON 诚实跳过/统计容错等

### SAM3 深水区（W37-W55，概览）

SAM3 权重 spec datas 自动打包与约定目录发现、点击/紧框口径实测定型（0.546/0.755）、松框悬崖四轮证伪终裁（维持 W53 形单发）、顶点细化与 E 键编辑模式、全图网格盒全覆盖+诚实降级；标注模式裁剪（9→5 形态，极柱工作流收缩）；规则债务清偿（ruff 棘轮归零）。详细逐波见 git log。

### 工程与质量（W61 发版窗）

- exe 重打包（PYZ 全新模块核验）+ lite 派生 1.980GiB（<2GiB 预算，零净增量）
- UIA 套件 23 用例（新增切割线 linestrip 铁证用例；编辑模式用例按自注解除仅源码守卫）
- 批量并发 benchmark 基线落档（docs/benchmarks/batch-concurrency-baseline-w61.md）
- CI：双远端 push 触发；test job 自 08-31 起红（先于本程序，含 88f1fb5 等历史提交）——失败步为 pytest 覆盖率门禁步（注记级取证仅 exit 1 无测试名）；本地全绿+CI 环境差仿真（无 weights/user_settings，嫌疑文件 134 绿）未复现；根因需日志级取证（owner PAT 已过期），留档待网络窗复核

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
- 已知待办：UIA 全量 12/12 空闲机取证；真机 cuda/OCR 离线权重端到端验证（需目标硬件）

## v2.0.0（M2）

初版双范式基线（详见仓库历史）。
