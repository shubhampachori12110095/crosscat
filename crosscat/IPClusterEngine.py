#
#   Copyright (c) 2010-2013, MIT Probabilistic Computing Project
#
#   Lead Developers: Dan Lovell and Jay Baxter
#   Authors: Dan Lovell, Baxter Eaves, Jay Baxter, Vikash Mansinghka
#   Research Leads: Vikash Mansinghka, Patrick Shafto
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
import itertools
import functools
#
from IPython.parallel import Client
#
import crosscat.cython_code.State as State
import crosscat.LocalEngine as LE
import crosscat.utils.sample_utils as su


class IPClusterEngine(LE.LocalEngine):
    """A simple interface to the Cython-wrapped C++ engine

    MultiprocessingEngine holds no state other than a seed generator.
    Methods use resources on the local machine.

    """

    def __init__(self, config_filename, seed=0, sshkey=None, packer='json'):
        """Initialize a MultiprocessingEngine

        This is really just setting the initial seed to be used for
        initializing CrossCat states.  Seeds are generated sequentially

        """
        super(IPClusterEngine, self).__init__(seed=seed)
        self.rc = Client(config_filename, sshkey=sshkey, packer=packer)
        self.view = self.rc[:]
        self.mapper = self.view.map
        with self.view.sync_imports():
            import crosscat
            import crosscat.LocalEngine
        return

    def initialize(self, M_c, M_r, T, initialization='from_the_prior',
            n_chains=1):
        """Sample a latent state from prior

        :param M_c: The column metadata
        :type M_c: dict
        :param M_r: The row metadata
        :type M_r: dict
        :param T: The data table in mapped representation (all floats, generated
                  by data_utils.read_data_objects)
        :type T: list of lists
        :returns: X_L, X_D -- the latent state

        """

        # FIXME: why is M_r passed?
        self.view.push(dict(
            M_c=M_c,
            M_r=M_r,
            T=T,
            initialization=initialization,
            do_initialize=do_initialize,
            ))
        seeds = [self.get_next_seed() for seed_idx in range(n_chains)]
        chain_tuples = self.mapper(do_initialize, seeds)
        X_L_list, X_D_list = zip(*chain_tuples)
        if n_chains == 1:
            X_L_list, X_D_list = X_L_list[0], X_D_list[0]
        return X_L_list, X_D_list

    def analyze(self, M_c, T, X_L, X_D, kernel_list=(), n_steps=1, c=(), r=(),
                max_iterations=-1, max_time=-1):
        """Evolve the latent state by running MCMC transition kernels

        :param M_c: The column metadata
        :type M_c: dict
        :param T: The data table in mapped representation (all floats, generated
                  by data_utils.read_data_objects)
        :param X_L: the latent variables associated with the latent state
        :type X_L: dict
        :param X_D: the particular cluster assignments of each row in each view
        :type X_D: list of lists
        :param kernel_list: names of the MCMC transition kernels to run
        :type kernel_list: list of strings
        :param n_steps: the number of times to run each MCMC transition kernel
        :type n_steps: int
        :param c: the (global) column indices to run MCMC transition kernels on
        :type c: list of ints
        :param r: the (global) row indices to run MCMC transition kernels on
        :type r: list of ints
        :param max_iterations: the maximum number of times ot run each MCMC
                               transition kernel. Applicable only if
                               max_time != -1.
        :type max_iterations: int
        :param max_time: the maximum amount of time (seconds) to run MCMC
                         transition kernels for before stopping to return
                         progress
        :type max_time: float
        :returns: X_L, X_D -- the evolved latent state

        """

        self.view.push(dict(
            M_c=M_c,
            T=T,
            kernel_list=kernel_list,
            n_steps=n_steps,
            c=c,
            r=r,
            max_iterations=max_iterations,
            max_time=max_time,
            ))
        X_L_list, X_D_list, was_multistate = su.ensure_multistate(X_L, X_D)
        seeds = [self.get_next_seed() for seed_idx in range(len(X_L_list))]
        arg_tuples = zip(zip(X_L_list, X_D_list), seeds)
        chain_tuples = self.mapper(do_analyze, arg_tuples)
        X_L_prime_list, X_D_prime_list = zip(*chain_tuples)
        if not was_multistate:
            X_L_prime_list, X_D_prime_list = X_L_prime_list[0], X_D_prime_list[0]
        return X_L_prime_list, X_D_prime_list

    def simple_predictive_sample(self, M_c, X_L, X_D, Y, Q, n=1):
        """Sample values from the predictive distribution of the given latent state

        :param M_c: The column metadata
        :type M_c: dict
        :param X_L: the latent variables associated with the latent state
        :type X_L: dict
        :param X_D: the particular cluster assignments of each row in each view
        :type X_D: list of lists
        :param Y: A list of constraints to apply when sampling.  Each constraint
                  is a triplet of (r, d, v): r is the row index, d is the column
                  index and v is the value of the constraint
        :type Y: list of lists
        :param Q: A list of values to sample.  Each value is doublet of (r, d):
                  r is the row index, d is the column index
        :type Q: list of lists
        :param n: the number of samples to draw
        :type n: int
        :returns: list of floats -- samples in the same order specified by Q

        """
        get_next_seed = self.get_next_seed
        samples = LE._do_simple_predictive_sample(M_c, X_L, X_D, Y, Q, n, get_next_seed)
        return samples

    def simple_predictive_probability(self, M_c, X_L, X_D, Y, Q, epsilon=0.001):
        """Calculate the probability of a cell taking a value within epsilon of 
        the specified values given a latent state

        :param M_c: The column metadata
        :type M_c: dict
        :param X_L: the latent variables associated with the latent state
        :type X_L: dict
        :param X_D: the particular cluster assignments of each row in each view
        :type X_D: list of lists
        :param Y: A list of constraints to apply when sampling.  Each constraint
                  is a triplet of (r, d, v): r is the row index, d is the column
                  index and v is the value of the constraint
        :type Y: list of lists
        :param Q: A list of values to sample.  Each value is doublet of (r, d):
                  r is the row index, d is the column index
        :type Q: list of lists
        :param epsilon: the window around the specified value to take the delta
                        in cdf of
        :type epsilon: float
        :returns: list of floats -- probabilities of the values specified by Q

        """
        return su.simple_predictive_probability(M_c, X_L, X_D, Y, Q, epsilon)

    def impute(self, M_c, X_L, X_D, Y, Q, n):
        """Impute values from the predictive distribution of the given latent state

        :param M_c: The column metadata
        :type M_c: dict
        :param X_L: the latent variables associated with the latent state
        :type X_L: dict
        :param X_D: the particular cluster assignments of each row in each view
        :type X_D: list of lists
        :param Y: A list of constraints to apply when sampling.  Each constraint
                  is a triplet of (r, d, v): r is the row index, d is the column
                  index and v is the value of the constraint
        :type Y: list of lists
        :param Q: A list of values to sample.  Each value is doublet of (r, d):
                  r is the row index, d is the column index
        :type Q: list of lists
        :param n: the number of samples to use in the imputation
        :type n: int
        :returns: list of floats -- imputed values in the same order as
                  specified by Q

        """
        e = su.impute(M_c, X_L, X_D, Y, Q, n, self.get_next_seed)
        return e

    def impute_and_confidence(self, M_c, X_L, X_D, Y, Q, n):
        """Impute values and confidence of the value from the predictive
        distribution of the given latent state

        :param M_c: The column metadata
        :type M_c: dict
        :param X_L: the latent variables associated with the latent state
        :type X_L: dict
        :param X_D: the particular cluster assignments of each row in each view
        :type X_D: list of lists
        :param Y: A list of constraints to apply when sampling.  Each constraint
                  is a triplet of (r, d, v): r is the row index, d is the column
                  index and v is the value of the constraint
        :type Y: list of lists
        :param Q: A list of values to sample.  Each value is doublet of (r, d):
                  r is the row index, d is the column index
        :type Q: list of lists
        :param n: the number of samples to use in the imputation
        :type n: int
        :returns: list of lists -- list of (value, confidence) tuples in the
                  same order as specified by Q

        """
        if isinstance(X_L, (list, tuple)):
            assert isinstance(X_D, (list, tuple))
            # TODO: multistate impute doesn't exist yet
            #e,confidence = su.impute_and_confidence_multistate(M_c, X_L, X_D, Y, Q, n, self.get_next_seed)
            e,confidence = su.impute_and_confidence(M_c, X_L, X_D, Y, Q, n, self.get_next_seed)
        else:
            e,confidence = su.impute_and_confidence(M_c, X_L, X_D, Y, Q, n, self.get_next_seed)
        return (e,confidence)

def do_initialize(seed):
    do_initialize = crosscat.LocalEngine._do_initialize
    return do_initialize(M_c, M_r, T, initialization, seed)

def do_analyze(((X_L, X_D), seed)):
    do_analyze = crosscat.LocalEngine._do_analyze
    return do_analyze(M_c, T, X_L, X_D, kernel_list, n_steps, c, r,
            max_iterations, max_time, seed)


if __name__ == '__main__':
    import os
    #
    import crosscat.utils.data_utils as du
    import crosscat.utils.convergence_test_utils as ctu
    import crosscat.utils.timing_test_utils as ttu


    # settings
    gen_seed = 0
    inf_seed = 0
    num_clusters = 4
    num_cols = 32
    num_rows = 400
    num_views = 2
    n_steps = 1
    n_times = 5
    n_chains = 3
    n_test = 100
    #
    config_filename = os.path.expanduser('~/ipcontroller-client.json')
    sshkey_filename = os.path.expanduser('~/.ssh/id_rsa')


    # generate some data
    T, M_r, M_c, data_inverse_permutation_indices = du.gen_factorial_data_objects(
            gen_seed, num_clusters, num_cols, num_rows, num_views,
            max_mean=100, max_std=1, send_data_inverse_permutation_indices=True)
    view_assignment_truth, X_D_truth = ctu.truth_from_permute_indices(
            data_inverse_permutation_indices, num_rows, num_cols, num_views, num_clusters)
    X_L_gen, X_D_gen = ttu.get_generative_clustering(M_c, M_r, T,
            data_inverse_permutation_indices, num_clusters, num_views)
    T_test = ctu.create_test_set(M_c, T, X_L_gen, X_D_gen, n_test, seed_seed=0)
    #
    generative_mean_test_log_likelihood = ctu.calc_mean_test_log_likelihood(M_c, T,
            X_L_gen, X_D_gen, T_test)


    # run some tests
    engine = IPClusterEngine(config_filename=config_filename,
            sshkey=sshkey_filename, seed=inf_seed)
    # single state test
    single_state_ARIs = []
    single_state_mean_test_lls = []
    X_L, X_D = engine.initialize(M_c, M_r, T, n_chains=1)
    single_state_ARIs.append(ctu.get_column_ARI(X_L, view_assignment_truth))
    single_state_mean_test_lls.append(
            ctu.calc_mean_test_log_likelihood(M_c, T, X_L, X_D, T_test)
            )
    for time_i in range(n_times):
        X_L, X_D = engine.analyze(M_c, T, X_L, X_D, n_steps=n_steps)
        single_state_ARIs.append(ctu.get_column_ARI(X_L, view_assignment_truth))
        single_state_mean_test_lls.append(
            ctu.calc_mean_test_log_likelihood(M_c, T, X_L, X_D, T_test)
            )
    # multistate test
    multi_state_ARIs = []
    multi_state_mean_test_lls = []
    X_L_list, X_D_list = engine.initialize(M_c, M_r, T, n_chains=n_chains)
    multi_state_ARIs.append(ctu.get_column_ARIs(X_L_list, view_assignment_truth))
    multi_state_mean_test_lls.append(ctu.calc_mean_test_log_likelihoods(M_c, T,
        X_L_list, X_D_list, T_test))
    for time_i in range(n_times):
        X_L_list, X_D_list = engine.analyze(M_c, T, X_L_list, X_D_list, n_steps=n_steps)
        multi_state_ARIs.append(ctu.get_column_ARIs(X_L_list, view_assignment_truth))
        multi_state_mean_test_lls.append(ctu.calc_mean_test_log_likelihoods(M_c, T,
            X_L_list, X_D_list, T_test))

    # print results
    print 'generative_mean_test_log_likelihood'
    print generative_mean_test_log_likelihood
    #
    print 'single_state_mean_test_lls:'
    print single_state_mean_test_lls
    #
    print 'single_state_ARIs:'
    print single_state_ARIs
    #
    print 'multi_state_mean_test_lls:'
    print multi_state_mean_test_lls
    #
    print 'multi_state_ARIs:'
    print multi_state_ARIs
