import time

######begin
my_img_scale = (1024, 640)
my_mean = [56.32, 56.32, 56.32]
my_std = [61.42, 61.42, 61.42]
my_work_dir = r'F:/DL项目测试/CDCD/saveyolomask'  # 保存路径
my_label_path = r"E:\SSIGMA\Projects\QP_PSEG_00003_1703234751\data\label.txt"
my_dataset_path_list = [r'D:/Datasets/AC040/Cam20']
my_samples_per_gpu = 2
my_workers_per_gpu = 2
my_endSplitData = 0.8
my_load_from = r"E:/SSIGMA/TrainConfigs"  # 预训练模型
my_base_batch_size = 16  # 批处理训练
my_max_epochs = 12
my_data_expansion = 1  # 数据扩充系数
pretrain_load_from = r"D:/SourceCode/New_Code/S_Sigma3.0/TrainConfigs/pretrain_pseg.pth"
my_num_classes = 2

my_max_rotate_angle = 10
my_rotate_prob = 0.5
my_max_translate_offset = 64
my_translate_direction = "horizontal"
my_translate_prob = 0.5
my_random_flip_ratio = 0.5
my_random_direction = "horizontal"
my_avg_non_ignore = False
my_ignore_index = my_num_classes - 1
######end

max_rotate_angle = my_max_rotate_angle
rotate_prob = my_rotate_prob
max_translate_offset = my_max_translate_offset
translate_direction = my_translate_direction
translate_prob = my_translate_prob
random_flip_ratio = my_random_flip_ratio
random_direction = my_random_direction


num_classes = my_num_classes
samples_per_gpu = my_samples_per_gpu
workers_per_gpu = my_workers_per_gpu
endSplitDAta = my_endSplitData
max_epochs = my_max_epochs
custom_imports = dict(
    imports=[
        # 'dl.encrypt_epoch_based_runner',
        'samsuncn.mdl.samsun_dataset',
        'samsuncn.mdl.samsun_epoch_based_runner',
        'samsuncn.mdl.pipelines.init_pipeline',
        'samsuncn.mdl.pipelines.eval_pipeline',
        'samsuncn.mdl.pipelines.save_pipeline',
        'samsuncn.mdl.pipelines.after_run_pipeline',
        'samsuncn.mdl.samsun_after_run_hook',
        'samsuncn.mdl.pipelines.dataset_pipeline',
        'samsuncn.mdl.core.loss_fuction'
    ],
    allow_failed_imports=True)

timestamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
dataset_type = 'SamsunDataset'
work_dir = my_work_dir
label_path = my_label_path
dataset_path_list = my_dataset_path_list
# word_dir = save_path
img_scale = my_img_scale  ##### 修改
img_norm_cfg = dict(mean=my_mean, std=my_std)  # 修改
data_expansion = my_data_expansion
# num_classes = 6

evaluation = dict(metric=['bbox'])
fp16 = dict(loss_scale=512.)

train_pipeline = [
    dict(type='LoadImageFromFile'),
    dict(type='LoadAnnotations', with_bbox=True, with_mask=True),
    dict(
        type='Resize',
        img_scale=img_scale,
        ratio_range=[0.75, 1.25],
        keep_ratio=True),


    # 默认关闭   随机旋转  1）旋转概率：prob  0  关闭，概率默认0.5 最大是1  2）最大旋转角度 默认10
    dict(type='Rotate', level=10, max_rotate_angle=max_rotate_angle, prob=rotate_prob),
    # 平移  默认关闭 开启后 0）平移方向：下拉可选'horizontal'    vertical   1）概率，默认0.5  2）最大平移像素 默认32
    dict(type='Translate', level=10, max_translate_offset=max_translate_offset, direction=translate_direction,
         prob=translate_prob),
    # zhangHaiGen dict(type='RandomCrop', crop_size=img_scale),

    dict(type='RandomFlip', flip_ratio=random_flip_ratio, direction=random_direction),
    # 随机翻转  默认开启   1)翻转方向：下拉可选'horizontal'    vertical  2）概率，默认0.5




    dict(type='Normalize', **img_norm_cfg, to_rgb=True),
    dict(type='Pad', size_divisor=32),
    dict(type='DefaultFormatBundle'),
    dict(type='Collect', keys=['img', 'gt_bboxes', 'gt_labels', 'gt_masks']),
]

test_pipeline = [
    dict(type='LoadImageFromFile'),
    dict(
        type='MultiScaleFlipAug',
        img_scale=img_scale,
        flip=False,
        transforms=[
            dict(type='Resize', keep_ratio=True),
            dict(type='RandomFlip'),
            dict(type='Normalize',
                 **img_norm_cfg, to_rgb=True),
            dict(type='Pad', size_divisor=32),
            dict(type='ImageToTensor', keys=['img']),
            dict(type='Collect', keys=['img']),
        ])
]

train_init_pipeline = [
    dict(type='LoadCategoryList', ignore_labels=['ignore']),
    dict(type='LoadPathList'),
    dict(type='SplitData', start=0, end=endSplitDAta, key='json_path_list'),
    dict(type='LoadJsonDataList'),
    dict(type='LoadLabelmeDataset'),
    dict(type='StatCategoryCounter'),
    dict(type='CopyData', times=data_expansion),
    # dict(type='RepeatDataset', times=data_expansion),
    dict(type='Labelme2Coco'),
    dict(type='SaveJson'),
]

test_init_pipeline = [
    dict(type='LoadCategoryList', ignore_labels=['ignore']),
    dict(type='LoadPathList'),
    dict(type='SplitData', start=0, end=1, key='json_path_list'),
    dict(type='LoadJsonDataList'),
    dict(type='LoadLabelmeDataset'),
    dict(type='Labelme2Coco'),
    dict(type='StatCategoryCounter'),
    dict(type='SaveJson'),
]

val_init_pipeline = [
    dict(type='LoadCategoryList', ignore_labels=['ignore']),
    dict(type='LoadPathList'),
    dict(type='SplitData', start=0.8, end=1, key='json_path_list'),
    dict(type='LoadJsonDataList'),
    dict(type='LoadLabelmeDataset'),
    dict(type='Labelme2Coco'),
    dict(type='StatCategoryCounter'),
    dict(type='SaveJson'),
]

eval_pipeline = [
    dict(
        type='CocoEvaluate', metric=['bbox'], classwise=True, iou_thrs=[0, 0]),
    dict(type='ShowScores'),

    dict(type='CalculateErrorCases')
]

save_pipeline = [
    dict(
        type='SaveEachEpochModel',
        save_each_epoch=True,
        encrypt_each_epoch=False,
        save_latest=True,
        encrypt_latest=False),
]

after_run_pipeline = [

    dict(type='SaveLog', create_briefing=False),
]
data = dict(
    persistent_workers=False,
    samples_per_gpu=samples_per_gpu,
    # samples_per_gpu=2,
    workers_per_gpu=workers_per_gpu,
    # workers_per_gpu=0,
    train=dict(
        type=dataset_type,
        label_path=label_path,
        dataset_path_list=dataset_path_list,
        pipeline=train_pipeline,
        init_pipeline=train_init_pipeline),
    # train_dataloader=dict(class_aware_sampler=dict(num_sample_class=1)),
    val=dict(
        type=dataset_type,
        label_path=label_path,
        dataset_path_list=dataset_path_list,
        pipeline=test_pipeline,
        init_pipeline=val_init_pipeline,
        eval_pipeline=eval_pipeline,
        timestamp=timestamp),
    test=dict(
        type=dataset_type,
        label_path=label_path,
        dataset_path_list=dataset_path_list,
        pipeline=test_pipeline,
        init_pipeline=test_init_pipeline,
        eval_pipeline=eval_pipeline,
        timestamp=timestamp))

model = dict(
    type='MaskRCNN',
    backbone=dict(
        type='ResNet',
        depth=18,
        num_stages=4,
        out_indices=(0, 1, 2, 3),
        frozen_stages=1,
        norm_cfg=dict(type='BN', requires_grad=True),
        norm_eval=True,
        style='pytorch',
        init_cfg=dict(type='Pretrained', checkpoint=r'./TrainConfigs/resnet18-f37072fd.pth')
    ),
    neck=dict(
        type='FPN',
        in_channels=[64, 128, 256, 512],
        out_channels=64,
        num_outs=5),
    rpn_head=dict(
        type='RPNHead',
        in_channels=64,
        feat_channels=64,
        anchor_generator=dict(
            type='AnchorGenerator',
            scales=[4],
            # scales=[8],
            ratios=[0.25, 1.0, 4.0],
            strides=[4, 8, 16, 32, 64]),
        bbox_coder=dict(
            type='DeltaXYWHBBoxCoder',
            target_means=[.0, .0, .0, .0],
            target_stds=[1.0, 1.0, 1.0, 1.0]),
        loss_cls=dict(
            # type='CrossEntropyLoss', use_sigmoid=True, loss_weight=1.0
            type='SamsunPSEGCrossEntropyLoss', use_sigmoid=True, loss_weight=1.0, ignore_index=my_ignore_index, avg_non_ignore=my_avg_non_ignore
        ),
        loss_bbox=dict(type='L1Loss', loss_weight=1.0)),
    roi_head=dict(
        type='StandardRoIHead',
        bbox_roi_extractor=dict(
            type='SingleRoIExtractor',
            roi_layer=dict(type='RoIAlign', output_size=7, sampling_ratio=0),
            out_channels=64,
            featmap_strides=[4, 8, 16, 32]),
        bbox_head=dict(
            type='Shared2FCBBoxHead',
            in_channels=64,
            fc_out_channels=256,
            roi_feat_size=7,
            num_classes=num_classes,
            bbox_coder=dict(
                type='DeltaXYWHBBoxCoder',
                target_means=[0., 0., 0., 0.],
                target_stds=[0.1, 0.1, 0.2, 0.2]),
            reg_class_agnostic=False,
            loss_cls=dict(
                # type='CrossEntropyLoss', use_sigmoid=False, loss_weight=1.0
                type='SamsunPSEGCrossEntropyLoss', use_sigmoid=False, loss_weight=1.0, ignore_index=my_ignore_index, avg_non_ignore=my_avg_non_ignore
            ),
            loss_bbox=dict(type='L1Loss', loss_weight=1.0)),
        mask_roi_extractor=dict(
            type='SingleRoIExtractor',
            roi_layer=dict(type='RoIAlign', output_size=14, sampling_ratio=0),
            out_channels=64,
            featmap_strides=[4, 8, 16, 32]),
        mask_head=dict(
            type='FCNMaskHead',
            num_convs=4,
            in_channels=64,
            conv_out_channels=64,
            num_classes=num_classes,
            loss_mask=dict(
                # type='CrossEntropyLoss', use_mask=True, loss_weight=1.0
                type='SamsunPSEGCrossEntropyLoss', use_mask=True, loss_weight=1.0, ignore_index=None
            ))),
    # model training and testing settings
    train_cfg=dict(
        rpn=dict(
            assigner=dict(
                type='MaxIoUAssigner',
                pos_iou_thr=0.7,
                neg_iou_thr=0.3,
                min_pos_iou=0.3,
                match_low_quality=True,
                ignore_iof_thr=-1),
            sampler=dict(
                type='RandomSampler',
                num=256,
                pos_fraction=0.5,
                neg_pos_ub=-1,
                add_gt_as_proposals=False),
            allowed_border=-1,
            pos_weight=-1,
            debug=False),
        rpn_proposal=dict(
            nms_pre=2000,
            max_per_img=1000,
            nms=dict(type='nms', iou_threshold=0.7),
            min_bbox_size=0),
        rcnn=dict(
            assigner=dict(
                type='MaxIoUAssigner',
                pos_iou_thr=0.5,
                neg_iou_thr=0.5,
                min_pos_iou=0.5,
                match_low_quality=True,
                ignore_iof_thr=-1),
            sampler=dict(
                type='RandomSampler',
                num=512,
                pos_fraction=0.25,
                neg_pos_ub=-1,
                add_gt_as_proposals=True),
            mask_size=28,
            pos_weight=-1,
            debug=False)),
    test_cfg=dict(
        rpn=dict(
            nms_pre=1000,
            max_per_img=1000,
            nms=dict(type='nms', iou_threshold=0.7),
            min_bbox_size=0),
        rcnn=dict(
            score_thr=0.05,
            nms=dict(type='nms', iou_threshold=0.5),
            max_per_img=100,
            mask_thr_binary=0.5)))

checkpoint_config = dict(
    interval=1,
)

log_config = dict(
    interval=50,
    hooks=[
        dict(type='TextLoggerHook'),

    ])

dist_params = dict(backend='nccl')
log_level = 'INFO'
load_from = pretrain_load_from
resume_from = None
workflow = [('train', 1)]

# disable opencv multithreading to avoid system being overloaded
opencv_num_threads = 0
# set multiprocess start method as `fork` to speed up the training
mp_start_method = 'fork'

# optimizer
optimizer = dict(type='SGD', lr=0.02, momentum=0.9, weight_decay=0.0001)
auto_scale_lr = dict(enable=True, base_batch_size=16)
optimizer_config = dict(grad_clip=dict(max_norm=35, norm_type=2))
# learning policy
lr_config = dict(
    policy='step',
    warmup='linear',
    warmup_iters=500,
    warmup_ratio=0.001,
    step=[9, 11])

custom_hooks = [dict(type='SamsunAfterRunHook'), dict(type='NumClassCheckHook')]

runner = dict(
    type='SamsunEpochBasedRunner',
    save_pipeline=save_pipeline,
    after_run_pipeline=after_run_pipeline,
    max_epochs=max_epochs,
)
