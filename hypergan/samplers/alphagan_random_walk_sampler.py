from hypergan.samplers.base_sampler import BaseSampler
import tensorflow as tf
import numpy as np

class AlphaganRandomWalkSampler(BaseSampler):
    def __init__(self, gan, samples_per_row=8):
        BaseSampler.__init__(self, gan, samples_per_row)
        self.z = None
        self.y = None
        self.x = None
        self.mask = None
        self.step = 0
        self.steps = 8
        self.target = None

    def _sample(self):
        gan = self.gan
        z_t = gan.uniform_encoder.sample
        inputs_t = gan.inputs.x
        mask_t = gan.mask_generator.sample

        if self.z is None:
            self.input = gan.session.run(gan.inputs.x)
            self.z = gan.session.run(gan.encoder.sample, feed_dict={
                inputs_t: self.input
            })
            direct = gan.uniform_encoder.sample.eval()[0]/2
            direct = np.reshape(direct, [1, direct.shape[0]])
            self.direction = np.tile(direct, [self.z.shape[0], 1])
            self.mask = gan.session.run(gan.autoencode_mask, feed_dict={
                inputs_t: self.input, 
                gan.encoder.sample: self.z
            })
            self.z = np.reshape(self.z, [self.z.shape[0], -1])

        if self.step > self.steps:
            self.z = np.minimum(self.z+self.direction, 1)
            self.z = np.maximum(self.z, -1)
            self.direction = gan.uniform_encoder.sample.eval()

            self.step = 0

        percent = float(self.step)/self.steps
        z_interp = self.z + self.direction*percent
        z_interp = np.minimum(z_interp, 1)
        z_interp = np.maximum(z_interp, -1)
        self.step+=1

        g=tf.get_default_graph()
        with g.as_default():
            tf.set_random_seed(1)
            return {
                'generator': gan.session.run(gan.uniform_sample, feed_dict={
                    z_t: z_interp, 
                    inputs_t: self.input, 
                    mask_t: self.mask
                })
            }

