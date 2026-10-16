# Real-ESRGAN 超分辨率引擎集成（v2.3）

## 背景与选型

[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)（xinntao，BSD-3-Clause，约 24.5K
stars）面向真实世界退化（模糊/噪声/压缩伪影）的盲超分复原，是工业低分辨率
图像增强的主流开源方案。本项目在既有 cv2.dnn_superres（EDSR 系 `.pb`）之外
接入其 PyTorch 权重，作为 SUPER 任务的第二后端。

## 为什么 vendor 而不是 pip 依赖

官方 `realesrgan` PyPI 包硬依赖 `basicsr==1.4.2`，后者 import 时执行
`from torchvision.transforms.functional_tensor import ...`——该模块在
torchvision 0.17 已移除（本项目锁定 `torchvision==0.20.1+cu121`），安装即
不可用（上游长期未发修复版）。故 `models/supervised/engines/super_realesrgan.py`
vendor 推理最小闭包：

- 网络定义：RRDBNet / ResidualDenseBlock / RRDB / SRVGGNetCompact，结构
  逐行对齐上游 `realesrgan/archs/realesrgan_arch.py`（BSD-3 授权，文件头
  含版权声明）；
- 权重加载：`AbstractTaskEngine._safe_torch_load`（weights_only 安全路径，
  R4-7）+ 官方历史包裹格式（`params` / `params_ema`）解包 + 按文件名推断
  架构候选、strict load 逐候选自愈；
- 分块推理：复用 `inference/tiling_inferencer.compute_tiles` 网格，瓦片
  各侧外扩 `tile_pad` 像素上下文后仅粘贴核心区，抑制接缝。

零新增 pip 依赖（torch / numpy / opencv 均为既有依赖）。

## 架构：SUPER 槽位路由

注册表每 TaskType 仅一工厂，SUPER 现有两种后端，故引入路由层：

```
get_engine(TaskType.SUPER) → SuperRouterEngine（super_router.py，唯一注册点）
    load("xxx.pth"/".pt") → RealEsrganEngine（Real-ESRGAN，GPU 优先/CPU 回退）
    load("xxx.pb")        → SuperCv2Engine（cv2.dnn_superres，EDSR/ESPCN/…）
```

- `super_cv2.py` 摘除 `@register_engine`（类保留，供路由委托与直连测试）；
- 两后端 `infer` 契约统一：`DetectionResult(task=SUPER, score=1.0,
  labels=("super_resolved",))`，HR 图像经 `extra["hr_image"]` 返回
  （BGR uint8）——预测页、视频超分（`gui/pages/predict/video_super.py`）、
  serving/gRPC 零改动；
- dispatcher 的 LRU 驱逐/卸载走基类 `unload()`，路由器委托后端释放显存。

## 权重获取（离线优先）

```bash
.venv/Scripts/python scripts/download_realesrgan.py --dest D:/realesrgan_weights [--models x4plus]
```

| key | 文件 | 架构 | 说明 |
| --- | --- | --- | --- |
| x4plus（默认） | RealESRGAN_x4plus.pth | RRDBNet x4 23块 | 通用真实场景（~64MB） |
| x2plus | RealESRGAN_x2plus.pth | RRDBNet x2 23块 | ~64MB |
| anime_6b | RealESRGAN_x4plus_anime_6B.pth | RRDBNet x4 6块 | 轻量（~18MB） |
| general_x4v3 | realesr-general-x4v3.pth | SRVGGNetCompact x4 | 小模型（~5MB） |

脚本产出 sha256 manifest（供给方校验）。下载渠道按优先序自动回退：官方
GitHub release → ModelScope 镜像（`AI-ModelScope/Real-ESRGAN`，即
ai-forever 再发布版——同款 RRDBNet 架构，x4plus/x2plus 对应镜像内
`RealESRGAN_x4/x2.pth`，落盘统一官方命名；GitHub releases CDN 国内常
不可达）；anime/general 两轻量模型仅官方渠道。单次尝试 60s 超时 ×2 重试，
不留半截文件。离线机器拷贝目录后，在推理页选择 SUPER 任务并加载目录下
`.pth` 即可。

## 使用

- GUI：推理页任务选「超分辨率」→ 选择模型权重（`.pth`，过滤器已含
  `*.pb`）→ 单张/批量推理或「视频超分」。
- 代码：
  ```python
  from industrial_vision_platform.vision_dispatcher import VisionModelDispatcher

  d = VisionModelDispatcher()
  d.load_supervised(TaskType.SUPER, "D:/realesrgan_weights/RealESRGAN_x4plus.pth")
  result = d.infer_supervised(TaskType.SUPER, bgr_image)
  hr = result.extra["hr_image"]   # BGR uint8，边长 ×4
  ```
- `load` 可选参数：`arch_overrides`（非官方骨干/测试小网络）、`half`
  （CUDA fp16，默认 False 保精度）、`tile_size`（默认 512，大图防 OOM）、
  `tile_pad`（默认 16）。

## 测试

`tests/test_engine_super_realesrgan.py`：CPU + tiny 架构覆盖全链路（架构
前向形状、按名推断候选、加载契约、推理契约、分块、包裹格式解包、路由分发、
注册表解析），不依赖官方权重；`TestOfficialWeightsE2E` 在设置
`AVA_REALESRGAN_X4PLUS` 环境变量指向官方 `.pth` 时跑真权重 e2e。
