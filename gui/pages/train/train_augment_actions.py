"""训练模板/增强参数动作 Mixin（W57 FR-004——页面 ≤800 行守卫，动作外置）。

对标 SKolpha TrainConfigs 的「任务级模板 + UI 参数覆盖」：模板下拉
（configs/train_templates/，明文 YAML）选中回填表单；增强参数面板
（AugmentationConfig 字段）随表单进 TrainConfig。引擎侧消费方接入前，
以诚实提示告知「当前引擎忽略增强参数」——首个引擎接入时改
_hint_augmentation_support 按引擎能力静默。
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QSpinBox, QWidget

from core.interfaces_supervised import AugmentationConfig
from gui.core.i18n import tr
from training.train_templates import REPO_TEMPLATE_DIR, TrainTemplate, load_templates

logger = logging.getLogger(__name__)


class TrainAugmentActionsMixin:
    """训练模板下拉 + 增强参数面板（构建/回填/取值；模板启动时一次加载）。"""

    def _build_template_row(self, form_frame: QWidget, form: QFormLayout) -> None:
        """模板下拉行（置于预设行后——模板比预设多任务维度，选中后覆盖）。"""
        self._templates: dict[tuple[str, str], TrainTemplate] = load_templates(
            REPO_TEMPLATE_DIR
        )
        self.cmb_template = QComboBox(form_frame)
        self.cmb_template.addItem(tr("（无模板）"), None)
        for (task_value, variant) in sorted(self._templates):
            self.cmb_template.addItem(f"{task_value} / {variant}",
                                      (task_value, variant))
        form.addRow(tr("训练模板"), self.cmb_template)
        self.cmb_template.currentIndexChanged.connect(self._apply_template)

    def _apply_template(self, idx: int) -> None:
        """选中模板 → 回填表单（任务/骨干/尺寸/批/学习率；轮数模板给了才改）。"""
        key = self.cmb_template.itemData(idx)
        if key is None:
            return
        template = self._templates.get(tuple(key))
        if template is None:
            return
        for i in range(self.cmb_task.count()):
            if self.cmb_task.itemData(i) is template.task:
                self.cmb_task.setCurrentIndex(i)
                break
        self.txt_backbone.setText(template.backbone)
        self.spin_img_size.setValue(template.img_size)
        self.spin_batch.setValue(template.batch_size)
        self.spin_lr.setValue(template.lr)
        if template.epochs is not None:
            self.spin_epochs.setValue(template.epochs)
        self.status_changed.emit(tr("模板"), f"{key[0]}/{key[1]}")

    def _build_augmentation_rows(
        self, form_frame: QWidget, form: QFormLayout
    ) -> None:
        """增强参数行（AugmentationConfig 可调子集；其余字段走模板默认）。"""
        self.spin_aug_hflip = QDoubleSpinBox(form_frame)
        self.spin_aug_hflip.setRange(0.0, 1.0)
        self.spin_aug_hflip.setSingleStep(0.05)
        self.spin_aug_hflip.setValue(0.5)
        form.addRow(tr("水平翻转概率"), self.spin_aug_hflip)

        self.spin_aug_rotate = QSpinBox(form_frame)
        self.spin_aug_rotate.setRange(0, 180)
        self.spin_aug_rotate.setValue(10)
        form.addRow(tr("最大旋转角"), self.spin_aug_rotate)

        self.spin_aug_translate = QDoubleSpinBox(form_frame)
        self.spin_aug_translate.setRange(0.0, 0.9)
        self.spin_aug_translate.setSingleStep(0.05)
        self.spin_aug_translate.setValue(0.1)
        form.addRow(tr("平移比例"), self.spin_aug_translate)

        self.spin_aug_split = QDoubleSpinBox(form_frame)
        self.spin_aug_split.setRange(0.1, 0.9)
        self.spin_aug_split.setSingleStep(0.05)
        self.spin_aug_split.setValue(0.8)
        form.addRow(tr("训练占比"), self.spin_aug_split)

        self.spin_aug_expansion = QSpinBox(form_frame)
        self.spin_aug_expansion.setRange(0, 10)  # SKolpha my_data_expansion 上限
        self.spin_aug_expansion.setValue(0)
        form.addRow(tr("数据扩充系数"), self.spin_aug_expansion)

    def _augmentation_from_form(self) -> AugmentationConfig:
        """表单增强控件 → AugmentationConfig（未列字段走默认）。"""
        return AugmentationConfig(
            hflip=float(self.spin_aug_hflip.value()),
            rotate_max=int(self.spin_aug_rotate.value()),
            translate=float(self.spin_aug_translate.value()),
            split_ratio=float(self.spin_aug_split.value()),
            data_expansion=int(self.spin_aug_expansion.value()),
        )

    def _hint_augmentation_support(self, cfg) -> None:
        """诚实提示：增强段配置存在但当前引擎不消费。

        引擎消费方接入 augmentation 后，此处按引擎能力静默
        （现状：全部引擎不消费——提示恒发，含原因留日志）。
        """
        if cfg.augmentation is None:
            return
        logger.info(
            "训练配置含增强段（hflip=%s rotate=%s translate=%s）——"
            "当前引擎不消费增强参数，仅记录",
            cfg.augmentation.hflip, cfg.augmentation.rotate_max,
            cfg.augmentation.translate,
        )
        self.status_changed.emit(tr("提示"), tr("当前引擎忽略增强参数"))


__all__ = ["TrainAugmentActionsMixin"]
