#!/usr/bin/env bash
set -euo pipefail

CLIM_VERSION=${CLIM_VERSION:-climate.v021}
RES=${RES:-399_4}
CLIM_ROOT=${CLIM_ROOT:-/home/rdx/data/climate/${CLIM_VERSION}/${RES}}
IRRIG_FILE=${IRRIG_FILE:-/perm/pa5/URBAN_MAPS/VERSION_2023_09September/irrigation_cover_NEXhub/${RES}/irrigation_cover}

OUTDIR=${OUTDIR:-/perm/pad/liaise/init_clim/work}
mkdir -p "$OUTDIR"
cd "$OUTDIR"

rm -f clim.grb tmp.grb tmp2.grb month_lai month_alb

cat "$CLIM_ROOT/lsmoro"        >> clim.grb
cat "$CLIM_ROOT/clake"         >> clim.grb
cat "$CLIM_ROOT/slt"           >> clim.grb
cat "$CLIM_ROOT/sfc"           >> clim.grb
cat "$CLIM_ROOT/wetlandf"      >> clim.grb
cat "$CLIM_ROOT/lakedl"        >> clim.grb
cat "$IRRIG_FILE"              >> clim.grb
cat "$CLIM_ROOT/urban_2000.grb" >> clim.grb

grib_set -s paramId=229001 -w paramId=200199 clim.grb tmp.grb
grib_set -s paramId=229007 -w paramId=200026 tmp.grb tmp2.grb
mv tmp2.grb clim.grb
rm -f tmp.grb

grib_set -w shortName=z -s longitudeOfLastGridPointInDegrees=359.777 clim.grb tmp.grb
mv tmp.grb clim.grb

cat "$CLIM_ROOT/c3_c4_mask.grb" >> clim.grb

mars -p << EOF
read,source="${CLIM_ROOT}/month_alnid",param=alnid,fieldset=alnid
read,source="${CLIM_ROOT}/month_aluvd",param=aluvd,fieldset=aluvd
compute,formula="0.45976*aluvd+0.54024*alnid",target="tmp.grb"
EOF

grib_set -s shortName=al tmp.grb month_alb
rm -f tmp.grb

cat "$CLIM_ROOT/month_laih" >> month_lai
cat "$CLIM_ROOT/month_lail" >> month_lai

cat month_lai >> clim.grb
cat month_alb >> clim.grb

echo "Created $OUTDIR/clim.grb"
grib_count clim.grb
