#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Base class for loading dataset for the CTC model.
   You can use the multi-GPU version.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import random
import numpy as np
import tensorflow as tf

from ..sparsetensor import list2sparsetensor


class DatasetBase(object):

    def __init__(self, data_type, label_type, batch_size,
                 num_stack=None, num_skip=None,
                 is_sorted=True, is_progressbar=False, num_gpu=1):
        """Load all dataset in advance.
        Args:
            data_type: string
            label_type: stirng
            batch_size: int, the size of mini-batch
            num_stack: int, the number of frames to stack
            num_skip: int, the number of frames to skip
            is_sorted: if True, sort dataset by frame num
            is_progressbar: if True, visualize progressbar
            num_gpu: int, if more than 1, divide batch_size by num_gpu
        """
        self.data_type = data_type
        self.label_type = label_type
        self.batch_size = batch_size * num_gpu
        self.is_sorted = is_sorted
        self.is_progressbar = is_progressbar
        self.num_gpu = num_gpu

        self.input_size = None

        # Step
        # 1. Load the frame number dictionary
        self.frame_num_dict = None

        # 2. Load all paths to input & label
        self.input_paths = None
        self.label_paths = None
        self.data_num = None

        # 3. Load all dataset in advance
        self.input_list = None
        self.label_list = None
        self.rest = set([i for i in range(self.data_num)])

    def next_batch(self, batch_size=None, session=None):
        """Make mini-batch.
        Args:
            batch_size: int, the size of mini-batch
            session:
        Returns:
            inputs: list of input data, size `[batch_size]`
            labels_st: list of SparseTensor of target labels
            inputs_seq_len: list of length of inputs of size `[batch_size]`
            input_names: list of file name of input data of size `[batch_size]`

            If num_gpu > 1, each return is divide into list of size `[num_gpu]`.
        """
        if session is None and self.num_gpu != 1:
            raise ValueError('Set session when using multiple GPUs.')

        if batch_size is None:
            batch_size = self.batch_size

        next_epoch_flag = False
        padded_value = -1

        while True:
            #########################
            # sorted dataset
            #########################
            if self.is_sorted:
                if len(self.rest) > batch_size:
                    sorted_indices = list(self.rest)[:batch_size]
                    self.rest -= set(sorted_indices)
                else:
                    sorted_indices = list(self.rest)
                    self.rest = set([i for i in range(self.data_num)])
                    next_epoch_flag = True
                    if self.data_type == 'train':
                        print('---Next epoch---')

                # Compute max frame num in mini-batch
                max_frame_num = self.input_list[sorted_indices[-1]].shape[0]

                # Compute max target label length in mini-batch
                max_seq_len = max(map(len, self.label_list[sorted_indices]))

                # Shuffle selected mini-batch
                random.shuffle(sorted_indices)

                # Initialization
                inputs = np.zeros(
                    (len(sorted_indices), max_frame_num, self.input_size))
                labels = np.array([[padded_value] * max_seq_len]
                                  * len(sorted_indices), dtype=int)
                inputs_seq_len = np.empty((len(sorted_indices),), dtype=int)
                input_names = [None] * len(sorted_indices)

                # Set values of each data in mini-batch
                for i_batch, x in enumerate(sorted_indices):
                    data_i = self.input_list[x]
                    frame_num = data_i.shape[0]
                    inputs[i_batch, :frame_num, :] = data_i
                    labels[i_batch, :len(self.label_list[x])
                           ] = self.label_list[x]
                    inputs_seq_len[i_batch] = frame_num
                    input_names[i_batch] = os.path.basename(
                        self.input_paths[x]).split('.')[0]

            #########################
            # not sorted dataset
            #########################
            else:
                if len(self.rest) > batch_size:
                    # Randomly sample mini-batch
                    random_indices = random.sample(
                        list(self.rest), batch_size)
                    self.rest -= set(random_indices)
                else:
                    random_indices = list(self.rest)
                    self.rest = set([i for i in range(self.data_num)])
                    next_epoch_flag = True
                    if self.data_type == 'train':
                        print('---Next epoch---')

                    # Shuffle selected mini-batch
                    random.shuffle(random_indices)

                # Compute max frame num in mini-batch
                max_frame_num = max(
                    map(lambda x: x.shape[0], self.input_list[random_indices]))

                # Compute max target label length in mini-batch
                max_seq_len = max(map(len, self.label_list[random_indices]))

                # Initialization
                inputs = np.zeros(
                    (len(random_indices), max_frame_num, self.input_size))
                labels = np.array([[padded_value] * max_seq_len]
                                  * len(random_indices), dtype=int)
                inputs_seq_len = np.empty((len(random_indices),), dtype=int)
                input_names = [None] * len(random_indices)

                # Set values of each data in mini-batch
                for i_batch, x in enumerate(random_indices):
                    data_i = self.input_list[x]
                    frame_num = data_i.shape[0]
                    inputs[i_batch, :frame_num, :] = data_i
                    labels[i_batch, :len(self.label_list[x])
                           ] = self.label_list[x]
                    inputs_seq_len[i_batch] = frame_num
                    input_names[i_batch] = os.path.basename(
                        self.input_paths[x]).split('.')[0]

            if self.num_gpu > 1:
                divide_num = self.num_gpu
                if next_epoch_flag:
                    for i in range(self.num_gpu, 0, -1):
                        if len(self.rest) % i == 0:
                            divide_num = i
                            break
                    next_epoch_flag = False

                # Now we split the mini-batch data by num_gpu
                inputs = tf.split(inputs, divide_num, axis=0)
                labels = tf.split(labels, divide_num, axis=0)
                inputs_seq_len = tf.split(inputs_seq_len, divide_num, axis=0)
                input_names = tf.split(input_names, divide_num, axis=0)

                # Convert from SparseTensor to numpy.ndarray
                inputs = list(map(session.run, inputs))
                labels = list(map(session.run, labels))
                labels_st = list(map(list2sparsetensor,
                                     zip(labels, [padded_value] * len(labels))))
                inputs_seq_len = list(map(session.run, inputs_seq_len))
                input_names = list(map(session.run, input_names))
            else:
                labels_st = list2sparsetensor(labels,
                                              padded_value=padded_value)

            yield inputs, labels_st, inputs_seq_len, input_names