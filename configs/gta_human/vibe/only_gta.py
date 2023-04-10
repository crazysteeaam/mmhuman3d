_base_ = ['../../_base_/default_runtime.py']
use_adversarial_train = True

# evaluate
evaluation = dict(interval=1, metric=['pa-mpjpe', 'mpjpe', 'pve'])
dist_params = dict(backend='gloo')
# dist_params = dict(backend='nccl', port=29496)

# optimizer
optimizer = dict(
    neck=dict(type='Adam', lr=2.5e-4), head=dict(type='Adam', lr=2.5e-4))
optimizer_config = dict(grad_clip=None)
# learning policy
lr_config = dict(policy='step', gamma=0.1, step=[10])
runner = dict(type='EpochBasedRunner', max_epochs=30)

log_config = dict(
    interval=50,
    hooks=[
        dict(type='TextLoggerHook'),
        # dict(type='TensorboardLoggerHook')
    ])

img_res = 224

# model settings
model = dict(
    type='VideoBodyModelEstimator',
    neck=dict(type='TemporalGRUEncoder', num_layers=2, hidden_size=1024),
    head=dict(
        type='HMRHead',
        feat_dim=2048,
        smpl_mean_params='data/body_models/smpl_mean_params.npz',
        init_cfg=dict(
            type='Pretrained', checkpoint='data/pretrained/spin.pth')),
    body_model_train=dict(
        type='SMPL',
        keypoint_src='smpl_54',
        keypoint_dst='smpl_54',
        model_path='data/body_models/smpl',
        extra_joints_regressor='data/body_models/J_regressor_extra.npy'),
    body_model_test=dict(
        type='SMPL',
        keypoint_src='h36m',
        keypoint_dst='h36m',
        model_path='data/body_models/smpl',
        joints_regressor='data/body_models/J_regressor_h36m.npy'),
    convention='smpl_54',
    loss_keypoints3d=dict(type='SmoothL1Loss', loss_weight=100),
    loss_keypoints2d=dict(type='SmoothL1Loss', loss_weight=10),
    loss_vertex=dict(type='L1Loss', loss_weight=2),
    loss_smpl_pose=dict(type='MSELoss', loss_weight=3),
    loss_smpl_betas=dict(type='MSELoss', loss_weight=0.02))

extractor = dict(
    backbone=dict(
        type='ResNet',
        depth=50,
        out_indices=[3],
        norm_eval=False,
        norm_cfg=dict(type='SyncBN', requires_grad=True)),
    checkpoint='data/pretrained/spin.pth')
# dataset settings
dataset_type = 'HumanVideoDataset'
data_keys = [
    'has_smpl', 'smpl_body_pose', 'smpl_global_orient', 'smpl_betas',
    'smpl_transl', 'keypoints2d', 'keypoints3d', 'features', 'sample_idx',
]
train_pipeline = [
    dict(type='GetRandomScaleRotation', rot_factor=0, scale_factor=0),
    dict(type='MeshAffine', img_res=224),
    dict(type='ToTensor', keys=data_keys),
    dict(type='Collect', keys=[*data_keys], meta_keys=['image_path'])
]
adv_data_keys = [
    'smpl_body_pose', 'smpl_global_orient', 'smpl_betas', 'smpl_transl'
]
train_adv_pipeline = [
    dict(type='ToTensor', keys=adv_data_keys),
    dict(type='Collect', keys=adv_data_keys, meta_keys=[])
]

test_meta_keys = ['image_path', 'frame_idx']
test_pipeline = [
    dict(type='ToTensor', keys=['features', 'sample_idx']),
    dict(type='Collect', keys=['features', 'sample_idx'], meta_keys=[])
]
img_norm_cfg = dict(
    mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375], to_rgb=True)
extractor_pipeline = [
    dict(type='MeshAffine', img_res=224),
    dict(type='Normalize', **img_norm_cfg),
    dict(type='ImageToTensor', keys=['img']),
    dict(
        type='Collect',
        keys=['img', 'sample_idx'],
        meta_keys=['image_path', 'center', 'scale', 'rotation'])
]
inference_pipeline = test_pipeline
cache_files = {
    # 'mpi_inf_3dhp': 'data/cache2/vibe_mpi_inf_3dhp_train_smpl_54.npz',
    # 'insta_variety': 'data/cache2/vibe_insta_variety_smpl_54.npz',
    's1': 'data/cache2/vibe_gta_0.npz',
    's2': 'data/cache2/vibe_gta_1.npz',
    's3': 'data/cache2/vibe_gta_2.npz',
    's4': 'data/cache2/vibe_gta_3.npz',
    's5': 'data/cache2/vibe_gta_4.npz',
}
data = dict(
    samples_per_gpu=32,
    workers_per_gpu=1,
    train=dict(
        type='MixedDataset',
        configs=[
            dict(
                type=dataset_type,
                dataset_name='gta1',
                data_prefix='data',
                seq_len=16,
                pipeline=train_pipeline,
                convention='smpl_54',
                cache_data_path=cache_files['s1'],
                ann_file='vibe_gta_train_0.npz'),
            dict(
                type=dataset_type,
                dataset_name='gta2',
                data_prefix='data',
                seq_len=16,
                pipeline=train_pipeline,
                convention='smpl_54',
                cache_data_path=cache_files['s2'],
                ann_file='vibe_gta_train_1.npz'),
            dict(
                type=dataset_type,
                dataset_name='gta3',
                data_prefix='data',
                seq_len=16,
                pipeline=train_pipeline,
                convention='smpl_54',
                cache_data_path=cache_files['s3'],
                ann_file='vibe_gta_train_2.npz'),
            dict(
                type=dataset_type,
                dataset_name='gta4',
                data_prefix='data',
                seq_len=16,
                pipeline=train_pipeline,
                convention='smpl_54',
                cache_data_path=cache_files['s4'],
                ann_file='vibe_gta_train_3.npz'),
            dict(
                type=dataset_type,
                dataset_name='gta5',
                data_prefix='data',
                seq_len=16,
                pipeline=train_pipeline,
                convention='smpl_54',
                cache_data_path=cache_files['s5'],
                ann_file='vibe_gta_train_4.npz'),
        ],
        partition=[0.2, 0.2, 0.2, 0.2, 0.2],
        num_data=8000),
    test=dict(
        type=dataset_type,
        body_model=dict(
            type='GenderedSMPL',
            keypoint_src='h36m',
            keypoint_dst='h36m',
            model_path='data/body_models/smpl',
            joints_regressor='data/body_models/J_regressor_h36m.npy'),
        dataset_name='pw3d',
        data_prefix='data',
        seq_len=16,
        pipeline=test_pipeline,
        ann_file='vibe_pw3d_test.npz'),
    val=dict(
        type=dataset_type,
        body_model=dict(
            type='GenderedSMPL',
            keypoint_src='h36m',
            keypoint_dst='h36m',
            model_path='data/body_models/smpl',
            joints_regressor='data/body_models/J_regressor_h36m.npy'),
        dataset_name='pw3d',
        data_prefix='data',
        seq_len=16,
        pipeline=test_pipeline,
        ann_file='vibe_pw3d_test.npz'),
)
