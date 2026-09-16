#!/usr/bin/env python

# create surfclim.nc/surfinit.nc/surfveg

from __future__ import print_function
from netCDF4 import Dataset
import time
import numpy as np
import eccodes as ec
import os

import sys
from osm_pyutils import grid_gaussian as gg

imiss = -9999
rmiss = 1e20

ncVARS = {}
ncVARS['ini'] = {}
ncVARS['clm'] = {}
ncVARS['veg'] = {}

ncVARS['ini']['SoilTemp'] = {
    'dims': ('nlevs', 'x'), 'long_name': 'Soil Temperature', 'units': 'K'}
ncVARS['ini']['SoilMoist'] = {
    'dims': ('nlevs', 'x'), 'long_name': 'Soil Moisture', 'units': 'm3/m3'}
ncVARS['ini']['iceTemp'] = {
    'dims': ('nlevs', 'x'), 'long_name': 'Ice Temperature', 'units': 'K'}

ncVARS['ini']['SWEML'] = {
    'dims': ('nlevsn', 'x'), 'long_name': 'SWEML', 'units': 'kg m-2'}
ncVARS['ini']['snowdensML'] = {
    'dims': ('nlevsn', 'x'), 'long_name': 'Snow density ML', 'units': 'kg m-3'}
ncVARS['ini']['SnowTML'] = {
    'dims': ('nlevsn', 'x'), 'long_name': 'SnowT ML', 'units': 'K'}
ncVARS['ini']['slwML'] = {
    'dims': ('nlevsn', 'x'), 'long_name': 'Snow Liq water cont ML', 'units': 'kg m-2'}

ncVARS['ini']['SWE'] = {'dims': ('x'), 'long_name': 'SWE', 'units': 'kg m-2'}
ncVARS['ini']['snowdens'] = {
    'dims': ('x'), 'long_name': 'Snow density', 'units': 'kg m-3'}
ncVARS['ini']['SAlbedo'] = {
    'dims': ('x'), 'long_name': 'Snow Albedo', 'units': '-'}
ncVARS['ini']['SnowT'] = {'dims': ('x'), 'long_name': 'SnowT', 'units': 'K'}
ncVARS['ini']['CanopInt'] = {
    'dims': ('x'), 'long_name': 'CanopInt', 'units': 'kg m-2'}
ncVARS['ini']['AvgSurfT'] = {
    'dims': ('x'), 'long_name': 'AvgSurfT', 'units': 'K'}
ncVARS['ini']['TLICE'] = {
    'dims': ('x'), 'long_name': 'lake ice temperature', 'units': 'K'}
ncVARS['ini']['TLMNW'] = {
    'dims': ('x'), 'long_name': 'lake mean water temperature', 'units': 'K'}
ncVARS['ini']['TLWML'] = {
    'dims': ('x'), 'long_name': 'lake mixed layer temperature', 'units': 'K'}
ncVARS['ini']['TLBOT'] = {
    'dims': ('x'), 'long_name': 'lake bottom temperature', 'units': 'K'}
ncVARS['ini']['TLSF'] = {
    'dims': ('x'), 'long_name': 'lake temperature shape factor', 'units': '-'}
ncVARS['ini']['HLICE'] = {
    'dims': ('x'), 'long_name': 'lake ice thickness', 'units': 'm'}
ncVARS['ini']['HLML'] = {
    'dims': ('x'), 'long_name': 'lake mixed layer thickness"', 'units': 'K'}
ncVARS['ini']['WTD'] = {
    'dims': ('x'), 'long_name': 'Water table depth', 'units': 'm',
    'comment': 'Optional (LEGWRECHARGE); falls back to a flat 100m default if absent. '
               'See init_clim/add_bedrock_wtd_fields.py -- Fan et al. (2017, PNAS) '
               'equilibrium water-table depth, not part of the MARS/ERA5 init pipeline above.'}
#*ncVARS['ini']['seaice'] = {
#*    'dims': ('x'), 'long_name': 'sea ice mask', 'units': '-'}

ncVARS['clm']['Malbedo'] = {
    'dims': ('month', 'x'), 'long_name': 'Monthly Albedo', 'units': '-'}
ncVARS['clm']['Mlail'] = {
    'dims': ('month', 'x'), 'long_name': 'Monthly LAI low veg', 'units': 'm2/m2'}
ncVARS['clm']['Mlaih'] = {
    'dims': ('month', 'x'), 'long_name': 'Monthly LAI high veg', 'units': 'm2/m2'}
ncVARS['clm']['fwet'] = {
    'dims': ('month','x'), 'long_name': 'wetland fraction', 'units': '-'}
ncVARS['clm']['Mask'] = {'dims': (
    'x'), 'long_name': 'Mask', 'units': '-', 'comment': '1==run model', 'dtype': 'i4', 'dflt': 0}
ncVARS['clm']['z0m'] = {'dims': (
    'x'), 'long_name': 'Surface roughness', 'units': '-', 'comment': 'not used'}
ncVARS['clm']['lz0h'] = {'dims': (
    'x'), 'long_name': 'log surface roughness length for heat', 'units': '-'}
ncVARS['clm']['landsea'] = {
    'dims': ('x'), 'long_name': 'Land Sea Mask', 'units': '-'}
ncVARS['clm']['geopot'] = {'dims': (
    'x'), 'long_name': 'Geopotential (at the surface = orography)', 'units': '"m**2 s**-2"'}
ncVARS['clm']['cvl'] = {
    'dims': ('x'), 'long_name': 'low vegetation cover', 'units': '-'}
ncVARS['clm']['cvh'] = {
    'dims': ('x'), 'long_name': 'hight vegetation cover', 'units': '-'}
ncVARS['clm']['tvl'] = {'dims': (
    'x'), 'long_name': 'type of low vegetation', 'units': '-', 'dtype': 'i4'}
ncVARS['clm']['tvh'] = {
    'dims': ('x'), 'long_name': 'type of hight vegetation', 'units': '-'}
ncVARS['clm']['sotype'] = {
    'dims': ('x'), 'long_name': 'soil type', 'units': '-'}
ncVARS['clm']['sdor'] = {
    'dims': ('x'), 'long_name': 'Standard deviation of orography', 'units': '-'}
ncVARS['clm']['sdfor'] = {
    'dims': ('x'), 'long_name': 'Standard deviation of filtered orography', 'units': '-'}
ncVARS['clm']['RDBEDROCK'] = {
    'dims': ('x'), 'long_name': 'Depth to bedrock', 'units': 'm',
    'comment': 'Optional (LEBEDROCKLIM); falls back to a flat 100m default if absent. '
               'See init_clim/add_bedrock_wtd_fields.py -- not part of the plain MARS/GRIB '
               'clim.sh pipeline above, since depth-to-bedrock is not a climate.v021 field.'}
ncVARS['clm']['sst'] = {'dims': (
    'x'), 'long_name': 'sea surface temperature', 'units': 'K', 'dflt': 280.}
ncVARS['clm']['glacierMask'] = {
    'dims': ('x'), 'long_name': 'land ice mask', 'units': '-', 'dflt': 0.}
ncVARS['clm']['LDEPTH'] = {
    'dims': ('x'), 'long_name': 'Lake Depth', 'units': 'm'}
ncVARS['clm']['CLAKE'] = {
    'dims': ('x'), 'long_name': 'LAKE COVER', 'units': '-'}
ncVARS['clm']['cu'] = {
    'dims': ('x'), 'long_name': 'urban cover', 'units': '-'}
ncVARS['clm']['Ctype'] = {
    'dims': ('x'), 'long_name': 'C3/C4 photosynthesis pathway', 'units': '-'}
ncVARS['clm']['glm'] = {
    'dims': ('x'), 'long_name': 'Glacier Mask', 'units': '-'}
ncVARS['clm']['par_avg'] = {
    'dims': ('month','x'), 'long_name': 'Average PAR', 'units': 'W/m2'}
ncVARS['clm']['ISOP_EP'] = {
    'dims': ('x'), 'long_name': 'Isoprene Emission potential', 'units': 'ug/m2/hour'}
ncVARS['veg']['Mlail'] = {
    'dims': ('month', 'x'), 'long_name': 'Monthly LAI low veg', 'units': 'm2/m2'}
ncVARS['veg']['Mlaih'] = {
    'dims': ('month', 'x'), 'long_name': 'Monthly LAI high veg', 'units': 'm2/m2'}
ncVARS['veg']['Mask'] = {'dims': (
    'x'), 'long_name': 'Mask', 'units': '-', 'comment': '1==run model', 'dtype': 'i4', 'dflt': 0}
ncVARS['veg']['cvl'] = {
    'dims': ('x'), 'long_name': 'low vegetation cover', 'units': '-'}
ncVARS['veg']['cvh'] = {
    'dims': ('x'), 'long_name': 'hight vegetation cover', 'units': '-'}
ncVARS['veg']['tvl'] = {'dims': (
    'x'), 'long_name': 'type of low vegetation', 'units': '-', 'dtype': 'i4'}
ncVARS['veg']['tvh'] = {
    'dims': ('x'), 'long_name': 'type of hight vegetation', 'units': '-'}
ncVARS['veg']['landsea'] = {
    'dims': ('x'), 'long_name': 'Land Sea Mask', 'units': '-'}
ncVARS['veg']['CLAKE'] = {
    'dims': ('x'), 'long_name': 'LAKE COVER', 'units': '-'}

gb2NC = {}
gb2NC['lsm'] = {'ncName': 'landsea'}
gb2NC['cl'] = {'ncName': 'CLAKE'}
gb2NC['sr'] = {'ncName': 'z0m'}
gb2NC['lsrh'] = {'ncName': 'lz0h'}
gb2NC['z'] = {'ncName': 'geopot'}
gb2NC['slt'] = {'ncName': 'sotype'}
gb2NC['dl'] = {'ncName': 'LDEPTH'}
gb2NC['al'] = {'ncName': 'Malbedo', 'klev': 'month'}
gb2NC['cwe'] = {'ncName': 'fwet', 'klev': 'month'}
gb2NC['cur'] = {'ncName': 'cu'}
gb2NC['lai_lv'] = {'ncName': 'Mlail', 'klev': 'month'}
gb2NC['lai_hv'] = {'ncName': 'Mlaih', 'klev': 'month'}

gb2NC['swvl1'] = {'ncName': 'SoilMoist', 'klev': 1, 'lmin': 0.01, 'lmax': 1.}
gb2NC['swvl2'] = {'ncName': 'SoilMoist', 'klev': 2, 'lmin': 0.01, 'lmax': 1.}
gb2NC['swvl3'] = {'ncName': 'SoilMoist', 'klev': 3, 'lmin': 0.01, 'lmax': 1.}
gb2NC['swvl4'] = {'ncName': 'SoilMoist', 'klev': 4, 'lmin': 0.01, 'lmax': 1.}

gb2NC['sdml']  = {'ncName': 'SWEML',  'lmin': 0.}
gb2NC['rsnml'] = {'ncName': 'snowdensML'        }
gb2NC['tsnml'] = {'ncName': 'SnowTML'           }
gb2NC['lwcsml'] = {'ncName': 'slwML', 'lmin': 0.}

gb2NC['stl1'] = {'ncName': 'SoilTemp', 'klev': 1}
gb2NC['stl2'] = {'ncName': 'SoilTemp', 'klev': 2}
gb2NC['stl3'] = {'ncName': 'SoilTemp', 'klev': 3}
gb2NC['stl4'] = {'ncName': 'SoilTemp', 'klev': 4}
gb2NC['istl1'] = {'ncName': 'iceTemp', 'klev': 1}
gb2NC['istl2'] = {'ncName': 'iceTemp', 'klev': 2}
gb2NC['istl3'] = {'ncName': 'iceTemp', 'klev': 3}
gb2NC['istl4'] = {'ncName': 'iceTemp', 'klev': 4}
gb2NC['skt'] = {'ncName': 'AvgSurfT'}
gb2NC['asn'] = {'ncName': 'SAlbedo'}
gb2NC['rsn'] = {'ncName': 'snowdens'}
gb2NC['sd'] = {'ncName': 'SWE', 'mfac': 1000., 'lmin': 0.}
gb2NC['tsn'] = {'ncName': 'SnowT'}
gb2NC['lmlt'] = {'ncName': 'TLWML'}
gb2NC['lmld'] = {'ncName': 'HLML'}
gb2NC['lblt'] = {'ncName': 'TLBOT'}
gb2NC['ltlt'] = {'ncName': 'TLMNW'}
gb2NC['lshf'] = {'ncName': 'TLSF'}
gb2NC['lict'] = {'ncName': 'TLICE'}
gb2NC['licd'] = {'ncName': 'HLICE'}
gb2NC['src'] = {'ncName': 'CanopInt', 'mfac': 1000., 'lmin': 0.}
gb2NC['lsmgrd'] = {'ncName': 'Ctype'}
gb2NC['glm']={'ncName':'glacierMask'}
gb2NC['paravg'] = {'ncName': 'par_avg', 'klev': 'month'}
gb2NC['ISOP_EP'] = {'ncName': 'ISOP_EP'}

# gb2NC['ci']={'ncName':'seaice'}


def gen_file(FOUT=None, FTYPE=None, ginfo=None, nlevs=4, nlevsn=1, nmonth=12):

    print("Generating:", FOUT)
    os.system(' rm -f ' + FOUT)

    ncfile = Dataset(FOUT, mode='w', format='NETCDF4')
    ncfile.history = 'Created ' + time.ctime(time.time())

    # dimensions
    ncfile.createDimension('x', ginfo['nptot'])
    # ncfile.createDimension('y',1)
    ncfile.createDimension('nv', 4)
    ncfile.createDimension('nlevs', nlevs)
    ncfile.createDimension('nlevsn', nlevsn)
    ncfile.createDimension('month', nmonth)

    # grid variables:
    cvar = ncfile.createVariable('lat', 'f8', ('x'))
    cvar.long_name = 'latitude'
    cvar.standard_name = 'latitude'
    cvar.units = 'degrees_north'
    cvar._CoordinateAxisType = "Lat"
    cvar.bounds = 'lat_bnds'
    cvar[:] = ginfo['lat']

    cvar = ncfile.createVariable('lon', 'f8', ('x'))
    cvar.long_name = 'longitude'
    cvar.standard_name = 'longitude'
    cvar.units = 'degrees_east'
    cvar._CoordinateAxisType = "Lon"
    cvar.bounds = 'lon_bnds'
    cvar[:] = ginfo['lon']
    cvar = ncfile.createVariable('x', 'i4', ('x',))
    cvar.long_name = 'Gaussian grid points 1-npoints'
    cvar.standard_name = 'Gaussian grid points 1-npoints'
    cvar.units = '-'
    cvar[:] = np.arange(ginfo['nptot']) + 1

    # cvar=ncfile.createVariable('lat_bnds','f8',('x','nv'),zlib=True,complevel=6)
    #cvar.units = 'degrees_north'
    #cvar[:] = ginfo['lat_bnds']

    # cvar=ncfile.createVariable('lon_bnds','f8',('x','nv'),zlib=True,complevel=6)
    #cvar.units = 'degrees_east'
    #cvar[:] = ginfo['lon_bnds']


    cvar = ncfile.createVariable(
        'cell_area', 'f8', ('x'), zlib=True, complevel=6)
    cvar.long_name = 'area of grid cell'
    cvar.standard_name = 'area'
    cvar.units = 'm2'
    cvar.coordinates = 'lat lon'
    cvar[:] = ginfo['area']

    if FTYPE == 'clm' or FTYPE == 'veg':
        cvar = ncfile.createVariable('month', 'f4', ('month',))
        cvar.long_name = 'month'
        cvar.units = 'months since 2000-01-01'
        ncfile.variables['month'][:] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    for cv, val in ncVARS[FTYPE].items():
        try:
            dd = val['dtype']
        except:
            dd = 'f4'
        # print cv,dd,val
        cvar = ncfile.createVariable(
            cv, dd, val['dims'], zlib=True, complevel=6)
        for kk in val.keys():
            if kk in ['dims', 'dtype', 'dflt']:
                continue
            setattr(cvar, kk, val[kk])
        try:
            f = val['dflt']
            cvar[:] = f
        except:
            pass

    ncfile.close()



def _as_tuple_dims(dims):
    """Return a NetCDF dimension tuple; old table sometimes uses ('x') which is a string."""
    if isinstance(dims, str):
        return (dims,)
    return tuple(dims)


def _dims_x_to_latlon(dims):
    """Convert ecLand compact x dimensions to regular lat/lon dimensions."""
    out = []
    for d in _as_tuple_dims(dims):
        if d == 'x':
            out.extend(['lat', 'lon'])
        else:
            out.append(d)
    return tuple(out)


def gen_file_LL(FOUT=None, FTYPE=None, lat=None, lon=None, ginfo=None, nlevs=4, nlevsn=1, nmonth=12):
    """Generate ecLand surfclim/soilinit on a regular latitude-longitude grid.

    This is the 2-D equivalent of gen_file(). Variables that normally use x are
    created as (lat, lon), (nlevs, lat, lon), or (month, lat, lon).
    """
    print("Generating regular lat/lon:", FOUT)
    os.system(' rm -f ' + FOUT)

    if lat is None or lon is None:
        if ginfo is None:
            raise ValueError("Either lat/lon or ginfo must be supplied to gen_file_LL")
        lat1d = np.asarray(ginfo['lat'])
        lon1d = np.asarray(ginfo['lon'])
        lat = np.unique(lat1d)
        lon = np.unique(lon1d)
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    nlat = lat.size
    nlon = lon.size

    ncfile = Dataset(FOUT, mode='w', format='NETCDF4')
    ncfile.history = 'Created ' + time.ctime(time.time()) + ' on regular lat/lon grid'

    ncfile.createDimension('lat', nlat)
    ncfile.createDimension('lon', nlon)
    ncfile.createDimension('nv', 4)
    ncfile.createDimension('nlevs', nlevs)
    ncfile.createDimension('nlevsn', nlevsn)
    ncfile.createDimension('month', nmonth)

    cvar = ncfile.createVariable('lat', 'f8', ('lat',))
    cvar.long_name = 'Latitude'
    cvar.standard_name = 'latitude'
    cvar.units = 'degrees_north'
    cvar.axis = 'Y'
    cvar[:] = lat

    cvar = ncfile.createVariable('lon', 'f8', ('lon',))
    cvar.long_name = 'Longitude'
    cvar.standard_name = 'longitude'
    cvar.units = 'degrees_east'
    cvar.axis = 'X'
    cvar[:] = lon

    cvar = ncfile.createVariable('cell_area', 'f8', ('lat','lon'), zlib=True, complevel=6)
    cvar.long_name = 'area of grid cell'
    cvar.standard_name = 'area'
    cvar.units = 'm2'
    cvar.coordinates = 'lat lon'
    if ginfo is not None and 'area' in ginfo and len(ginfo['area']) == nlat*nlon:
        # GRIB/MARS area ordering is normally north-to-south. If target latitude is
        # south-to-north, flip in latitude to match the NetCDF coordinate order.
        area2d = np.asarray(ginfo['area']).reshape(nlat, nlon)
        if lat[0] < lat[-1]:
            area2d = area2d[::-1, :]
        cvar[:] = area2d
    else:
        cvar[:] = 0.0

    if FTYPE == 'clm' or FTYPE == 'veg':
        cvar = ncfile.createVariable('month', 'f4', ('month',))
        cvar.long_name = 'month'
        cvar.units = 'months since 2000-01-01'
        cvar[:] = np.arange(nmonth, dtype='f4')

    for cv, val in ncVARS[FTYPE].items():
        dd = val.get('dtype', 'f4')
        dims = _dims_x_to_latlon(val['dims'])
        cvar = ncfile.createVariable(cv, dd, dims, zlib=True, complevel=6)
        for kk in val.keys():
            if kk in ['dims', 'dtype', 'dflt']:
                continue
            setattr(cvar, kk, val[kk])
        if 'dflt' in val:
            cvar[:] = val['dflt']

    ncfile.close()

def fix_snow_ml(nc):
    """Make multilayer snow state finite and consistent with bulk snow fields.

    The ecLand output writer uses SWEML, snowdensML, SnowTML and slwML
    directly. Missing multilayer values can therefore trigger floating-point
    exceptions even when the corresponding bulk SWE/snow-density/temperature
    fields are valid.

    For a one-layer setup, the bulk snow state is copied into layer 1. For
    multiple layers, all bulk SWE is placed in layer 1 and the remaining
    layers are initialized snow-free. Existing finite multilayer values are
    preserved unless an entire SWEML column is missing.
    """
    required = (
        'SWE', 'snowdens', 'SnowT',
        'SWEML', 'snowdensML', 'SnowTML', 'slwML',
    )
    if not all(name in nc.variables for name in required):
        return

    swe = np.ma.filled(nc.variables['SWE'][:], 0.0).astype(np.float64)
    rho = np.ma.filled(nc.variables['snowdens'][:], 100.0).astype(np.float64)
    tsn = np.ma.filled(nc.variables['SnowT'][:], 273.16).astype(np.float64)

    swe = np.where(np.isfinite(swe) & (swe > 0.0), swe, 0.0)
    rho = np.where(np.isfinite(rho) & (rho > 0.0), rho, 100.0)
    tsn = np.where(np.isfinite(tsn), np.minimum(tsn, 273.16), 273.16)

    sweml = np.ma.filled(nc.variables['SWEML'][:], np.nan).astype(np.float64)
    rhoml = np.ma.filled(nc.variables['snowdensML'][:], np.nan).astype(np.float64)
    tsnml = np.ma.filled(nc.variables['SnowTML'][:], np.nan).astype(np.float64)
    slwml = np.ma.filled(nc.variables['slwML'][:], np.nan).astype(np.float64)

    # SWEML has dimensions (nlevsn, spatial dimensions...).  If the entire
    # multilayer column is missing at a grid point, initialize it from bulk SWE.
    missing_column = ~np.any(np.isfinite(sweml), axis=0)
    if np.any(missing_column):
        sweml[:, missing_column] = 0.0
        sweml[0, missing_column] = swe[missing_column]

    # Repair any remaining invalid/negative layer SWE without altering valid data.
    bad_swe = ~np.isfinite(sweml) | (sweml < 0.0)
    sweml[bad_swe] = 0.0

    # Density must always be strictly positive because WRTPCDF divides by it.
    bad_rho = ~np.isfinite(rhoml) | (rhoml <= 0.0)
    if np.any(bad_rho):
        for lev in range(rhoml.shape[0]):
            fallback = rho if lev == 0 else np.full_like(rho, 100.0)
            rhoml[lev] = np.where(bad_rho[lev], fallback, rhoml[lev])

    # Initialize missing layer temperatures from bulk snow temperature in layer 1
    # and from the melting point in otherwise snow-free deeper layers.
    bad_tsn = ~np.isfinite(tsnml)
    if np.any(bad_tsn):
        for lev in range(tsnml.shape[0]):
            fallback = tsn if lev == 0 else np.full_like(tsn, 273.16)
            tsnml[lev] = np.where(bad_tsn[lev], fallback, tsnml[lev])
    tsnml = np.minimum(tsnml, 273.16)

    # Start missing liquid-water content at zero and enforce non-negativity.
    bad_slw = ~np.isfinite(slwml) | (slwml < 0.0)
    slwml[bad_slw] = 0.0

    nc.variables['SWEML'][:] = sweml.astype(nc.variables['SWEML'].dtype)
    nc.variables['snowdensML'][:] = rhoml.astype(nc.variables['snowdensML'].dtype)
    nc.variables['SnowTML'][:] = tsnml.astype(nc.variables['SnowTML'].dtype)
    nc.variables['slwML'][:] = slwml.astype(nc.variables['slwML'].dtype)

    print('Snow ML consistency fixes:')
    print('  initialized missing SWEML columns:', int(np.count_nonzero(missing_column)))
    print('  repaired invalid SWEML values:', int(np.count_nonzero(bad_swe)))
    print('  repaired invalid snowdensML values:', int(np.count_nonzero(bad_rho)))
    print('  repaired invalid SnowTML values:', int(np.count_nonzero(bad_tsn)))
    print('  repaired invalid slwML values:', int(np.count_nonzero(bad_slw)))


def grib2nc(FNC, FGRB, LEXTENDSOIL=False,LSNML=False,gpoints=None):
    print("Reading:", FGRB)
    print("Writting to:", FNC)
    nc = Dataset(FNC, 'r+')
    grb = open(FGRB)

    ifld = 0
    while 1:
        gid = ec.codes_grib_new_from_file(grb)
        if gid is None:
            break
        ifld = ifld + 1
        sname = ec.codes_get(gid, 'shortName')
        gribid = ec.codes_get(gid, 'param')
        # exception for paravg
        if gribid == 212250:
          sname='paravg'
        if gribid == 212251:
          sname='ISOP_EP'
        kmm = ec.codes_get(gid, 'month')
        lev=None
        if (LSNML) & (ec.codes_get(gid, 'typeOfLevel')=='snowLayer'):
          sname=sname+'ml'
          lev=ec.codes_get(gid, 'level')

        klev = None
        mfac = 1
        lmin = -1.e20
        lmax = 1.e20
        ncName = None
        if sname in gb2NC:
            ncName = gb2NC[sname]['ncName']
            if 'klev' in gb2NC[sname]:
                klev = gb2NC[sname]['klev']
            else:
                klev = None
            if lev is not None:
              klev = lev
            if 'mfac' in gb2NC[sname]:
                mfac = gb2NC[sname]['mfac']
            if 'lmin' in gb2NC[sname]:
                lmin = gb2NC[sname]['lmin']
            if 'lmax' in gb2NC[sname]:
                lmax = gb2NC[sname]['lmax']
        else:
            if sname in nc.variables.keys():
                ncName = sname

        print(ifld, sname, ncName, klev, mfac, kmm)

        if ncName is not None:
            xdata = ec.codes_get_array(gid, 'values')
            if (np.any(xdata==9999)):
              xdata =xdata[xdata!=9999]
            xdata = np.maximum(lmin, np.minimum(lmax, xdata * mfac))
            if klev is None:
                nc.variables[ncName][:] = xdata
            elif klev == 'month':
                nc.variables[ncName][kmm - 1, :] = xdata
            else:
                nc.variables[ncName][klev - 1, :] = xdata

        ec.codes_release(gid)

    if LEXTENDSOIL:
        rIN = np.array([0.07, 0.21, .72, 1.89])
        if len(nc.dimensions['nlevs']) == 9:
            rOUT = np.array([0.01, 0.02, 0.04, 0.08, 0.1, 0.25, .50, 1, 1])
        elif len(nc.dimensions['nlevs']) == 10:
            rOUT = np.array([0.01, 0.02, 0.04, 0.09, 0.12, 0.3, .42, 1, 2, 4])
        zremap = compute_remap(rIN, rOUT)
        print(zremap)
        for cvar in ['SoilMoist', 'SoilTemp', 'iceTemp']:
            xin = nc.variables[cvar][:]
            xout = np.dot(zremap, xin[0:len(rIN), :])  # xin.copy()
            # for il in range(len(rOUT)):
            #xout[il,:] = np.sum(zremap[il:il+1,:].T*xin[0:len(rIN),:],axis=0)
            nc.variables[cvar][:] = xout

    fix_snow_ml(nc)

    nc.close()
    grb.close()


def grib2nc_LL(FNC, FGRB, LEXTENDSOIL=False, LSNML=False, gpoints=None, nlat=None, nlon=None, flip_lat=True):
    """Read GRIB fields into a regular lat/lon NetCDF file made by gen_file_LL().

    Assumes GRIB values are ordered west-to-east, north-to-south for a MARS area
    request. If the NetCDF latitude coordinate is south-to-north, use flip_lat=True.
    """
    print("Reading:", FGRB)
    print("Writting to:", FNC)
    if nlat is None or nlon is None:
        raise ValueError("nlat and nlon must be provided to grib2nc_LL")

    nc = Dataset(FNC, 'r+')
    grb = open(FGRB, 'rb')

    ifld = 0
    while 1:
        gid = ec.codes_grib_new_from_file(grb)
        if gid is None:
            break
        ifld += 1
        sname = ec.codes_get(gid, 'shortName')
        gribid = ec.codes_get(gid, 'param')
        if gribid == 212250:
            sname = 'paravg'
        if gribid == 212251:
            sname = 'ISOP_EP'

        try:
            kmm = ec.codes_get(gid, 'month')
        except Exception:
            kmm = 1

        lev = None
        if LSNML and ec.codes_get(gid, 'typeOfLevel') == 'snowLayer':
            sname = sname + 'ml'
            lev = ec.codes_get(gid, 'level')

        klev = None
        mfac = 1.0
        lmin = -1.e20
        lmax = 1.e20
        ncName = None
        if sname in gb2NC:
            ncName = gb2NC[sname]['ncName']
            klev = gb2NC[sname].get('klev', None)
            if lev is not None:
                klev = lev
            mfac = gb2NC[sname].get('mfac', 1.0)
            lmin = gb2NC[sname].get('lmin', -1.e20)
            lmax = gb2NC[sname].get('lmax', 1.e20)
        elif sname in nc.variables.keys():
            ncName = sname

        print(ifld, sname, ncName, klev, mfac, kmm)

        if ncName is not None:
            xdata = ec.codes_get_values(gid)
            xdata = np.asarray(xdata, dtype='f8')
            if gpoints is not None:
                xdata = xdata[gpoints-1]
            if xdata.size != nlat*nlon:
                raise ValueError("%s has %d points, expected %d" % (sname, xdata.size, nlat*nlon))

            xdata[xdata == 9999] = np.nan
            xdata[np.abs(xdata) > 0.9e20] = np.nan
            xdata = np.maximum(lmin, np.minimum(lmax, xdata * mfac))
            x2d = xdata.reshape((nlat, nlon))
            if flip_lat:
                x2d = x2d[::-1, :]

            if klev is None:
                if ncName == 'sotype':
                    x2d[x2d == 0] = 3  # avoid seg faults if sotype==0
                nc.variables[ncName][:, :] = x2d
            elif klev == 'month':
                nc.variables[ncName][int(kmm) - 1, :, :] = x2d
            else:
                nc.variables[ncName][int(klev) - 1, :, :] = x2d

        ec.codes_release(gid)

    if LEXTENDSOIL:
        rIN = np.array([0.07, 0.21, .72, 1.89])
        if len(nc.dimensions['nlevs']) == 9:
            rOUT = np.array([0.01, 0.02, 0.04, 0.08, 0.1, 0.25, .50, 1, 1])
        elif len(nc.dimensions['nlevs']) == 10:
            rOUT = np.array([0.01, 0.02, 0.04, 0.09, 0.12, 0.3, .42, 1, 2, 4])
        zremap = compute_remap(rIN, rOUT)
        for cvar in ['SoilMoist', 'SoilTemp', 'iceTemp']:
            xin = nc.variables[cvar][:]
            xout = np.tensordot(zremap, xin[0:len(rIN), :, :], axes=(1, 0))
            nc.variables[cvar][:] = xout

    # For regular lat/lon surfclim files, activate exactly the land points.
    # Mask=1 means that ecLand runs at that grid point.
    # Final consistency fixes for regular lat/lon surfclim files.
    if 'landsea' in nc.variables:
        landsea = np.ma.filled(nc.variables['landsea'][:], 0.0)
        active = np.isfinite(landsea) & (landsea > 0.5)

        if 'Mask' in nc.variables:
            nc.variables['Mask'][:] = active.astype(np.int32)

        # Some climate bundles do not provide sdfor on every grid.
        # Use sdor as a finite fallback.
        if 'sdfor' in nc.variables and 'sdor' in nc.variables:
            sdfor = np.ma.filled(nc.variables['sdfor'][:], np.nan)
            sdor = np.ma.filled(nc.variables['sdor'][:], 0.0)

            bad = ~np.isfinite(sdfor)
            sdfor[bad] = sdor[bad]
            nc.variables['sdfor'][:] = sdfor.astype(np.float32)

            print("sdfor values replaced from sdor:", int(bad.sum()))

        # glm and glacierMask represent the glacier mask in this setup.
        if 'glm' in nc.variables and 'glacierMask' in nc.variables:
            glm = np.ma.filled(nc.variables['glm'][:], np.nan)
            glacier = np.ma.filled(
                nc.variables['glacierMask'][:],
                0.0,
            )

            bad = ~np.isfinite(glm)
            glm[bad] = glacier[bad]
            nc.variables['glm'][:] = glm.astype(np.float32)

            print("glm values replaced from glacierMask:", int(bad.sum()))

        if 'tvl' in nc.variables and 'tvh' in nc.variables:
            tvl = np.ma.filled(nc.variables['tvl'][:], 1)
            tvh = np.ma.filled(nc.variables['tvh'][:], np.nan)

            bad_tvl = ~np.isfinite(tvl) | (tvl < 1) | (tvl > 20)
            tvl[bad_tvl] = 1

            bad_tvh = ~np.isfinite(tvh) | (tvh < 1) | (tvh > 20)
            tvh[bad_tvh] = tvl[bad_tvh]

            nc.variables['tvl'][:] = np.rint(tvl).astype(np.int32)
            nc.variables['tvh'][:] = np.rint(tvh).astype(np.float32)

            print("Invalid tvl repaired:", int(bad_tvl.sum()))
            print("Invalid tvh repaired:", int(bad_tvh.sum()))

        print(
            "Updated Mask from landsea > 0.5:",
            int(active.sum()),
            "active points out of",
            active.size,
        )

    fix_snow_ml(nc)

    nc.close()
    grb.close()


def get_mask(FIN, LLAND, LLAKE, LOCEAN, BBOX):
    nc = Dataset(FIN, 'r')
    lsm = nc.variables['landsea'][:]
    clake = nc.variables['CLAKE'][:]
    lat = nc.variables['lat'][:]
    lon = nc.variables['lon'][:]
    lon[lon > 180.] = lon[lon > 180.] - 360.

    LDLAND = lsm > 0.5
    LDLAKE = clake > 0.5 * (1 - lsm)
    LDLAKE_RESOL = clake > 0.5
    LDOCEAN = (lsm <= 0.5) & (~LDLAKE)
    LDREG = ((lon >= BBOX[0]) & (lon <= BBOX[1]) &
             (lat >= BBOX[2]) & (lat <= BBOX[3]))

    LDMASK = LDREG & (LDLAND * LLAND | LDLAKE * LLAKE | LDOCEAN * LOCEAN)
    print("NPTOT:", lsm.size)
    print("NPLAND:", np.sum(LDLAND))
    print("NPLAKE:", np.sum(LDLAKE))
    print("NPLAKE_RESOL:", np.sum(LDLAKE_RESOL))
    print("NPOCEAN:", np.sum(LDOCEAN))
    print("NPREG:", np.sum(LDREG))
    print("NPMASK:", np.sum(LDMASK))

    return LDMASK


def cut_mask(mask, FIN, FOUT):

    NPTOT = np.sum(mask)
    print("Generating:", FOUT, NPTOT)
    os.system(' rm -f ' + FOUT)
    ncOUT = Dataset(FOUT, mode='w', format='NETCDF4')
    ncOUT.history = 'Created ' + time.ctime(time.time()) + 'based on' + FIN

    ncIN = Dataset(FIN, 'r')

    # copy dimensions
    for cdim in ncIN.dimensions.keys():
        if ncIN.dimensions[cdim].isunlimited():
            dlen = None
        else:
            dlen = len(ncIN.dimensions[cdim])
        if cdim == 'x':
            dlen = NPTOT
        ncOUT.createDimension(cdim, dlen)

    for vname, varin in ncIN.variables.items():
        vtype = varin.dtype
        vdim = varin.dimensions
        vfill = None
        zlib = True
        complevel = 6
        if hasattr(varin, '_FillValue'):
            vfill = varin._FillValue
        # if hasattr(varin,'_Shuffle'):
            #zlib = True
        # if hasattr(varin,'_DeflateLevel'):
            #complevel = getattr(varin,'_DeflateLevel')
        print(vname, vtype, vdim, vfill, zlib, complevel)
        cdfvar = ncOUT.createVariable(vname, vtype, vdim, fill_value=vfill,
                                      zlib=zlib, complevel=complevel)

        # copy attributes
        for catt in varin.ncattrs():
            if catt == '_FillValue':
                continue
            ccat = getattr(varin, catt)
            setattr(cdfvar, catt, ccat)

        xIN = ncIN.variables[vname][:]
        ndim = xIN.ndim
        if ndim == mask.ndim and cdfvar.size == NPTOT:
            cdfvar[:] = xIN[mask]
        elif ndim == mask.ndim + 1:
            cdfvar[:] = xIN[:, mask]
        elif (ndim == mask.ndim - 1) and (cdfvar.size == NPTOT):
            cdfvar[:] = xIN[mask.squeeze()]

    ncOUT.close()
    ncIN.close()


def compute_remap(rIN, rOUT):
    # rOUT=np.array([0.07,0.21,.72,1.89])
    # rIN=np.array([0.01,0.02,0.04,0.08,0.1,0.25,.50,1,1])

    dIN = np.concatenate([[0.], np.cumsum(rIN)])
    dOUT = np.concatenate([[0.], np.cumsum(rOUT)])

    dmax = np.maximum(dIN[-1], dOUT[-1])
    # dIN[-1]=dmax
    # dOUT[-1]=dmax

    nOUT = len(rOUT)
    nIN = len(rIN)
    zremap = np.zeros((nOUT, nIN))
    for jk in range(1, nOUT + 1):
        z1 = np.maximum(dOUT[jk - 1], dIN[0:-1])
        z2 = np.minimum(dOUT[jk], dIN[1:])
        zremap[jk - 1, :] = np.maximum(0, z2 - z1)
        # print jk,z1,z2,zremap[jk-1,:]

    for jk in range(nOUT):
        zz = np.sum(zremap[jk, :], axis=0)
        if zz != 0:
            zremap[jk, :] = zremap[jk, :] / np.sum(zremap[jk, :], axis=0)
        else:
            zremap[jk, -1] = 1
    print(zremap)
    return zremap


def adjust_glacier_sd(FIN='sd.grb',FIN_RSN='rsn.grb',FGL='cicecap',FOUT='sd_new.grb',LGLACIERINI="false", ISMLIN=False, NREP=5):
  # Those two parameters can be input to the function to have more flexibility
  # if the setup changes in the future
  snowDepthGlacier=np.array([0.50, 0.50, 0.50, 0.50, 0.0]) # Last layer is set to 0.0 as it is used as accumulation layer

  if LGLACIERINI == 'false':
      LGLACIERINI = False
  else:
      LGLACIERINI = True

# Read FIN, FIN_RSN and FGL
  fin      = open(FIN,'rb')
  finDens  = open(FIN_RSN,'rb')
  fglac    = open(FGL,'rb')
  # Use fin as a template for the output file
  ftemp    = open(FIN,'rb')
  gidTEMP  = ec.codes_grib_new_from_file(ftemp)
  # Read metadata
  NPTOT = ec.codes_get(gidTEMP,'numberOfPoints')

  if ISMLIN:
      levSD = NREP
      snowMassGlacier=10000.0
  else:
      levSD = 1
      snowMassGlacier=10.0

  # Create output file
  fout   = open(FOUT,'wb')

  # Start
  gidGlacier  = ec.codes_grib_new_from_file(fglac)
  cicecap = ec.codes_get_values(gidGlacier)
  sd_in   = np.zeros((NPTOT, levSD))
  rsn_in  = np.zeros((NPTOT, levSD))
  sd_out  = np.zeros((NPTOT, levSD))
  #depth   = np.zeros((NPTOT, levSD))
  for jk in range(levSD):
      gidIn        = ec.codes_grib_new_from_file(fin)
      gidInDens    = ec.codes_grib_new_from_file(finDens)
      sd_in[:,jk]  = ec.codes_get_values(gidIn)
      rsn_in[:,jk] = ec.codes_get_values(gidInDens)
      ec.codes_release(gidIn)
      ec.codes_release(gidInDens)


  #*LGLACIERINI - true:  SD == 0 over fully resolved glaciers, let the model accumulate the snow mass.
  #*            - false: SD == SD initial conditions everywhere but fully-resolved glacier points set to 1500 kg/m2
  if LGLACIERINI:
      seasSnowFact=1.0
      glacSnowFact=0.0
  else:
      seasSnowFact=1.0
      glacSnowFact=1.0

  if levSD > 1:
    for jk in range(levSD):
        sd_out[:,jk] = sd_in[:,jk]*seasSnowFact*(cicecap < 0.99)+glacSnowFact*(0.50*rsn_in[:,jk])*(cicecap >= 0.99)
    # compute now the accumulation layer as residual between the snowMassGlacier and the snow mass in the levSD-1 layers
    sdtot=np.sum(sd_out[:,0:levSD-1],axis=1)
    sd_out[:,levSD-1] = sd_out[:,levSD-1]*(cicecap < 0.99) + (snowMassGlacier-sdtot)*(cicecap >= 0.99)
  else:
    sd_out[:,0] = sd_in[:,0]*seasSnowFact*(cicecap < 0.99)+glacSnowFact*snowMassGlacier*(cicecap >= 0.99)


  # Release unesed codes
  ec.codes_release(gidGlacier)

  # Write first snow depth
  for jk in range(levSD):
    gidOut   = ec.codes_clone(gidTEMP)

    ec.codes_set_values(gidOut,sd_out[:,jk])

    # Write and release for next jk
    ec.codes_write(gidOut,fout)
    ec.codes_release(gidOut)
    # This trick is used to avoid the creation of a new gid for each layer and
    # setting metadata
    # but using always the same but pointing at different levels
    if jk < levSD-1:
      ec.codes_release(gidTEMP)
      gidTEMP = ec.codes_grib_new_from_file(ftemp)

