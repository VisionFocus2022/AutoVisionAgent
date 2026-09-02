import time
import samsuncn.mdl.pipelines.init_pipeline as smpi

custom_imports = dict(
    imports=[

        'samsuncn.mdl.samsun_dataset',

    ],
    allow_failed_imports=True)

######begin
my_img_scale = (1024, 640)  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_mean = [56.32, 56.32, 56.32]  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_std = [61.42, 61.42, 61.42]  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_work_dir = r'D:\Datasets\SSEG\traindir\process\train'  # #~~~~~~~~~~~~~~~~~~~~~~~~
my_label_path = ""  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_samples_per_gpu = 2  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_workers_per_gpu = 0  # ~~~~~~~~~~~~~~~~~~~~~~~~
my_max_epochs = 12  # #~~~~~~~~~~~~~~~~~~~~~~~~ 默认200000
my_data_expansion = 1  # 数据扩充系数    #~~~~~~~~~~~~~~~~~~~~~~~~ 默认1 最大10
my_data_root = r'D:\Datasets\SSEG\savevoc\SamsunDataset'
my_img_suffix = '.bmp'
my_checkpoint_interval = 1000
my_evaluation_interval = 1000
my_resume_from = None
######end
checkpoint_interval = my_checkpoint_interval
evaluation_interval = my_evaluation_interval
img_scale = my_img_scale
mean = my_mean
std = my_std

work_dir = my_work_dir  # ~~~~~~~
label_path = my_label_path  # ~~~~~~~~
samples_per_gpu = my_samples_per_gpu
workers_per_gpu = my_workers_per_gpu
max_iters = my_max_epochs
data_expansion = my_data_expansion
data_root = my_data_root  # 需要新增这

img_norm_cfg = dict(
    mean=mean, std=std, to_rgb=True)
crop_size = (256, 256)
img_suffix = my_img_suffix

timestamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
dataset_type = 'SamsunVOCDataset'
num_classes = len(
    smpi.LoadCategoryList()(results={'label_path': label_path
                                     })['category_list'])

classes_list = smpi.LoadCategoryList()(results={'label_path': label_path})['category_list']
if 'background' not in classes_list:
    num_classes += 1
classes_map = (smpi.LoadCategoryList()(results={
    'label_path': label_path
})['category_map'])

train_pipeline = [
    dict(type='LoadImageFromFile'),
    dict(type='LoadAnnotations'),
    dict(type='Resize', img_scale=img_scale, keep_ratio=True),
    dict(type='RandomCrop', crop_size=crop_size, cat_max_ratio=0.75),
    dict(type='RandomFlip', prob=0.5),
    dict(
        type='Normalize', **img_norm_cfg),
    dict(type='Pad',

         size_divisor=32,
         pad_val=0, seg_pad_val=255),
    dict(type='DefaultFormatBundle'),
    dict(type='Collect', keys=['img', 'gt_semantic_seg'])
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
            dict(
                type='Normalize', **img_norm_cfg),
            dict(type='Pad',

                 size_divisor=32,
                 pad_val=0, seg_pad_val=255),
            dict(type='ImageToTensor', keys=['img']),
            dict(type='Collect', keys=['img'])
        ])
]
data = dict(
    persistent_workers=False,
    samples_per_gpu=samples_per_gpu,
    workers_per_gpu=workers_per_gpu,
    train=dict(
        type='RepeatDataset',
        times=data_expansion,
        dataset=dict(
            type=dataset_type,
            data_root=data_root,
            img_suffix=img_suffix,
            label_mapping_dict=classes_map,
            img_dir='JPEGImages',
            ann_dir='SegmentationClass',
            split='ImageSets/Segmentation/train.txt',
            pipeline=train_pipeline)),
    val=dict(
        type=dataset_type,
        data_root=data_root,
        img_suffix=img_suffix,
        label_mapping_dict=classes_map,
        img_dir='JPEGImages',
        ann_dir='SegmentationClass',
        split='ImageSets/Segmentation/val.txt',
        pipeline=test_pipeline),

    test=dict(
        type=dataset_type,
        data_root=data_root,
        img_suffix=img_suffix,
        label_mapping_dict=classes_map,
        img_dir='JPEGImages',
        ann_dir='SegmentationClass',
        split='ImageSets/Segmentation/all.txt',
        pipeline=test_pipeline))

norm_cfg = dict(type='BN', requires_grad=True)
model = dict(
    type='EncoderDecoder',
    pretrained=r'./TrainConfigs/resnet50_v1c-2cccc1ad.pth',
    backbone=dict(
        type='ResNetV1c',
        depth=50,
        num_stages=4,
        out_indices=(0, 1, 2, 3),
        dilations=(1, 1, 2, 4),
        strides=(1, 2, 1, 1),
        norm_cfg=dict(type='BN', requires_grad=True),
        norm_eval=False,
        style='pytorch',
        contract_dilation=True),
    decode_head=dict(
        type='DepthwiseSeparableASPPHead',
        in_channels=2048,
        in_index=3,
        channels=512,
        dilations=(1, 12, 24, 36),
        c1_in_channels=256,
        c1_channels=48,
        dropout_ratio=0.1,
        num_classes=num_classes,
        norm_cfg=dict(type='BN', requires_grad=True),
        align_corners=False,
        loss_decode=dict(
            type='CrossEntropyLoss', use_sigmoid=False, loss_weight=1.0)),
    auxiliary_head=dict(
        type='FCNHead',
        in_channels=1024,
        in_index=2,
        channels=256,
        num_convs=1,
        concat_input=False,
        dropout_ratio=0.1,
        num_classes=num_classes,
        norm_cfg=dict(type='BN', requires_grad=True),
        align_corners=False,
        loss_decode=dict(
            type='CrossEntropyLoss', use_sigmoid=False, loss_weight=0.4)),
    train_cfg=dict(),
    test_cfg=dict(mode='whole'))

log_config = dict(
    interval=50, hooks=[dict(type='TextLoggerHook', by_epoch=False)])
dist_params = dict(backend='nccl')
log_level = 'INFO'
load_from = "./TrainConfigs/pretrain_sseg.pth"
# resume_from = None                      #    开放，点击训练，弹窗是否继承，是，从上次最后的resume,否，重来
resume_from = my_resume_from
workflow = [('train', 1)]
cudnn_benchmark = True
opencv_num_threads = 0
optimizer = dict(type='SGD', lr=0.01, momentum=0.9, weight_decay=0.0005)
optimizer_config = dict()
lr_config = dict(policy='poly', power=0.9, min_lr=0.0001, by_epoch=False)
runner = dict(type='IterBasedRunner', max_iters=max_iters)
checkpoint_config = dict(by_epoch=False, interval=checkpoint_interval, max_keep_ckpts=3)    # interval=1000     save间隔系数
evaluation = dict(interval=evaluation_interval, metric='mIoU', pre_eval=True)              # interval=1000      eval间隔系数

gpu_ids = [0]
auto_resume = False
