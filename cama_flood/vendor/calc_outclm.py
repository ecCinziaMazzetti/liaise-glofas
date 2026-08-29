# Module/program to generate climatology of discharge
# adapted from s01-channel_params.sh / calc_outclm.F90
# E. Dutra Oct 2019
#
# Vendored from /ec/vol/ifs/rd/pad/ja8f/include/calc_outclm.py (an ECMWF
# colleague's personal, non-permanent ecFlow suite include directory -- see
# CLAUDE.md) for build_global_cmf_fixdir.sh. One local fix below: the
# ecland repo's cython_ext.pyx `remap()` expects float64 input (its own
# signature says dtype_f8), but this script originally passed float32;
# unmodified it raises "Buffer dtype mismatch, expected 'dtype_f8' but got
# 'float'". remap()'s own return value is already always float64
# regardless of input dtype, so this is the only change needed.

from __future__ import print_function
from netCDF4 import Dataset 
import numpy as np
import sys 
import os
import time

import cython_ext as ce

def gen_output(fout,lat,lon,xout,zmiss):
  
  t0 = time.time()
  print('generating',fout)
  if os.path.isfile(fout):
    os.remove(fout)
  
  ncfile = Dataset(fout,mode='w',format='NETCDF4_CLASSIC')
  ncfile.history = "Created "+time.ctime(time.time())
  
  ncfile.createDimension('lat',len(lat))
  ncfile.createDimension('lon',len(lon))
  
  cvar=ncfile.createVariable('lat','f8',('lat'))
  cvar.long_name = 'latitude'
  cvar.standard_name = 'latitude'
  cvar.units = 'degrees_north'
  cvar[:] = lat
  
  cvar=ncfile.createVariable('lon','f8',('lon'))
  cvar.long_name = 'longitude'
  cvar.standard_name = 'longitude'
  cvar.units = 'degrees_east'
  cvar[:] = lon
  
  cvar=ncfile.createVariable('outclm','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'Average discharge (for channel parameters)'
  cvar.units = 'm3/s'
  cvar[:] = xout 
  ncfile.close()

def accumulate_river(i1seqx,i1seqy,i2nextx,i2nexty,xin):
  ## do the routing 
  xout=np.ma.masked_all(i2nextx.shape,dtype=xin.dtype)

  for iseq in range(len(i1seqx)):
    ix = i1seqx[iseq]
    iy = i1seqy[iseq]
    xout[iy,ix] = xin[iy,ix]
  
  for iseq in range(len(i1seqx)):
    ix = i1seqx[iseq]
    iy = i1seqy[iseq]
    if (i2nextx[iy,ix] > 0):
      jx = i2nextx[iy,ix] -1 
      jy = i2nexty[iy,ix] -1 
      xout[jy,jx] = xout[jy,jx]+xout[iy,ix]
  return xout 

def get_args():
  from argparse import ArgumentParser,ArgumentDefaultsHelpFormatter

  description = 'Compute discharge climatology'
  parser = ArgumentParser(description=description,formatter_class=ArgumentDefaultsHelpFormatter)
  parser.add_argument('-iriv',dest='friv',type=str,default=None,
                     help="river network file")
  parser.add_argument('-irof',dest='frunoff',type=str,default=None,
                     help="Input runoff file")
  parser.add_argument('-imap',dest='finpmat',type=str,default=None,
                     help="Input inpmat")
  parser.add_argument('-o',dest='foutput',type=str,default='outclm.nc',
                     help="output file")
  parser.add_argument("-d", dest='debug',help="swith debug",default=False,
                    action="store_true")
  
  opts = parser.parse_args()
  return opts 

zmiss=-9999
opts = get_args()
print(opts)

##=================================
## 1. Load data 
t0 = time.time()
  # river network 
nc_riv = Dataset(opts.friv,'r')
i2nextx = nc_riv['nextx'][:]
i2nexty = nc_riv['nexty'][:]
lat = nc_riv['lat'][:]
lon = nc_riv['lon'][:]
if opts.debug:
  rivseq_riv = nc_riv['rivseq'][:,:]
nc_riv.close()
  
 ## load runoff 
nc_rof = Dataset(opts.frunoff,'r')
runoff = nc_rof.variables['ro'][:].squeeze()  # is in m/day (strange units...)
runoff = runoff/(86400.)  # transform to m/s
nc_rof.close()

  ## load input matrix 
nc_inp = Dataset(opts.finpmat,'r')
inpa = nc_inp.variables['inpa'][:]
inpx = nc_inp.variables['inpx'][:]
inpy = nc_inp.variables['inpy'][:]
inpn = nc_inp.variables['nlev'][:]
nc_inp.close()
print("Loading data in %6.2f seconds"%(time.time()-t0))

##=================================================
## 2. River sequence 
t0 = time.time()
rivseq = ce.gen_rivseq(i2nextx,i2nexty)
print("computing rivseq in %6.2f seconds"%(time.time()-t0))
if opts.debug:
  assert np.allclose(rivseq_riv,rivseq) , 'computed rivseq does not match clim file'
  
## compute i1seq 
t0 = time.time()
i1seqx,i1seqy = ce.calc_1d_seq_rivseq(rivseq)
print("computing i1seq in %6.2f seconds "%(time.time()-t0))

##=================================================
## 3. interpolate runoff to river network 
t0 = time.time()
runoff_river = ce.remap(inpn,inpx,inpy,inpa,runoff.astype('f8'))
print("Interpolate runoff to river network in %6.2f seconds "%(time.time()-t0))

##=================================================
## 4. Accumulate over the river network 
#t0 = time.time()
#rivout = accumulate_river(i1seqx,i1seqy,i2nextx,i2nexty,runoff_river)
#print("Accumulate on river network in %6.2f seconds "%(time.time()-t0))
t0 = time.time()
rivout = ce.accumulate_river(i1seqx,i1seqy,i2nextx,i2nexty,runoff_river)
print("Accumulate on river network in %6.2f seconds "%(time.time()-t0))
#assert np.allclose(rivout_,rivout) , 'rivout are not equal'

##=================================================
## 5. Save to output 
print('Saving to',opts.foutput)
gen_output(opts.foutput,lat,lon,rivout,zmiss)
