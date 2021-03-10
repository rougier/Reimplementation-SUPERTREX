#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
    Created on Tue Mar 24 19:12:15 2020
    @author: rsankar
    
    This script belongs to a modified reimplementation of the models described in -
    Pyle, R. and Rosenbaum, R., 2019.
    A reservoir computing model of reward-modulated motor learning and automaticity.
    Neural computation, 31(7), pp.1430-1461.
    
    This script builds the model object for the RMHL algorithm, trains and tests it on the described tasks and plots the results.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from tqdm import tqdm
import os

class ModelRMHL():

    def __init__(s, parameters, task, exp):                                                 # self -> s
        """
            Initialise the model object.
            
            exp: dict
                Task description where:
                    rseed           : seed for random generator; if rseed=0, a random seed is used
                    dataset_file    : file to store task datapoints
                    algorithm       : learning algorithm to simulate
                    results_folder  : path to store results
                    git-hash        : version of model being simulated
                    timespan        : duration of 1 experiment trial
                    task_type       : type of task, the model is to be run on
                    n_segs          : no. of arm segments (irrelevant for task #1)
                    arm_len         : length of each arm segment (irrelevant for task #1)
                    arm_cost        : cost of moving each arm segment (irrelevant for task #1 and #2)
                    display_plot    : show the plot, too, or just save it
                    plot_format     : file format for saving plot (ps, eps, pdf, pgf, png, raw, rgba, svg, svgz, jpg, jpeg, tif, tiff)
            
            parameters: dict
                Parameter values where:
                    N               : no. of neurons in reservoir
                    lmbda           : controls spectral radius
                    sparsity        : connectivity sparsity in reservoir
                    dT              : time gradient in ms
                    n_train_trials  : no. of training trials
                    n_test_trials   : no. of testing trials
                    alpha           : attenuate noise
                    gamma           : Initialising factor for P matrix
                    k               : SUPERTREX learning rate
                    tau             : time constant of reservoir
                    tau_w           : time constant of weight updation
                    tau_e           : low pass filter for MSE
                    tau_z           : low pass filter for z
            
            task: Task
                Task object created for this experiment
        """

        # Model parameters
        s.task_type         = exp['task_type']                                              # Type of task
        s.T                 = exp['timespan']                                               # Timescale of experiment in ms
        s.n_out             = exp['n_segs']                                                 # No. of arm segments
        if s.task_type == 1:    s.n_out = 2                                                 # or coordinates

        s.N                 = parameters['N']                                               # No. of neurons in reservoir
        s.lmbda             = parameters['lmbda']                                           # Related to spectral radius
        s.sparsity          = parameters['sparsity']                                        # Connectivity sparsity in reservoir
        s.dT                = parameters['dT']                                              # Time gradient
        s.n_train_trials    = parameters['n_train_trials']                                  # No. of trials for training > 5
        s.n_test_trials     = parameters['n_test_trials']                                   # No. of trials for testing
        s.n_total_trials     = parameters['n_train_trials'] + parameters['n_test_trials']   # No. of total trials
        s.alpha             = parameters['alpha']                                           # Noise attenuating factor
        s.tau               = parameters['tau']                                             # Time constant of reservoir leak
        s.tau_w             = parameters['tau_w']                                           # Time constant of weight updation
        s.tau_e             = parameters['tau_e']                                           # Low pass filter for displaying MSE
        s.tau_z             = parameters['tau_z']                                           # Low pass filter for displaying z

        s.leak              = s.dT/s.tau                                                    # Reservoir leak
        s.n_timesteps       = int(s.T/s.dT)                                                 # No. of timesteps in a trial
        s.sigma             = s.lmbda / np.sqrt((s.sparsity*s.N))                           # Standard deviation of initial reservoir connectivity

        s.learningrate      = .0005                                                         # RMHL learning rate as per authors

        if exp['rseed'] == 0:   s.rseed = np.random.randint(0,1e7)
        else :                  s.rseed = exp['rseed']                                      # Seed for randomisation
        print('Seed:', s.rseed)

        s.results_path = exp['results_folder'] + '/' + str(s.rseed) + '_nsegs' + str(exp['n_segs']) + '/'

        if not os.path.exists(s.results_path):   os.makedirs(s.results_path)

        # Build reservoir architecture
        s.build(task)

    def build(s, task):
        """ Building the model architecture. """

        _data = task.data

        # Network initialisations
        np.random.seed(s.rseed)

        # Build reservoir
        s.J = np.zeros((s.N, s.N))
        Jne = task.round_up(s.N * s.N * s.sparsity)
        idx_x, idx_y = task.rand_int(s.N, Jne), task.rand_int(s.N, Jne)
        s.J[idx_x, idx_y] = 1
        Jnz, Jcnz = np.nonzero(s.J), np.count_nonzero(s.J)
        Jr = stats.norm.ppf(np.random.uniform(size=Jcnz))
        s.J[Jnz] = Jr[:Jcnz]
        s.J = s.J * s.sigma                                                                 # Reservoir connectivity strengths
        unnec = np.random.uniform(size=2090)                                                # Hard-coded for N=1000, to make it equivalent to matlab


        # Build network
        s.Q = (np.random.rand(s.n_out, s.N) * 2 - 1).T                                      # Reservoir feedback connectivity
        s.x = np.random.rand(s.N, 1) - .5 * np.ones((s.N, 1))                               # Reservoir voltages
        s.r = np.tanh(s.x)                                                                  # Resevoir  output activity
        s.z = np.zeros((s.n_out, 1))                                                        # Reservoir output
        s.W_RMHL = np.zeros((s.n_out, s.N))                                                 # RMHL readout weights


        # Training initialisations
        s.outputs = np.column_stack((_data['x'], _data['y']))
        s.outputs = s.outputs.reshape((s.outputs.shape[0], 2, 1))
        s.e = 0
        s.e_bar = 0
        s.z_bar = np.zeros((s.n_out, 1))
        s.z_RMHL_bar = np.zeros((s.n_out, 1))


        # Plotting purposes
        s.error = np.zeros((s.n_total_trials, s.n_timesteps))
        s.cost_rec = np.zeros((s.n_total_trials, s.n_timesteps))
        s.z_rec = np.zeros((s.n_out, s.n_total_trials, s.n_timesteps, 1))
        s.z_RMHL_rec = np.zeros((s.n_out, s.n_total_trials, s.n_timesteps, 1))
        s.hz_rec = np.zeros((2, s.n_total_trials, s.n_timesteps, 1))
        s.W_RMHL_rec = np.zeros((s.n_total_trials, s.n_timesteps))


    def train(s, task):
        """ Training the model using the RMHL algorithm. """

        # Online training
        print('Training')
        for trial_num in tqdm(range(s.n_train_trials)):
            for time_step in range(s.n_timesteps):

                # Update reservoir state
                s.x     = s.x + (s.leak)*(-s.x +np.dot(s.J,s.r) + np.dot(s.Q,s.z))
                xi_r    = np.random.uniform(0, 1, (s.N, 1)) * s.alpha * 2 - s.alpha
                s.r     = np.tanh(s.x) + xi_r

                # Compute output at current timestep
                t_psi   = task.psi(s.e_bar, trial_num, time_step)
                xi_z    = np.random.uniform(0, 1, (s.n_out, 1)) * t_psi * 2 - t_psi
                z_RMHL  = np.dot(s.W_RMHL, s.r) + xi_z
                s.z     = z_RMHL
                hz      = task.h(s.z)

                # Computing high pass filtered values for output
                s.z_RMHL_bar = (1 - s.dT/s.tau_z) * s.z_RMHL_bar + s.dT/s.tau_z * z_RMHL
                if trial_num==0 and time_step==0:   s.z_RMHL_bar = z_RMHL
                z_RMHL_hat   = z_RMHL - s.z_RMHL_bar
                s.z_bar = (1 - s.dT/s.tau_z) * s.z_bar + s.dT/s.tau_z * s.z
                if trial_num==0 and time_step==0:   s.z_bar = s.z                           # Change: Adding s.z_bar and z_hat
                z_hat   = s.z - s.z_bar

                # Computing error and its high pass filtered values
                cost    = task.cost(z_hat)
                ze      = hz-s.outputs[time_step]
                s.e     = np.sum(ze ** 2) + cost
                s.e_bar = (1 - s.dT) * s.e_bar + s.dT * s.e
                if trial_num == 0 and time_step == 0:   s.e_bar = s.e
                e_hat   = s.e-s.e_bar

                # Update readout weights
                s.W_RMHL += s.learningrate * task.phi(e_hat) * np.dot(z_RMHL_hat,s.r.T) * task.compensation('RMHL')

                # Recording purposes
                s.error[trial_num, time_step]           = s.e
                s.cost_rec[trial_num, time_step]        = cost
                s.hz_rec[:, trial_num, time_step]       = hz[:]
                s.z_rec[:, trial_num, time_step]        = s.z[:]
                s.z_RMHL_rec[:, trial_num, time_step]   = z_RMHL[:]
                s.W_RMHL_rec[trial_num, time_step]      = task.norm(s.W_RMHL)


        print('Training done')

    def test(s, task):
        """ Testing the stability of the RMHL algorithm. """

        # Testing
        print('Testing')
        z_RMHL = np.zeros((s.n_out,1))
        for trial_num in tqdm(range(s.n_train_trials, s.n_total_trials)):
            for time_step in range(s.n_timesteps):

                # Update reservoir state
                zt  = s.z_rec[:,trial_num-5,time_step]
                s.x = s.x + (s.leak)*(-s.x +np.dot(s.J,s.r) + np.dot(s.Q,zt))
                s.r = np.tanh(s.x)

                # Compute output and error at current timestep
                z_RMHL = np.dot(s.W_RMHL,s.r)
                s.z     = z_RMHL
                hz      = task.h(s.z)

                # Computing high pass filtered values for output
                s.z_RMHL_bar = (1 - s.dT) * s.z_RMHL_bar + s.dT * z_RMHL
                s.z_bar = (1 - s.dT/s.tau_z) * s.z_bar + s.dT/s.tau_z * s.z
                z_hat   = s.z - s.z_bar

                # Computing error and cost
                cost    = task.cost(z_hat)
                ze      = hz-s.outputs[time_step]
                s.e     = np.sum(ze ** 2) + cost

                # Recording purposes
                s.error[trial_num, time_step]           = s.e
                s.cost_rec[trial_num, time_step]        = cost
                s.hz_rec[:, trial_num, time_step]       = hz[:]
                s.z_rec[:, trial_num, time_step]        = s.z[:]
                s.z_RMHL_rec[:, trial_num, time_step]   = z_RMHL[:]


    def save_results(s, exp):
        """ Saves the results of the simulation. """

        print('Saving results')
        np.savez(s.results_path + 'Data',
                    error               = s.error,
                    cost                = s.cost_rec,
                    z                   = s.z_rec,
                    z_RMHL              = s.z_RMHL_rec,
                    hz                  = s.hz_rec,
                    W_RMHL              = s.W_RMHL_rec,
                    )

    def plot(s, exp, task):
        """
            Loads the saved results and plots an overall figure.
        """

        # Load dataset
        data = np.load(exp['dataset_file'])

        target_coord = np.array((np.tile(data['x'], s.n_train_trials+s.n_test_trials),
                                   np.tile(data['y'], s.n_train_trials+s.n_test_trials)))

        # Load result arrays
        _ = np.load(s.results_path + 'Data.npz')
        _hz = _['hz']
        _z = _['z']
        _z_RMHL = _['z_RMHL']
        _W_RMHL = _['W_RMHL']
        _error = _['error']
        _cost = _['cost']

        # Low pass filter results
        _cost = _cost.flatten()
        _error = _error.flatten()
        _z = np.reshape(_z, (s.n_out, _z[0].size))
        _W_RMHL = _W_RMHL.flatten()
        _z_RMHL = np.reshape(_z_RMHL, (s.n_out, _z_RMHL[0].size))
        _hz = np.reshape(_hz, (2, _hz[0].size))

        cost_bar = np.copy(_cost)
        mse_bar = np.copy(_error)
        z_bar = np.copy(_z)
        z_RMHL_bar = np.copy(_z_RMHL)
        hz_bar = np.copy(_hz)
        ce = s.dT / s.tau_e
        cz = s.dT / s.tau_z

        for i in np.arange(1, s.n_timesteps * s.n_total_trials):
            z_bar[:, i]      = z_bar[:, i - 1]      + cz * (-z_bar[:, i - 1]      + _z[:, i])
            z_RMHL_bar[:, i] = z_RMHL_bar[:, i - 1] + cz * (-z_RMHL_bar[:, i - 1] + _z_RMHL[:, i])
            hz_bar[:, i]     = hz_bar[:, i - 1]     + cz * (-hz_bar[:, i - 1]     + _hz[:, i])
            mse_bar[i]       = mse_bar[i - 1]       + ce * (-mse_bar[i - 1]       + _error[i])
            cost_bar[i]      = cost_bar[i - 1]      + ce * (-cost_bar[i - 1]      + _cost[i])
        mse = np.sqrt(mse_bar)

        # Adjusting for uncalculated W_FORCE norms and NANs/INF while calculating norm
        for i in np.arange(1,s.n_timesteps * s.n_total_trials):
            if _W_RMHL[i] == 0:     _W_RMHL[i] = _W_RMHL[i-1]

        # ------------------------------------------------------------------- #
        # Plot
        print('Plotting')

        n_subplots = 5                                                   # For timeseries output, norm and error, x and y coordinates
        if s.task_type != 1 and s.n_out <= 4: n_subplots += s.n_out      # For network output
        if task.type == 3:    n_subplots += 1                            # For cost


        fig, ax = plt.subplots(n_subplots)
        fig.suptitle('Results of RMHL simulation on Task #' + str(task.type) + ' with ' + str(exp['n_segs']) + ' segments at seed: ' + str(s.rseed))

        ax[0].set_title('Output during testing phase')
        ax[0].set(aspect='equal')
        l1 = ax[0].plot(data['x'], data['y'], marker=',', color='red', markersize=1)
        sp, ep = int(s.n_timesteps * (s.n_train_trials-1)), int(s.n_timesteps * s.n_train_trials)
        ax[0].plot(hz_bar[0, sp:ep], hz_bar[1, sp:ep], marker=',', markersize=2, color='grey', alpha=0.8)
        sp, ep = int(s.n_timesteps * s.n_train_trials), int(s.n_timesteps * s.n_total_trials)
        ax[0].plot(hz_bar[0, sp:ep], hz_bar[1, sp:ep], marker=',', markersize=2, color='green')

        ax[1].set_title('Norm of weight matrix')
        ax[1].plot(_W_RMHL.flatten(), color='green')
        ax[1].set_ylabel('||W||')
        ax[1].axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=4, alpha=0.5)

        ax[2].set_title('Distance from target')
        ax[2].plot(mse, color='green')
        ax[2].set_ylabel('E')
        l2 = ax[2].axvline(x=(s.n_train_trials * s.n_timesteps), color='grey', linewidth=4, alpha=0.5)
        ax[2].set_yscale('log')

        ax[3].set_title('Coordinates')
        ax[3].set_ylabel('x')
        ax[3].plot(hz_bar[0], color='purple')
        ax[3].plot(target_coord[0], color='red')
        ax[3].axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=4, alpha=0.5)

        ax[4].set_ylabel('y')
        ax[4].plot(hz_bar[1], color='purple')
        ax[4].plot(target_coord[1], color='red')
        ax[4].axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=4, alpha=0.5)

        if s.task_type != 1 and s.n_out <= 4:
            ax[5].set_title('Joint angles')
            for i in range(s.n_out):
                ax[5+i].plot(z_bar[i], color='purple')
                ax[5+i].plot(z_RMHL_bar[i], alpha=0.5, color='green', linestyle='dashed')
                ax[5+i].set_ylabel('Theta' + str(i))
                ax[5+i].axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=4, alpha=0.5)

        if task.type == 3:
            ax[n_subplots-1].set_title('Cost of moving the arm')
            ax[n_subplots-1].plot(cost_bar, color='green')
            ax[n_subplots-1].set_ylabel('Cost')
            ax[n_subplots-1].axvline(x=(s.n_train_trials * s.n_timesteps), color='grey', linewidth=4, alpha=0.5)
            ax[n_subplots-1].set_yscale('log')

        lines = [ax[0].plot(1, 1, color='purple')[0], ax[0].plot(1, 1, color='green')[0],
                 ax[0].plot(1, 1, color='orange')[0], l1, l2]
        labels = ['SUPERTREX', 'Exploratory', 'Mastery', 'Target', 'Test phase']
        fig.legend(lines, labels)

        for k in range(n_subplots):
            ax[k].spines['top'].set_visible(False)
            ax[k].spines['right'].set_visible(False)
            ax[k].spines['bottom'].set_visible(False)
            ax[k].get_xaxis().set_ticks([])

        plt.savefig(s.results_path + 'Overall.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))

        if exp['display_plot'] == 'Yes':
            fig.canvas.manager.window.showMaximized()
            plt.show()

        print('Done.')
        # ------------------------------------------------------------------- #

    def plot_distinct(s, exp, task):
        """
            Loads the saved results and plots individual figures.
        """

        # Load dataset
        data = np.load(exp['dataset_file'])
        target_coord = np.array((np.tile(data['x'], s.n_train_trials+s.n_test_trials),
                                   np.tile(data['y'], s.n_train_trials+s.n_test_trials)))

        # Load result arrays
        # _ = np.load(s.results_file + '.npz')
        _ = np.load(s.results_path + 'Data' + '.npz')
        _hz = _['hz']
        _z = _['z']
        _z_RMHL = _['z_RMHL']
        _W_RMHL = _['W_RMHL']
        _error = _['error']
        _cost = _['cost']

        # Low pass filter results
        _cost = _cost.flatten()
        _error = _error.flatten()
        _z = np.reshape(_z, (s.n_out, _z[0].size))
        _W_RMHL = _W_RMHL.flatten()
        _z_RMHL = np.reshape(_z_RMHL, (s.n_out, _z_RMHL[0].size))
        _hz = np.reshape(_hz, (2, _hz[0].size))

        cost_bar = np.copy(_cost)
        mse_bar = np.copy(_error)
        z_bar = np.copy(_z)
        z_RMHL_bar = np.copy(_z_RMHL)
        hz_bar = np.copy(_hz)
        ce = s.dT / s.tau_e
        cz = s.dT / s.tau_z

        for i in np.arange(1, s.n_timesteps * s.n_total_trials):
            z_bar[:, i]      = z_bar[:, i - 1]      + cz * (-z_bar[:, i - 1]      + _z[:, i])
            z_RMHL_bar[:, i] = z_RMHL_bar[:, i - 1] + cz * (-z_RMHL_bar[:, i - 1] + _z_RMHL[:, i])
            hz_bar[:, i]     = hz_bar[:, i - 1]     + cz * (-hz_bar[:, i - 1]     + _hz[:, i])
            mse_bar[i]       = mse_bar[i - 1]       + ce * (-mse_bar[i - 1]       + _error[i])
            cost_bar[i]      = cost_bar[i - 1]      + ce * (-cost_bar[i - 1]      + _cost[i])
        mse = np.sqrt(mse_bar)

        # Adjusting for uncalculated W_FORCE norms and NANs/INF while calculating norm
        for i in np.arange(1,s.n_timesteps * s.n_total_trials):
            if _W_RMHL[i] == 0:     _W_RMHL[i] = _W_RMHL[i-1]

        # ------------------------------------------------------------------- #
        # Plot
        print('Plotting')

        n_plots = 5                                                   # For timeseries output, norm and error, x and y outputs
        if s.task_type != 1 and s.n_out <= 4: n_plots += s.n_out      # For network output
        if task.type == 3:    n_plots += 1                            # For cost


        fig, ax = plt.subplots(1)

        # ax[0].set_title('Output during testing phase')
        ax.set(aspect='equal')
        # sp, ep = int(s.n_timesteps * (s.n_train_trials-1)), int(s.n_timesteps * s.n_train_trials)
        # ax[0].plot(hz_bar[0, sp:ep], hz_bar[1, sp:ep], marker=',', markersize=2, color='grey', alpha=0.8)
        sp, ep = int(s.n_timesteps * s.n_train_trials), int(s.n_timesteps * s.n_total_trials)
        ax.plot(hz_bar[0, sp:ep:10], hz_bar[1, sp:ep:10], marker=',', markersize=0.5, color='blue')
        l1 = ax.plot(data['x'], data['y'], marker=',', color='red', markersize=0.5)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])

        plt.savefig(s.results_path + 'TimeSeries.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))


        fig, ax = plt.subplots(1)

        # ax[1].set_title('Norm of weight matrix')
        ax.plot(_W_RMHL.flatten(), color='grey', linewidth=0.5)
        ax.set_ylabel('||W||')
        ax.axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=2, alpha=0.5)
        ax.set_ylim(0, 0.5)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.get_xaxis().set_ticks([])

        plt.savefig(s.results_path + 'W_norm.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))


        fig, ax = plt.subplots(1)

        # ax[2].set_title('Distance from target')
        ax.plot(mse, color='blue', linewidth=0.5)
        ax.set_ylabel('Distance from Target')
        l2 = ax.axvline(x=(s.n_train_trials * s.n_timesteps), color='grey', linewidth=2, alpha=0.5)
        ax.set_yscale('log')
        ax.get_yaxis().set_ticks([1e-6, 1e-4, 1e-2, 1])

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.get_xaxis().set_ticks([])

        plt.savefig(s.results_path + 'MSE.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))


        fig, ax = plt.subplots(1)

        # ax[3].set_title('Coordinates')
        ax.set_ylabel('x(t)')
        ax.plot(hz_bar[0], color='blue', linewidth=0.5)
        ax.plot(target_coord[0], color='red', linewidth=0.5)
        ax.axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=2, alpha=0.5)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])

        plt.savefig(s.results_path + 'CoordinateX.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))


        fig, ax = plt.subplots(1)

        ax.set_ylabel('y(t)')
        ax.plot(hz_bar[1], color='blue', linewidth=0.5)
        ax.plot(target_coord[1], color='red', linewidth=0.5)
        ax.axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=2, alpha=0.5)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])

        plt.savefig(s.results_path + 'CoordinateY.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))

        if task.type == 3:
            fig, ax = plt.subplots(1)

            ax.plot(cost_bar, color='green', linewidth=0.5)
            ax.set_ylabel('Cost')
            l2 = ax.axvline(x=(s.n_train_trials * s.n_timesteps), color='grey', linewidth=2, alpha=0.5)
            ax.set_yscale('log')
            ax.get_yaxis().set_ticks([1e-6, 1e-4, 1e-2, 1])

            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.get_xaxis().set_ticks([])

            plt.savefig(s.results_path + 'Cost.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))

        if s.task_type != 1 and s.n_out <= 4:
            for i in range(s.n_out):
                fig, ax = plt.subplots(1)

                ax.set_ylabel(r'$\theta_' + str(i+1) + '$')
                ax.plot(z_bar[i], color='blue', linewidth=0.5)
                ax.axvline(x=s.n_train_trials * s.n_timesteps, color='grey', linewidth=2, alpha=0.5)

                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_visible(False)
                ax.spines['left'].set_visible(False)
                ax.get_xaxis().set_ticks([])
                ax.get_yaxis().set_ticks([])

                plt.savefig(s.results_path + 'Theta' + str(i) + '.' + exp['plot_format'], rasterized=(exp['plot_format']=='pdf'))

        print('Done.')
        # ------------------------------------------------------------------- #

