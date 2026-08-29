# Module/program to generate Mask for Mixed Kinematic and local inertia
# E. Dutra May 2019
#
# Vendored unmodified from /ec/vol/ifs/rd/pad/ja8f/include/gen_mask_mixKinIner.py
# (an ECMWF colleague's personal, non-permanent ecFlow suite include
# directory -- see CLAUDE.md) for build_global_cmf_fixdir.sh.

#import pyximport
#pyximport.install(reload_support=True)

from netCDF4 import Dataset 
import numpy as np
import sys 
import os
import time

import cmflood_pylib as cfl
try:
  import cython_ext as ce
except:
  pass


def get_args():
  from argparse import ArgumentParser,ArgumentDefaultsHelpFormatter

  description = 'Compute mask for mixed Kinematic and Local inertial solutions'
  parser = ArgumentParser(description=description,formatter_class=ArgumentDefaultsHelpFormatter)
  parser.add_argument('-i',dest='frivclm',type=str,default=None,
                     help="Input file containing nextx/nexty/elevtn/nxtdst variables")
  parser.add_argument('-o',dest='fout',type=str,default=None,
                     help="output file to add variable")
  parser.add_argument('-t',dest='PMAXSLP',type=float,default=1.e-3,
                     help="Maximum slope accepted")

  
  opts = parser.parse_args()
  return opts 

t0 = time.time()
PMINSLP=1.e-5  # minimum accepted slope as in cama-flood source code 
zmiss=-9999
ldiag=True   # for extra diagnostics/ plots 
ldiag=False
## get command line arguments 
opts = get_args()
frivclm=opts.frivclm
PMAXSLP=opts.PMAXSLP
fout=opts.fout

#frivclm='/media/tor_md1/emanuel/CMF/ini_clm_co_cmf25_025_ea/rivclim.nc'
#frivclm='/media/tor_md3/emanuel/cama_flood/CaMa_data_v392_20180727_NC/map/glb_0.25d/ncdata.nc'
#frivclm='/media/tor_md3/emanuel/cama_flood/CaMa_data_v392_20180727_NC/map/glb_0.1d/ncdata.nc'
#PMAXSLP=1e-3
#fout=None #'/media/tor_md1/emanuel/CMF/ini_clm_co_cmf25_025_ea/rivpar.nc'


## Open file and read river network 
nc_clm = Dataset(frivclm,'r')
i2nextx = nc_clm['nextx'][:]
i2nexty = nc_clm['nexty'][:]
nlat,nlon = i2nextx.shape

## Compute 1D river network 
i2vector,i1seqx,i1seqy,i1next,nseqriv,nseqall = ce.calc_1d_seq(i2nextx,i2nexty,True)
#i2vector1,i1seqx1,i1seqy1,i1next1,nseqriv1,nseqall1 = cfl.calc_1d_seq(i2nextx,i2nexty,True)


## Load elevation and distrance to next cell 
xtmp = nc_clm['elevtn'][:]
d2elevtn  = cfl.map2vec(xtmp,i1seqx,i1seqy)
#xtmp1 = cfl.vec2map(d2elevtn,i1seqx,i1seqy,xtmp)
#assert(np.allclose(xtmp,xtmp1))
xtmp = nc_clm['nxtdst'][:]
d2nextdst = cfl.map2vec(xtmp,i1seqx,i1seqy)
#xtmp1 = cfl.vec2map(d2nextdst,i1seqx,i1seqy,xtmp)
#assert(np.allclose(xtmp,xtmp1))
nc_clm.close()

# Compute slopes
dslope = np.zeros((nseqall,1),dtype=np.float32)
dslope[0:nseqriv] = (d2elevtn[0:nseqriv] - d2elevtn[i1next[0:nseqriv],0] ) / d2nextdst[0:nseqriv]
dslope = np.maximum(dslope,PMINSLP)

npoints0 = np.sum(dslope>PMAXSLP)

rivseq,Smask = ce.calc_slope_mask(i1next,dslope,PMAXSLP)
#rivseq1,Smask1 = cfl.calc_slope_mask(i1next,dslope,PMAXSLP)
#assert(np.allclose(rivseq,rivseq1))
#assert(np.allclose(Smask,Smask1))
Smask[Smask==-1]=0

npoints1 = np.sum(Smask)
#sys.exit()
if fout is not None:
  print("Calculations done, writing variable mask_slope to file:",fout)
  nc = Dataset(fout,'a')
  try:
    cvar=nc.createVariable('mask_slope','f4',('lat','lon'),
                               zlib=True,complevel=6,fill_value=zmiss)
  except:
    cvar=nc.variables['mask_slope']
  cvar.long_name = 'Mixed Kinematic and local inertia mask'
  cvar.units = '-'
  cvar[:,:] = cfl.vec2map(Smask,i1seqx,i1seqy,i2vector)
  
  try:
    cvar=nc.createVariable('slope','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  except:
    cvar=nc.variables['slope']
  cvar.long_name = 'slope'
  cvar.units = 'm/m'
  cvar[:,:] = cfl.vec2map(dslope,i1seqx,i1seqy,i2vector)
  
  nc.history = time.ctime(time.time())+": Added mkineiner %f \n"%PMAXSLP+nc.history
  nc.close()

# It's done: 
elapsed =  time.time() -t0 
print("Npoints total:",len(i1next))
print("Npoints  > PMAXSLP, %i %4.2f "%(npoints0,npoints0/float(len(i1next))))
print("Npoints > PMAXSLP & continuity %i, %4.2f"%(npoints1,npoints0/float(len(i1next))))
print("Mask calculation done in %6.2f seconds"%elapsed)


if ldiag:

  ## compute #downstream cells 
  ndown = np.zeros((nseqall,2),dtype=int)
  for iseq in range(nseqall):
    icount=0
    icountS=0
    iseqk=iseq
    while (i1next[iseqk,0] > 0 ):
        #print(iseq,iseqk,i1next[iseqk,0],icount)
        icount=icount+1
        if Smask[iseqk] == 1: icountS=icountS+1
        iseqk = i1next[iseqk,0]
    ndown[iseq,0]=icount
    ndown[iseq,1]=icountS
    #print('--',iseq,ndown[iseq,:])


        
  ## diagnostic: find max path 
  iseq=np.argmax(ndown[:,1])
  #iseq=np.nonzero(ndown==54)[0][0]

  xtmp=np.zeros(((ndown[iseq,0]),4))
  for kk in range(ndown[iseq,0]):
    xtmp[kk,0]=d2nextdst[iseq]
    xtmp[kk,1]=dslope[iseq]
    xtmp[kk,2]=d2elevtn[iseq]
    xtmp[kk,3]=Smask[iseq]
    iseq=i1next[iseq,0]
  #pcolormesh(lon,lat,cfl.vec2map(rivseq,i1seqx,i1seqy,i2vector));colorbar()


  ## for plotting 
  fncdata="/media/tor_md1/emanuel/CMF/ini_clm_co_cmf25_025_ea/ncdata_new.nc"
  nc=Dataset(frivclm,'r')
  lat = nc_clm['lat'][:]
  lon = nc_clm['lon'][:]
  nc.close()
  nc=Dataset(fncdata,'r')
  latp = nc['latp'][:]
  lonp = nc['lonp'][:]
  nc.close()
  lonpS=cfl.map2vec(lonp,i1seqx,i1seqy)
  latpS=cfl.map2vec(latp,i1seqx,i1seqy)

  splot = np.zeros((nseqall,1),dtype=int)-1
  xlon=[]
  xlat=[]
  xlonS=[]
  xlatS=[]
  for iseq in range(nseqall):
    if rivseq[iseq] == 0:
      iseqk=iseq
      while (i1next[iseqk,0] > 0 and splot[iseqk] == -1):
        iseqk1=i1next[iseqk,0]
        if Smask[iseqk,0] ==1:
          xlonS.append(lonpS[iseqk].filled()[0]);xlonS.append(lonpS[iseqk1].filled()[0])
          xlatS.append(latpS[iseqk].filled()[0]);xlatS.append(latpS[iseqk1].filled()[0])
        xlon.append(lonpS[iseqk].filled()[0]);xlon.append(lonpS[iseqk1].filled()[0])
        xlat.append(latpS[iseqk].filled()[0]);xlat.append(latpS[iseqk1].filled()[0])
        splot[iseqk]=0
        iseqk=iseqk1
        xlon.append(np.nan)
        xlat.append(np.nan)
        xlonS.append(np.nan)
        xlatS.append(np.nan)
  import matplotlib.pyplot as plt
  plt.figure()
  plt.plot(xlon,xlat,'.-k',ms=2)   
  plt.plot(xlonS,xlatS,'.-r',ms=2)   
  mm=i1next[:,0]<0
  plt.plot(lonpS[mm],latpS[mm],'xb',ms=4)  
  mm=rivseq[:,0]==0
  plt.plot(lonpS[mm],latpS[mm],'xg',ms=4) 
  plt.show() 


  ## Just for testing stuff 
  ##i1nextx = cfl.map2vec(i2nextx,i1seqx,i1seqy)
  ##i2nextx_tmp = cfl.vec2map(i1nextx,i1seqx,i1seqy,i2vector)
  ## End of testing 
