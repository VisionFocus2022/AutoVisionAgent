"""
缺陷生成引擎（copy-paste blend）— FR-A8 / FR-G1 · T-FIX-1-02（W2 自兄弟树移植）

Option A 轻量库：弃 mmedit GAN，改用 cv2.seamlessClone（Poisson 融合）从缺陷库
合成到 OK 模板，产 ground truth mask。免 GAN、免 mmedit。

工作流：
1. 输入 OK 模板图像 + 缺陷库目录
2. 随机选缺陷图，用 seamlessClone 融合到模板随机位置
3. 输出合成图 + 缺陷区域 mask（DetectionResult.extra）

诚实回退：无缺陷库 → raise SupervisedEngineError（不返输入拷贝的假数据）。
W2 适配：_to_numpy 走 imread_unicode（本树根路径含中文）。
"""
from __future__ import annotations

import os
import random
from typing import Any, List, Optional

from core.exceptions import SupervisedEngineError
from core.interfaces_supervised import DetectionResult, TaskType
from models.supervised import AbstractTaskEngine, register_engine


@register_engine(TaskType.SGAN)
class SganBlendEngine(AbstractTaskEngine):
    """copy-paste blend 缺陷生成引擎。

    load(flaw_database) → infer(ok_image) → 合成缺陷图 + mask。
    """

    def __init__(self) -> None:
        super().__init__(TaskType.SGAN)
        self._flaw_database: Optional[str] = None
        self._flaw_files: List[str] = []

    def load(
        self,
        weights_path: str = "",
        device: str = "cuda",
        flaw_database: str = "",
    ) -> None:
        """初始化缺陷生成引擎。

        weights_path 对标接口签名（本引擎的 "权重" 即缺陷库路径）。
        flaw_database 为含缺陷裁剪图的目录路径。
        路径不存在时 raise SupervisedEngineError（诚实回退，不伪装就绪）。
        """
        self._device = device

        db = flaw_database or weights_path
        if db and os.path.isdir(db):
            self._flaw_database = db
            exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
            self._flaw_files = sorted(
                f for f in os.listdir(db)
                if os.path.splitext(f)[1].lower() in exts
            )
        elif db and os.path.isfile(db):
            # 单文件缺陷图
            self._flaw_database = os.path.dirname(db)
            self._flaw_files = [os.path.basename(db)]
        elif db:
            # 路径提供但不存在 → raise（不静默跳过）
            raise SupervisedEngineError(
                f"缺陷库路径不存在: {db}", task=self.task.value
            )
        else:
            self._flaw_database = None
            self._flaw_files = []

        self._weights_path = weights_path or "(blend_engine)"

        # 标记为"已加载"（blend 引擎不需要神经网络权重）
        self._model = True  # type: ignore[assignment]

    def set_flaw_database(self, db_path: str) -> None:
        """设置缺陷库路径。"""
        self.load(flaw_database=db_path)

    def infer(
        self,
        image: Any,
        threshold: float = 0.5,
        labels: Optional[list] = None,
    ) -> DetectionResult:
        """合成缺陷：OK 模板 + 随机缺陷 → seamlessClone → 合成图 + mask。"""
        if self._model is None:
            raise SupervisedEngineError("引擎未初始化", task=self.task.value)
        if not self._flaw_files or self._flaw_database is None:
            raise SupervisedEngineError(
                "缺陷库为空，无法生成合成缺陷图（请先 set_flaw_database 设置含缺陷图的目录）",
                task=self.task.value,
            )

        import cv2
        import numpy as np

        # 加载 OK 模板
        template = self._to_numpy(image)
        if template.ndim == 2:
            template = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
        h_t, w_t = template.shape[:2]

        # 随机选缺陷图
        flaw_name = random.choice(self._flaw_files)
        flaw_path = os.path.join(self._flaw_database, flaw_name)
        flaw = self._to_numpy(flaw_path)
        if flaw.ndim == 2:
            flaw = cv2.cvtColor(flaw, cv2.COLOR_GRAY2BGR)

        # 缺陷尺寸缩放到模板的 10%-30%
        h_f, w_f = flaw.shape[:2]
        scale = random.uniform(0.1, 0.3) * min(h_t, w_t) / max(h_f, w_f)
        new_h, new_w = max(1, int(h_f * scale)), max(1, int(w_f * scale))
        flaw_resized = cv2.resize(flaw, (new_w, new_h))

        # 生成 mask（缺陷区域=255）
        mask = 255 * np.ones((new_h, new_w), dtype=np.uint8)

        # 随机放置位置（确保在模板内）
        max_x = max(1, w_t - new_w)
        max_y = max(1, h_t - new_h)
        center = (random.randint(new_w // 2, max_x + new_w // 2),
                  random.randint(new_h // 2, max_y + new_h // 2))

        # seamlessClone（NORMAL_CLONE = Poisson 融合）
        try:
            synthesized = cv2.seamlessClone(
                flaw_resized, template, mask, center, cv2.NORMAL_CLONE
            )
        except cv2.error:
            # 融合失败（位置越界等）→ 回退到简单贴图
            synthesized = template.copy()
            y0 = max(0, center[1] - new_h // 2)
            x0 = max(0, center[0] - new_w // 2)
            y1 = min(h_t, y0 + new_h)
            x1 = min(w_t, x0 + new_w)
            synthesized[y0:y1, x0:x1] = flaw_resized[: y1 - y0, : x1 - x0]

        # 生成 ground truth mask（缺陷区域=1，其余=0）
        gt_mask = np.zeros((h_t, w_t), dtype=np.uint8)
        y0 = max(0, center[1] - new_h // 2)
        x0 = max(0, center[0] - new_w // 2)
        y1 = min(h_t, y0 + new_h)
        x1 = min(w_t, x0 + new_w)
        gt_mask[y0:y1, x0:x1] = 1

        return DetectionResult(
            task=TaskType.SGAN,
            score=float(gt_mask.sum()) / (h_t * w_t),  # 缺陷占比
            labels=("synthesized",),
        ).with_extra("synthesized_image", synthesized).with_extra(
            "defect_mask", gt_mask
        )

    @staticmethod
    def _to_numpy(image: Any) -> Any:
        import numpy as np

        if isinstance(image, str):
            from core.image_io import imread_unicode
            return imread_unicode(image)
        return np.asarray(image)


__all__ = ["SganBlendEngine"]
