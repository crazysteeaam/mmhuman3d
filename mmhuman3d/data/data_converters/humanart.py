from typing import List

import pdb
import time
import numpy as np
import pandas as pd
import json
import cv2
import glob
import random
from tqdm import tqdm
import torch
import smplx
import ast

from mmhuman3d.core.cameras import build_cameras
from mmhuman3d.core.conventions.keypoints_mapping import convert_kps
from mmhuman3d.data.data_structures.human_data import HumanData
from .base_converter import BaseModeConverter
from .builder import DATA_CONVERTERS
# import mmcv
from mmhuman3d.models.body_models.builder import build_body_model
# from mmhuman3d.core.conventions.keypoints_mapping import smplx
from mmhuman3d.core.conventions.keypoints_mapping import get_keypoint_idxs_by_part


import pdb


@DATA_CONVERTERS.register_module()
class HumanartConverter(BaseModeConverter):

    ACCEPTED_MODES = ['']

    def __init__(self, modes: List[str] = None):

        super(HumanartConverter, self).__init__(modes)
