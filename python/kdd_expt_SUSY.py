from __future__ import division
import numpy as np, numpy.random as nr, numpy.linalg as nlg
import scipy as sp, scipy.linalg as slg, scipy.io as sio, scipy.sparse as ss
# import matplotlib.pyplot as plt

from multiprocessing import Pool

import time
import os, os.path as osp
import csv
import cPickle as pick
# import sqlparse as sql

import activeSearchInterface as ASI
import competitorsInterface as CI

import data_utils as du
import graph_utils as gu

import lapsvmp as LapSVM
import anchorGraph as AG

import IPython

results_dir = osp.join(du.results_dir, 'kdd/SUSY/expts')

def test_SUSY_small (arg_dict):

	if 'seed' in arg_dict:
		seed = arg_dict['seed']
	else: seed = None
	
	if 'prev' in arg_dict:
		prev = arg_dict['prev']
	else: prev = 0.05

	if 'proj' in arg_dict:
		proj = arg_dict['proj']
	else: proj = False

	if 'save' in arg_dict:
		save = arg_dict['save']
	else: save = False

	nr.seed()

	verbose=True
	sparse = True
	pi = 0.5
	eta = 0.5
	K = 10
	
	t1 = time.time()
	X0,Y0,classes = du.load_SUSY(sparse=sparse, normalize=False)
	X0 = du.bias_normalize_ft(X0,sparse=True)
	if proj:
		proj_file = osp.join(du.data_dir, 'SUSY_proj_mat.npz')
		proj_data = np.load(proj_file)
		L = proj_data['L']
		train_samp = proj_data['train_samp']

		rem_inds = np.ones(X0.shape[1]).astype(bool)
		rem_inds[train_samp] = False

		X0 = ss.csc_matrix(ss.csc_matrix(L).T.dot(X0[:,rem_inds]))
		Y0 = Y0[rem_inds]

	## DUMMY STUFF
	# n = 1000
	# r = 20
	# X0 = ss.csc_matrix(np.r_[nr.randn(int(n/2),r), (2*nr.randn(n-int(n/2),r)+2)].T)
	# print (X0.shape)
	# Y0 = np.array([1]*int(n/2) + [0]*(n-int(n/2)))
	##
	print ('Time taken to load SUSY data: %.2f'%(time.time()-t1))
	t1 = time.time()
	if proj:
		ag_file = osp.join(du.data_dir, 'SUSY_AG_kmeans100_proj.npz')
		Z,rL = AG.load_AG(ag_file)
	else:
		ag_file = osp.join(du.data_dir, 'SUSY_AG_kmeans100.npz')
		Z,rL = AG.load_AG(ag_file)
	print ('Time taken to load SUSY AG: %.2f'%(time.time()-t1))
	
	# Changing prevalence of +
	if Y0.sum()/Y0.shape[0] < prev:
		prev = Y0.sum()/Y0.shape[0]
		X,Y = X0,Y0
	else:
		t1 = time.time()
		X,Y,inds = du.change_prev (X0,Y0,prev=prev,return_inds=True)
		Z = Z[inds, :]
		print ('Time taken to change prev: %.2f'%(time.time()-t1))

	n = 5000
	strat_frac = n/X.shape[1]
	# strat_frac = 1.0
	if strat_frac < 1.0:
		t1 = time.time()
		X, Y, strat_inds = du.stratified_sample(X, Y, classes=[0,1], strat_frac=strat_frac,return_inds=True)
		Z = Z[strat_inds, :]
		print ('Time taken to stratified sample: %.2f'%(time.time()-t1))
	d,n = X.shape


	# init points
	n_init = 1
	init_pt = Y.nonzero()[0][nr.choice(len(Y.nonzero()[0]),n_init,replace=False)]
	init_labels = {p:1 for p in init_pt}

	t1 = time.time()
	# Kernel AS
	ASprms = ASI.Parameters(pi=pi,sparse=sparse, verbose=verbose, eta=eta)
	kAS = ASI.kernelAS (ASprms)
	kAS.initialize(X, init_labels=init_labels)
	print ('KAS initialized.')
	
	# NN AS
	normalize = True
	NNprms = CI.NNParameters(normalize=normalize ,sparse=sparse, verbose=verbose)
	NNAS = CI.averageNNAS (NNprms)
	NNAS.initialize(X, init_labels=init_labels)
	print ('NNAS initialized.')
	
	# # lapSVM AS
	relearnT = 1
	LapSVMoptions = LapSVM.LapSVMOptions()
	LapSVMoptions.gamma_I = 1
	LapSVMoptions.gamma_A = 1e-5
	LapSVMoptions.NN = 6
	LapSVMoptions.KernelParam = 0.35
	LapSVMoptions.Verbose = False ## setting this to be false
	LapSVMoptions.UseBias = True
	LapSVMoptions.UseHinge = True
	LapSVMoptions.LaplacianNormalize = False
	LapSVMoptions.NewtonLineSearch = False
	LapSVMoptions.Cg = 1 # PCG
	LapSVMoptions.MaxIter = 1000  # upper bound
	LapSVMoptions.CgStopType = 1 # 'stability' early stop
	LapSVMoptions.CgStopParam = 0.015 # tolerance: 1.5%
	LapSVMoptions.CgStopIter = 3 # check stability every 3 iterations
	LapSVMprms = CI.lapSVMParameters(options=LapSVMoptions, relearnT=relearnT, sparse=False, verbose=verbose)
	LapSVMAS = CI.lapsvmAS (LapSVMprms)
	LapSVMAS.initialize(du.matrix_squeeze(X.todense()), init_labels=init_labels)
	print ('LapSVMAS initialized.')

	# # anchorGraph AS
	gamma = 0.01
	AGprms = CI.anchorGraphParameters(gamma=gamma, sparse=sparse, verbose=verbose)
	AGAS = CI.anchorGraphAS (AGprms)
	AGAS.initialize(Z, rL, init_labels=init_labels)	
	print ('AGAS initialized.')

	hits_K = [n_init]
	hits_NN = [n_init]
	hits_LSVM = [n_init]
	hits_AG = [n_init]

	print ('Time taken to initialize all approaches: %.2f'%(time.time()-t1))
	print ('Beginning experiment.')

	for i in xrange(K):

		print('Iter %i out of %i'%(i+1,K))
		idx1 = kAS.getNextMessage()
		kAS.setLabelCurrent(Y[idx1])
		hits_K.append(hits_K[-1]+Y[idx1])

		idx2 = NNAS.getNextMessage()
		NNAS.setLabelCurrent(Y[idx2])
		hits_NN.append(hits_NN[-1]+Y[idx2])

		idx3 = LapSVMAS.getNextMessage()
		LapSVMAS.setLabelCurrent(Y[idx3])
		hits_LSVM.append(hits_LSVM[-1]+Y[idx3])

		idx4 = AGAS.getNextMessage()
		AGAS.setLabelCurrent(Y[idx4])
		hits_AG.append(hits_AG[-1]+Y[idx4])
		print('')
	
	if save:
		if seed is None: 
			seed = -1
		save_results = {'kAS': hits_K,
						'NNAS': hits_NN,
						'LSVMAS': hits_LSVM,
						'AGAS': hits_AG}


		fname = 'expt_seed_%d.cpk'%seed
		if proj:
			dname = osp.join(results_dir, 'small/%.2f/proj/'%(prev*100))
		else:
			dname = osp.join(results_dir, 'small/%.2f/'%(prev*100))
		if not osp.isdir(dname):
			os.makedirs(dname)
		fname = osp.join(dname,fname)
		with open(fname, 'w') as fh: pick.dump(save_results, fh)

		fname = osp.join(results_dir, fname)
		with open(fname, 'w') as fh: pick.dump(save_results, fh)
	else:
		IPython.embed()


def test_SUSY_large (arg_dict):

	if 'seed' in arg_dict:
		seed = arg_dict['seed']
	else: seed = None
	
	if 'prev' in arg_dict:
		prev = arg_dict['prev']
	else: prev = 0.05

	if 'proj' in arg_dict:
		proj = arg_dict['proj']
	else: proj = False

	if 'save' in arg_dict:
		save = arg_dict['save']
	else: save = False

	nr.seed()

	verbose=True
	sparse = True
	K = 200
	
	t1 = time.time()
	X0,Y0,classes = du.load_SUSY(sparse=sparse, normalize=False)
	X0 = du.bias_square_normalize_ft(X0,sparse=True)
	if proj:
		proj_file = osp.join(du.data_dir, 'SUSY_proj_mat.npz')
		proj_data = np.load(proj_file)
		L = proj_data['L']
		train_samp = proj_data['train_samp']

		rem_inds = np.ones(X0.shape[1]).astype(bool)
		rem_inds[train_samp] = False

		X0 = ss.csc_matrix(ss.csc_matrix(L).T.dot(X0[:,rem_inds]))
		Y0 = Y0[rem_inds]

	print ('Time taken to load SUSY data: %.2f'%(time.time()-t1))
	t1 = time.time()
	if proj:
		ag_file = osp.join(du.data_dir, 'SUSY_AG_kmeans100_proj.npz')
		Z,rL = AG.load_AG(ag_file)
	else:
		ag_file = osp.join(du.data_dir, 'SUSY_AG_kmeans100.npz')
		Z,rL = AG.load_AG(ag_file)
	print ('Time taken to load SUSY AG: %.2f'%(time.time()-t1))
	
	# Changing prevalence of +
	if Y0.sum()/Y0.shape[0] < prev:
		prev = Y0.sum()/Y0.shape[0]
		X,Y = X0,Y0
	else:
		t1 = time.time()
		X,Y,inds = du.change_prev (X0,Y0,prev=prev,return_inds=True)
		Z = Z[inds, :]
		print ('Time taken to change prev: %.2f'%(time.time()-t1))

	strat_frac = 1.0
	if strat_frac < 1.0:
		t1 = time.time()
		X, Y, strat_inds = du.stratified_sample(X, Y, classes=[0,1], strat_frac=strat_frac,return_inds=True)
		Z = Z[strat_inds, :]
		print ('Time taken to stratified sample: %.2f'%(time.time()-t1))
	d,n = X.shape
	# IPython.embed()

	# init points
	n_init = 1
	init_pt = Y.nonzero()[0][nr.choice(len(Y.nonzero()[0]),n_init,replace=False)]
	init_labels = {p:1 for p in init_pt}

	t1 = time.time()
	# Kernel AS
	pi = prev
        eta = 0.5
	ASprms = ASI.Parameters(pi=pi,sparse=sparse, verbose=verbose, eta=eta)
	kAS = ASI.kernelAS (ASprms)
	kAS.initialize(X, init_labels=init_labels)
	print ('KAS initialized.')
	
	# NN AS
	normalize = True
	NNprms = CI.NNParameters(normalize=normalize ,sparse=sparse, verbose=verbose)
	NNAS = CI.averageNNAS (NNprms)
	NNAS.initialize(X, init_labels=init_labels)
	print ('NNAS initialized.')

	# # anchorGraph AS
	gamma = 0.01
	AGprms = CI.anchorGraphParameters(gamma=gamma, sparse=sparse, verbose=verbose)
	AGAS = CI.anchorGraphAS (AGprms)
	AGAS.initialize(Z, rL, init_labels=init_labels)	
	print ('AGAS initialized.')

	hits_K = [n_init]
	hits_NN = [n_init]
	hits_AG = [n_init]

	print ('Time taken to initialize all approaches: %.2f'%(time.time()-t1))
	print ('Beginning experiment.')

	for i in xrange(K):

		print('Iter %i out of %i'%(i+1,K))
		idx1 = kAS.getNextMessage()
		kAS.setLabelCurrent(Y[idx1])
		hits_K.append(hits_K[-1]+Y[idx1])

		idx2 = NNAS.getNextMessage()
		NNAS.setLabelCurrent(Y[idx2])
		hits_NN.append(hits_NN[-1]+Y[idx2])

		idx4 = AGAS.getNextMessage()
		AGAS.setLabelCurrent(Y[idx4])
		hits_AG.append(hits_AG[-1]+Y[idx4])
		print('')
	
	if save:
		if seed is None: 
			seed = -1
		save_results = {'kAS': hits_K,
						'NNAS': hits_NN,
						'AGAS': hits_AG}


		fname = 'expt_seed_%d.cpk'%seed
		if proj:
			dname = osp.join(results_dir, 'large/%.2f/proj/'%(prev*100))
		else:
			dname = osp.join(results_dir, 'large/%.2f/'%(prev*100))
		if not osp.isdir(dname):
			os.makedirs(dname)
		fname = osp.join(dname,fname)
		with open(fname, 'w') as fh: pick.dump(save_results, fh)
	else:
		IPython.embed()

if __name__ == '__main__':
	import sys

	## Argument 1: 1/2 -- small/large expt
	## Argument 2: number of experiments to run in parallel
	## Argument 3: prevalence of +ve class
	## Argument 4: projected features or normal features

	exp_type = 1
	num_expts = 10
	prev = 0.01
	proj = False

	if len(sys.argv) > 1:
		try:
			exp_type = int(sys.argv[1])
		except:
			exp_type = 1
		if exp_type not in [1,2]:
			exp_type = 1

	if len(sys.argv) > 2:
		try:
			num_expts = int(sys.argv[2])
		except:
			num_expts = 3
		if num_expts > 10:
			num_expts = 10
		elif num_expts < 1:
			num_expts = 1

	if len(sys.argv) > 3:
		try:
			prev = float(sys.argv[3])
		except:
			prev = 0.01
		if prev < 0 or prev > 0.05:
			prev = 0.01	

	if len(sys.argv) > 4:
		try:
			proj = bool(int(sys.argv[4]))
		except:
			proj = False

	test_funcs = {1:test_SUSY_small, 2:test_SUSY_large}
	# seeds = nr.choice(10e6,num_expts,replace=False)
	seed = range(1, num_expts+1)
	save = True
	arg_dicts = [{'prev':prev, 'proj':proj, 'seed':s, 'save':save} for s in seed]

	if num_expts == 1:
		print ('Running 1 experiment')
		#test_funcs[dset](seeds[0])
		test_funcs[exp_type](arg_dicts[0])
	else:
		print ('Running %i experiments'%num_expts)
		pl = Pool(num_expts)
		pl.map(test_funcs[exp_type], arg_dicts)
