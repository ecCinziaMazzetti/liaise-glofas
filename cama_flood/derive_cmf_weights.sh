#!/usr/bin/env bash
set -euo pipefail

# Derive the ecLand <-> CaMa-Flood interpolation weights and river-network
# fix files for the LIAISE domain.
#
# This regenerates the small, LIAISE-specific files tracked (via Git LFS)
# under cama_flood/data/:
#   inpmat.nc    interpolation weights: ecLand runoff grid -> CaMa-Flood
#                river grid (and the reverse mapping, if COMPUTE_INV=true)
#   ncdata.nc    CaMa-Flood river network, clipped to the (extended) domain
#   rivclim.nc   subset of ncdata.nc (ctmare, elevtn, nxtdst, rivlen,
#                fldhgt, lat, lon, nextx, nexty)
#   rivpar.nc    river physical parameters, clipped
#   outclm.nc    outlet climatology, clipped
#   mpireg.nc    single-region MPI map -- see "Why -e and a flat mpireg"
#                below; NOT a plain clip of the source file
#   bifprm.txt   river bifurcation parameters, clipped
#   diminfo.txt  dimension summary consumed by the CaMa-Flood namelist setup
#
# It does NOT commit the large upstream global/1-arcmin datasets these are
# derived from (see CMFDIR/FIXDIR below) -- only the small clipped output
# goes into the repo, same as init_clim/data/{soilinit,surfclim} versus the
# climate.v021 archive it is built from. See CLAUDE.md.
#
# Why -e (extend crossing basins) and a flattened mpireg.nc
# -----------------------------------------------------------
# The first version of this script clipped strictly to the LIAISE box
# (sel_region.py's default: any basin crossing the box boundary is dropped
# in its entirety, not just the part outside) and reused $FIXDIR/mpireg.nc
# as-is. Running CaMa-Flood coupled against that produced only ~10-11 cells
# of discharge output out of 522 "active" (ctmare>0) river cells -- a
# fragmented, disconnected-looking network. Root causes (see CLAUDE.md for
# the full trace):
#   1. Dropping crossing basins truncated real rivers at the domain edge --
#      for this location that meant losing the Rhone's basin entirely, not
#      just clipping it. -e keeps crossing basins whole.
#   2. $FIXDIR/mpireg.nc is the *global* multi-process MPI decomposition
#      map. CaMa-Flood (NPROC_CMF=1 here) only computes cells tagged region
#      1; a plain clip carries over 15+ other regions' worth of cells that
#      then silently never get computed. This script instead flattens every
#      valid cell in the clip to region 1 -- correct for a single-process
#      regional run, and NOT equivalent to just clipping.
# -e also requires gen_inpmat.py's Cython extension to tolerate 1-arcmin
# pixels that fall outside the LIAISE ecLand grid (a river cell's basin can
# now extend far beyond ecLand's own coverage) -- see the cython_ext.pyx
# patch note below.
#
# Requires: the ecland repo checked out with two source patches applied
# (both in the "ecland" repo, not this one -- see CLAUDE.md for the exact
# diffs, since a fresh ecland checkout will not have them):
#   - src/surf/offline/driver/cnt41s.F90: the LECMF1WAY runoff-coupling
#     loops must iterate NPOI, not NLALO (a real memory-safety bug, unrelated
#     to this script but required for ANY LIAISE CaMa-Flood run to be valid)
#   - tools/create_forcing/scripts/osm_pyutils/cython_ext.pyx: out-of-grid
#     high-res pixels must be skipped, not raise -- required for -e above
# ...and the create_forcing tool's Cython extension built from that patched
# source:
#   cd $ECLAND_ROOT/tools/create_forcing/scripts/osm_pyutils
#   python3 setup_cython.py build_ext --inplace --path=.
# (produces cython_ext*.so; this script builds/rebuilds it automatically if
# missing or older than cython_ext.pyx, so a stale pre-patch .so is never
# silently reused)
#
# Usage:
#   cd cama_flood
#   ./derive_cmf_weights.sh
#
# Override any of the paths/settings below via environment variables.

ECLAND_ROOT=${ECLAND_ROOT:-/perm/pad/ecland}
SCRIPTS_DIR="${ECLAND_ROOT}/tools/create_forcing/scripts/osm_pyutils"

# Shared ECMWF static CaMa-Flood data (see tools/create_forcing/README.md,
# "prepare_cmf_basin" / cmfdir convention):
#   CMFDIR  : 1-arcmin high-resolution catchment maps (1min.catmxy.nc,
#             1min.grdare.nc), one subdirectory per CMF_RES.
#   FIXDIR  : the matching global river-network fix files (ncdata.nc,
#             bifprm.txt, rivpar.nc, outclm.nc, mpireg.nc) at the same
#             CMF_RES.
# FIXDIR's default below is a colleague's personal work area, not a
# permanent path -- override it (or ask for these ~23MB files to be staged
# somewhere permanent) if it stops existing.
CMFDIR=${CMFDIR:-/home/rdx/data/50r1/camaflood/static_network_nc_v2.1}
FIXDIR=${FIXDIR:-/ec/fws5/sb/work/rd/pad/jaan/data/osm/inidata/fix/control}
CMF_RES=${CMF_RES:-glb_15min}

# Requested domain (N/W/S/E), matching init_clim.sh's TARGET_AREA and the
# WFDE5-CRU-GPCC forcing grid (see prepare_liaise_forcing_ecland.py). With
# EXTEND_CROSSING_BASINS=true (the default -- see above), the *actual*
# derived domain will be larger than this: any basin crossing this box is
# kept in full, not clipped to it.
CLATN=${CLATN:-46.75}
CLATS=${CLATS:-39.25}
CLONW=${CLONW:--5.75}
CLONE=${CLONE:-5.25}
DX=${DX:-0.50}
EXTEND_CROSSING_BASINS=${EXTEND_CROSSING_BASINS:-true}

# ecLand grid reference file, used only for its lat/lon dimensions -- any
# file on the exact LIAISE grid works (soilinit and surfclim share it).
LIAISE_GRID_FILE=${LIAISE_GRID_FILE:-../init_clim/data/soilinit}

# Compute the real (2-way) inverse mapping, or fill it with dummy values
# (1-way coupling only). Matches the LECMF2LAKEC=0 / LECMF1WAY default in
# namelist/create_liaise_namelist.sh.
COMPUTE_INV=${COMPUTE_INV:-false}

WORKDIR=${WORKDIR:-./work}

# nmax/nmaxI (max number of source/target links per cell): mirrors the
# case table in ecland/tools/create_forcing/scripts/prepare_basin_ini.bash.
# LIAISE's dx (0.5) doesn't match either of that table's explicit dx cases
# (0.25/0.10), so it falls to its wildcard row. Verified comfortably above
# the observed max (11 levels) with the extended domain.
#
# WARNING: NMAX is not just a safety margin -- gen_inpmat.py's find_inpn()
# preallocates inpa/inpx/inpy at (NMAX, nlat, nlon) of the *global*
# (unclipped) FIXDIR/ncdata.nc grid, not the clipped regional one. At
# glb_01min that global grid is 10800x21600 (233M cells), so the generic
# wildcard default here (NMAX=100) tried to allocate a ~186GB float64
# array and got EC_MEMKILL'd well before doing any real work, even under
# --mem=128G (the qos=nf cap) -- confirmed the hard way. The actual value
# needed is small and resolution-independent (it just counts how many
# coarse 0.5deg ecLand cells overlap one fine river-network cell -- 5-11
# in every case observed here regardless of CMF_RES), so NMAX=10 is ample
# headroom at glb_01min while keeping the array under ~40GB. If adding a
# case for a still-finer resolution, do not fall through to the wildcard;
# size NMAX by this same reasoning instead of guessing.
case ${CMF_RES} in
  glb_15min) NMAX=156; NMAXI=40  ;;
  glb_06min) NMAX=23;  NMAXI=78  ;;
  glb_03min) NMAX=48;  NMAXI=152 ;;
  glb_01min) NMAX=10;  NMAXI=40  ;;
  *)         NMAX=100; NMAXI=100 ;;
esac

for f in "$LIAISE_GRID_FILE" "$FIXDIR/ncdata.nc" "$FIXDIR/bifprm.txt" \
         "$FIXDIR/rivpar.nc" "$FIXDIR/outclm.nc" "$FIXDIR/mpireg.nc" \
         "$CMFDIR/$CMF_RES/1min.catmxy.nc" "$CMFDIR/$CMF_RES/1min.grdare.nc"; do
    [[ -f "$f" ]] || { echo "ERROR: required input not found: $f" >&2; exit 1; }
done

# Build (or rebuild, if stale relative to the .pyx source) the Cython
# extension gen_inpmat.py needs.
SO_FILE=$(find "$SCRIPTS_DIR" -maxdepth 1 -iname 'cython_ext*.so' -print -quit)
if [[ -z "$SO_FILE" || "$SCRIPTS_DIR/cython_ext.pyx" -nt "$SO_FILE" ]]; then
    echo "Building cython_ext (into ${SCRIPTS_DIR})"
    ( cd "$SCRIPTS_DIR" && rm -f cython_ext.c cython_ext*.so && rm -rf osm_pyutils build \
      && python3 setup_cython.py build_ext --inplace --path=. )
    # cythonize infers the package path from osm_pyutils/__init__.py and
    # nests the .so one level too deep with --inplace; flatten it.
    # `[[ -f pattern* ]]` does NOT glob-expand inside [[ ]] (only == / != treat
    # the right side as a pattern) -- it tests the literal string "pattern*",
    # which never exists, so this check silently no-opped every time. Only went
    # unnoticed because a pre-existing .so from an earlier build usually
    # already satisfied the staleness check above and skipped this block
    # entirely. Use find, which does do real matching, instead.
    NESTED_SO=$(find "$SCRIPTS_DIR/osm_pyutils" -maxdepth 1 -iname 'cython_ext*.so' -print -quit 2>/dev/null)
    if [[ -n "$NESTED_SO" ]]; then
        mv "$NESTED_SO" "$SCRIPTS_DIR/"
        rmdir "$SCRIPTS_DIR/osm_pyutils" 2>/dev/null || true
    fi
fi

# Resolve before cd'ing into WORKDIR, since these are commonly given as
# paths relative to this script's own directory.
LIAISE_GRID_FILE=$(cd -- "$(dirname -- "$LIAISE_GRID_FILE")" && pwd)/$(basename -- "$LIAISE_GRID_FILE")

mkdir -p "$WORKDIR"
cd "$WORKDIR"
export PYTHONPATH="${SCRIPTS_DIR}:${PYTHONPATH:-}"

echo "== Clipping global CaMa-Flood river network to the LIAISE domain =="
EXTEND_FLAG=""
if [[ "$EXTEND_CROSSING_BASINS" == "true" ]]; then
    EXTEND_FLAG="-e"
fi

python3 "$SCRIPTS_DIR/sel_region.py" \
    -d "$CLONW" "$CLONE" "$CLATS" "$CLATN" \
    -t clip ${EXTEND_FLAG} \
    -i "$FIXDIR/ncdata.nc" \
    -o ncdata.nc \
    -pi "$FIXDIR/bifprm.txt" \
    -po bifprm.txt

cdo_sel=$(cat cdo_clip_cama.txt)
cdo -f nc4 -z zip_6 -selindexbox,"$cdo_sel" "$FIXDIR/rivpar.nc" rivpar.nc
cdo -f nc4 -z zip_6 -selindexbox,"$cdo_sel" "$FIXDIR/outclm.nc" outclm.nc
cdo -f nc4 -z zip_6 -selindexbox,"$cdo_sel" "$FIXDIR/mpireg.nc" mpireg_global.nc
ncks -O -v ctmare,elevtn,nxtdst,rivlen,fldhgt,lat,lon,nextx,nexty ncdata.nc rivclim.nc

echo "== Flattening mpireg.nc to a single region (single-process run) =="
python3 - "mpireg_global.nc" "mpireg.nc" << 'PY'
import sys
import shutil
import numpy as np
from netCDF4 import Dataset

src, dst = sys.argv[1], sys.argv[2]
shutil.copy(src, dst)
with Dataset(dst, "r+") as nc:
    var = nc.variables["mpireg"]
    data = np.ma.filled(var[:], -9999)
    valid = data != -9999
    data[valid] = 1
    var[:] = data
    print(f"mpireg.nc: {valid.sum()} cells set to region 1")
PY

echo "== Deriving ecLand -> CaMa-Flood interpolation weights =="
ix0=$(awk '{print $1}' clip_cama_ix0_iy0.txt)
iy0=$(awk '{print $2}' clip_cama_ix0_iy0.txt)

CINV_FLAG=""
if [[ "$COMPUTE_INV" != "true" ]]; then
    CINV_FLAG="-cinv"
fi

python3 "$SCRIPTS_DIR/gen_inpmat.py" \
    -igrid "$LIAISE_GRID_FILE" \
    -iriv "$FIXDIR/ncdata.nc" \
    -ihcat "$CMFDIR/$CMF_RES/1min.catmxy.nc" \
    -iharea "$CMFDIR/$CMF_RES/1min.grdare.nc" \
    -o inpmat_tmp.nc \
    -m pmask.nc \
    ${CINV_FLAG} \
    -ix0 "$ix0" -iy0 "$iy0" -n "$NMAX" -nI "$NMAXI"

cdo -f nc4 -z zip_6 -selindexbox,"$cdo_sel" -selvar,inpa,inpx,inpy,nlev inpmat_tmp.nc inpmat.nc
ncks -A -v lonin,latin,inpaI,inpxI,inpyI,nlevI inpmat_tmp.nc inpmat.nc

echo "== Writing diminfo.txt =="
NX=$(ncdump -h rivclim.nc | grep "^.lon = " | head -1 | awk '{print $3}')
NY=$(ncdump -h rivclim.nc | grep "^.lat = " | head -1 | awk '{print $3}')
NLFP=$(ncdump -h rivclim.nc | grep "^.lev = " | head -1 | awk '{print $3}')
NXIN=$(ncdump -h inpmat.nc | grep "^.lonin = " | head -1 | awk '{print $3}')
NYIN=$(ncdump -h inpmat.nc | grep "^.latin = " | head -1 | awk '{print $3}')
INPN=$(ncdump -h inpmat.nc | grep "^.lev = " | head -1 | awk '{print $3}')

cat > diminfo.txt << EOF
$NX       !! nXX
$NY       !! nYY
$NLFP     !! floodplain layer
$NXIN     !! input nXX
$NYIN     !! input nYY
$INPN     !! input num
NONE
0     !! west  edge
0     !! east  edge
0     !! north edge
0     !! south edge
EOF

echo
echo "Done. LIAISE CaMa-Flood fix files written to: $(pwd)"
ls -lh inpmat.nc ncdata.nc rivclim.nc rivpar.nc outclm.nc mpireg.nc bifprm.txt diminfo.txt
echo
echo "Review these against cama_flood/data/ and copy them over to refresh"
echo "the committed reference files."
