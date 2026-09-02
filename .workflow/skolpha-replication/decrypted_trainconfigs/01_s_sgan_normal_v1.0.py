
domain_a = 'horse'
domain_b = 'zebra'
######begin
my_img_scale = (256, 256)
my_mean = [0.5, 0.5, 0.5]
my_std = [0.5, 0.5, 0.5]
my_work_dir = 'E:/SSIGMA/Projects/gangan_SGAN_00002_1714035803/process/train'
my_label_path = 'E:/SSIGMA/Projects/gangan_SGAN_00002_1714035803/process/train'
my_samples_per_gpu = 2
my_workers_per_gpu = 2
my_max_epochs = 20000
my_data_expansion = 10
my_data_root = 'E:/SSIGMA/Projects/gangan_SGAN_00002_1714035803/data/SamsunDataset/train'
my_img_suffix = '.bmp'
my_checkpoint_interval = 1000
my_evaluation_interval = 1000
my_resume_from = None 
######end
train_dataset_type = val_dataset_type = 'UnpairedImageDataset'
total_iters = my_max_epochs
work_dir = my_work_dir  

model = dict(
    type='CycleGAN',
    generator=dict(
        type='ResnetGenerator',
        in_channels=3,
        out_channels=3,
        base_channels=64,
        norm_cfg=dict(type='IN'),
        use_dropout=False,
        num_blocks=9,
        padding_mode='reflect',
        init_cfg=dict(type='normal', gain=0.02)),
    discriminator=dict(
        type='PatchDiscriminator',
        in_channels=3,
        base_channels=64,
        num_conv=3,
        norm_cfg=dict(type='IN'),
        init_cfg=dict(type='normal', gain=0.02)),
    gan_loss=dict(
        type='GANLoss',
        gan_type='lsgan',
        real_label_val=1.0,
        fake_label_val=0.0,
        loss_weight=1.0),
    default_domain=domain_b,
    reachable_domains=[domain_a, domain_b],
    related_domains=[domain_a, domain_b],
    gen_auxiliary_loss=[
        dict(
            type='L1Loss',
            loss_weight=10.0,
            loss_name='cycle_loss',
            data_info=dict(
                pred=f'cycle_{domain_a}', target=f'real_{domain_a}'),
            reduction='mean'),
        dict(
            type='L1Loss',
            loss_weight=10.0,
            loss_name='cycle_loss',
            data_info=dict(
                pred=f'cycle_{domain_b}',
                target=f'real_{domain_b}',
            ),
            reduction='mean')
    ])
train_cfg = dict(buffer_size=50)
test_cfg = None

img_norm_cfg = dict(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
train_pipeline = [
    dict(
        type='LoadImageFromFile',
        io_backend='disk',
        key=f'img_{domain_a}',
        flag='color'),
    dict(
        type='LoadImageFromFile',
        io_backend='disk',
        key=f'img_{domain_b}',
        flag='color'),
    dict(
        type='Resize',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        scale=my_img_scale,
        interpolation='bicubic'),
    dict(
        type='Crop',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        crop_size=(256, 256),
        random_crop=True),
    dict(type='Flip', keys=[f'img_{domain_a}'], direction='horizontal'),
    dict(type='Flip', keys=[f'img_{domain_b}'], direction='horizontal'),
    dict(type='RescaleToZeroOne', keys=[f'img_{domain_a}', f'img_{domain_b}']),     # 将图像从[0，255]重缩放到[0，1]
    dict(
        type='Normalize',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        to_rgb=True,
        mean=[0.5, 0.5, 0.5],
        std=[0.5, 0.5, 0.5]),
    dict(type='ImageToTensor', keys=[f'img_{domain_a}', f'img_{domain_b}']),
    dict(
        type='Collect',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        meta_keys=[f'img_{domain_a}_path', f'img_{domain_b}_path'])
]

test_pipeline = [
    dict(
        type='LoadImageFromFile',
        io_backend='disk',
        key=f'img_{domain_a}',
        flag='color'),
    dict(
        type='LoadImageFromFile',
        io_backend='disk',
        key=f'img_{domain_b}',
        flag='color'),
    dict(
        type='Resize',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        scale=my_img_scale,
        interpolation='bicubic'),
    dict(type='RescaleToZeroOne', keys=[f'img_{domain_a}', f'img_{domain_b}']),
    dict(
        type='Normalize',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        to_rgb=True,
        mean=[0.5, 0.5, 0.5],
        std=[0.5, 0.5, 0.5]),
    dict(type='ImageToTensor', keys=[f'img_{domain_a}', f'img_{domain_b}']),
    dict(
        type='Collect',
        keys=[f'img_{domain_a}', f'img_{domain_b}'],
        meta_keys=[f'img_{domain_a}_path', f'img_{domain_b}_path'])
]

data = dict(
    samples_per_gpu=my_samples_per_gpu,
    workers_per_gpu=my_workers_per_gpu,
    drop_last=True,
    train=dict(
        type='RepeatDataset',
        times=my_data_expansion,
        dataset=dict(
            type=train_dataset_type,
            dataroot=my_data_root,
            pipeline=train_pipeline,
            test_mode=False,
            domain_a=domain_a,
            domain_b=domain_b)),
    val=dict(
        type=val_dataset_type,
        dataroot=my_data_root,
        test_mode=True,
        domain_a=domain_a,
        domain_b=domain_b,
        pipeline=test_pipeline),
    test=dict(
        type=val_dataset_type,
        dataroot=my_data_root,
        test_mode=True,
        domain_a=domain_a,
        domain_b=domain_b,
        pipeline=test_pipeline))

optimizer = dict(
    generators=dict(type='Adam', lr=0.0002, betas=(0.5, 0.999)),
    discriminators=dict(type='Adam', lr=0.0002, betas=(0.5, 0.999)))

# learning policy
lr_config = dict(
    policy='Linear', by_epoch=False, target_lr=0, start=1000, interval=1000)

# default_runtime
checkpoint_config = dict(interval=my_checkpoint_interval, save_optimizer=True, by_epoch=False)
log_config = dict(
    interval=100,
    hooks=[
        dict(type='TextLoggerHook'),
        # dict(type='TensorboardLoggerHook'),
    ])
custom_hooks = [
    dict(
        type='MMGenVisualizationHook',
        output_dir='training_samples',
        res_name_list=[f'fake_{domain_a}', f'fake_{domain_b}'],
        interval=my_checkpoint_interval)
]

runner = None
use_ddp_wrapper = True
dist_params = dict(backend='nccl')
log_level = 'INFO'
load_from = './TrainConfigs/pretrain_sgan.pth'
resume_from = my_resume_from
find_unused_parameters = True
cudnn_benchmark = True
# disable opencv multithreading to avoid system being overloaded
opencv_num_threads = 0
# set multi-process start method as `fork` to speed up the training
mp_start_method = 'fork'

image_shape = (3,) + my_img_scale
workflow = [('train', 1)]
num_images = 5
metrics = dict(
    FID=dict(type='FID', num_images=num_images, image_shape=image_shape),
    IS=dict(
        type='SamsunIS',
        num_images=num_images,
        image_shape=image_shape,
        inception_args=dict(type='pytorch')))

evaluation = dict(
    type='TranslationEvalHook',
    target_domain=domain_b,
    interval=my_evaluation_interval,
    metrics=[
        dict(type='FID', num_images=num_images, bgr2rgb=True),
        dict(
            type='SamsunIS',
            num_images=num_images,
            inception_args=dict(type='pytorch'))
    ],
    best_metric=['fid', 'is'])