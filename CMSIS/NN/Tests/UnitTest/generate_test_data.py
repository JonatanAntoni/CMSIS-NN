#!/usr/bin/env python3
#
# Copyright (C) 2010-2020 Arm Limited or its affiliates. All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the License); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an AS IS BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import sys
import math
import argparse
import numpy as np

from packaging import version
from abc import ABC, abstractmethod

try:
    import tensorflow as tf
except Exception as e:
    print(e)
    sys.exit(1)

REQUIRED_MINIMUM_TENSORFLOW_VERSION = version.parse("2.1.0")
DEFAULT_TESTDATA_SET = 'basic'
ALL_TESTDATA_SETS = {}
LICENSE = """/*
 * Copyright (C) 2010-2020 Arm Limited or its affiliates. All rights reserved.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the License); you may
 * not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an AS IS BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Generate input and refererence output data for unittests."
                                     " It can regenerate all data, load all stored data or a combination of it.")
    parser.add_argument('--dataset', type=str, default=DEFAULT_TESTDATA_SET, help="Name of generated test set.")
    parser.add_argument('--regenerate-weights', action='store_true', help="Regenerate and store new weights.")
    parser.add_argument('--regenerate-input', action='store_true', help="Regenerate and store new input.")
    parser.add_argument('--regenerate-biases', action='store_true', help="Regenerate and store new biases.")
    parser.add_argument('-a', '--regenerate-all', action='store_true', help="Regenerate and store all data.")
    parser.add_argument('-t', '--testtype', type=str, default='conv', choices=['conv', 'depthwise_conv', 'avgpool',
                                                                               'maxpool', 'fully_connected'],
                        help='Type of test.')
    parser.add_argument('--run-all-testsets', action='store_true', help="Run the script for all existing test "
                        "sets. Regenerate all, partially all or no input data (output may still change, depending on"
                        " changes in script) depending on regenerate flags.")

    args = parser.parse_args()
    return args


class TestSettings(ABC):

    # This is the generated test data used by the test cases.
    OUTDIR = 'TestCases/TestData/'

    # This is input to the data generation. If everything or something is regenerated then it is overwritten.
    # So it always has the same data as the OUTDIR.
    # The purpose of the pregen is primarily for debugging, as it enables to change a single parameter and see how the
    # output changes, without regenerating all input data.
    # It also convinient when tesing changes in the script, to be able to run all test sets again.
    PREGEN = 'PregeneratedData/'

    INT32_MAX = 2147483647
    INT32_MIN = -2147483648
    INT16_MAX = 32767
    INT16_MIN = -32767
    INT8_MAX = 127
    INT8_MIN = -128
    UINT8_MAX = 255
    UINT8_MIN = 0

    def __init__(self, dataset, testtype, args, in_ch, out_ch, x_in, y_in, w_x, w_y, stride_x, stride_y, pad, randmin,
                 randmax, outminrange=-128, outmaxrange=127, batches=1):

        self.tensor_flow_reference_version = ("// Generated by {} using TFL version {} as reference.\n".
                                              format(os.path.basename(__file__), tf.__version__))

        # Randomization interval
        self.mins = randmin
        self.maxs = randmax

        self.input_ch = in_ch
        self.output_ch = out_ch
        self.x_input = x_in
        self.y_input = y_in
        self.filter_x = w_x
        self.filter_y = w_y
        self.stride_x = stride_x
        self.stride_y = stride_y
        self.batches = batches
        self.test_type = testtype
        self.has_padding = pad

        minrange = randmin - 1
        maxrange = randmax + 1

        (self.input_scale, self.input_zero_point) = self.derive_scale_and_zeropoint_from_min_max(minrange, maxrange)
        (self.output_scale, self.output_zero_point) = self.derive_scale_and_zeropoint_from_min_max(outminrange,
                                                                                                   outmaxrange)
        # Always use output scale of 1, when derived it sometimes gets slighly smaller than 1,
        # which may cause output to differ.
        self.output_scale = 1.0

        self.generated_header_files = []
        self.pregenerated_data_dir = self.PREGEN
        self.testdataset = DEFAULT_TESTDATA_SET

        self.config_data = "config_data.h"
        self.testdataset = dataset
        self.kernel_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'kernel.txt'
        self.inputs_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'input.txt'
        self.bias_table_file = self.pregenerated_data_dir + self.testdataset + '/' + 'bias.txt'
        self.parameters_file = self.pregenerated_data_dir + self.testdataset + '/' + 'params.txt'

        self.set_output_dims_and_padding()

        self.regenerate_new_weights = args.regenerate_weights
        self.regenerate_new_input = args.regenerate_input
        self.regenerate_new_bias = args.regenerate_biases
        if not os.path.exists(self.parameters_file) or args.regenerate_all:
            self.regenerate_new_bias = True
            self.regenerate_new_weights = True
            self.regenerate_new_input = True
            self.save_parameters()
        else:
            self.load_parameters()

        self.headers_dir = self.OUTDIR + self.testdataset + '/'

    def clamp_int8(self, result):
        int8_min = self.INT8_MIN
        int8_max = self.INT8_MAX
        if result < int8_min:
            result = int8_min
        elif result > int8_max:
            result = int8_max
        return result

    def clamp_int32(self, result):
        int32_min = self.INT32_MIN
        int32_max = self.INT32_MAX
        if result < int32_min:
            result = int32_min
        elif result > int32_max:
            result = int32_max
        return result

    def quantize_input(self, value):
        result = round(value / self.input_scale) + self.input_zero_point
        return self.clamp_int8(result)

    def derive_scale_from_min_max(self, minrange, maxrange):
        scale = (maxrange - minrange) / ((self.INT8_MAX * 1.0) - self.INT8_MIN)
        return scale

    def derive_scale_and_zeropoint_from_min_max(self, minrange, maxrange):
        scale = self.derive_scale_from_min_max(minrange, maxrange)
        zeropoint = self.INT8_MIN + int(-minrange / scale + 0.5)
        zeropoint = max(self.INT8_MIN, min(zeropoint, -self.INT8_MIN))
        return (scale, zeropoint)

    def save_multiple_dim_array_in_txt(self, file, data):
        header = ','.join(map(str, data.shape))
        np.savetxt(file, data.reshape(-1, data.shape[-1]), header=header,
                   delimiter=',')

    def load_multiple_dim_array_from_txt(self, file):
        with open(file) as f:
            shape = list(map(int, next(f)[1:].split(',')))
            data = np.genfromtxt(f, delimiter=',').reshape(shape)
        return data.astype(np.float32)

    def save_parameters(self):
        regendir = os.path.dirname(self.parameters_file)
        if not os.path.exists(regendir):
            os.makedirs(regendir)
        params = np.array([self.input_ch, self.output_ch, self.x_input, self.y_input, self.filter_x, self.filter_y,
                           self.stride_x, self.stride_y, self.pad_x, self.pad_y, self.batches, self.has_padding])
        np.savetxt(self.parameters_file, params, fmt='%i')

    def load_parameters(self):
        params = np.loadtxt(self.parameters_file).astype(int)
        (self.input_ch, self.output_ch, self.x_input, self.y_input, self.filter_x, self.filter_y,
         self.stride_x, self.stride_y, self.pad_x, self.pad_y, self.batches, self.has_padding) = \
            (map(lambda x: x, params))

    def convert_tensor_np(self, tensor_in, converter):
        w = tensor_in.numpy()
        shape = w.shape
        w = w.ravel()
        fw = converter(w)
        fw.shape = shape
        return tf.convert_to_tensor(fw)

    def convert_tensor(self, tensor_in, converter, params=None):
        w = tensor_in.numpy()
        shape = w.shape
        w = w.ravel()
        normal = np.array(w)
        float_normal = []

        for i in normal:
            if params:
                float_normal.append(converter(i, params))
            else:
                float_normal.append(converter(i))

        np_float_array = np.asarray(float_normal)
        np_float_array.shape = shape

        return tf.convert_to_tensor(np_float_array)

    def get_randomized_data(self, dims, npfile, regenerate, decimals=0):
        if not os.path.exists(npfile) or regenerate:
            regendir = os.path.dirname(npfile)
            if not os.path.exists(regendir):
                os.makedirs(regendir)
            if decimals == 0:
                data = tf.Variable(tf.random.uniform(dims, minval=self.mins, maxval=self.maxs, dtype=tf.dtypes.int32))
                data = tf.cast(data, dtype=tf.float32)
            else:
                data = tf.Variable(tf.random.uniform(dims, minval=self.mins, maxval=self.maxs, dtype=tf.dtypes.float32))
                data = np.around(data.numpy(), decimals)
                data = tf.convert_to_tensor(data)

            print("Saving data to {}".format(npfile))
            self.save_multiple_dim_array_in_txt(npfile, data.numpy())
        else:
            print("Loading data from {}".format(npfile))
            data = tf.convert_to_tensor(self.load_multiple_dim_array_from_txt(npfile))
        return data

    def get_randomized_input_data(self, input_data):
        # Generate or load saved input data unless hardcoded data provided
        if input_data is not None:
            input_data = tf.reshape(input_data, [self.batches, self.y_input, self.x_input, self.input_ch])
        else:
            input_data = self.get_randomized_data([self.batches, self.y_input, self.x_input, self.input_ch],
                                                  self.inputs_table_file,
                                                  regenerate=self.regenerate_new_input)
        return input_data

    def get_randomized_bias_data(self, biases):
        # Generate or load saved bias data unless hardcoded data provided
        if biases is not None:
            biases = tf.reshape(biases, [self.output_ch])
        else:
            biases = self.get_randomized_data([self.output_ch],
                                              self.bias_table_file,
                                              regenerate=self.regenerate_new_bias)
        return biases

    def write_c_header_wrapper(self):
        filename = "test_data.h"
        filepath = self.headers_dir + filename

        print("Generating C header wrapper {}...".format(filepath))
        with open(filepath, 'w+') as f:
            f.write("{}\n\n".format(LICENSE))
            f.write(self.tensor_flow_reference_version)
            while len(self.generated_header_files) > 0:
                f.write('#include "{}"\n'.format(self.generated_header_files.pop()))

    def write_common_config(self, f, prefix):
        """
        Shared by conv/depthwise_conv and pooling
        """
        f.write("#define {}_FILTER_X {}\n".format(prefix, self.filter_x))
        f.write("#define {}_FILTER_Y {}\n".format(prefix, self.filter_y))
        f.write("#define {}_STRIDE_X {}\n".format(prefix, self.stride_x))
        f.write("#define {}_STRIDE_Y {}\n".format(prefix, self.stride_y))
        f.write("#define {}_PAD_X {}\n".format(prefix, self.pad_x))
        f.write("#define {}_PAD_Y {}\n".format(prefix, self.pad_y))
        f.write("#define {}_OUTPUT_W {}\n".format(prefix, self.x_output))
        f.write("#define {}_OUTPUT_H {}\n".format(prefix, self.y_output))

    def write_c_config_header(self):
        filename = self.config_data

        self.generated_header_files.append(filename)
        filepath = self.headers_dir + filename

        prefix = self.testdataset.upper()

        print("Writing C header with config data {}...".format(filepath))
        with open(filepath, "w+") as f:
            f.write("{}\n\n".format(LICENSE))
            f.write(self.tensor_flow_reference_version)
            f.write("#pragma once\n")
            f.write("#define {}_OUT_CH {}\n".format(prefix, self.output_ch))
            f.write("#define {}_IN_CH {}\n".format(prefix, self.input_ch))
            f.write("#define {}_INPUT_W {}\n".format(prefix, self.x_input))
            f.write("#define {}_INPUT_H {}\n".format(prefix, self.y_input))
            f.write("#define {}_DST_SIZE {}\n".format(prefix, self.x_output * self.y_output * self.output_ch
                                                      * self.batches))
            f.write("#define {}_INPUT_SIZE {}\n".format(prefix, self.x_input * self.y_input * self.input_ch))
            f.write("#define {}_INPUT_OFFSET {}\n".format(prefix, -self.input_zero_point))
            f.write("#define {}_OUTPUT_OFFSET {}\n".format(prefix, self.output_zero_point))
            f.write("#define {}_OUT_ACTIVATION_MIN {}\n".format(prefix, self.INT8_MIN))
            f.write("#define {}_OUT_ACTIVATION_MAX {}\n".format(prefix, self.INT8_MAX))
            f.write("#define {}_INPUT_BATCHES {}\n".format(prefix, self.batches))

    def generate_c_array(self, name, array, datatype="q7_t", const="const "):
        if not os.path.exists(self.headers_dir):
            os.makedirs(self.headers_dir)

        w = None
        if type(array) is list:
            w = array
            size = len(array)
        else:
            w = array.numpy()
            w = w.ravel()
            size = tf.size(array)
        filename = name + "_data.h"
        filepath = self.headers_dir + filename

        self.generated_header_files.append(filename)

        print("Generating C header {}...".format(filepath))
        with open(filepath, "w+") as f:
            f.write("{}\n\n".format(LICENSE))
            f.write(self.tensor_flow_reference_version)
            f.write("#pragma once\n")
            f.write("#include <stdint.h>\n\n")
            f.write(const + datatype + " " + self.testdataset + '_' + name + "[%d] =\n{\n" % size)
            for i in range(size - 1):
                f.write("  %d,\n" % w[i])
            f.write("  %d\n" % w[size - 1])
            f.write("};\n")

    def quantize_output(self, value):
        result = round(value / self.output_scale) + self.output_zero_point
        return self.clamp_int8(result)

    def set_output_dims_and_padding(self):
        if self.has_padding:
            self.x_output = math.ceil(float(self.x_input) / float(self.stride_x))
            self.y_output = math.ceil(float(self.y_input) / float(self.stride_y))
            self.padding = 'SAME'
            pad_along_width = max((self.x_output - 1) * self.stride_x + self.filter_x - self.x_input, 0)
            pad_along_height = max((self.y_output - 1) * self.stride_y + self.filter_y - self.y_input, 0)
            pad_top = pad_along_height // 2
            pad_left = pad_along_width // 2
            self.pad_x = pad_left
            self.pad_y = pad_top
        else:
            self.x_output = math.ceil(float(self.x_input - self.filter_x + 1) / float(self.stride_x))
            self.y_output = math.ceil(float(self.y_input - self.filter_y + 1) / float(self.stride_y))
            self.padding = 'VALID'
            self.pad_x = 0
            self.pad_y = 0

    @abstractmethod
    def generate_data(self, input_data=None, weights=None, biases=None):
        ''' Must be overriden '''

    def reshape_conv_kernel(self, kernel):
        """
        TFL & TFLu conv weight format: kOHWI
        Tensorflow conv weight format: kHWIO
        """
        kernel = tf.reshape(kernel, [self.output_ch, self.filter_y, self.filter_x, self.input_ch])
        kernel = tf.transpose(kernel, (1, 2, 0, 3))
        kernel = tf.transpose(kernel, (0, 1, 3, 2))
        return kernel

    def reshape_depthwise_conv_kernel(self, kernel):
        """
        TFL & TFLu depthwise conv weight format: k1HWO
        Tensorflow depthwise conv weight format: kHWIM
        """
        kernel = tf.reshape(kernel, [1, self.filter_y, self.filter_x, self.output_ch])
        kernel = tf.transpose(kernel, (1, 0, 2, 3))
        kernel = tf.transpose(kernel, (0, 2, 1, 3))
        kernel = tf.reshape(kernel, [self.filter_y, self.filter_x, self.input_ch, self.channel_multiplier])
        return kernel

    def conv2d(self, indata, weights, bias=None):
        """
        There is no tf.nn.fully_connected so this is used by fully_connected tests as well.
        """
        indata = tf.cast(indata, dtype=tf.dtypes.float32)
        weights = tf.cast(weights, dtype=tf.dtypes.float32)
        bias = tf.cast(bias, dtype=tf.dtypes.float32)

        out = tf.nn.conv2d(indata, weights, strides=[1, self.stride_y, self.stride_x, 1], padding=self.padding)

        if tf.TensorShape([self.batches, self.y_output, self.x_output, self.output_ch]).as_list() != \
           out.shape.as_list():
            raise RuntimeError("Shape mismatch, need to regenerate data?")

        out = tf.nn.bias_add(out, bias)
        out = tf.clip_by_value(out, self.INT8_MIN, self.INT8_MAX)

        return out

    def quantize_scale(self, scale):
        significand, shift = math.frexp(scale)
        significand_q31 = round(significand * (1 << 31))
        return significand_q31, shift


class ConvSettings(TestSettings):

    def __init__(self, dataset, testtype, args, in_ch=1, out_ch=1, x_in=7, y_in=7, w_x=3, w_y=3, stride_x=2, stride_y=2,
                 pad=True, randmin=-7, randmax=7, outminrange=-128, outmaxrange=127, batches=1):
        super().__init__(dataset, testtype, args, in_ch, out_ch, x_in, y_in, w_x, w_y, stride_x, stride_y, pad,
                         randmin, randmax, outminrange, outmaxrange, batches)

        self.scaling_factors = []

        if self.test_type == 'conv':
            self.quantized_dimension = 0
        elif self.test_type == 'depthwise_conv':
            self.quantized_dimension = 3
            self.channel_multiplier = self.output_ch // self.input_ch
            if self.output_ch % self.input_ch != 0:
                raise RuntimeError("out channel ({}) is not multiple of in channel ({})".format(out_ch, in_ch))

        else:
            raise RuntimeError("Invalid test type {}".format(self.test_type))

    def write_c_config_header(self):
        super().write_c_config_header()

        filename = self.config_data
        filepath = self.headers_dir + filename
        prefix = self.testdataset.upper()

        with open(filepath, "a") as f:
            self.write_common_config(f, prefix)
            if self.test_type == 'depthwise_conv':
                f.write("#define {}_CH_MULT {}\n".format(prefix, self.channel_multiplier))

    def quantize_bias(self, nparray):
        num_channels = self.output_ch
        quantized_values = []

        values = np.array(nparray)

        def quantize_float_to_int(value, scale):
            if scale == 0:
                print("WARNING: scale is 0")
                scale = 0.0000001
            quantized = round(value / scale)
            if quantized > self.INT16_MAX:
                quantized = self.INT16_MAX
            elif quantized < self.INT16_MIN:
                quantized = self.INT16_MIN
            return quantized

        for x in range(num_channels):
            quantized_values.append(quantize_float_to_int(values[x], self.scaling_factors[x]*self.input_scale))

        return np.asarray(quantized_values)

    def quantize_filter(self, nparray):
        channel_count = self.output_ch

        if self.quantized_dimension == 0:
            input_size = self.filter_y * self.filter_x * self.input_ch * self.output_ch
        elif self.quantized_dimension == 3:
            input_size = self.filter_y * self.filter_x * self.input_ch * self.channel_multiplier

        per_channel_size = input_size // channel_count

        if self.quantized_dimension == 0:
            stride = 1
            channel_stride = per_channel_size
        elif self.quantized_dimension == 3:
            stride = channel_count
            channel_stride = 1

        values = np.array(nparray)
        quantized_values = values.copy()

        for channel in range(channel_count):
            fmin = 0
            fmax = 0
            for i in range(per_channel_size):
                idx = channel * channel_stride + i * stride
                fmin = min(fmin, values[idx])
                fmax = max(fmax, values[idx])

            self.scaling_factors.append(max(abs(fmin), abs(fmax)) / self.INT8_MAX)

            for x in range(per_channel_size):
                chs = channel * channel_stride + x * stride
                quantized_value = round(round(values[chs]) / self.scaling_factors[channel])

                # Clamp
                quantized_value = min(127, max(-127, quantized_value))
                quantized_values[chs] = quantized_value

        return np.asarray(quantized_values)

    def generate_quantize_per_channel_multiplier(self):
        num_channels = self.output_ch
        per_channel_multiplier = []
        per_channel_shift = []

        if len(self.scaling_factors) != num_channels:
            raise RuntimeError("Missing scaling factors")

        for i in range(num_channels):
            effective_output_scale = self.input_scale * self.scaling_factors[i] / self.output_scale
            (quantized_multiplier, shift) = self.quantize_scale(effective_output_scale)

            per_channel_multiplier.append(quantized_multiplier)
            per_channel_shift.append(shift)

        self.generate_c_array("output_mult", per_channel_multiplier, datatype='int32_t')
        self.generate_c_array("output_shift", per_channel_shift, datatype='int32_t')

    def depthwise_conv2d(self, indata, weights, bias=None):
        indata = tf.cast(indata, dtype=tf.dtypes.float32)
        weights = tf.cast(weights, dtype=tf.dtypes.float32)
        bias = tf.cast(bias, dtype=tf.dtypes.float32)

        out = tf.nn.depthwise_conv2d(indata,
                                     weights,
                                     strides=[1, self.stride_y, self.stride_x, 1],
                                     padding=self.padding)

        if tf.TensorShape([self.batches, self.y_output, self.x_output, self.output_ch]) \
             .as_list() != out.shape.as_list():
            raise RuntimeError("Shape mismatch, regenerate data?")

        out = tf.nn.bias_add(out, bias)
        out = tf.clip_by_value(out, self.INT8_MIN, self.INT8_MAX)

        return out

    def generate_data(self, input_data=None, weights=None, biases=None):
        # Tensorflow Lite has a different kernel format compared to Tensorflow
        reshaped_weights = None

        input_data = self.get_randomized_input_data(input_data)

        if self.test_type == 'conv':
            out_channel = self.output_ch
        elif self.test_type == 'depthwise_conv':
            out_channel = self.channel_multiplier

        if weights is not None:
            weights = tf.reshape(weights, [self.filter_y, self.filter_x, self.input_ch, out_channel])
        else:
            weights = self.get_randomized_data([self.filter_y, self.filter_x, self.input_ch, out_channel],
                                               self.kernel_table_file,
                                               regenerate=self.regenerate_new_weights)

        if self.test_type == 'conv':
            reshaped_weights = self.reshape_conv_kernel(weights)
        elif self.test_type == 'depthwise_conv':
            reshaped_weights = self.reshape_depthwise_conv_kernel(weights)

        biases = self.get_randomized_bias_data(biases)

        # Generate reference
        if self.test_type == 'conv':
            conv = self.conv2d(input_data, reshaped_weights, biases)
        elif self.test_type == 'depthwise_conv':
            conv = self.depthwise_conv2d(input_data, reshaped_weights, biases)

        # Quantize and write to C headers
        self.generate_c_array("input", self.convert_tensor(input_data, self.quantize_input))
        self.generate_c_array("weights", self.convert_tensor_np(weights, self.quantize_filter))
        self.generate_c_array("biases", self.convert_tensor_np(biases, self.quantize_bias), "int32_t")
        self.generate_quantize_per_channel_multiplier()
        self.generate_c_array("output_ref", self.convert_tensor(conv, self.quantize_output))

        self.write_c_config_header()
        self.write_c_header_wrapper()


class PoolingSettings(TestSettings):

    def __init__(self, dataset, testtype, args, randmin=-7, randmax=7, channels=8, x_in=4, y_in=4, w_x=4, w_y=4,
                 stride_x=1, stride_y=1, batches=1, pad=False):
        super().__init__(dataset, testtype, args, channels, channels, x_in, y_in, w_x, w_y, stride_x, stride_y, pad,
                         randmin, randmax)

    def generate_data(self, input_data=None):
        input_data = self.get_randomized_input_data(input_data)
        input_data = self.convert_tensor(input_data, self.quantize_input)
        self.generate_c_array("input", input_data, datatype="int8_t", const="")

        input_data = tf.cast(input_data, tf.float32)

        if self.test_type == 'avgpool':
            pooling = self.average_pooling(input_data)
        elif self.test_type == 'maxpool':
            pooling = self.max_pooling(input_data)
        else:
            raise RuntimeError("Wrong test type")

        if self.y_output != pooling.shape[1] or self.x_output != pooling.shape[2] or self.output_ch != pooling.shape[3]:
            raise RuntimeError("Mismatching output dimensions")

        self.generate_c_array("output_ref", self.convert_tensor(pooling, self.quantize_output), datatype="int8_t")

        self.write_c_config_header()
        self.write_c_header_wrapper()

    def write_c_config_header(self):
        super().write_c_config_header()

        filename = self.config_data
        filepath = self.headers_dir + filename
        prefix = self.testdataset.upper()

        with open(filepath, "a") as f:
            self.write_common_config(f, prefix)

    def average_pooling(self, x):
        return tf.nn.avg_pool(x,
                              ksize=[1, self.filter_y, self.filter_x, 1],
                              strides=[1, self.stride_y, self.stride_x, 1],
                              padding=self.padding)

    def max_pooling(self, x):
        return tf.nn.max_pool(x,
                              ksize=[1, self.filter_y, self.filter_x, 1],
                              strides=[1, self.stride_y, self.stride_x, 1],
                              padding=self.padding)


class FullyConnectedSettings(TestSettings):

    def __init__(self, dataset, testtype, args, in_ch=1, out_ch=1, x_in=1, y_in=1, w_x=1, w_y=1, stride_x=1, stride_y=1,
                 pad=False, randmin=-7, randmax=7, outminrange=-128, outmaxrange=127, batches=1, input_scale=1.0,
                 input_zero_point=0, weights_scale=1.0, weights_zero_point=0, bias_scale=1.0, output_scale=1.0,
                 output_zero_point=0):
        super().__init__(dataset, testtype, args, in_ch, out_ch, x_in, y_in, w_x, w_y, stride_x, stride_y, pad, randmin,
                         randmax, outminrange, outmaxrange, batches)

        if not self.test_type == 'fully_connected':
            raise RuntimeError("Invalid test type {}".format(self.test_type))
        if x_in != w_x or y_in != w_y:
            raise RuntimeError("Mismatching input and filter dimensions")

        self.input_scale = input_scale
        self.input_zero_point = input_zero_point
        self.weights_scale = weights_scale
        self.weights_zero_point = weights_zero_point
        self.bias_scale = bias_scale
        self.output_scale = output_scale
        self.output_zero_point = output_zero_point

    def write_c_config_header(self):
        super().write_c_config_header()

        filename = self.config_data
        filepath = self.headers_dir + filename
        prefix = self.testdataset.upper()

        with open(filepath, "a") as f:
            f.write("#define {}_WEIGHTS_OFFSET {}\n".format(prefix, -self.weights_zero_point))
            f.write("#define {}_OUTPUT_MULTIPLIER {}\n".format(prefix, self.quantized_multiplier))
            f.write("#define {}_OUTPUT_SHIFT {}\n".format(prefix, self.quantized_shift))
            f.write("#define {}_ACCUMULATION_DEPTH {}\n".format(prefix, self.input_ch*self.x_input*self.y_input))

    def quantize_multiplier(self):
        input_product_scale = self.input_scale * self.weights_scale
        if input_product_scale < 0:
            raise RuntimeError("negative input product scale")
        real_multipler = input_product_scale / self.output_scale
        (self.quantized_multiplier, self.quantized_shift) = self.quantize_scale(real_multipler)

    def derive_filter_scale_and_zeropoint_from_min_max(self, mini, maxi):
        scale = self.derive_scale_from_min_max(mini, maxi)
        zero = int(self.INT8_MIN + (-mini/scale + 0.5))
        return (scale, zero)

    def quantize_bias(self, value):
        result = int(value / self.bias_scale)
        return self.clamp_int32(result)

    def quantize_weights(self, value):
        result = round(value / self.weights_scale) + self.weights_zero_point
        return self.clamp_int8(result)

    def generate_data(self, input_data=None, weights=None, biases=None):
        input_data = self.get_randomized_input_data(input_data)

        if weights is not None:
            weights = tf.reshape(weights, [self.filter_y, self.filter_x, self.input_ch, self.output_ch])
        else:
            weights = self.get_randomized_data([self.filter_y, self.filter_x, self.input_ch, self.output_ch],
                                               self.kernel_table_file,
                                               regenerate=self.regenerate_new_weights)

        biases = self.get_randomized_bias_data(biases)

        conv = self.conv2d(input_data, self.reshape_conv_kernel(weights), biases)

        self.generate_c_array("input", self.convert_tensor(input_data, self.quantize_input))
        self.generate_c_array("weights", self.convert_tensor(weights, self.quantize_weights))
        self.generate_c_array("biases", self.convert_tensor(biases, self.quantize_bias), "int32_t")
        self.generate_c_array("output_ref", self.convert_tensor(conv, self.quantize_output))

        self.quantize_multiplier()

        self.write_c_config_header()
        self.write_c_header_wrapper()


def load_all_testdatasets():
    """
    Add all new testdata sets here
    """

    type_of_test = 'conv'
    dataset = 'kernel1x1'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=4, out_ch=17, x_in=15,
                                              y_in=15, w_x=1, w_y=1, stride_x=1, stride_y=1, pad=False,
                                              randmin=1, randmax=4, outminrange=-126, outmaxrange=127)
    dataset = 'conv_3'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=3, out_ch=1, x_in=10, y_in=49, w_x=4,
                                              w_y=10, stride_x=1, stride_y=2, pad=True, randmin=-2, randmax=2,
                                              outminrange=-127, outmaxrange=127)
    dataset = 'conv_1_x_n_1'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=3, out_ch=3, x_in=5, y_in=5, w_x=2,
                                              w_y=1, stride_x=2, stride_y=1, pad=False, randmin=-2, randmax=2,
                                              outminrange=-127, outmaxrange=127, batches=2)
    dataset = 'conv_1_x_n_2'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=3, out_ch=1, x_in=11, y_in=11, w_x=11,
                                              w_y=1, stride_x=1, stride_y=1, pad=True, randmin=-2, randmax=2,
                                              outminrange=-127, outmaxrange=127)
    dataset = 'conv_1_x_n_3'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=1, out_ch=3, x_in=11, y_in=11, w_x=1,
                                              w_y=11, stride_x=1, stride_y=1, pad=True, randmin=-2, randmax=2,
                                              outminrange=-127, outmaxrange=127)
    dataset = 'conv_2'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=2, out_ch=4, x_in=6, y_in=3, w_x=3,
                                              w_y=3, stride_x=1, stride_y=1, pad=True, randmin=1, randmax=4,
                                              outminrange=-126, outmaxrange=127)
    dataset = 'conv_4'  # batches > 2
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=3, out_ch=3, x_in=5, y_in=5, w_x=2,
                                              w_y=3, stride_x=2, stride_y=2, pad=False, randmin=-2, randmax=2,
                                              outminrange=-127, outmaxrange=127, batches=3)

    type_of_test = 'depthwise_conv'
    dataset = 'depthwise_2'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=3, out_ch=9, x_in=6, y_in=5, w_x=3,
                                              w_y=4, stride_x=2, stride_y=2, pad=True, randmin=-2, randmax=2,
                                              outminrange=-126, outmaxrange=127)
    dataset = 'depthwise_kernel_3x3'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=5, out_ch=5, x_in=4, y_in=5, w_x=3,
                                              w_y=3, stride_x=2, stride_y=2, pad=True, randmin=-2, randmax=2,
                                              outminrange=-126, outmaxrange=127)
    dataset = 'depthwise_eq_in_out_ch'
    ALL_TESTDATA_SETS[dataset] = ConvSettings(dataset, type_of_test, args, in_ch=6, out_ch=6, x_in=4, y_in=5, w_x=2,
                                              w_y=3, stride_x=1, stride_y=1, pad=True, randmin=-2, randmax=2,
                                              outminrange=-126, outmaxrange=127)

    type_of_test = 'fully_connected'
    dataset = 'fully_connected'
    ALL_TESTDATA_SETS[dataset] = FullyConnectedSettings(dataset, type_of_test, args, in_ch=10, out_ch=6, x_in=2, y_in=1,
                                                        w_x=2, w_y=1, randmin=-4, randmax=4, batches=3,
                                                        input_zero_point=-50, weights_zero_point=-22,
                                                        output_zero_point=-2)

    type_of_test = 'avgpool'
    dataset = 'avgpooling'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=8, x_in=22, y_in=12, stride_x=9,
                                                 stride_y=5, w_x=6, w_y=5, pad=True)
    dataset = 'avgpooling_1'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=3, x_in=9, y_in=5, stride_x=1,
                                                 stride_y=2, w_x=9, w_y=5, pad=False)
    dataset = 'avgpooling_2'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=5, x_in=12, y_in=1, stride_x=1,
                                                 stride_y=2, w_x=3, w_y=1, pad=True)
    dataset = 'avgpooling_3'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=2, x_in=9, y_in=1, stride_x=2,
                                                 stride_y=1, w_x=1, w_y=1, pad=False)
    dataset = 'avgpooling_4'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=2, x_in=1, y_in=20, stride_x=1,
                                                 stride_y=3, w_x=1, w_y=3, pad=True)
    dataset = 'maxpooling_5'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=20, x_in=1, y_in=1, stride_x=1,
                                                 stride_y=1, w_x=1, w_y=1, pad=True)

    type_of_test = 'maxpool'
    dataset = 'maxpooling_6'
    ALL_TESTDATA_SETS[dataset] = PoolingSettings(dataset, type_of_test, args, channels=17, x_in=1, y_in=5, stride_x=1,
                                                 stride_y=3, w_x=3, w_y=4, pad=True)


if __name__ == '__main__':
    if version.parse(tf.__version__) < REQUIRED_MINIMUM_TENSORFLOW_VERSION:
        print("Unsupported tensorflow version, ", version.parse(tf.__version__))
        sys.exit(0)

    args = parse_args()
    testdataset = args.dataset
    test_type = args.testtype

    load_all_testdatasets()

    if (args.run_all_testsets):
        for testset_name, testset_generator in ALL_TESTDATA_SETS.items():
            print("Generating testset {}..".format(testset_name))
            testset_generator.generate_data()
            print()
    else:
        try:
            generator = ALL_TESTDATA_SETS[testdataset]
        except KeyError:
            print("WARNING: testset {} not in testset list".format(testdataset))
            if args.testtype == 'conv' or args.testtype == 'depthwise_conv':
                generator = ConvSettings(testdataset, test_type, args)
            elif args.testtype == 'fully_connected':
                generator = FullyConnectedSettings(testdataset, test_type, args)
            elif args.testtype == 'avgpool' or args.testtype == 'maxpool':
                generator = PoolingSettings(testdataset, test_type, args)
        generator.generate_data()
