# PRD：W30 文件夹批量预标注（L2 · 精简）

> v1.0 · 2026-08-22 · 上游：计划 W30 节（已批准）· 档位 🟡L2 · 门禁代偿同 W28/29
> 定档：高确定 × 大影响（写盘产物位置约定与 W33 共享）

## FR
- FR-1 worker（Qt-free `gui/pages/label/batch_prelabel.py`）：目录→逐图 DET 推理→LabelMe JSON；预检查 loaded（W28 语义）；坏图跳过+记录；取消停当前图（manifest 记 cancelled）；零检出照样写空 shapes JSON
- FR-2 产物共享约定：{项目根 or workspace}/results/autolabel_{ts}/（镜像 batchPredict；标注页无项目态→workspace 根，不污染被扫描目录）；manifest.json 原子写
- FR-3 页面：批量预标注按钮 + run_job 协作取消 + 完成态三槽（完成/取消/失败）
- FR-4 permissions：label.batch_prelabel 三角色登记
- FR-5 i18n zh+en 同 commit

## AC
N 图→N JSON+manifest ✓ 取消停第 k 张 ✓ 坏图跳过记录 ✓ 未加载引擎诚实 raise ✓ 约定镜像+回退 ✓ action 三角色 True ✓ 页面接线+预检诚实 ✓

## 范围外：masks/seg 预标注（W33 产物机制）、UIA 专项（空闲机取证批次）
