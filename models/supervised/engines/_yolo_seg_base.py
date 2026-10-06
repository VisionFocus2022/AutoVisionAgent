"""YOLOv8-Seg 实例分割引擎基类（TD-01 去重；W2 自兄弟树移植）。

seg/pseg 共享 load/infer 逻辑，子类只覆写 task 与 mask 处理顺序。

去重前：seg_yolo.py（69 行）与 pseg_yolo.py（71 行）~95% 代码相同。
（W2 注：本树 pseg_yolo 暂保持独立实现，去重重构不在本波范围。）
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine
from models.supervised.device import resolve_device

logger = logging.getLogger(__name__)

# ultralytics 自带 AMP 检查的探针资产（check_amp 按运行 CWD 解析，缺文件
# 即联网下载——离线/弱网工位会悬挂训练，W70 exe 实证）
_AMP_CHECK_ASSET = "yolo26n.pt"


def _ensure_amp_asset() -> bool:
    """W70：冻结态把 AMP 检查资产从 _MEIPASS 落到运行 CWD（幂等）。

    ultralytics 的 check_amp 用 yolo26n.pt 做 fp16 探针，查找口径是运行
    CWD（不走 _resolve_backbone）——权重打包进 _internal 后 CWD 永远
    miss → attempt_download_asset 联网 → 弱网悬挂训练。
    """
    if not getattr(sys, "frozen", False):
        return False
    if os.path.isfile(_AMP_CHECK_ASSET):
        return False
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), _AMP_CHECK_ASSET)
    if os.path.isfile(bundled):
        import shutil

        shutil.copy2(bundled, _AMP_CHECK_ASSET)
        logger.info("AMP 检查资产已落运行目录: %s", _AMP_CHECK_ASSET)
        return True
    return False


def _resolve_backbone(backbone: str, seg: bool = True) -> str:
    """骨干名/路径 → ultralytics 模型路径（W58 契约 + W65/W69 回退）。

    .pt 路径原样透传（现成权重微调，免下载）；裸骨干名按任务归一化
    （seg → -seg.pt，det → .pt）。冻结态（PyInstaller 6 datas 落
    _internal=sys._MEIPASS）下 ultralytics 按运行 CWD 解析裸名会 miss
    转联网下载（W64 复盘的下载失败形态）——_MEIPASS 命中随包权重即
    绝对化。CWD 就近优先（手拷 dist 根形态兼容）。
    W69：det 侧裸名（如 yolov8n.pt）无本地权重时回退随包 yolo26n.pt
    （同量级检测骨干，离线开箱即用）——杜绝检测训练静默转联网。
    """
    if not backbone.endswith(".pt"):
        backbone = f"{backbone}-seg.pt" if seg else f"{backbone}.pt"
    if not os.path.isfile(backbone):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), backbone)
        if os.path.isfile(bundled):
            return bundled
        if not seg:
            det_fallback = os.path.join(
                getattr(sys, "_MEIPASS", ""), "yolo26n.pt"
            )
            if os.path.isfile(det_fallback):
                logger.warning(
                    "检测骨干 %s 无随包权重，回退 yolo26n.pt（离线可用）",
                    backbone,
                )
                return det_fallback
    return backbone


class _YoloSegBase(AbstractTaskEngine):
    """YOLOv8-Seg 实例分割共享基类。

    子类设置 self.task 并可选覆写 _process_results()。
    """

    def __init__(self, task: TaskType) -> None:
        super().__init__(task)
        # W58 真训练通道（PRD FR-1）状态：一次性 ultralytics 适配器
        self._train_model: Any = None
        self._train_metrics: dict[str, float] = {}
        self._train_output_dir: str = ""

    def load(self, weights_path: str, device: str = "cuda") -> None:
        """加载 YOLOv8-Seg 权重。"""
        # W19（v3 第三波 FR-3.1）：cuda 不可用时诚实回退 cpu（lite 派生场景）
        device = resolve_device(device)
        if not os.path.exists(weights_path):
            raise SupervisedEngineError(
                f"权重文件不存在: {weights_path}", task=self.task.value
            )
        from ultralytics import YOLO

        self._model = YOLO(weights_path)
        self._weights_path = weights_path
        self._device = device

    # ============================== 真训练通道（W58 · PRD FR-1） ============================== #
    def train_epoch(self, epoch: int, cfg) -> dict:
        """ultralytics 一次性训练适配器（GUI 真训练通道）。

        ultralytics ``train()`` 自带完整训练循环，不适合作逐轮切片——本
        适配器在**首轮**调用一次性跑完全部 epochs（进度经其自身日志流），
        后续轮次直接返回末轮 metrics；GenericTrainer 的逐轮循环退化为
        「总耗时摊到首轮 + 后续空转」，最优轨迹按末轮值记账（工程案例
        流程铁证口径，非精度调优面——精度调优仍走脚本侧
        scripts/train_pole_seg.py 全量口径）。

        Args:
            epoch: 当前轮次（仅记账，ultralytics 自管轮次）。
            cfg: TrainConfig（data_yaml/epochs/img_size/batch_size/device/
                workers/backbone/output_dir/amp 生效）。

        Returns:
            metrics dict（loss 末轮值，best-effort 提取，缺省 0.0）。

        Raises:
            ValueError: 未选择数据集（data_yaml 为空）——由训练页在选择
                面拦截回退模拟，此为纵深防御第二道。
        """
        if self._train_model is not None:
            return dict(self._train_metrics)
        data_yaml = getattr(cfg, "data_yaml", "") or ""
        if not data_yaml:
            raise ValueError(
                "未选择训练数据集（data.yaml）——请先在数据管理页导出训练集"
            )
        from ultralytics import YOLO

        backbone = cfg.backbone or "yolov8n"
        backbone = _resolve_backbone(backbone, seg=self.task is TaskType.SEG)
        model = YOLO(backbone)
        # W70：ultralytics 自带 AMP 检查按 CWD 找 yolo26n.pt，miss 即联网
        # 下载（弱网悬挂训练）——冻结态先落一份随包资产
        if cfg.amp:
            _ensure_amp_asset()
        # project 必须绝对化：相对路径触发 ultralytics 的 {runs_dir}/{task}/
        # 嵌套落点（W58 探针实证 runs/segment/outputs/train），产物位置随
        # cwd/版本漂移——绝对路径钉死 {output_dir}/train/
        # workers 冻结态清零：PyInstaller exe 下 DataLoader 多进程会重_exec
        # 自身（经典冻结态崩溃，exe 模式实证：训练启动即失败且无异常日志；
        # python 模式不受影响）
        workers = 0 if getattr(sys, "frozen", False) else cfg.workers
        model.train(
            data=data_yaml,
            epochs=max(1, cfg.epochs),
            imgsz=cfg.img_size,
            batch=cfg.batch_size,
            device=cfg.device,
            workers=workers,
            project=os.path.abspath(cfg.output_dir),
            name="train",
            exist_ok=True,
            amp=cfg.amp,
        )
        # best-effort 末轮 loss 提取（ultralytics 各版本返回形态不一）
        loss = 0.0
        trainer = getattr(model, "trainer", None)
        for attr in ("loss", "loss_items", "final_epoch_loss"):
            val = getattr(trainer, attr, None) if trainer is not None else None
            if val is not None:
                try:
                    loss = float(val[-1] if isinstance(val, (list, tuple)) else val)
                    break
                except (TypeError, ValueError):
                    continue
        self._train_model = model
        # W58 落盘口径修正：ultralytics 实际写到 {runs_dir}/{task}/{project}/
        # {name}/（探针实证 runs/segment/outputs/train/weights/best.pt），
        # 与 cfg.output_dir 直连直觉不符——以 trainer.save_dir 为准
        save_dir = str(getattr(trainer, "save_dir", "") or "")
        self._train_output_dir = save_dir or os.path.join(cfg.output_dir, "train")
        self._train_metrics = {"loss": round(loss, 6)}
        return dict(self._train_metrics)

    def save(self, path: str) -> None:
        """保存真训练产物：ultralytics best.pt 拷贝到训练器目标路径。

        未跑过真训练时 no-op（空权重落盘无意义；模拟路径由
        GenericTrainer 的既有 save 兜底语义管辖）。
        """
        import shutil

        best = os.path.join(self._train_output_dir, "weights", "best.pt")
        if os.path.isfile(best):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            shutil.copyfile(best, path)

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: list | None = None,
    ) -> DetectionResult:
        """执行实例分割，返回每个实例的 bbox + 二值 mask。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未加载权重", task=self.task.value)

        results = self._model(image, conf=threshold, verbose=False)
        r = results[0]

        # 提取 mask（所有子类共享逻辑）
        masks_tensor = None
        if r.masks is not None and len(r.masks) > 0:
            masks_tensor = r.masks.data.cpu()  # [N,H,W]

        # 检查检测结果
        if r.boxes is None or len(r.boxes) == 0:
            return DetectionResult(
                task=self.task, boxes=(), scores=(), labels=(),
                masks=masks_tensor,
            )

        xyxy = r.boxes.xyxy.cpu().numpy()
        conf = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy()

        return DetectionResult(
            task=self.task,
            boxes=tuple(tuple(float(v) for v in row) for row in xyxy),
            scores=tuple(float(c) for c in conf),
            labels=tuple(
                labels[int(c)] if labels and int(c) < len(labels)
                else f"defect_{int(c)}"
                for c in cls
            ),
            masks=masks_tensor,
        )


__all__ = ["_YoloSegBase"]
