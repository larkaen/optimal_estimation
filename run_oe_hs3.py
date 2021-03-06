#!/usr/bin/env python
#############################################################################_80
#_script	run_oe.py
# author	Walter R Sessions
# purpose	barebones outline for individual FOV optimal estimation retrieval
#			qsubmission.py will likely be the call source
################################################################################
''' if FINAL works, then we just need to rewrite a gathering script '''
''' and also to write uncertainties to SOMEWHERE '''
import os
import sys
import matplotlib
from libtools import dbg

if 'DISPLAY' not in os.environ: matplotlib.use('Agg')

try:
	DIR_WORK = os.environ['TMPDIR'] #os.environ['WORK'] + '/tmp'
except KeyError:
	DIR_WORK = '/odyssey/scratch/wsessions/logs'

print "TMPDIR", DIR_WORK


def main(fidx, dir_lblrtm_fmt='', dir_lblrtm=None, dir_plot='.',
	persistence=False, hostname=False, file_col=None,
	experiment='HS3', surf_temp='GDAS', rerun=False, **kwargs):
	'''
	completely relies upon the kwargs pickle 
	written by optimal_estimation.real_case()

	fidx	int,	Field of view number associated with
					flight segment file in $PRODUCTS/hs3
	'''

	import matplotlib.pyplot as plt
	from optimal_estimation import optimal_estimation as oe
	from numpy import diag, matrix
	from lblrtm_utils import microwindow_average, microwindow_stdev
	from lblrtm_utils import get_surf_temp
	from libtools import mkdir_p, epoch2dtg, dbg
	from shutil import copytree, rmtree, copy2
	from glob import glob
	from oe_utils import read_airs
	from time import sleep
	from hs3_utils import Flight_segment as F
	from os import unlink

	try:
		file_col, hostname = remote_copy(file_col)
	except:
		pass

	#_read in radiance data for profile
	flight = F(**kwargs)
	fov = flight[fidx]
	wave = flight.SHIS_wavenumber
	rads = fov.SHIS_radiances
	errs = flight.SHIS_HBB_NESR 

	#_initialize plot
#	fig, ax = plt.subplots(1, **{'figsize' : (4,1)})
	fig, ax = plt.subplots(1, figsize=(4,1))
	fig.suptitle(kwargs.get('desc'), size='xx-small')
	out_label = kwargs.get('out_label')
	pname = 'oe_{0}_{1}_f{2:04d}.png'.format(out_label, flight.dtg0, fidx)
	pname = os.path.join(dir_plot, 'OE', pname)
	mkdir_p(os.path.join(dir_plot, 'OE'))
	if os.path.exists(pname):
		os.unlink(pname)

	#_build covariance matrix
	#_when using microwindows, average observation data
	dv = kwargs.get('dv')
	if dv < 0:
		std, d		= microwindow_stdev(rads, wave, dv)
		nesr, d		= microwindow_average(errs, wave, dv, error=True)
		y, wave_obs = microwindow_average(rads, wave, dv)

		#_std deviation within microwindows applied to ref
		# blackbody 
		cov = matrix(diag(nesr) + diag(std))

	else:
		cov = matrix(diag(errs))

	#_allow for arbitrary lblrtm directory, get location of LBL-RTM output
	dtgfov = (flight.dtg0, flight.dtg1, fidx, experiment, flight.dtg0[2:])
	dir_lblrtm = dir_lblrtm_fmt.format(*dtgfov)
	dir_lblrtm_arc = dir_lblrtm_fmt.format(*dtgfov) if dir_lblrtm is None \
		else dir_lblrtm




	#_update kwargs based upon dynamic ATP/CTP
	surf_temp = get_surf_temp(fov, surf_temp_src=surf_temp, dir_lblrtm=dir_lblrtm_arc, 
			**kwargs)
	check_ctp(fov, wave, **kwargs)
	check_atp(fov, **kwargs)		

	#_if already run and not desired to redo, kill
	lbldis_output = kwargs.get('lbldis_output')
	file_out = os.path.join(dir_lblrtm_arc, lbldis_output)

	#_check last field of view for persistence
	if type(persistence) == dict and fidx != 0:
		print 'DONT USE THIS IS PROBABLY WRONG DIRECTORY'
		dtgfov_tmp = (experiment, dtg)
		dir_lblrtm_arc_tmp = dir_lblrtm_fmt.format(*dtgfov_tmp)
		print 'CHECKING PERSIST', kwargs['apriori']

		#_put this in a try clause to allow for failure
		try:
			check_persistence(dir_lblrtm_arc_tmp, persistence, **kwargs)
		except IOError:
			pass
		print 'CHECKING OUTSIST', kwargs['apriori']

	#_copy the archive LBLRTM directory locally and work form there
	dir_lblrtm = os.path.join(DIR_WORK,'/'.join(dir_lblrtm_arc.split('/')[-2:]))

	if not os.path.exists(dir_lblrtm + '/TAPE5'):
		killcount = 0 
		while killcount < 10:
			try:
				mkdir_p(dir_lblrtm)
				[ copy2(cp, dir_lblrtm) for cp in glob(dir_lblrtm_arc + '/*') ]
				break
			except:
				#_if fails, try ten times
				sleep(10)
				killcount += 1

			if killcount >= 10:
				exit()
	
	#_update keyword arguments for this fov
	args = (rads, wave, cov)
	kwargs.update({ 'fig'		: fig,
					'ax'		: ax,
					'pname'		: pname,
					'nproc'		: 1,	#_just in case I forgot to tone it down
					'dir_lblrtm_arc' : dir_lblrtm_arc,
					'dir_lblrtm' : dir_lblrtm,
					'surf_temp'	: surf_temp,
				
						})

	#_pull_the_trigger_#
	#__________________#
	dbg('LAUNCHING...')
	oe(*args, **kwargs)

	#_archive crap
	for out_file in glob(dir_lblrtm + '/*' + out_label + '*'):

		killcount = 0
		out = os.path.join(dir_lblrtm_arc, out_file.split('/')[-1])

		#_remove old output if rerunning
		if rerun and os.path.exists(out):
			unlink(out)

		while not os.path.exists(out):
			try:
				dbg(('archiving', out_file, '->', out))
				copy2(out_file, dir_lblrtm_arc)
			except:
				dbg(('failed to copy', out_file, '->', out))
				sleep(10)

	#_plot up results with flight data
	kwargs.update({'dir_plot' : os.path.join(dir_plot, 'DASHBOARD')})
	flight.plot(fidx=fidx, rerun=rerun, **kwargs)
		
	#_remove temporary directory
	rmtree(dir_lblrtm)	


def check_atp(fov, apriori=[], dynamic_ATP=False, **kwargs):
	'''

	'''
	if not dynamic_ATP:
		return

	from hs3_utils import get_naaps_ctp
	from libgeo import p2z
	from numpy import ndarray

	#_loop over each aerosol layer
	for layer in apriori:
		dbg('LAYER0')
		if layer['type'] != 'aerosol':
			continue

		#_loop over potential sources by priority
		for src in dynamic_ATP:
			dbg(('LAYER1', src))

			if src == 'NAAPS':

				arg = (fov.SHIS_epoch, fov.SHIS_latitude, fov.SHIS_longitude)
				CTP, CBP = get_naaps_ctp(*arg, **kwargs)#_layer top and bot pressures	
				CTZ = p2z(CTP) / 1e3
				CBZ = p2z(CBP) / 1e3

				#_if apprioriate layer and naaaps, use
				if ((type(CTZ) == list or type(CTZ) == ndarray) and max(CTZ) > 0) or   \
					(type(CTZ) == float and CTZ > 0):
						dbg(('WRS0', CTZ))
			
						#_update layer
						layer['z_top'] = max(CTZ) 
						layer['z'] = max(CBZ) 
						dbg(('LAYER3', CTZ))

			##	elif src == 'SHIS':

			break
	

def check_ctp(fov, wave_obs, apriori=[], dynamic_CTP=False, **kwargs):
	'''
	setting dyanmic_CTP to True replaces the
	apriori cloud top pressure with one from a separate 
	source.  Currently, only supporting dual regression
	heights from Scanning-HIS
	'''
	from libgeo import p2z, planck_inv
	from lblrtm_utils import microwindow_average
	if not dynamic_CTP:
		return

	#_loop over each layer
	for layer in apriori:
		
		#_skip aerosol layers
		if layer['type'] != 'cloud':
			continue

		#_giving source priority by list order
		for src in dynamic_CTP:

			if src == 'SHIS':

				#_calc cloud top height
				CTP = getattr(fov, '{0}_CTP'.format(src))
				CTZ = p2z(CTP) / 1e3

				#_get brightness temperatures for a few windows 
				obs_rads = getattr(fov, '{0}_radiances'.format(src))
				r, w = microwindow_average(obs_rads, wave_obs, -26)
				bt = planck_inv(r,w*100,domain='wavenumber')[-3:].mean()

				#_if apprioriate layer and there is a value, use SHIS-DR
				if CTZ > 0:
					layer['z_top'] = CTZ
					layer['z'] = CTZ-0.1

					dbg(('WRS0', CTZ))
				#_check if 'ice' cloud
				if bt < 273.15: #_maybe lower

					#_add ice ssp to list and change cloud database to it
					ice = '/data/wsessions/lbldis_inputs/' \
						+ 'ssp_db.mie_ice.gamma_sigma_0p100'
					kwargs['ssp_db_files'].append(ice)
					layer['dbnum'] = len(kwargs['ssp_db_files'])
			
			#_other source options here elif 'cloudsat' or whatever
			else:
				continue

			#_once complete for one source, skip rest
			break
					

def check_persistence(dir_last, persistence, apriori=None, out_label='',
	ssp_db_files=[], **kwargs):
	'''
	Look at dir_last, pull out values, and if within uncertainty
	limits, use as next apriori
	dir_last	str,	path to last field of view directory
	out_label	str,	output label for version
	apriori		dict,	dictionary containing threshold levels  

	'''
	from lblrtm_utils import Lbldis_input
	from pickle import load
	
	#_name of final solution from last fov input file 
	final = 'lbldis_input.{0}.final'.format(out_label)
	final = os.path.join(dir_last, final)
	final = Lbldis_input(final)
	final.merge_layers()	

	#_read in posterior
	pickle = 'posterior.{0}.pk'.format(out_label)
	pickle = os.path.join(dir_last, pickle)
	uncert = load(open(pickle, 'rb'))
	
	#_check each layer and update
	for i, layer in enumerate(apriori):

		#_pull out database of layer
		db_path = ssp_db_files[layer['dbnum']]
		db = db_path.split('/')[-1]

		#_use db as key to pull out uncertainty and final value
		layer_uncert = uncert[db]
		result_idx = final.ssp_db.index(db_path)
		layer_result = final.layers[result_idx]

		#_make sure layers match
		layer_sspdb = final.ssp_db[layer_result['dbnum']]
		if layer_sspdb != db_path:
			raise RuntimeError, 'Databases do not match {0} {1}'.format(
				layer_sspdb, db_path)
	
		#_loop over previous results and update apriori
		for state_var, uncertainty in layer_uncert.iteritems():
			#_pull out final solution from last fov for same layer
			result_sv = layer_result[state_var]

			#_tau is in a list, this is dumb
			if type(result_sv) == list:
				result_sv = result_sv[0]
				islist = True
			else:
				islist = False	

			#_calculate fractional uncertainty
			f = uncertainty / result_sv 

			#_if within range, set apriori
			if f < persistence[state_var]:
				if islist:
					apriori[i][state_var] = [result_sv]
				else:
					apriori[i][state_var] = result_sv 


def remote_copy(src, dst='.', passarg=''):
	''' copy over via scp '''
	import re
	import os
	result = re.search('^(.*?):(.*)$', src)

	if not result:
		return False

	host = result.group(1)
	fnam = result.group(2)
	cmd = 'scp {1} {0} {2}'.format(src, passarg, dst)
	print cmd
	print '\n\n'
	os.system(cmd)
	return (fnam.split('/')[-1], host)
	#_just assume no colons in file.  We aren't using WRF output.
	

################################################################################
#_end_main_#####################################################################
################################################################################


if __name__ == '__main__':
##	try:
		import pickle
		#_pull out command line arguments 
		script, fidx, file_kwarg = sys.argv

		#_check if kwargs file is local
		remote = remote_copy(file_kwarg)
		if remote:
			file_kwarg = remote[0]
			hostname = remote[1] 
			
		#_read in kwargs pickle
		kwargs = pickle.load(open(file_kwarg, 'rb'))
		if remote:
			kwargs['hostname'] = hostname

		#_launch!
		main(int(fidx), **kwargs)

		#_if all is successful, delete sbatch and kwarg files
		print 'Unlinking', file_kwarg
		os.unlink(file_kwarg)
##	except:
##		print \
##		'''
##		USAGE:	./run_oe.py <fov#> <file_kwarg>
##
##		'''
