# SKolpha 能力复刻立项 — 实现方案设计文档

> 版本: 1.0 | 日期: 2026-09-02 | 关联 PRD: docs/prd-skolpha-replication.md v1.0 | 档位: 🔴 L3 | 门禁: S3 自主留痕（本会话无 AskUserQuestion）
> 取证依据: docs/skolpha-forensics-wave2.md §6（复刻映射建议）；AVA 现状锚点见各节 inline。

---

## 1. 设计概述

### 1.1 核心设计思路

差距驱动增量复刻：不做平行体系，全部落在 AVA 既有框架上——标注形态走 `labeling/modes/` 注册表模式（与 2026-09-01 裁剪同一链路反向新增）、训练模板走纯函数 loader + 页面回填、工程绑定走 project store 可选段、预测模式走 batch_runner 扩展、数据工具走纯函数 + Mixin。**页面文件已达 W24 ≤800 守卫边缘（predict 784/data_manage 792），一切新 UI 动作外置 Mixin/子模块**（先例：gui/pages/predict/video_super_actions.py）。

### 1.2 设计原则
- 复用既有模式先例（模式注册/jobs 调度/原子写/resolve_device/ui_on_error）；每个新模块独立小文件（200-400 行惯例）；错误显式上抛不静默；SKolpha 反面教材不带入（无硬编码密钥、无加密、无重依赖）。

### 1.3 架构图（增量视角）

```
labeling/base.py(AnnotationMode +2) ─ modes/cut_line.py + modes/operation.py
        └→ io_labelme 映射 ↔ gui/pages/label（工具栏+2 按钮）
training/train_templates.py(loader 纯函数) ← configs/train_templates/*.yaml(明文)
        └→ gui/pages/train/page.py(模板下拉+回填) ─→ TrainConfig(+augmentation 段)
project/store(+可选三段) ─→ predict 页带出 / label 页 transferType 联动
gui/pages/predict/batch_runner.py(模式+并发) + inference/api_client.py(纯函数)
gui/pages/data_manage/tools_actions.py(Mixin) ─→ project/label_tools.py(纯函数)
```

---

## 2. 方案评估

### 2.1 备选方案

**方案 A: 差距驱动增量复刻（在既有框架上补 8 项差距）** ⬅ 推荐
- 描述: 如 §1.1，逐 FR 落地，每波独立验收。
- 优点: 零架构风险；复用测试/守卫/spec 全链路；可逐波回滚。
- 缺点: 部分能力与 SKolpha 实现形态不同（如训练无子进程隔离，FR-009 缓解）。
- 适用: 现状（AVA 成熟度已高，只差能力点）。

**方案 B: 照抄 SKolpha 架构（mm 系引擎+子进程训练+加密工程+双标注器）**
- 优点: 行为与原品逐点一致。
- 缺点: 引入 mmcv/mmseg/mmdeploy 重依赖（lite 2GiB 必爆）、PyQt5 双框架、labelme fork 维护面、加密反面教材。
- 适用: 无（明确否决——PRD §7.2 Out of Scope）。

**方案 C: 仅做用户点名 2 项（切割线/操作标注+批量模式），其余不立项**
- 优点: 最小工作量。
- 缺点: 违背「所有能力」指令意图（S1 范围）；训练模板/工具集/工程绑定真差距悬空。

### 2.2 方案对比
| 维度 | 方案 A | 方案 B | 方案 C |
|------|--------|--------|--------|
| 实现复杂度 | 中 | 高 | 低 |
| 性能影响 | 低 | 中 | 低 |
| 可维护性 | 高 | 低 | 高 |
| 风险等级 | 🟢 | 🔴 | 🟡 |
| 对现有代码的侵入性 | 低 | 高（框架级） | 低 |

### 2.3 最终选择及理由
选择方案 A。差距矩阵显示 AVA 引擎/页面/项目框架已承载 SKolpha 90% 能力面，增量补 8 项即可能力对齐且不引入技术债；B 的行为级一致无业务价值（用户要的是能力不是实现形态）；C 违背显式指令范围。

### 2.4 多视角交叉评审纪要
N/A（未启用深度并行规划——取证已由 wave1/wave2+codegraph 完成，无并行探索纪要可引）。单代理自评留痕：**架构**——新形态/模板/工具均挂既有注册表与纯函数层，无新横向依赖；**安全**——apiKey 仅环境变量/凭据文件+gitignore（wave1 §5 反面教材直接输入）；**性能**——并行批量竞态面是唯一高危点，默认串行+后处理层并行+原子落盘复用（§7.1）；**存量**——TrainConfig/AnnotationMode 增量成员走五方消费方核查（tasks W56-0 前置任务）。

---

## 3. 文件变更清单

| 文件路径 | 操作 | 变更内容 | 关联需求 |
|----------|------|----------|----------|
| `labeling/base.py` | 修改 | AnnotationMode +CUT_LINE/OPERATION 两成员 | FR-001/002 |
| `labeling/modes/cut_line.py` | 新建 | CutLineLabeler（折线，≥2 点提交） | FR-001 |
| `labeling/modes/operation.py` | 新建 | OperationLabeler（矩形/多边形区域，标签=操作名） | FR-002 |
| `labeling/modes/__init__.py` | 修改 | 注册两新模式（`__all__` 自动生长） | FR-001/002 |
| `labeling/canvas.py` | 修改 | 切割线虚线渲染分支 | FR-001 |
| `labeling/io_labelme.py` | 修改 | CUT_LINE↔`linestrip`、OPERATION↔原生形态+`operation:true` 往返映射 | FR-001/002 |
| `gui/pages/label/page.py` | 修改 | 工具栏 +2 按钮/快捷键 C/O（现 5 按钮位） | FR-001/002 |
| `gui/pages/label/page.py`（transferType） | 修改 | 项目打开时按 transferType 预设默认形态 | FR-005 |
| `gui/pages/predict/batch_runner.py` | 修改 | 逐张即时模式+并发选项（ThreadPool 仅后处理） | FR-003 |
| `gui/pages/predict/batch_actions.py` | 新建 | 模式/并发 UI 动作 Mixin（page.py 已 784 行，外置） | FR-003 |
| `training/train_templates.py` | 新建 | 模板 loader 纯函数（load/validate/merge，<150 行） | FR-004 |
| `configs/train_templates/*.yaml` | 新建 | ≥9 任务×≥1 变体（初值取自解密 TrainConfigs） | FR-004 |
| `core/interfaces_supervised.py` | 修改 | TrainConfig +augmentation 子段（带默认值） | FR-004 |
| `gui/pages/train/page.py` | 修改 | 模板下拉+回填；增强参数进 `train_augment_actions.py` 新 Mixin | FR-004 |
| `project/store.py`（FileSystemProjectStore） | 修改 | 可选三段读写（predictionParams/transferType/dataPath） | FR-005 |
| `gui/pages/predict/page.py` | 修改 | 项目绑定「带入模型+阈值」动作（挂 batch_actions Mixin） | FR-005 |
| `project/label_tools.py` | 新建 | 标签统计/替换/删除纯函数 | FR-006 |
| `gui/pages/data_manage/tools_actions.py` | 新建 | 数据工具 Mixin（对话框+run_job 调度） | FR-006 |
| `inference/api_client.py` | 新建 | HTTP API 推理纯函数（requests，显式契约校验） | FR-007 |
| `gui/pages/predict/api_actions.py` | 新建 | API 推理源 UI 动作 Mixin | FR-007 |
| `tests/test_w56_label_modes_industrial.py` 等 | 新建 | 每波 TDD 测试（见 §9） | AC 全 |
| `autovisionagent.spec` | 修改 | hiddenimports + 新模块（PYZ 守卫口径） | AC-009 |
| `gui/core/i18n.py` | 修改 | 新增双语键（无死键） | AC-009 |

---

## 4. 组件详细设计

### 4.1 标注两形态（FR-001/002）

**职责**: 工业专属形态绘制与持久化，交互范式与既有形态完全一致。

**接口定义**:
```python
# labeling/modes/cut_line.py
class CutLineLabeler(AbstractLabeler):
    """切割线标注（快捷键 C）：折线，≥2 点，右键/回车提交。"""
    mode = AnnotationMode.CUT_LINE
    def __init__(self, label: str, color: RGBA = DEFAULT_COLOR, **_options) -> None: ...
    def commit(self) -> Shape | None: ...   # len(points)>=2 才成形状

# labeling/modes/operation.py
class OperationLabeler(RectangleLabeler):
    """操作标注（快捷键 O）：矩形区域 + 操作名标签（复用标签输入）。"""
    mode = AnnotationMode.OPERATION
```
（OperationLabeler 继承 RectangleLabeler 仅换 mode——操作区域以矩形为主；若实机核对为多边形再扩。）

**落盘映射**（io_labelme）：`CUT_LINE → shape_type="linestrip"`（labelme 原生，跨工具可读）；`OPERATION → shape_type="rectangle"` + shape 级附加字段 `"operation": true`（labelme 允许额外键；loader 读到该字段还原 OPERATION，无字段按普通矩形读——向后兼容）。

**依赖项**: `labeling/modes/_base.py` AbstractLabeler（现状锚点：rectangle.py:15 同基类）。
**错误处理**: 单点提交→静默忽略（同矩形 MIN_SIZE 误触保护语义）；落盘未知形态→既有 loader 诚实跳过路径。
**状态管理**: 无状态（与既有 Labeler 同）。

### 4.2 批量预测模式扩展（FR-003）

**职责**: 逐张即时/整批两模式 + 并发选项；page.py 不增行（动作全部进 `batch_actions.py` Mixin）。

**接口定义**:
```python
# gui/pages/predict/batch_runner.py（扩展现有函数签名）
def run_batch(
    paths: list[str], engine, mode: str = "batch",   # "batch"|"incremental"
    concurrency: int = 1, on_row=None, on_progress=None, should_stop=None,
) -> None: ...

# inference 侧并发：ThreadPoolExecutor(max_workers=concurrency) 仅包裹
# 「图像 IO+引擎 infer」以外的后处理（渲染/产物写）；引擎调用本身串行
# （线程安全口径：同引擎实例不并发前向）。
```
**关键决策**: 并发只做 IO/后处理并行，引擎前向保持串行——规避模型线程安全与显存竞争；「逐张即时」= 每张完成后立即 on_row 回调（现有 batch 已逐行回调，差距实为 UI 侧「边推边显示+可中途追加文件」的窗口行为，Mode 切换改的是结果聚合时机与 batch_results.json 落盘时机：incremental 模式每 N=10 张滚动落盘）。
**依赖项**: gui/core/jobs.py run_job（协作取消/异常路由）；core 既有 temp+os.replace 原子写。
**错误处理**: 单图失败不炸整批（既有语义）；并发异常聚合上报。

### 4.3 训练模板体系（FR-004）

**职责**: 明文 YAML 模板加载/校验/合并；训练页选择回填。

**接口定义**:
```python
# training/train_templates.py
@dataclass(frozen=True)
class TrainTemplate:
    task: TaskType
    variant: str                     # normal/small/large...
    backbone: str
    img_size: int
    augmentation: AugmentationConfig # hflip/vflip/rotate_max/translate/
                                     # crop_scale/mean/std/split_ratio/data_expansion

def load_templates(dir_path: str) -> dict[tuple[str, str], TrainTemplate]: ...
def validate_raw(raw: dict) -> list[str]: ...   # 未知字段名清单（诚实告警）
```
**数据来源**: 初值字典提取自解密后的 SKolpha TrainConfigs（%TEMP%/skolpha-forensics 工具链 decrypt_skolpha.py 复用，只读取证——任务 W57-1 执行）。
**TrainConfig 扩展**: `augmentation: AugmentationConfig | None = None`（None=旧行为，五方消费方核查后合入）。
**错误处理**: 模板文件损坏→跳过+WARNING 清单；任务码无模板→内置默认（现 _TRAIN_PRESETS 值）；未知字段→状态栏告警不中断。

### 4.4 工程绑定三段（FR-005）

**职责**: project 记录可选三段读写 + 页面联动。
**接口定义**: FileSystemProjectStore 增加 `get_binding(pid)/set_binding(pid, binding: ProjectBinding)`；`ProjectBinding` dataclass：`model_file: str = ""`、`threshold: float | None = None`、`transfer_type: str | None = None`（"Rect"|"Polygon"|None）、`data_path: str = ""`。
**兼容性**: 旧记录无该文件/字段→全默认值（缺段读侧 isinstance/形状收口——吸取 W24 sweep 教训）。存储为项目目录内明文 `binding.json`（**不做加密**；与 .spro 五段对齐但格式自主）。
**联动**: label 页打开时 transferType="Rect"→默认 RECTANGLE、"Polygon"→默认 POLYGON；predict 页「从项目带入」按钮填 modelFile/threshold。

### 4.5 数据工具集（FR-006）

**职责**: 纯函数工具 + data_manage Mixin（页面 792 行，零增行）。
**接口定义**:
```python
# project/label_tools.py
def label_statistics(json_dir: str) -> dict[str, dict]: ...      # {label: {count,total_area,...}}
def replace_labels(json_dir: str, old: str, new: str) -> Report: ...
def delete_labels(json_dir: str, name: str) -> Report: ...
# Report: dataclass(rewritten, skipped, failed, backup_dir)
```
**规则**: 只认 LabelMe JSON（`shapes` 键）；改写=同目录 `.bak` 备份 + temp+os.replace 原子写；空 shapes 残留在 Report 中警示。
**调度**: Mixin 内 run_job（后台+取消+on_error 兜底）。

### 4.6 HTTP API 推理（FR-007）

**职责**: 远端推理纯函数 + predict 页 API 源。
**接口定义**:
```python
# inference/api_client.py
def infer_remote(endpoint: str, image_path: str, timeout: float = 30.0,
                 api_key: str | None = None) -> DetectionResult: ...
# POST multipart 图像；响应契约 {"boxes":[[x1,y1,x2,y2],...],
#  "labels":[...], "scores":[...], "task": "det"}；缺键/类型不符→ApiInferError
def resolve_api_key() -> str | None: ...   # AVA_API_KEY env > configs/api_key.txt(gitignored)
```
**安全**: api_key 不入日志（异常文案只含 endpoint+状态码）；configs/api_key.txt 进 .gitignore（W23 initial_credentials 同型防呆——元守卫 pathspec 一并加）。
**错误处理**: 超时/ConnectionError/非 200/契约不符四分支显式中文文案。

---

## 5. 数据模型

### 5.1 数据结构
```python
class AnnotationMode(Enum):        # labeling/base.py（5→7）
    POLYGON, RECTANGLE, INTERACTIVE, REGION_SAM, EDIT, CUT_LINE, OPERATION

@dataclass(frozen=True)
class AugmentationConfig:           # core/interfaces_supervised.py
    hflip: float = 0.5
    vflip: float = 0.0
    rotate_max: int = 10            # SKolpha my_max_rotate 对标
    translate: float = 0.1
    crop_scale: tuple[float, float] = (0.8, 1.2)
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)
    split_ratio: float = 0.8        # SKolpha my_endSplitData=0.8 对标
    data_expansion: int = 0         # SKolpha my_data_expansion 对标

@dataclass
class ProjectBinding: ...           # 见 §4.4
```

### 5.2 数据流转（训练模板）
```
configs/train_templates/*.yaml → [load_templates] → TrainTemplate
  → UI 下拉选择 → 表单回填 → 用户覆盖 → TrainConfig(含 augmentation)
  → GenericTrainer.fit（引擎 train_epoch 消费或忽略增强段——按引擎能力诚实降级提示）
```

### 5.3 验证规则
| 字段 | 规则 | 错误提示 |
|------|------|----------|
| 模板 task 码 | ∈TaskType 枚举值 | 「模板任务码无效：{code}（已跳过）」 |
| augmentation.split_ratio | (0,1) 开区间 | 「split_ratio 须在 0~1 之间」 |
| transfer_type | Rect/Polygon/空 | 「transferType 取值无效，忽略」 |
| 并发数 | 1-4 | 并发微调控件 setRange 硬约束 |

---

## 6. 集成设计

### 6.1 与现有代码的集成点
| 集成点 | 现有模块 | 集成方式 | 兼容性处理 |
|--------|----------|----------|------------|
| 模式注册 | labeling/modes/__init__ 工厂 | 新增注册项（裁剪链路反向） | `__all__` 自动生长；spec 守卫口径同步 |
| 批量调度 | gui/core/jobs.run_job | 沿用（取消/异常路由） | 无签名变更 |
| 项目存储 | project/ FileSystemProjectStore | 新增 binding.json 可选文件 | 旧项目无文件→默认值 |
| 引擎消费 | TrainConfig.augmentation | None 默认=零行为变化 | 五方消费方核查先行（W56-0） |
| UIA | tests/uia 既有 12 用例 | 新增 1 用例（切割线标注硬断言） | 既有用例零改动预期 |

### 6.2 事件与触发器
- `transferType 联动`: project_opened 信号 → label 页预设默认形态（无项目打开时不干预）。
- `模板选择`: cmb_template.currentIndexChanged → 回填表单 → 状态栏提示模板名。

### 6.3 配置与国际化
- 新增配置: configs/train_templates/（入仓模板=内置资产）；configs/api_key.txt（**gitignore**）。
- i18n: 新键 ≈25 条双语（切割线/操作标注/批量模式/模板/工具/API 全套文案）。

---

## 7. 边界条件与异常处理

### 7.1 边界条件清单
| 场景 | 条件 | 预期行为 | 关联需求 |
|------|------|----------|----------|
| 切割线单点提交 | len(points)<2 | 忽略（不生成 Shape） | FR-001 |
| 并行批量取消 | should_stop()=True | 在飞任务收敛后退出，JSON 落已完部分 | FR-003 |
| 模板目录为空/损坏 | load_templates | 空表+WARNING，UI 回退内置预设 | FR-004 |
| 旧工程无 binding | get_binding | 全默认值不报错 | FR-005 |
| 工具目录无 JSON | label_statistics | 空报表+「未发现 LabelMe JSON」 | FR-006 |
| API 契约不符 | 缺 boxes 键 | ApiInferError 具体指出缺键 | FR-007 |
| 并发写 batch_results.json | incremental 滚动落盘 | temp+os.replace 原子（既有机制） | FR-003 |

### 7.2 降级策略
- 模板缺失→内置 `_TRAIN_PRESETS` 值；引擎无增强消费→训练日志提示「当前引擎忽略增强参数」（诚实降级）；API 推理失败→本地引擎路径完全不受影响。

---

## 8. 性能设计

### 8.1 性能预期
| 操作 | 预期耗时 | 瓶颈分析 | 优化手段 |
|------|----------|----------|----------|
| 并行批量（IO 后处理）50 图 | ≤串行基线 | 引擎前向占大头 | 并行仅后处理层，N≤4 |
| 模板加载 | <100ms | YAML 解析×N 文件 | 启动时一次性加载缓存 |
| 标注两形态交互 | <16ms/事件 | 与多边形同路径 | 事件路径零新增计算 |

### 8.2 资源预估
- 磁盘: train_templates ≈10KB 级；内存增量 ≈0（模板 dataclass 微量）；lite 零新增依赖零体积增量（实测守卫把关）。

### 8.3 优化策略
incremental 模式滚动落盘节流（每 10 张或 2s 取先到）。

---

## 9. 测试策略

### 9.1 测试范围
| 测试类型 | 覆盖组件 | 测试要点 | 优先级 |
|----------|----------|----------|--------|
| 单元测试 | modes/cut_line+operation、io_labelme 映射、train_templates、label_tools、api_client、ProjectBinding | 提交边界/roundtrip/校验规则/原子写/四错误分支 | 必须 |
| 集成测试 | batch_runner 两模式、train 页回填、project→predict/label 联动 | 取消语义不回归/表单反映/兼容旧工程 | 必须 |
| UIA 回归 | label 页新形态标注 | 切割线硬断言用例 1 条（真窗） | 按需（发版窗） |
| 回归 | 全量主门禁 | fail-under 92、既有批量/标注用例零改动 | 必须 |

### 9.2 测试用例设计
```
用例1: CutLineLabeler 3 点提交→Shape(mode=CUT_LINE, len=3)；1 点提交→None [FR-001]
用例2: CUT_LINE 落盘→重读 roundtrip；linestrip 无附加字段被旧版读为 CUT_LINE 之外也不炸 [FR-001]
用例3: OPERATION 落盘含 "operation":true→重读还原；无字段矩形读为 RECTANGLE [FR-002]
用例4: incremental 模式中途取消→JSON 含已完成部分、进度条复位、按钮恢复 [FR-003]
用例5: 并发=4 与串行同集结果一致（集合比较，允许顺序差）[FR-003]
用例6: 模板含未知字段→validate_raw 报告、回填仍成功 [FR-004]
用例7: 旧项目目录无 binding.json→get_binding 全默认；写后重读一致 [FR-005]
用例8: replace_labels 生成 .bak、内容往返、Report 计数正确 [FR-006]
用例9: mock 503/超时/缺键三分支→ApiInferError 文案含 endpoint [FR-007]
```
TDD 原则: 每波先 RED（上述用例失败）再 GREEN（实现）再 REFACTOR；守护测试增量生长（每波给 W 守卫加一行，末任务翻全集断言——FB-016）。

### 9.3 Mock / Stub 策略
- api_client: 本地 http.server 线程 mock（同 W-先例 conftest 风格）；引擎: 既有 FakeAdapter 惯例；并发一致性: 临时目录+确定性小图集。

---

## 10. 需求覆盖追溯

| PRD 需求 | 设计章节 | 实现方式 |
|----------|----------|----------|
| FR-001 | §4.1 | CutLineLabeler + linestrip 映射 |
| FR-002 | §4.1 | OperationLabeler + operation:true 属性 |
| FR-003 | §4.2 | batch_runner 模式参数 + 后处理层并发 |
| FR-004 | §4.3/§5.2 | train_templates loader + YAML + augmentation 段 |
| FR-005 | §4.4 | ProjectBinding + binding.json + 双页联动 |
| FR-006 | §4.5 | label_tools 纯函数 + tools_actions Mixin |
| FR-007 | §4.6 | api_client 纯函数 + api_actions Mixin |
| NFR-001 | §8.1 | 并行不劣化硬门 + 计时断言 |
| NFR-002 | §6.1 | 兼容性表 + lite 实测守卫 |
| NFR-003 | §4.6 | env/凭据文件 + gitignore + 日志零明文 |
| NFR-005 | §1.1 | Mixin 外置硬约束（≤800 行守卫） |
| AC-001..010 | §9.2 + Tasks 末任务 | 逐 AC 验证点映射（见 tasks 文档） |

---

## 11. 待确认事项
- [ ] D-1 复刻分级表（PRD §3.1/§7.2）——用户裁决
- [ ] D-2 StyleGAN3 训练不立项——用户确认（默认不做）
- [ ] D-3 FR-009 子进程隔离优先级——用户裁决（默认 P2）
- [ ] D-4 批量线程模式语义实机核对（AC-010）——用户配合 SKolpha 实机
- [ ] OPERATION 形态主矩形还是多边形——实机核对后定稿（设计按矩形先行）

---

## 附录

### A. 参考代码
- `labeling/modes/rectangle.py`（Labeler 模式范本）；`gui/pages/predict/video_super_actions.py`（Mixin 外置范本）；`gui/pages/predict/workers.py:110`（产物原子写范本）；`gui/core/jobs.py`（run_job 调度）。

### B. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 1.0 | 2026-09-02 | 初始版本（L3 立项） | Claude |

---

## 自检（9 项）
- [x] 完整性: FR-001..007 全有设计章节（§10 追溯表）
- [x] 方案对比: §2 三方案+选择理由
- [x] 接口明确: §4 六组件签名+类型标注
- [x] 影响可控: §3 文件清单 23 项全覆盖
- [x] 异常覆盖: §7.1 边界表 7 场景
- [x] 性能达标: §8 引用 PRD §4.1
- [x] 向后兼容: §6.1 集成兼容列+§4.4 缺段默认
- [x] 测试策略: §9 范围/用例/Mock 齐
- [x] 可追溯: §10 矩阵无遗漏

## ✅ 门禁（Phase 2 · S3 自主留痕）
- [x] 出示物=本文档（可回滚 docs 落盘）；用户复核翻案权保留，与门禁 4 合并披露
