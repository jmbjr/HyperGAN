import tensorflow as tf
import hyperchamber as hc
import inspect
import copy
import os
import operator
from functools import reduce

from hypergan.ops.tensorflow.extended_ops import bicubic_interp_2d
from .base_discriminator import BaseDiscriminator
from hypergan.configurable_component import ConfigurableComponent

class ConfigurableDiscriminator(BaseDiscriminator, ConfigurableComponent):
    def __init__(self, gan, config, name=None, input=None, reuse=None, x=None, g=None, features=[], skip_connections=[]):
        ConfigurableComponent.__init__(self, gan, config, name=name, input=input,features=features,reuse=reuse, x=x, g=g)
        BaseDiscriminator.__init__(self, gan, config, name=name, input=input,reuse=reuse, x=x, g=g)

