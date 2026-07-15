#!/usr/bin/env bash
set -euo pipefail

module load nco
module load pproc/1.4.0.0

BASEDIR=${BASEDIR:-/perm/pad/liaise/init_clim}
WORKDIR=${WORKDIR:-/perm/pad/liaise/init_clim/work}
OUTDIR=${FINAL_OUTDIR:-/perm/pad/liaise/init_clim/output}

DATE=${DATE:-19800101}
TIME=${TIME:-00}

RES=${RES:-399_4}
CLIM_ROOT=${CLIM_ROOT:-/home/rdx/data/climate/climate.v021/${RES}}
FORCING_TEMPLATE=${FORCING_TEMPLATE:-/perm/pad/liaise/forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_2014.nc}

# LIAISE WFDE5 0.5 degree grid. MARS area order is N/W/S/E.
TARGET_GRID=${TARGET_GRID:-0.5/0.5}
TARGET_AREA=${TARGET_AREA:-46.75/-5.75/39.25/5.25}
NLAT=${NLAT:-16}
NLON=${NLON:-23}

mkdir -p "$WORKDIR" "$OUTDIR"
cd "$WORKDIR"

# ------------------------------------------------------------
# 1. Make clim.grb on native climate.v021 grid, then remap to LIAISE grid
# ------------------------------------------------------------
bash "$BASEDIR/clim.sh"
mv -f clim.grb clim_native.grb

pproc-interpol \
  --grid="$TARGET_GRID" \
  --area="$TARGET_AREA" \
  --interpolation=nn \
  clim_native.grb clim.grb

# ------------------------------------------------------------
# 2. Retrieve ERA5 initial state directly on LIAISE grid
# ------------------------------------------------------------
rm -f init_0.grb init.grb mars_retrieve_init

cat > mars_retrieve_init << EOF_MARS
retrieve,
  stream=oper,
  class=ea,
  expver=1,
  date=${DATE},
  time=${TIME},
  type=an,
  levtype=sfc,
  accuracy=av,
  grid=${TARGET_GRID},
  area=${TARGET_AREA},
  param=SWVL1/SWVL2/SWVL3/SWVL4/STL1/STL2/STL3/STL4/SKT/ASN/RSN/SD/TSN/SRC/ISTL1/ISTL2/ISTL3/ISTL4/CI/8.228/9.228/10.228/11.228/12.228/13.228/14.228,
  target="init_0.grb"
EOF_MARS

mars -p mars_retrieve_init

# Fix lake-cover shortName if present.
grib_set -w shortName=cl -s shortName=ci init_0.grb init.grb

# ------------------------------------------------------------
# 3. Glacier snow-depth correction and glacier mask on the same LIAISE grid
# ------------------------------------------------------------
rm -f all_but_sd.grb sd.grb rsn.grb sd_new.grb glacierMask
rm -f fcicecap cicecap cicecap_native

cp "$CLIM_ROOT/cicecap" cicecap_native

pproc-interpol \
  --grid="$TARGET_GRID" \
  --area="$TARGET_AREA" \
  --interpolation=nn \
  cicecap_native fcicecap

grib_copy -w paramId=207 fcicecap cicecap

grib_copy -w shortName!=sd init.grb all_but_sd.grb
grib_copy -w shortName=sd,typeOfLevel=surface init.grb sd.grb
grib_copy -w shortName=rsn,typeOfLevel=surface init.grb rsn.grb

PYTHONPATH="$BASEDIR:${PYTHONPATH:-}" python3 << 'PY'
from init_clim import *

adjust_glacier_sd(
    FIN="sd.grb",
    FIN_RSN="rsn.grb",
    FGL="cicecap",
    FOUT="sd_new.grb",
    LGLACIERINI="false",
    ISMLIN=False,
    NREP=1,
)
PY

cat sd_new.grb >> all_but_sd.grb
mv -f all_but_sd.grb init.grb

grib_set \
  -s paramId=260294,typeOfLevel=surface,typeOfFirstFixedSurface=1,scaledValueOfFirstFixedSurface=0 \
  cicecap glacierMask

cat glacierMask >> clim.grb

# ------------------------------------------------------------
# 4. Create 2-D surfclim and soilinit NetCDF files directly on lat/lon grid
# ------------------------------------------------------------
rm -f surfclim soilinit surfclim_x soilinit_x surfclim_all soilinit_all

PYTHONPATH="$BASEDIR:${PYTHONPATH:-}" python3 << PY
from init_clim import *
from netCDF4 import Dataset

FCLIMgrb = "clim.grb"
FINITgrb = "init.grb"
forcing = "${FORCING_TEMPLATE}"

with Dataset(forcing) as ft:
    lat = ft.variables["lat"][:]
    lon = ft.variables["lon"][:]

# ginfo only provides cell areas. lat/lon come from the forcing template.
ginfo = gg.get_grib_grid(FCLIMgrb, True, retbounds=True)

gen_file_LL(FOUT="surfclim", FTYPE="clm", lat=lat, lon=lon, ginfo=ginfo, nlevs=4, nlevsn=1)
gen_file_LL(FOUT="soilinit", FTYPE="ini", lat=lat, lon=lon, ginfo=ginfo, nlevs=4, nlevsn=1)

# MARS/GRIB area is north-to-south; WFDE5 lat is south-to-north, so flip_lat=True.
grib2nc_LL(FNC="surfclim", FGRB=FCLIMgrb, LEXTENDSOIL=False, LSNML=False, nlat=${NLAT}, nlon=${NLON}, flip_lat=True)
grib2nc_LL(FNC="soilinit", FGRB=FINITgrb, LEXTENDSOIL=False, LSNML=False, nlat=${NLAT}, nlon=${NLON}, flip_lat=True)
PY

# Optional cleanup of fields sometimes not needed by ecLand
ncks -O -x -v par_avg,ISOP_EP surfclim surfclim.tmp 2>/dev/null && mv surfclim.tmp surfclim || true

# ------------------------------------------------------------
# 5. Diagnostics and copy outputs
# ------------------------------------------------------------
echo "Forcing template: $FORCING_TEMPLATE"
echo "Points:"
grib_get -p numberOfPoints clim.grb | sort -u
grib_get -p numberOfPoints init.grb | sort -u
grib_get -p numberOfPoints cicecap | sort -u

echo "NetCDF headers:"
ncdump -h surfclim | head -40
ncdump -h soilinit | head -40

echo "Ranges:"
ncap2 -O -s 'mn=SoilTemp.min(); mx=SoilTemp.max();' soilinit /tmp/soilinit_range.nc >/dev/null 2>&1 || true
ncks -H -C -v SoilTemp -d nlevs,0 soilinit | head -20 || true
ncks -H -C -v SoilMoist -d nlevs,0 soilinit | head -20 || true

cp -f clim.grb init.grb surfclim soilinit "$OUTDIR"

echo "Created:"
ls -lh "$OUTDIR"/clim.grb "$OUTDIR"/init.grb "$OUTDIR"/surfclim "$OUTDIR"/soilinit
