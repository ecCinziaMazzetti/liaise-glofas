# Module/program to generate cama-flood parameters
# adapted from s01-channel_params.sh / calc_rivwith.F90 / set_bifparam.F90 /set_gwdlr.F90
# E. Dutra Oct 2019
#
# Vendored unmodified from /ec/vol/ifs/rd/pad/ja8f/include/calc_rivpar.py
# (an ECMWF colleague's personal, non-permanent ecFlow suite include
# directory -- see CLAUDE.md) for build_global_cmf_fixdir.sh.

from __future__ import print_function
from netCDF4 import Dataset 
import numpy as np
import sys 
import os
import time
import gzip


def get_args():
  from argparse import ArgumentParser,ArgumentDefaultsHelpFormatter

  description = 'Compute cama-flood parameters'
  parser = ArgumentParser(description=description,formatter_class=ArgumentDefaultsHelpFormatter)
  parser.add_argument('-iriv',dest='friv',type=str,default=None,
                     help="river network file")
  parser.add_argument('-irofc',dest='frunoffc',type=str,default=None,
                     help="Input runoff file with climatology")
  parser.add_argument('-o',dest='foutput',type=str,default='rivpar.nc',
                     help="output file")
  parser.add_argument('-pHC',dest='pHC',type=float,default='0.1',
                     help="coefficient for bank height")
  parser.add_argument('-pHP',dest='pHP',type=float,default='0.5',
                     help="Power for bank height")
  parser.add_argument('-pHO',dest='pHO',type=float,default='0',
                     help="offset for bank height")
  parser.add_argument('-pHMIN',dest='pHMIN',type=float,default='1.',
                     help="Minimum bank height")
  parser.add_argument('-pWC',dest='pWC',type=float,default='2.5',
                     help="coefficient for width")
  parser.add_argument('-pWP',dest='pWP',type=float,default='0.6',
                     help="Power for bank width")
  parser.add_argument('-pWO',dest='pWO',type=float,default='0',
                     help="offset for bank width")
  parser.add_argument('-pWMIN',dest='pWMIN',type=float,default='5.',
                     help="Minimum bank width")
  parser.add_argument('-pMAN',dest='pMAN',type=float,default='0.03',
                     help="Manning roughness")
  parser.add_argument('-pGWDELAY',dest='pGWDELAY',type=float,default='0.',
                     help="Ground water delay (days)")
  parser.add_argument('-pBIFLAYER',dest='pBIFLAYER',type=int,default='5',
                     help="number of bifurcation layers")
  parser.add_argument('-ibifori',dest='fbifori',type=str,default=None,
                     help="Original bifurcation")
  
  
    
  opts = parser.parse_args()
  return opts 

def calc_bathymetry(rivclm,pp):
  
  ## HC:Coefficient, HP:Power, and HMIN:Minimum for channel depth
  # (H=max(HMIN,HC*Qave**HP)+HO
  rivhgt = np.maximum( pp['HMIN'], pp['HC'] * rivclm**pp['HP'] + pp['HO'])

  ## WC:Coefficient, WP:Power, and WMIN:Minimum for channel width
  #  (W=max(WMIN,WC*Qave**WP)+WO
  rivwth = np.maximum( pp['WMIN'], pp['WC'] * rivclm**pp['WP'] + pp['WO'])
  
  return rivhgt,rivwth

def gen_output(fout,lat,lon,zmiss,hist=''):
  
  print('generating',fout)
  if os.path.isfile(fout):
    os.remove(fout)
  
  ncfile = Dataset(fout,mode='w',format='NETCDF4_CLASSIC')
  ncfile.history = "Created "+time.ctime(time.time())+' '+hist
  
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
  
  cvar=ncfile.createVariable('gwdelay','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'Ground water delay'
  cvar.units = 'days'
  
  cvar=ncfile.createVariable('rivhgt','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'Channel Depth'
  cvar.units = 'm'
  
  cvar=ncfile.createVariable('rivwth_par','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'Channel width based only on parameter'
  cvar.units = 'm'
  
  cvar=ncfile.createVariable('rivwth','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'Channel width merged with gwdlr'
  cvar.units = 'm'
  
  cvar=ncfile.createVariable('rivman','f4',('lat','lon'),
                             zlib=True,complevel=6,fill_value=zmiss)
  cvar.long_name = 'manning roughness '
  cvar.units = 'm'
  
  return ncfile


zmiss=-9999
opts = get_args()
print(opts)

channel_bathymetry_params={'HC':opts.pHC,
                           'HP':opts.pHP,
                           'HO':opts.pHO,
                           'HMIN':opts.pHMIN,
                           'WC':opts.pWC,
                           'WP':opts.pWP,
                           'WO':opts.pWO,
                           'WMIN':opts.pWMIN}

##================================================
## 1. Channel bathymetry parameters 

## read data
nc = Dataset(opts.frunoffc,'r')
outclm = nc.variables['outclm'][:]
lat = nc.variables['lat'][:]
lon = nc.variables['lon'][:]
nc.close()

## compute river channel parameters
rivhgt,rivwth_par = calc_bathymetry(outclm,channel_bathymetry_params)

## Manning roughness : for now it's constant 
rivman = rivhgt*0 + opts.pMAN

## Ground water delay: for now it's constant 
gwdelay = rivhgt*0 + opts.pGWDELAY

##================================================
## merge with GWDLR
ncriv = Dataset(opts.friv,'r')
width = ncriv.variables['width'][:]
i2nextx = ncriv.variables['nextx'][:]
basin = ncriv.variables['basin'][:]
ncriv.close()

## to estimate optimal WP to match GWDLR 
nbmax=100
pp=( basin<=nbmax) & (width< 10000) & (width > channel_bathymetry_params['WMIN'])
y = width[pp]
A = np.vstack([outclm[pp]**channel_bathymetry_params['WP']]).T
m = np.linalg.lstsq(A, y, rcond=None)[0]
print('WC original,estimate:',channel_bathymetry_params['WC'],m,
      np.sqrt(np.mean( (y-rivwth_par[pp])**2 )),np.sqrt(np.mean( (y-m*A[:,0])**2 )))


rivwth = np.ma.masked_where(i2nextx.mask,np.minimum(width,10000) )
cp1 = (~i2nextx.mask) & (width < 50 )  # small widths 
rivwth[cp1] = np.maximum(width[cp1],rivwth_par[cp1])
cp2 = (~i2nextx.mask) & (width >= 50 ) & (width < 0.5 * rivwth_par )
rivwth[cp2] =0.5*rivwth_par[cp2]
cp3 = (~i2nextx.mask) & (width >= 50 ) & (width > 5 * rivwth_par )
rivwth[cp3] =5*rivwth_par[cp3]


##===============================================
## write to output file 
ncout = gen_output(opts.foutput,lat,lon,zmiss,hist=' '.join(sys.argv[1:]))
ncout.variables['rivman'][:] = rivman
ncout.variables['gwdelay'][:] = gwdelay
ncout.variables['rivhgt'][:] = rivhgt
ncout.variables['rivwth_par'][:] = rivwth_par
ncout.variables['rivwth'][:] = rivwth
ncout.close()


##=============================================
## Set bifurcation 
if opts.fbifori is not None: 
  fid = gzip.open(opts.fbifori)
  il=0
  npth_new=0
  for line in fid:
    if il== 0 :
      npath,nlev = [int(line.split()[0]),int(line.split()[1])]
      xdata=[]
      print("npath,nlev",npath,nlev)
    else:
      xtmp=[float(val) for val in line.split()]
      if np.sum(np.array(xtmp[6:6+opts.pBIFLAYER]) > 0)> 0:
        npth_new=npth_new+1
        if ( xtmp[6]<=0):
          dph=-9999
          wth1=0
        else:
          ix=int(xtmp[0]-1)
          iy=int(xtmp[1]-1)
          jx=int(xtmp[2]-1)
          jy=int(xtmp[3]-1)
          dph0=np.maximum(rivhgt[iy,ix],rivhgt[jy,jx])
          dph=np.maximum(0.5,np.log10(xtmp[6])*2.5-4)
          dph=np.minimum(dph0,dph)
        xtmp1=xtmp[0:6]+[dph]+xtmp[6:6+opts.pBIFLAYER]+xtmp[-2:]
        #print(xtmp1) 
        xdata.append(xtmp1)
        #if npth_new> 2: sys.exit()
    il=il+1
  #fid.close()
  print("npth_new,nlev_new",npth_new,opts.pBIFLAYER)
  assert npth_new 
  bifOUT='bifprm.txt'
  print("Generating:",bifOUT)
  fidO = open(bifOUT,'w')
  fidO.write("%8i%8i   npath_new, nlev_new, (ix,iy), (jx,jy), length, elevtn, depth, (width1, width2, ... wodth_nlev), (lon,lat)\n"%(npth_new,opts.pBIFLAYER))
  
  for il in range(len(xdata)):
    fidO.write(("%8i"*4+"%12.2f"*(opts.pBIFLAYER+3)+"%10.3f"*2+"\n")%(tuple(xdata[il][:])))
  fidO.close()
  





