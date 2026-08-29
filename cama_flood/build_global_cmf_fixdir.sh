#!/usr/bin/env bash
set -euo pipefail

# Build a global CaMa-Flood "FIXDIR" bundle (ncdata.nc, rivpar.nc, outclm.nc,
# bifprm.txt, mpireg.nc) at an arbitrary resolution, for derive_cmf_weights.sh
# to clip a regional LIAISE domain out of.
#
# WHY THIS EXISTS. derive_cmf_weights.sh originally depended on a colleague's
# personal work directory (jaan's fix/control) for this bundle, only staged
# at glb_15min. That directory turns out to just be the *output* of running
# ECMWF's own operational global-init script once -- reproducible from data
# already sitting in the shared, permanent CMFDIR at all four resolutions
# (glb_15min/06min/03min/01min), using three small Python tools this script
# borrows. So: run this once per CMF_RES you need, point derive_cmf_weights.sh
# at the result via FIXDIR, and jaan's directory is no longer required.
#
# Ported from ECMWF's operational create_init_clim_cmf.ksh (E. Dutra 2019,
# /ec/vol/ifs/rd/pad/ja8f/include/) -- only the resolution-independent,
# regional-LIAISE-relevant steps are kept (river-network params, discharge
# climatology, bifurcation, MPI region, mixed kinematic/inertia mask). Not
# ported: the *global* atmospheric-grid inpmat.nc that script also builds
# (from an operational IFS climatology grid via `lsmoro`) -- irrelevant here,
# since derive_cmf_weights.sh derives LIAISE's own inpmat.nc separately.
#
# calc_outclm.py/calc_rivpar.py/gen_mask_mixKinIner.py are vendored into
# cama_flood/vendor/ (from a colleague's personal, non-permanent ecFlow
# suite include directory, /ec/vol/ifs/rd/pad/ja8f/include -- otherwise-
# unavailable ECMWF operational tooling, not something to reimplement from
# scratch). calc_outclm.py needed one local fix: it called cython_ext's
# remap() with float32 input, but our (patched, see CLAUDE.md) cython_ext
# expects float64 -- see the comment in the vendored copy.
#
# Usage:
#   cd cama_flood
#   CMF_RES=glb_06min ./build_global_cmf_fixdir.sh
#
# Output lands in OUTDIR (default ./work_global/$CMF_RES); point
# derive_cmf_weights.sh at it: FIXDIR=<OUTDIR> CMF_RES=<same> ./derive_cmf_weights.sh

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ECLAND_ROOT=${ECLAND_ROOT:-/perm/pad/ecland}
SCRIPTS_DIR="${ECLAND_ROOT}/tools/create_forcing/scripts/osm_pyutils"
COMPANION_SCRIPTS_DIR=${COMPANION_SCRIPTS_DIR:-${SCRIPT_DIR}/vendor}

CMFDIR=${CMFDIR:-/home/rdx/data/50r1/camaflood/static_network_nc_v2.1}
CMF_RES=${CMF_RES:?set CMF_RES, e.g. glb_15min/glb_06min/glb_03min/glb_01min}
CMF_RES_SRC="${CMFDIR}/${CMF_RES}"
# The runoff climatology lives one level up from the per-resolution
# subdirectories, and is resolution-independent (same file feeds all four).
CMF_CLIMATE_DIR=${CMF_CLIMATE_DIR:-$(dirname "$CMFDIR")/climate}
FRUNOFFC=${FRUNOFFC:-${CMF_CLIMATE_DIR}/runoff_rd_h8hg_24_mean.nc}

# Single-process regional run -- see CLAUDE.md ("mpireg.nc: flattened to a
# single region"): NPES_CMF=1 selects the pre-built single-region map
# directly, rather than flattening a multi-region one ourselves.
NPES_CMF=${NPES_CMF:-1}

# 1-way coupling only (matches LECMF2LAKEC=0 / LECMF1WAY in
# namelist/create_liaise_namelist.sh) -- dummy inverse weights for inpmat_ro.
NCMF2LAKEC=${NCMF2LAKEC:-0}

# Channel bathymetry / bifurcation parameters: ECMWF operational defaults
# (create_init_clim_cmf.ksh), not LIAISE-specific.
HC=${HC:-2}; HP=${HP:-0.2}; HO=${HO:-0.00}; HMIN=${HMIN:-1.0}
WC=${WC:-10.}; WP=${WP:-0.50}; WO=${WO:-0.00}; WMIN=${WMIN:-5.0}
MAN=${MAN:-0.03}
GWDELAY=${GWDELAY:-0}
SLOPELIM=${SLOPELIM:-1e10}
BIFLAYER=${BIFLAYER:-5}

OUTDIR=${OUTDIR:-./work_global/${CMF_RES}}
WORKDIR=${WORKDIR:-./work_global_scratch/${CMF_RES}}

# nmax/nmaxI for the runoff-climatology-to-river-network mapping (inpmat_ro):
# ECMWF operational wildcard-case defaults per CMF_RES (create_init_clim_cmf.ksh).
case ${CMF_RES} in
  glb_15min) NMAXRC=48; NMAXIRC=42  ;;
  glb_06min) NMAXRC=22; NMAXIRC=67  ;;
  glb_03min) NMAXRC=13; NMAXIRC=109 ;;
  glb_01min) NMAXRC=7;  NMAXIRC=227 ;;
  *) echo "ERROR: unsupported CMF_RES: ${CMF_RES}" >&2; exit 1 ;;
esac

for f in "${CMF_RES_SRC}/ncdata.nc" "${CMF_RES_SRC}/bifori.txt.gz" \
         "${CMF_RES_SRC}/1min.catmxy.nc" "${CMF_RES_SRC}/1min.grdare.nc" \
         "${CMF_RES_SRC}/mpireg-${NPES_CMF}.nc" "${FRUNOFFC}"; do
    [[ -f "$f" ]] || { echo "ERROR: required input not found: $f" >&2; exit 1; }
done
for f in "${COMPANION_SCRIPTS_DIR}/calc_outclm.py" \
         "${COMPANION_SCRIPTS_DIR}/calc_rivpar.py" \
         "${COMPANION_SCRIPTS_DIR}/gen_mask_mixKinIner.py"; do
    [[ -f "$f" ]] || { echo "ERROR: required companion script not found: $f" >&2; exit 1; }
done

# Build (or rebuild, if stale) the Cython extension, same as derive_cmf_weights.sh.
SO_FILE=$(find "$SCRIPTS_DIR" -maxdepth 1 -iname 'cython_ext*.so' -print -quit)
if [[ -z "$SO_FILE" || "$SCRIPTS_DIR/cython_ext.pyx" -nt "$SO_FILE" ]]; then
    echo "Building cython_ext (into ${SCRIPTS_DIR})"
    ( cd "$SCRIPTS_DIR" && rm -f cython_ext.c cython_ext*.so && rm -rf osm_pyutils build \
      && python3 setup_cython.py build_ext --inplace --path=. )
    if [[ -f "$SCRIPTS_DIR/osm_pyutils"/cython_ext*.so ]]; then
        mv "$SCRIPTS_DIR"/osm_pyutils/cython_ext*.so "$SCRIPTS_DIR/"
        rmdir "$SCRIPTS_DIR/osm_pyutils" 2>/dev/null || true
    fi
fi

# Resolve to absolute paths before cd'ing into WORKDIR below, so later
# references to OUTDIR (relative by default) don't get reinterpreted
# relative to WORKDIR instead of the directory this script was invoked from.
mkdir -p "$WORKDIR" "$OUTDIR"
WORKDIR=$(cd -- "$WORKDIR" && pwd)
OUTDIR=$(cd -- "$OUTDIR" && pwd)
cd "$WORKDIR"
# COMPANION_SCRIPTS_DIR first: calc_outclm.py/calc_rivpar.py are ECMWF
# operational tools, kept as-is; SCRIPTS_DIR supplies our own (patched)
# cython_ext/gen_inpmat/cmflood_pylib that they import.
export PYTHONPATH="${COMPANION_SCRIPTS_DIR}:${SCRIPTS_DIR}:${PYTHONPATH:-}"

echo "== [$CMF_RES] Copying river network and 1-arcmin catchment data =="
cp -f "${CMF_RES_SRC}/ncdata.nc" ncdata.nc
cp -f "${CMF_RES_SRC}/1min.catmxy.nc" 1min.catmxy.nc
cp -f "${CMF_RES_SRC}/1min.grdare.nc" 1min.grdare.nc
cp -f "${CMF_RES_SRC}/bifori.txt.gz" bifori.txt.gz
cp -f "${FRUNOFFC}" runoff_clm.nc

CINV_FLAG=""
if [[ "$NCMF2LAKEC" == "0" ]]; then
    CINV_FLAG="-cinv"
    NMAXIRC=$NMAXRC
fi

echo "== [$CMF_RES] Mapping runoff climatology onto the river network (inpmat_ro.nc) =="
time python3 -u "$SCRIPTS_DIR/gen_inpmat.py" \
    -igrid runoff_clm.nc \
    -iriv ncdata.nc \
    -ihcat 1min.catmxy.nc \
    -iharea 1min.grdare.nc \
    ${CINV_FLAG} \
    -o inpmat_ro.nc -n "$NMAXRC" -nI "$NMAXIRC"

echo "== [$CMF_RES] Computing discharge climatology (outclm.nc) =="
time python3 -u "${COMPANION_SCRIPTS_DIR}/calc_outclm.py" \
    -iriv ncdata.nc \
    -irof runoff_clm.nc \
    -imap inpmat_ro.nc \
    -o outclm.nc

echo "== [$CMF_RES] Computing channel bathymetry + bifurcation (rivpar.nc, bifprm.txt) =="
time python3 -u "${COMPANION_SCRIPTS_DIR}/calc_rivpar.py" \
    -iriv ncdata.nc \
    -irofc outclm.nc \
    -pHC "$HC" -pHP "$HP" -pHO "$HO" -pHMIN "$HMIN" \
    -pWC "$WC" -pWP "$WP" -pWO "$WO" -pWMIN "$WMIN" \
    -pMAN "$MAN" -pGWDELAY "$GWDELAY" \
    -pBIFLAYER "$BIFLAYER" -ibifori bifori.txt.gz \
    -o rivpar.nc

echo "== [$CMF_RES] Adding mixed kinematic/local-inertia mask to rivpar.nc =="
time python3 -u "${COMPANION_SCRIPTS_DIR}/gen_mask_mixKinIner.py" \
    -i ncdata.nc -o rivpar.nc -t "$SLOPELIM"

echo "== [$CMF_RES] Selecting single-region mpireg.nc (NPES_CMF=$NPES_CMF) =="
cp -f "${CMF_RES_SRC}/mpireg-${NPES_CMF}.nc" mpireg.nc

cp -f ncdata.nc rivpar.nc outclm.nc bifprm.txt mpireg.nc "$OUTDIR/"

echo
echo "Done. Global CaMa-Flood fix bundle at $CMF_RES written to: $OUTDIR"
ls -lh "$OUTDIR"
echo
echo "Use it as FIXDIR for a regional derive:"
echo "  FIXDIR=$(cd "$OUTDIR" && pwd) CMF_RES=${CMF_RES} ./derive_cmf_weights.sh"
