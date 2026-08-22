# PRD：W34 逐帧视频超分（L2 · 精简）

> v1.0 · 2026-08-22 · 上游：计划 W34 节（用户指令含本波——不裁撤）· 档位 🟡L2 · 门禁代偿同前
> 三栏：【已知】super 引擎 extra["hr_image"] 契约/cv2 VideoWriter mp4v 自带；【假设】mp4v 后端 Windows 可用（实测 ✓）；【未知】无
> 显式 non-goal：视频插帧（RIFE 系重依赖，计划已拒）

## FR
- FR-1 video_super.py 纯函数 super_video：逐帧 infer→hr_image→mp4v；帧数保持；尺寸随引擎倍数；progress_cb 单调；cancel 停帧保留已写；坏输入明确 raise；输出共享约定 {root}/results/superres_{ts}/
- FR-2 页面：视频超分按钮（仅 SUPER 任务，其他诚实提示）+ 四方法抽 VideoSuperActionsMixin（规模守卫 800 线触发后 SamSession 同款抽取）
- FR-3 permissions：predict.video_super 三角色；i18n zh+en

## AC
10 帧入=10 帧出/64→128/进度单调 ✓ 取消停第 3 帧 ✓ 坏输入 raise ✓ 页面接线产物+状态 ✓ 非 SUPER 诚实提示 ✓ action 三角色 ✓ page 773 行 ✓
