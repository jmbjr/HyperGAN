from hypergan.gan_component import GANComponent
import numpy as np
import tensorflow as tf

class BaseLoss(GANComponent):
    def __init__(self, gan, config, discriminator=None, generator=None, x=None, split=2, d_fake=None, d_real=None, reuse=False, name="BaseLoss"):
        self.sample = None
        self.ops = None
        self.reuse=reuse
        self.x = x
        self.d_fake = d_fake
        self.d_real = d_real
        self.discriminator = discriminator
        self.generator = generator
        self.split = split
        GANComponent.__init__(self, gan, config, name=name)

    def reuse(self, d_real=None, d_fake=None):
        self.discriminator.ops.reuse()
        net = self._create(d_real, d_fake)
        self.discriminator.ops.stop_reuse()
        return net


    def create(self):
        gan = self.gan
        config = self.config
        ops = self.gan.ops
        split = self.split
        d_real = self.d_real
        d_fake = self.d_fake

        d_loss = None
        g_loss = None
        if d_real is None or d_fake is None:
            # Not passed in, lets populate d_real/d_fake

            net = self.discriminator.sample

            ds = self.split_batch(net, split)
            d_real = ds[0]
            d_fake = tf.add_n(ds[1:])/(len(ds)-1)
            d_loss, g_loss = self._create(d_real, d_fake)
        else:
            d_loss, g_loss = self._create(d_real, d_fake)

        d_regularizers = []
        g_regularizers = []
        d_loss_features = d_loss
        g_loss_features = g_loss
        self.d_loss_features = d_loss_features
        self.g_loss_features = g_loss_features

        if config.minibatch:
            d_net = tf.concat([d_real, d_fake], axis=0)
            d_regularizers.append(self.minibatch(d_net)) # TODO on d_loss_features?

        if config.gradient_locally_stable:
            d_vars = gan.discriminator.variables()
            g_vars = (gan.encoder.variables() + gan.generator.variables())
            gls = tf.gradients(d_loss, d_vars+g_vars)
            gls = tf.square(tf.global_norm(gls))
            g_regularizers.append(config.gradient_locally_stable * gls)
            self.add_metric('gradient_locally_stable', ops.squash(gls, tf.reduce_mean))
            print("Gradient locally stable applied")

        if config.gradient_penalty:
            gp = self.gradient_penalty()
            d_regularizers.append(gp)
            self.add_metric('gradient_penalty', ops.squash(gp, tf.reduce_mean))
            print("Gradient penalty applied")

        if config.k_lipschitz_penalty:
            lipschitz_penalty = tf.maximum(tf.square(d_real) - 1, 0) + tf.maximum(tf.square(d_fake) - 1, 0)
            self.add_metric('k_lipschitz', ops.squash(lipschitz_penalty))

            d_regularizers.append(lipschitz_penalty)

        if config.jg_penalty:
            d_vars = gan.d_vars()
            g_vars = gan.g_vars()
            reg_g_grads = tf.gradients(g_loss, g_vars)
            reg_d_grads = tf.gradients(g_loss, d_vars)
            reg_d_grads = tf.square(tf.global_norm(reg_d_grads))
            reg_g_grads = tf.square(tf.global_norm(reg_g_grads))
            d_loss += 0.5*(config.jg_lambda or 0.01)*reg_d_grads
            g_loss += 0.5*(config.jg_lambda or 0.01)*reg_g_grads

            self.add_metric('reg_d', reg_d_grads)
            self.add_metric('reg_g', reg_g_grads)

            self.add_metric('reg_d', g_d_grads)
            self.add_metric('reg_g', g_g_grads)

        if config.l2nn_penalty:
            l2nn_penalties = []
            weights = self.gan.weights()
            if config.l2nn_penalty_only_d:
                weights = self.discriminator.weights()
            if len(weights) > 0:
                for w in weights:
                    w = tf.reshape(w, [-1, self.ops.shape(w)[-1]])
                    wt = tf.transpose(w)
                    wtw = tf.matmul(wt,w)
                    wwt = tf.matmul(w,wt)
                    def _l(m):
                        m = tf.abs(m)
                        m = tf.reduce_sum(m, axis=0,keep_dims=True)
                        m = tf.maximum(m-1, 0)
                        m = tf.reduce_max(m, axis=1,keep_dims=True)
                        return m
                    l2nn_penalties.append(tf.minimum(_l(wtw), _l(wwt)))
                print('l2nn_penalty', self.config.l2nn_penalty, l2nn_penalties)
                l2nn_penalty = self.config.l2nn_penalty * tf.add_n(l2nn_penalties)
                self.add_metric('l2nn_penalty', self.gan.ops.squash(l2nn_penalty))
                l2nn_penalty = tf.tile(l2nn_penalty, [self.gan.batch_size(), 1])
                d_regularizers.append(l2nn_penalty)

        if config.ortho_penalty:
            penalties = []
            for w in self.gan.weights():
                print("PENALTY", w)
                w = tf.reshape(w, [-1, self.ops.shape(w)[-1]])
                wt = tf.transpose(w)
                wtw = tf.matmul(wt,w)
                wwt = tf.matmul(w,wt)
                mwtw = tf.matmul(w, wtw)
                mwwt = tf.matmul(wt, wwt)
                def _l(w,m):
                    l = tf.reduce_mean(tf.abs(w - m))
                    l = self.ops.squash(l)
                    return l
                penalties.append(tf.minimum(_l(w, mwtw), _l(wt, mwwt)))
            penalty = self.config.ortho_penalty * tf.add_n(penalties)
            self.add_metric('ortho_penalty', self.gan.ops.squash(penalty))
            print("PENALTY", penalty)
            penalty = tf.reshape(penalty, [1,1])
            penalty = tf.tile(penalty, [self.gan.batch_size(), 1])
            d_regularizers.append(penalty)



        if config.rothk_penalty:
            rothk = self.rothk_penalty(d_real, d_fake)
            self.add_metric('rothk_penalty', self.gan.ops.squash(rothk))
            #d_regularizers.append(rothk)
            d_loss += rothk
            print("rothk penalty applied")

        if config.k_lipschitz_penalty_ragan:
            lipschitz_penalty = tf.maximum(tf.square(d_real-d_fake) - 1, 0) + tf.maximum(tf.square(d_fake-d_real) - 1, 0)
            self.metrics['k_lipschitz_ragan']=lipschitz_penalty

            d_regularizers.append(lipschitz_penalty)
 
        if config.random_penalty:
            gp = self.random_penalty(d_fake, d_real)
            d_regularizers.append(gp)
            self.add_metric('random_penalty', ops.squash(gp, tf.reduce_mean))


        if self.gan.config.infogan and not hasattr(self.gan, 'infogan_q'):
            sample = self.gan.generator.sample
            d = self.gan.create_component(self.gan.config.discriminator, name="discriminator", input=sample, reuse=True, features=[tf.zeros([1,16,16,256])])
            last_layer = d.controls['infogan']
            q = self.gan.create_component(self.gan.config.infogan, input=(self.gan.discriminator.controls['infogan']), name='infogan')
            self.gan.infogan_q=q
            std_cont = tf.sqrt(tf.exp(q.sample))
            true = self.gan.uniform_distribution.z
            mean = tf.reshape(q.sample, self.ops.shape(true))
            std_cont = tf.reshape(std_cont, self.ops.shape(true))
            eps = (true - mean) / (std_cont + 1e-8)
            continuous = -tf.reduce_mean( -0.5 * np.log(2*np.pi)- tf.log(std_cont+1e-8)*tf.square(eps), reduction_indices=1)
            if self.gan.config.infogan.flipped:
                continuous = -continuous

            self.metrics['cinfo']=ops.squash(continuous)
            d_regularizers.append(continuous)

        d_regularizers += self.d_regularizers()
        g_regularizers += self.g_regularizers()

        print("prereg", d_loss)
        if len(d_regularizers) > 0:
            d_loss += tf.add_n(d_regularizers)
        if len(g_regularizers) > 0:
            g_loss += tf.add_n(g_regularizers)

        d_loss = ops.squash(d_loss, config.reduce or tf.reduce_mean) #linear doesn't work with this

        # TODO: Why are we squashing before gradient penalty?
        self.add_metric('d_loss', d_loss)
        if g_loss is not None:
            g_loss = ops.squash(g_loss, config.reduce or tf.reduce_mean)
            self.add_metric('g_loss', g_loss)

        self.sample = [d_loss, g_loss]
        self.d_loss = d_loss
        self.g_loss = g_loss
        self.d_fake = d_fake
        self.d_real = d_real

        return self.sample

    def d_regularizers(self):
        return []

    def g_regularizers(self):
        return []

    # This is openai's implementation of minibatch regularization
    def minibatch(self, net):
        discriminator = self.discriminator
        ops = discriminator.ops
        config = self.config
        batch_size = ops.shape(net)[0]
        single_batch_size = batch_size//2
        n_kernels = config.minibatch_kernels or 300
        dim_per_kernel = config.dim_per_kernel or 50
        print("[discriminator] minibatch from", net, "to", n_kernels*dim_per_kernel)
        x = ops.linear(net, n_kernels * dim_per_kernel)
        activation = tf.reshape(x, (batch_size, n_kernels, dim_per_kernel))

        big = np.zeros((batch_size, batch_size))
        big += np.eye(batch_size)
        big = tf.expand_dims(big, 1)
        big = tf.cast(big,dtype=ops.dtype)

        abs_dif = tf.reduce_sum(tf.abs(tf.expand_dims(activation,3) - tf.expand_dims(tf.transpose(activation, [1, 2, 0]), 0)), 2)
        mask = 1. - big
        masked = tf.exp(-abs_dif) * mask
        def half(tens, second):
            m, n, _ = tens.get_shape()
            m = int(m)
            n = int(n)
            return tf.slice(tens, [0, 0, second * single_batch_size], [m, n, single_batch_size])

        f1 = tf.reduce_sum(half(masked, 0), 2) / tf.reduce_sum(half(mask, 0))
        f2 = tf.reduce_sum(half(masked, 1), 2) / tf.reduce_sum(half(mask, 1))

        return ops.squash(ops.concat([f1, f2]))

    def gradient_locally_stable(self, d_net):
        config = self.config
        generator = self.generator
        g_sample = self.gan.uniform_sample
        gradients = tf.gradients(d_net, [g_sample])[0]
        return float(config.gradient_locally_stable) * \
                tf.nn.l2_normalize(gradients, dim=1)

    def rothk_penalty(self, d_real, d_fake):
        config = self.config
        g_sample = self.gan.uniform_sample
        x = self.gan.inputs.x
        gradx = tf.gradients(d_real, [x])[0]
        gradg = tf.gradients(d_fake, [g_sample])[0]
        gradx = tf.reshape(gradx, [self.ops.shape(gradx)[0], -1])
        gradg = tf.reshape(gradg, [self.ops.shape(gradg)[0], -1])
        gradx_norm = tf.norm(gradx, axis=1, keep_dims=True)
        gradg_norm = tf.norm(gradg, axis=1, keep_dims=True)
        if int(gradx_norm.get_shape()[0]) != int(d_real.get_shape()[0]):
            print("Condensing along batch for rothk")
            gradx_norm = tf.reduce_mean(gradx_norm, axis=0)
            gradg_norm = tf.reduce_mean(gradg_norm, axis=0)
        gradx = tf.square(gradx_norm) * tf.square(1-tf.nn.sigmoid(d_real))
        gradg = tf.square(gradg_norm) * tf.square(tf.nn.sigmoid(d_fake))
        loss = gradx + gradg
        loss *= config.rothk_lambda or 1
        if config.rothk_decay:
            decay_function = config.decay_function or tf.train.exponential_decay
            decay_steps = config.decay_steps or 50000
            decay_rate = config.decay_rate or 0.9
            decay_staircase = config.decay_staircase or False
            global_step = tf.train.get_global_step()
            loss = decay_function(loss, global_step, decay_steps, decay_rate, decay_staircase)

        return loss

    def gradient_penalty(self):
        config = self.config
        gan = self.gan
        ops = self.gan.ops
        gradient_penalty = config.gradient_penalty
        x = self.x 
        if x is None:
            x=gan.inputs.x
        g = self.generator
        discriminator = self.discriminator or gan.discriminator
        shape = [1 for t in ops.shape(x)]
        shape[0] = gan.batch_size()
        uniform_noise = tf.random_uniform(shape=shape,minval=0.,maxval=1.)
        print("[gradient penalty] applying x:", x, "g:", g, "noise:", uniform_noise)
        if config.gradient_penalty_type == 'dragan':
            axes = [0, 1, 2, 3]
            if len(ops.shape(x)) == 2:
                axes = [0, 1]
            mean, variance = tf.nn.moments(x, axes=axes)
            interpolates = x + uniform_noise * 0.5 * variance * tf.random_uniform(shape=ops.shape(x), minval=0.,maxval=1.)
        else:
            interpolates = x + uniform_noise * (g - x)
        reused_d = discriminator.reuse(interpolates)
        gradients = tf.gradients(reused_d, [interpolates])[0]
        penalty = tf.sqrt(tf.reduce_sum(tf.square(gradients), axis=1))
        penalty = tf.square(penalty - 1.)
        return float(gradient_penalty) * penalty

    def random_penalty(self, d_fake, d_real):
        config = self.config
        gan = self.gan
        ops = self.gan.ops
        gradient_penalty = config.gradient_penalty
        x = self.x 
        if x is None:
            x=gan.inputs.x
        shape = [1 for t in ops.shape(x)]
        shape[0] = gan.batch_size()
        uniform_noise = tf.random_uniform(shape=shape,minval=0.,maxval=1.)
        mask = tf.cast(tf.greater(0.5, uniform_noise), tf.float32)
        #interpolates = x * mask + g * (1-mask)
        d = d_fake *(1-mask) + d_real * mask#discriminator.reuse(interpolates)
        offset = config.random_penalty_offset or -0.8
        penalty = tf.square(d - offset)
        return penalty


    def sigmoid_kl_with_logits(self, logits, targets):
       # broadcasts the same target value across the whole batch
       # this is implemented so awkwardly because tensorflow lacks an x log x op
       assert isinstance(targets, float)
       if targets in [0., 1.]:
         entropy = 0.
       else:
         entropy = - targets * np.log(targets) - (1. - targets) * np.log(1. - targets)
         return tf.nn.sigmoid_cross_entropy_with_logits(logits=logits, labels=tf.ones_like(logits) * targets) - entropy
