import numpy as np
import glob
import random
import cv2
import os
import argparse
import torch
import pyrender
import trimesh
import PIL.Image as pil_img

from tqdm import tqdm

from mmhuman3d.core.cameras import build_cameras
from mmhuman3d.core.conventions.keypoints_mapping import get_keypoint_idx, get_keypoint_idxs_by_part
from tools.convert_datasets import DATASET_CONFIGS
from mmhuman3d.models.body_models.builder import build_body_model
from tools.utils.request_files_server import request_files, request_files_name
from tools.vis.visualize_humandata_qp import render_pose as render_pose_qp
import pdb

smpl_shape = {'betas': (-1, 10), 'transl': (-1, 3), 'global_orient': (-1, 3), 'body_pose': (-1, 69)}
smplx_shape = {'betas': (-1, 10), 'transl': (-1, 3), 'global_orient': (-1, 3), 
        'body_pose': (-1, 21, 3), 'left_hand_pose': (-1, 15, 3), 'right_hand_pose': (-1, 15, 3), 
        'leye_pose': (-1, 3), 'reye_pose': (-1, 3), 'jaw_pose': (-1, 3), 'expression': (-1, 10)}
smplx_shape_except_expression = {'betas': (-1, 10), 'transl': (-1, 3), 'global_orient': (-1, 3), 
        'body_pose': (-1, 21, 3), 'left_hand_pose': (-1, 15, 3), 'right_hand_pose': (-1, 15, 3), 
        'leye_pose': (-1, 3), 'reye_pose': (-1, 3), 'jaw_pose': (-1, 3)}
smplx_shape = smplx_shape_except_expression

def get_cam_params(camera_params_dict, dataset_name, param, idx):

    eft_datasets = ['ochuman','lspet', 'posetrack']

    R, T = None, None
    # read cam params
    if dataset_name in camera_params_dict.keys():
        cx, cy = camera_params_dict[dataset_name]['principal_point']
        fx, fy = camera_params_dict[dataset_name]['focal_length']
        camera_center = (cx, cy)
        focal_length = (fx, fy)
        if R in camera_params_dict[dataset_name].keys():
            R = camera_params_dict[dataset_name]['R']
        if T in camera_params_dict[dataset_name].keys():
            T = camera_params_dict[dataset_name]['T']
    elif dataset_name in eft_datasets:
        pred_cam = param['meta'].item()['pred_cam'][idx]
        cam_scale, cam_trans = pred_cam[0], pred_cam[1:]
        # pdb.set_trace()
        bbox_xywh = param['bbox_xywh_vis'][idx][:4]
        R = np.eye(3) * cam_scale * bbox_xywh[-1] / 2
        T = np.array([
                (cam_trans[0]+1)*bbox_xywh[-1]/2 + bbox_xywh[0], 
                (cam_trans[1]+1)*bbox_xywh[-1]/2 + bbox_xywh[1], 
                0])
        focal_length = [5000, 5000]
        camera_center = [0, 0]
    else:
        try:
            focal_length = param['meta'].item()['focal_length'][idx]
            camera_center = param['meta'].item()['principal_point'][idx]
        except KeyError:
            focal_length = param['misc'].item()['focal_length']
            camera_center = param['meta'].item()['principal_point']
        except TypeError:
            focal_length = param['meta'].item()['focal_length']
            camera_center = param['meta'].item()['princpt']
        try:
            R = param['meta'].item()['R'][idx]
            T = param['meta'].item()['T'][idx]
        except KeyError:
            R = None
            T = None
        except IndexError:
            R = None
            T = None

    if dataset_name in ['muco3dhp']:
        R = None
        T = None
    # pdb.set_trace()
        
    focal_length = np.asarray(focal_length).reshape(-1)
    camera_center = np.asarray(camera_center).reshape(-1)

    if len(focal_length)==1:
        focal_length = [focal_length, focal_length]
    if len(camera_center)==1:
        camera_center = [camera_center, camera_center]

    return focal_length, camera_center, R, T


def render_pose(img, body_model_param, body_model, camera, return_mask=False,
                 R=None, T=None, dataset_name=None, camera_opencv=None):

    # the inverse is same
    pyrender2opencv = np.array([[1.0, 0, 0, 0],
                                [0, -1, 0, 0],
                                [0, 0, -1, 0],
                                [0, 0, 0, 1]])
    
    output = body_model(**body_model_param, return_verts=True)
    
    vertices = output['vertices'].detach().cpu().numpy().squeeze()

    # # overlay on img
    # verts = output['vertices']
    # verts2d = camera_opencv.transform_points_screen(verts)[..., :2].detach().cpu().numpy()
    
    # for i in range(verts2d.shape[1]):
    #     cv2.circle(img, (int(verts2d[0, i, 0]), int(verts2d[0, i, 1])), 1, (0, 255, 0), -1)


    eft_datasets = ['ochuman', 'lspet', 'posetrack']
    # adjust vertices beased on R and T
    if R is not None:
        joints = output['joints'].detach().cpu().numpy().squeeze()
        root_joints = joints[0]
        if dataset_name in eft_datasets:
            vertices = np.dot(R, vertices.transpose(1,0)).transpose(1,0) + T.reshape(1,3)
            vertices[:, 2] = (vertices[:, 2]-vertices[:, 2].min())/ (vertices[:, 2].max()-vertices[:, 2].min())*30 +500
            vertices[:, :2] *= vertices[:, [2]]
            vertices[:, :2] /= 5000.
        else:
            T = np.dot(np.array(R), root_joints) - root_joints  + np.array(T)
            vertices = vertices + T

    faces = body_model.faces

    # render material
    base_color = (1.0, 193/255, 193/255, 1.0)
    material = pyrender.MetallicRoughnessMaterial(
            metallicFactor=0.0,
            alphaMode='OPAQUE',
            baseColorFactor=base_color)
    
    # get body mesh
    body_trimesh = trimesh.Trimesh(vertices, faces, process=False)
    body_mesh = pyrender.Mesh.from_trimesh(body_trimesh, material=material)

    # prepare camera and light
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=2.0)
    cam_pose = pyrender2opencv @ np.eye(4)
    
    # build scene
    scene = pyrender.Scene(bg_color=[0.0, 0.0, 0.0, 0.0],
                                    ambient_light=(0.3, 0.3, 0.3))
    scene.add(camera, pose=cam_pose)
    scene.add(light, pose=cam_pose)
    scene.add(body_mesh, 'mesh')

    # render scene
    os.environ["PYOPENGL_PLATFORM"] = "osmesa" # include this line if use in vscode
    r = pyrender.OffscreenRenderer(viewport_width=img.shape[1],
                                    viewport_height=img.shape[0],
                                    point_size=1.0)
    
    color, _ = r.render(scene, flags=pyrender.RenderFlags.RGBA)
    color = color.astype(np.float32) / 255.0
    # alpha = 1.0  # set transparency in [0.0, 1.0]
    # color[:, :, -1] = color[:, :, -1] * alpha
    valid_mask = (color[:, :, -1] > 0)[:, :, np.newaxis]
    img = img / 255
    # output_img = (color[:, :, :-1] * valid_mask + (1 - valid_mask) * img)
    output_img = (color[:, :, :] * valid_mask + (1 - valid_mask) * img)

    # output_img = color

    img = (output_img * 255).astype(np.uint8)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    if return_mask:
        return img, valid_mask, (color * 255).astype(np.uint8)

    return img


def render_multi_pose(img, body_model_params, body_models, genders, cameras,
                        Rs=[], Ts=[]):

    masks, colors = [], []

    # render separate masks
    for i, body_model_param in enumerate(body_model_params):

        R = Rs[i]
        T = Ts[i]
        _, mask, color = render_pose(img=img, 
                                        body_model_param=body_model_param, 
                                        body_model=body_models[genders[i]],
                                        camera=cameras[i],
                                        return_mask=True,
                                        R=R, T=T,)
        masks.append(mask)
        colors.append(color)

    # sum masks
    mask_sum = np.sum(masks, axis=0)
    mask_all = (mask_sum > 0)

    # pp_occ = 1 - np.sum(mask_all) / np.sum(mask_sum)

    # overlay colors to img
    for i, color in enumerate(colors):
        mask = masks[i]
        img = img * (1 - mask) + color * mask

    img = img.astype(np.uint8)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    return img


def visualize_humandata(args, local_datasets, server_datasets):
    
    humandata_datasets = [ # name, glob pattern, exclude pattern
        ('agora', 'agora*forvis*.npz', ''),
        ('arctic', 'p1_train.npz', ''),
        ('bedlam', 'bedlam_train.npz', ''),
        ('behave', 'behave_train_230516_231_downsampled.npz', ''),
        ('chi3d', 'CHI3D_train_230511_1492_*.npz', ''),
        ('crowdpose', 'crowdpose_neural_annot_train_new.npz', ''),
        ('lspet', 'eft_lspet*.npz', ''),
        ('ochuman', 'eft_ochuman*.npz', ''),
        ('posetrack', 'eft_posetrack*.npz', ''),
        ('egobody_ego', 'egobody_egocentric_train_230425_065_fix_betas.npz', ''),
        ('egobody_kinect', 'egobody_kinect_train_230503_065_fix_betas.npz', ''),
        ('fit3d', 'FIT3D_train_230511_1504_*.npz', ''),
        ('gta', 'gta_human2multiple_230406_04000_0.npz', ''),
        ('ehf', 'h4w_ehf_val_updated_v2.npz', ''),  # use humandata ehf to get bbox
        ('h36m', 'h36m*', ''),
        ('humansc3d', 'HumanSC3D_train_230511_2752_*.npz', ''),
        ('instavariety', 'insta_variety_neural_annot_train.npz', ''),
        ('mpii', 'mpii*.npz', ''),
        ('mpi_inf_3dhp', 'mpi_inf_3dhp_neural_annot_train.npz', ''),
        ('mscoco', '*coco2017*.npz', ''),
        ('mtp', 'mtp_smplx_train.npz', ''),
        ('muco3dhp', 'muco3dhp_train.npz', ''),
        ('prox', 'prox_train_smplx_new.npz', ''),
        ('pw3d', 'pw3d*.npz', ''),
        ('renbody', 'renbody_train_230525_399_*.npz', ''),
        ('renbody_highres', 'renbody_train_highrescam_230517_399_*_fix_betas.npz', ''),
        ('rich', 'rich_train_fix_betas.npz', ''),
        ('spec', 'spec_train_smpl.npz', ''),
        ('ssp3d', 'ssp3d_230525_311.npz', ''),
        ('synbody_magic1', 'synbody_amass_230328_02172.npz', ''),
        ('synbody', 'synbody_train_230521_04000_fix_betas.npz', ''),
        ('talkshow', 'talkshow_smplx_*.npz', 'path'),
        ('up3d', 'up3d*.npz', ''),
    ]

    dataset_path_dict = {
        'agora': '/lustrenew/share_data/caizhongang/data/datasets/agora',
        'arctic': '/lustre/share_data/weichen1/arctic/unpack/arctic_data/data/images',
        'behave': '/mnt/e/behave',
        'bedlam': '/lustre/share_data/weichen1/bedlam/train_images',
        'CHI3D': '/mnt/d/sminchisescu-research-datasets',
        'crowdpose': '/lustrenew/share_data/zoetrope/data/datasets/crowdpose',
        'lspet': '/lustrenew/share_data/zoetrope/data/datasets/hr-lspet',
        'ochuman': '/lustrenew/share_data/zoetrope/data/datasets/ochuman',
        'egobody': '/mnt/d/egobody',
        'FIT3D': '/mnt/d/sminchisescu-research-datasets',
        'gta_human2': '/mnt/e/gta_human2',
        'ehf': '/mnt/e/ehf',
        'HumanSC3D': '/mnt/d/sminchisescu-research-datasets',
        'h36m': '/lustrenew/share_data/zoetrope/osx/data/Human36M',
        'instavariety': '/lustrenew/share_data/zoetrope/data/datasets/neural_annot_data/insta_variety/',
        'mpii': '/lustrenew/share_data/zoetrope/data/datasets/mpii',
        'mpi_inf_3dhp': '/lustrenew/share_data/zoetrope/osx/data/MPI_INF_3DHP_folder/data/',
        'mscoco': '/lustrenew/share_data/zoetrope/data/datasets/coco/train_2017',
        'mtp': '/lustre/share_data/weichen1/mtp',
        'muco3dhp': '/lustre/share_data/weichen1/MuCo',
        'posetrack': 'lustrenew/share_data/zoetrope/data/datasets/posetrack/data/images',
        'prox': '/lustre/share_data/weichen1/PROXFlip',
        'pw3d': '',
        'renbody': '/lustre/share_data/weichen1/renbody',
        'renbody_highres': '/lustre/share_data/weichen1/renbody',
        'rich': '/lustrenew/share_data/zoetrope/data/datasets/rich/images/train',
        'spec': '/lustre/share_data/weichen1/spec/',
        'ssp3d': '/mnt/e/ssp-3d',
        'synbody': '/lustre/share_data/meihaiyi/shared_data/SynBody',
        'synbody_magic1': '/lustre/share_data/weichen1/synbody',
        'talkshow': '/lustre/share_data/weichen1/talkshow_frames',
        'ubody': '/mnt/d/ubody',
        'up3d': '/lustrenew/share_data/zoetrope/data/datasets/up3d/up-3d/up-3d',

        }
    
    anno_path = {
        'shapy': 'output',
        'gta_human2': 'output',
        'egobody': 'output',
        'ubody': 'output',
        'ssp3d': 'output',
        'FIT3D': 'output',
        'CHI3D': 'output',
        'HumanSC3D': 'output',
        'behave': 'output',
        'ehf': 'output'}
    
    camera_params_dict = {
        'gta_human2': {'principal_point': [960, 540], 'focal_length': [1158.0337, 1158.0337]},
        'ssp3d': {'focal_length': [5000, 5000], 'principal_point': [256, 256]},
        'synbody': {'focal_length': [640, 640], 'principal_point': [640, 360]},
        'ehf': {'focal_length': [1498.224, 1498.224], 'principal_point': [790.263706, 578.90334],
                'T': np.array([-0.03609917, 0.43416458, 2.37101226]),
                'R': np.array([[ 0.9992447 , -0.00488005,  0.03855169],
                            [-0.01071995, -0.98820424,  0.15276562],
                            [ 0.03735144, -0.15306349, -0.9875102 ]]),},
    }

    # load humandata
    dataset_name = args.dataset_name
    flat_hand_mean = args.flat_hand_mean

    if dataset_name not in server_datasets:
        param_ps = glob.glob(os.path.join(dataset_path_dict[dataset_name], 
                                            anno_path[dataset_name], f'*{dataset_name}*.npz'))
        param_ps = [p for p in param_ps if 'test' not in p]
        # param_ps = [p for p in param_ps if 'val' not in p]
    else:
        data_info = [info for info in humandata_datasets if info[0] == dataset_name][0]
        _, filename, exclude = data_info

        param_ps = glob.glob(os.path.join(args.server_local_path, filename))
        if exclude != '':
            param_ps = [p for p in param_ps if exclude not in p]
    
    # render
    # for npz_id, param_p in enumerate(tqdm(param_ps, desc=f'Processing npzs',
    #                     position=0, leave=False)):
    for npz_id, param_p in enumerate(param_ps):
        param = dict(np.load(param_p, allow_pickle=True))

        # check for params
        has_smplx, has_smpl, has_gender = False, False, False
        if 'smplx' in param.keys():
            has_smplx = True
        elif 'smpl' in param.keys():
            has_smpl = True
        elif 'smplh' in param.keys():
            has_smplh = True

        # check for params
        has_smplx, has_smpl, has_gender = False, False, False
        if 'smplx' in param.keys():
            has_smplx = True
        elif 'smpl' in param.keys():
            has_smpl = True

        # load params
        if has_smpl:
            body_model_param_smpl = param['smpl'].item()
        if has_smplx:
            body_model_param_smplx = param['smplx'].item()  
            if dataset_name == 'bedlam':
                body_model_param_smplx['betas'] = body_model_param_smplx['betas'][:, :10]
                flat_hand_mean = True
        if has_smplh:
            body_model_param_smpl = param['smplh'].item()
            data_len = body_model_param_smpl['betas'].shape[0]
            body_model_param_smpl['body_pose'] = np.concatenate([body_model_param_smpl['body_pose'], 
                                                np.array([0, 0, 0], dtype=np.float32).reshape(-1, 1, 3).repeat(data_len, axis=0),
                                               np.array([0, 0, 0], dtype=np.float32).reshape(-1, 1, 3).repeat(data_len, axis=0),], axis=1)
            # pdb.set_trace()
            has_smpl = True

        if 'meta' in param.keys():
            if 'gender' in param['meta'].item().keys():
                has_gender = True
        # read smplx only if has both smpl and smplx
        if has_smpl and has_smplx:
            has_smpl = False

        device = 'cuda:0' if torch.cuda.is_available() else 'cpu'

        # build smpl model
        if has_smpl:
            smpl_model = {}
            for gender in ['male', 'female', 'neutral']:
                smpl_model[gender] = build_body_model(dict(
                        type='SMPL',
                        keypoint_src='smpl_45',
                        keypoint_dst='smpl_45',
                        model_path='data/body_models/smpl',
                        gender=gender,
                        num_betas=10,
                        use_face_contour=True,
                        flat_hand_mean=flat_hand_mean,
                        use_pca=False,
                        batch_size=1
                    )).to(device)
                
        # build smplx model
        if has_smplx:
            smplx_model = {}
            for gender in ['male', 'female', 'neutral']:
                smplx_model[gender] = build_body_model(dict(
                        type='SMPLX',
                        keypoint_src='smplx',
                        keypoint_dst='smplx',
                        model_path='data/body_models/smplx',
                        gender=gender,
                        num_betas=10,
                        use_face_contour=True,
                        flat_hand_mean=flat_hand_mean,
                        use_pca=False,
                        batch_size=1
                    )).to(device)
        
        # for idx in idx_list:
        sample_size =  args.sample_size
        if sample_size > len(param['image_path']):
            idxs = range(len(param['image_path']))
        else:
            idxs = random.sample(range(len(param['image_path'])), sample_size)

        # idxs = [340, 139181]
        # prepare for server request if datasets on server
        # pdb.set_trace()
        if dataset_name in server_datasets:
            # print('getting images from server...')
            files = param['image_path'][idxs].tolist()
            # pdb.set_trace()
            local_image_folder = os.path.join(args.image_cache_path, dataset_name)
            os.makedirs(local_image_folder, exist_ok=True)
            request_files(files, 
                        server_path=dataset_path_dict[dataset_name], 
                        local_path=local_image_folder, 
                        server_name='1988')
            # print('done')
        else:
            local_image_folder = dataset_path_dict[dataset_name]

        for idx in tqdm(sorted(idxs), desc=f'Processing npzs {npz_id}/{len(param_ps)}, sample size: {sample_size}',
                        position=0, leave=False):

            image_p = param['image_path'][idx]
            image_path = os.path.join(local_image_folder, image_p)
            image = cv2.imread(image_path)
            # convert to BGR
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            # check for if multiple people exist
            range_min = max(0, idx - 3000)
            img_idxs = [img_i for img_i, imgp in enumerate(
                        # param['image_path'].tolist()[range_min:idx+3000]) if imgp == image_p]
                        param['image_path'].tolist()) if imgp == image_p]


            # temporal fix for betas and gender
            if dataset_name in ['bedlam']:
                has_gender = False

            if not (args.render_all_smpl and len(img_idxs) >= 2):
                # ---------------------- render single pose ------------------------
                # read cam params
                focal_length, camera_center, R, T = get_cam_params(
                                camera_params_dict, args.dataset_name, param, idx)
        
                # read gender
                if has_gender:
                    try:
                        gender = param['meta'].item()['gender'][idx]
                        if gender == 'f':
                            gender = 'female'
                        elif gender == 'm':
                            gender = 'male'
                    except IndexError: 
                        gender = 'neutral'
                else:
                    gender = 'neutral'

                if args.save_pose:
                    # prepare for mesh projection
                    camera = pyrender.camera.IntrinsicsCamera(
                        fx=focal_length[0], fy=focal_length[1],
                        cx=camera_center[0], cy=camera_center[1])
                    # camera_opencv = build_cameras(
                    #             dict(type='PerspectiveCameras',
                    #                 convention='opencv',
                    #                 in_ndc=False,
                    #                 focal_length=np.array([focal_length[0], focal_length[1]]).reshape(-1, 2),
                    #                 principal_point=np.array([camera_center[0], camera_center[1]]).reshape(-1, 2),
                    #                 image_size=(image.shape[0], image.shape[1]))).to(device)
                    
                    # read smpl smplx params and build body model
                    if has_smpl:
                        intersect_key = list(set(body_model_param_smpl.keys()) & set(smpl_shape.keys()))
                        body_model_param_tensor = {key: torch.tensor(
                                np.array(body_model_param_smpl[key][idx:idx+1]).reshape(smpl_shape[key]),
                                        device=device, dtype=torch.float32)
                                        for key in intersect_key
                                        if len(body_model_param_smpl[key][idx:idx+1]) > 0}
                        
                        # temporal fix for ochuman, lspet, posetrack
                        if dataset_name in ['ochuman', 'lspet', 'posetrack']:
                            zfar, znear= 600, 30
                            camera = pyrender.camera.IntrinsicsCamera(
                                fx=focal_length[0], fy=focal_length[1],
                                cx=camera_center[0], cy=camera_center[1],
                                zfar=zfar, znear=znear)
                            rendered_image = render_pose(img=image, 
                                                    body_model_param=body_model_param_tensor, 
                                                    body_model=smpl_model[gender],
                                                    camera=camera,
                                                    dataset_name=dataset_name,
                                                    # eft=True,
                                                    R=R, T=T)             
                        else:
                            rendered_image = render_pose(img=image, 
                                                body_model_param=body_model_param_tensor, 
                                                body_model=smpl_model[gender],
                                                camera=camera,
                                                dataset_name=dataset_name,
                                                R=R, T=T)

                    if has_smplx:
                        intersect_key = list(set(body_model_param_smplx.keys()) & set(smplx_shape.keys()))
                        body_model_param_tensor = {key: torch.tensor(
                                np.array(body_model_param_smplx[key][idx:idx+1]).reshape(smplx_shape[key]),
                                        device=device, dtype=torch.float32)
                                        for key in intersect_key
                                        if len(body_model_param_smplx[key][idx:idx+1]) > 0}
                        rendered_image = render_pose(img=image, 
                                                    body_model_param=body_model_param_tensor, 
                                                    body_model=smplx_model[gender],
                                                    camera=camera,
                                                    dataset_name=dataset_name,
                                                    R=R, T=T, camera_opencv=None)

            else:
                # ---------------------- render multiple pose ----------------------
                params, genders, cameras, Rs, Ts = [], [], [], [], []

                # prepare camera
                for pp_img_idx in img_idxs:
                    focal_length, camera_center, R, T = get_cam_params(
                        camera_params_dict, args.dataset_name, param, pp_img_idx)
                    camera = pyrender.camera.IntrinsicsCamera(
                        fx=focal_length[0], fy=focal_length[1],
                        cx=camera_center[0], cy=camera_center[1])
                    if dataset_name in ['ochuman', 'lspet', 'posetrack']:
                        zfar, znear= 600, 30
                        camera = pyrender.camera.IntrinsicsCamera(
                            fx=focal_length[0], fy=focal_length[1],
                            cx=camera_center[0], cy=camera_center[1],
                        zfar=zfar, znear=znear)
                    cameras.append(camera)
                    Rs.append(R)
                    Ts.append(T)

                    # read gender
                    if has_gender:
                        try:
                            gender = param['meta'].item()['gender'][pp_img_idx]
                            if gender == 'f':
                                gender = 'female'
                            elif gender == 'm':
                                gender = 'male'
                        except IndexError: 
                            gender = 'neutral'
                    else:
                        gender = 'neutral'
                    genders.append(gender)

                    # print(genders)


                if has_smpl:
                    for pp_img_idx in img_idxs:
                        intersect_key = list(set(body_model_param_smpl.keys()) & set(smpl_shape.keys()))
                        body_model_param_tensor = {key: torch.tensor(
                                np.array(body_model_param_smpl[key][pp_img_idx:pp_img_idx+1]).reshape(smpl_shape[key]),
                                        device=device, dtype=torch.float32)
                                        for key in intersect_key
                                        if len(body_model_param_smpl[key][pp_img_idx:pp_img_idx+1]) > 0}
                        params.append(body_model_param_tensor)
                    rendered_image = render_multi_pose(img=image, 
                                                body_model_params=params, 
                                                body_models=smpl_model,
                                                genders=genders,
                                                cameras=cameras,
                                                Rs=Rs, Ts=Ts)

                if has_smplx:
                    for pp_img_idx in img_idxs:
                        intersect_key = list(set(body_model_param_smplx.keys()) & set(smplx_shape.keys()))
                        body_model_param_tensor = {key: torch.tensor(
                        np.array(body_model_param_smplx[key][pp_img_idx:pp_img_idx+1]).reshape(smplx_shape[key]),
                                device=device, dtype=torch.float32)
                                for key in intersect_key
                                if len(body_model_param_smplx[key][pp_img_idx:pp_img_idx+1]) > 0}
                        params.append(body_model_param_tensor)
                    rendered_image = render_multi_pose(img=image, 
                                                body_model_params=params, 
                                                body_models=smplx_model,
                                                genders=genders,
                                                cameras=cameras,
                                                Rs=Rs, Ts=Ts)
                    
            # ---------------------- render results ----------------------
            # print(f'Truncation: {trunc}')
            if not args.save_pose:
                rendered_image = image
            os.makedirs(os.path.join(args.out_path, args.dataset_name), exist_ok=True)

            # for writting on image
            font_size = image.shape[1] / 1000
            line_sickness = int(image.shape[1] / 1000) + 1
            front_location_y = int(image.shape[1] / 10)
            front_location_x = int(image.shape[0] / 10)

            if args.save_pose:
                out_image_path = os.path.join(args.out_path, args.dataset_name,
                                            f'{os.path.basename(param_ps[npz_id])[:-4]}_{idx}.png')
                # print(f'Saving image to {out_image_path}')
                cv2.imwrite(out_image_path, rendered_image)
            
            if args.save_original_img:
                out_image_path_org = os.path.join(args.out_path, args.dataset_name,
                                            f'{os.path.basename(param_ps[npz_id])[:-4]}_{idx}_original.png')
                # convert to RGB
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                cv2.imwrite(out_image_path_org, image)

            # pdb.set_trace()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset_name', type=str, required=False, 
                        help='which dataset', 
                        default='')
    # parser.add_argument('--dataset_path', type=str, required=True, help='path to the dataset')
    parser.add_argument('--out_path', type=str, required=False, 
                        help='path to the output folder',
                        default='/mnt/c/users/12595/desktop/humandata_vis')
    parser.add_argument('--server_local_path', type=str, required=False, 
                        help='local path to where you save the annotations of server datasets',
                        default='/mnt/d/annotations_1988')
    parser.add_argument('--image_cache_path', type=str, required=False,
                        help='local path to image cache folder for server datasets',
                        default='/mnt/d/image_cache_1988')

    # optional args
    parser.add_argument('--save_original_img', type=bool, required=False,
                        help='save original images',
                        default=True)
    parser.add_argument('--save_pose', type=bool, required=False,
                        help='save rendered smpl/smplx pose images',
                        default=True)
    parser.add_argument('--sample_size', type=int, required=False,
                        help='number of samples to visualize',
                        default=1000)
    parser.add_argument('--render_all_smpl', type=bool, required=False,
                        help='render all smpl/smplx models (works for multipeople datasets)',
                        default=True)
    parser.add_argument('--flat_hand_mean', type=bool, required=False,
                        help='use flat hand mean for smplx',
                        default=False)
    args = parser.parse_args()

    # dataset status
    local_datasets = ['gta_human2', 'egobody', 'ubody', 'ssp3d', 
                          'FIT3D', 'CHI3D', 'HumanSC3D']
    # some datasets are on 1988
    server_datasets = ['agora', 'arctic', 'bedlam', 'crowdpose', 'lspet', 'ochuman',
                       'posetrack', 'instavariety', 'mpi_inf_3dhp',
                       'mtp', 'muco3dhp', 'prox', 'renbody', 'rich', 'spec',
                       'synbody','talkshow', 'up3d', 'renbody_highres',
                       'mscoco', 'mpii', 'h36m']
    
    if args.dataset_name != '':
        visualize_humandata(args, local_datasets, server_datasets)
    else:
        for dataset_to_vis in server_datasets:
            args.dataset_name = dataset_to_vis
            try:
                print(f'processing dataset: {args.dataset_name}')
                visualize_humandata(args, local_datasets, server_datasets)
            except:
                pass
    