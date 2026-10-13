# 单人开发者自审清单（commit 前走查）

> 来源：工程保障团队 2026-10-07 方案（Cody 设计）。
> 用法：档 A 每次 commit 必走（30 秒）；档 B 在 feat/fix 触碰相关高风险域时走（3 分钟）。
> 所有判例锚点均取自本项目真实历史，非通用清单。

## 档 A：30 秒快扫（每次提交必走，8 条）

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 1 | 提交只做一件事？类型标注（feat+test / fix+test / docs / test / chore）与内容相符？feat/fix 有对应 test（项目惯例成对）？ | 提交史全量 feat+test 成对 |
| ☐ | 2 | 本机 `bash scripts/check-gate.sh` 全绿（ruff 0 / 命名 / 主门禁），而非只信 CI？ | check-gate 三段制 |
| ☐ | 3 | 无调试残留：print / pdb / breakpoint / 注释掉的旧代码 / 空 except 占位？ | — |
| ☐ | 4 | 无硬编码：绝对路径（e:\、C:\Users）、本机用户名、密钥/密码字面量？路径一律仓锚或环境变量？ | W55：12 脚本去绝对路径→仓锚+AVA_POLE_DATA |
| ☐ | 5 | 本次新增的每个 open()/write_text()/json.dump/subprocess 读写都显式 `encoding="utf-8"`？ | W58：exe 继承句柄 GBK 读线程判例 |
| ☐ | 6 | 无临时产物入库（logs/*.log、outputs/、__pycache__）；权重入库走 spec datas 条件打包而非手动拷贝？ | W64：dist 重建丢权重→联网下载撞网络 |
| ☐ | 7 | 提交信息含 W 编号 + 一句话"真缺陷 vs 环境噪声"结论，半年后的自己能看懂？ | 提交史格式 |
| ☐ | 8 | `git diff --cached` 通读一遍：删的代码确认真没人引用（槽函数/导入/i18n 键连带删净）？读不懂/拿不准 → 跑 `bash scripts/ai-review.sh` 转 AI 审 | W2-4 孤儿控件判例、W61 i18n 8 死键 |

## 档 B：3 分钟细查（feat/fix 触碰相关域时走，17 条）

### PySide6 / GUI 线程

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 9 | 耗时操作（推理/IO/训练，>100ms）在 worker 线程？主线程只碰 UI？ | W55：SAM 同步推理冻 UI 1.4-1.5s |
| ☐ | 10 | worker→UI 回投走信号/invoke_main，无跨线程直接 setXxx 控件？ | ADR0003 请求-回投契约 |
| ☐ | 11 | 异步回调校验"陈旧结果"（换图/切页后旧结果丢弃）；忙态拒收而非回落同步？ | W55 陈旧双校验+忙拒收 |
| ☐ | 12 | 信号槽生命周期：页面销毁后断连？动态控件有 parent 或显式管理（无孤儿控件）？QThread worker 对象无被 GC 提前回收的引用悬空？ | W2-4 孤儿控件陷阱判例 |

### PyTorch / 推理

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 13 | 推理路径包在 torch.no_grad()/inference_mode() 内？ | — |
| ☐ | 14 | device 走统一 CUDA 可用性决策→CPU 回退，无裸 .cuda()/.to("cuda")？CPU-only 环境此路径可跑（双产物回退）？ | 双产物 CPU 回退约定 |
| ☐ | 15 | 大模型卸载三步齐：del model + torch.cuda.empty_cache() + 引用置 None？页面切换/closeEvent 触发卸载？ | W58：卸载 SAM 释放 ~4GB 显存 |
| ☐ | 16 | frozen（打包）态 DataLoader workers=0 守卫未被新代码破坏？批量推理批大小与显存上限匹配？ | W58：exe 冻结态 worker 重_exec 崩溃 |

### Windows 特有

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 17 | 文件句柄：图像/PIL/cv2/np.memmap 对象先 close/del 再 rmtree/unlink/覆盖写？with 语句包住所有 open？ | 提交史高频踩坑：句柄释放顺序 |
| ☐ | 18 | 路径全用 pathlib/os.path.join，无手拼 "/"？深目录（dataset 嵌套）不会破 260 字符？中文/空格路径安全？ | 路径问题踩坑史 |
| ☐ | 19 | subprocess 输出编码显式指定；继承控制台句柄场景（exe/PIPE/Rich 探测）不重蹈覆辙？ | W58：conftest PIPE+GBK 判例 |

### 资源生命周期

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 20 | 临时目录用 TemporaryDirectory 或 try/finally，异常路径（raise 后）也清理？ | — |
| ☐ | 21 | 日志：模块级 getLogger(__name__)，无重复 addHandler；多进程/子进程写同一日志文件有防混写（文件锁/分文件）？ | serving_run.log 混写判例 |

### 异常处理

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 22 | 无裸 except: / except Exception: pass（吞异常）？捕获面收窄到具体异常？ | v7 架构审 broad except 口径修正 |
| ☐ | 23 | 失败"诚实"：用户可见的错误反馈/状态回显，而非静默 return？无恒真断言？ | W59：导出取消静默 return 判例；W55 恒真断言回炉 |

### 测试

| ☐ | # | 检查问题 | 判例锚点 |
|---|---|---------|---------|
| ☐ | 24 | 新 feat/fix 的测试是 RED→GREEN（先证伪再实现），不是事后补的必绿测试？ | 提交史 RED→GREEN 惯例 |
| ☐ | 25 | 删除/修改功能时，守护用例、__all__、i18n 键、行数守卫（page.py 800）同批同步更新？ | W61：六层同批转守护判例 |

---

## AI 辅助审查触发约定（并入选 A 第 8 条）

| 场景 | 是否跑 AI 审 | 上下文范围 |
|------|-------------|-----------|
| chore / docs / 纯测试基建 | 否 | — |
| fix 单行（文案/常量/注释） | 否 | — |
| feat 或 fix，源码 diff ≥50 行 | **必跑** | `bash scripts/ai-review.sh`（staged） |
| 触碰高风险域（gui 页面/worker 线程/模型加载卸载/文件 IO/serving） | **无论行数必跑** | 同上 |
| 收尾怀疑类（"这段逻辑我拿不准"） | 随时 | `bash scripts/ai-review.sh <range>` |

AI 审不做门禁、不阻塞提交——定位是第二双眼睛，最终裁决是人 + check-gate。
