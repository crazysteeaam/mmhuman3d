import glob
import json
import os
import pdb
import random
import time
from typing import List

import cv2
import numpy as np
import pandas as pd
import smplx
import torch
from tqdm import tqdm

from mmhuman3d.core.cameras import build_cameras
# from mmhuman3d.core.conventions.keypoints_mapping import smplx
from mmhuman3d.core.conventions.keypoints_mapping import (
    convert_kps,
    get_keypoint_idx,
    get_keypoint_idxs_by_part,
)
from mmhuman3d.data.data_structures.human_data import HumanData
# import mmcv
from mmhuman3d.models.body_models.builder import build_body_model
from mmhuman3d.models.body_models.utils import (
    batch_transform_to_camera_frame,
    transform_to_camera_frame,
)
from .base_converter import BaseModeConverter
from .builder import DATA_CONVERTERS


@DATA_CONVERTERS.register_module()
class Cimi4dConverter(BaseModeConverter):

    ACCEPTED_MODES = ['train']

    def __init__(self, modes: List = []) -> None:
        # check pytorch device
        self.device = torch.device(
            'cuda' if torch.cuda.is_available() else 'cpu')
        self.misc_config = dict(
            bbox_source='keypoints2d_smplx',
            smplx_source='original',
            flat_hand_mean=False,
            camera_param_type='perspective',
            kps3d_root_aligned=False,
            bbox_body_scale=1.2,
            bbox_facehand_scale=1.0,
        )
        self.smplx_shape = {
            'betas': (-1, 10),
            'transl': (-1, 3),
            'global_orient': (-1, 3),
            'body_pose': (-1, 21, 3),
            'left_hand_pose': (-1, 15, 3),
            'right_hand_pose': (-1, 15, 3),
            'leye_pose': (-1, 3),
            'reye_pose': (-1, 3),
            'jaw_pose': (-1, 3),
            'expression': (-1, 10)
        }

        super(Cimi4dConverter, self).__init__(modes)


    def convert_by_mode(self, dataset_path: str, out_path: str,
                    mode: str) -> dict:
        
        # get target sequences
        seqs = glob.glob(os.path.join(dataset_path, 'XMU*', '*'))

        # use HumanData to store all data
        human_data = HumanData()

        # parse each sequence
        for seq in seqs:
            
            # load params
            pickle_p = glob.glob(os.path.join(seq, '*.pkl'))[0]
            params = dict(np.load(pickle_p, allow_pickle=True))

            # get info
            transl = np.array(params['gt_trans'], dtype=np.float32)
            betas = np.array(params['beta'], dtype=np.float32)
            betas = betas.reshape(-1, 10)

            pose = np.array(params['gt_pose_3D'], dtype=np.float32).reshape(-1, 24, 3)
            body_pose = pose[:, 1:, :]
            global_orient = pose[:, 0, :].reshape(-1, 3)

            # repeat betas
            betas = np.repeat(betas, transl.shape[0], axis=0) 
            
            # image paths
            image_paths = sorted(glob.glob(os.path.join(seq, '**', '*.jpg'), recursive=True))

            # translation need for official vis tools

        




            pdb.set_trace() 





        pass