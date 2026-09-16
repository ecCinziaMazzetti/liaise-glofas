#!/usr/bin/env bash
set -euo pipefail

module load nco >/dev/null 2>&1 || true

OUTDIR=${OUTDIR:-/perm/pad/liaise/namelist}
FORCING_TEMPLATE=${FORCING_TEMPLATE:-/perm/pad/liaise/forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_2014.nc}

mkdir -p "$OUTDIR"
[[ -f "$FORCING_TEMPLATE" ]] || { echo "ERROR: missing $FORCING_TEMPLATE" >&2; exit 1; }

read -r NLAT_FILE NLON_FILE < <(
    ncdump -h "$FORCING_TEMPLATE" |
    awk '
        $1 == "lat" && $2 == "=" {
            gsub(/;/, "", $3)
            nlat = $3
        }
        $1 == "lon" && $2 == "=" {
            gsub(/;/, "", $3)
            nlon = $3
        }
        END {
            print nlat, nlon
        }
    '
)

NLAT=${NLAT:-$NLAT_FILE}
NLON=${NLON:-$NLON_FILE}

NDFORC=${NDFORC:-$((366 * 24 + 1))}
NDIMCDF=${NDIMCDF:-2}
NDLEVEL=${NDLEVEL:-0}
NCDFTYPE=${NCDFTYPE:-4}

START_DATE=${START_DATE:-19800101}
END_DATE=${END_DATE:-19810101}
START_TIME=${START_TIME:-00}
END_TIME=${END_TIME:-00}
OSMTSTEP=${OSMTSTEP:-1800}
ZDTFORC=${ZDTFORC:-3600}

# GNU `date -d` vs BSD/macOS `date -j -f`
epoch_from_date() {
    local d="$1" t="$2" out
    if out=$(date -u -d "${d} ${t}:00" +%s 2>/dev/null); then
        echo "$out"
    else
        date -u -j -f "%Y%m%d %H:%M" "${d} ${t}:00" +%s
    fi
}

START_EPOCH=$(epoch_from_date "$START_DATE" "$START_TIME")
END_EPOCH=$(epoch_from_date "$END_DATE" "$END_TIME")
RUN_SECONDS=$((END_EPOCH - START_EPOCH))
(( RUN_SECONDS > 0 )) || { echo "ERROR: invalid run period" >&2; exit 1; }
(( RUN_SECONDS % OSMTSTEP == 0 )) || { echo "ERROR: run length not divisible by OSMTSTEP" >&2; exit 1; }
(( 3600 % OSMTSTEP == 0 )) || { echo "ERROR: OSMTSTEP must divide 3600" >&2; exit 1; }

NSTART=${NSTART:-0}
NSTOP=${NSTOP:-$((RUN_SECONDS / OSMTSTEP))}
NFRPOS=${NFRPOS:-$((3600 / OSMTSTEP))}
NINDAT=${NINDAT:-$START_DATE}
IFYYYY=${IFYYYY:-${START_DATE:0:4}}
IFMM=${IFMM:-${START_DATE:4:2}}
IFDD=${IFDD:-${START_DATE:6:2}}
IFTIM=${IFTIM:-${START_TIME}00}

EXPVER=${EXPVER:-liaise_wfde5}
IFS_CYCLE=${IFS_CYCLE:-CY50R1}
LNF=${LNF:-.TRUE.}
LPROD=${LPROD:-.TRUE.}
LDBGS1=${LDBGS1:-.FALSE.}
IDBGS1=${IDBGS1:-0}
NCSS=${NCSS:-4}
NCWS=${NCWS:-0}
NCSNEC=${NCSNEC:-5}
FCHEIGHT_TQ=${FCHEIGHT_TQ:-2.0}
FCHEIGHT=${FCHEIGHT:-10.0}
LPREINT=${LPREINT:-.FALSE.}
TCOUPFREQ=${TCOUPFREQ:-24}

LEVGEN=${LEVGEN:-.TRUE.}
LESSRO=${LESSRO:-.TRUE.}
LEFLAKE=${LEFLAKE:-.TRUE.}
LESN09=${LESN09:-.TRUE.}
LELAIV=${LELAIV:-.TRUE.}
LECTESSEL=${LECTESSEL:-.TRUE.}
LEAGS=${LEAGS:-.FALSE.}
LEFARQUHAR=${LEFARQUHAR:-.TRUE.}
LEOPTSURF=${LEOPTSURF:-.FALSE.}
LEAIRCO2COUP=${LEAIRCO2COUP:-.FALSE.}
LEC4MAP=${LEC4MAP:-.TRUE.}
RLAIINT=${RLAIINT:-0.0}
LCLIM10D=${LCLIM10D:-FALSE}
LESNML=${LESNML:-.TRUE.}
LECMF1WAY=${LECMF1WAY:-false}
LESSDP_CALIB=${LESSDP_CALIB:-false}
LEINTWIND=${LEINTWIND:-true}

LEWBCHECK=${LEWBCHECK:-.FALSE.}
LEWBCHECKAbort=${LEWBCHECKAbort:-.FALSE.}
LESNCHECK=${LESNCHECK:-.FALSE.}
LESNCHECKAbort=${LESNCHECKAbort:-.FALSE.}
LEWBSOILFIX=${LEWBSOILFIX:-.TRUE.}
LESKTI5=${LESKTI5:-.FALSE.}
LESKTI8=${LESKTI8:-.FALSE.}
LESOILCOND=${LESOILCOND:-.TRUE.}
LESNWBCON=${LESNWBCON:-.FALSE.}
LEROLAKE=${LEROLAKE:-true}
LEIRRIGATION=${LEIRRIGATION:-false}
LBVOC_EMIS=${LBVOC_EMIS:-false}

# "Depth trilogy" prototype switches (develop branch NAMPARSOIL) -- the
# per-gridpoint RDBEDROCK/WTD fields (init_clim/add_bedrock_wtd_fields.py)
# only take effect when these are on. Default off, matching plain ecLand
# behaviour and leaving the existing control run's namelist/input
# untouched unless explicitly exported.
LEUNIFORMROOT=${LEUNIFORMROOT:-.FALSE.}
LEBEDROCKLIM=${LEBEDROCKLIM:-.FALSE.}
LEGWRECHARGE=${LEGWRECHARGE:-.FALSE.}
RWTDRECHARGE=${RWTDRECHARGE:-1.0}

CFORCV=${CFORCV:-Wind.nc}
CFORCU=${CFORCU:-Wind.nc}
CFORCT=${CFORCT:-Tair.nc}
CFORCQ=${CFORCQ:-Qair.nc}
CFORCC=${CFORCC:-CO2air.nc}
CFORCP=${CFORCP:-PSurf.nc}
CFORCRAIN=${CFORCRAIN:-Rainf.nc}
CFORCSNOW=${CFORCSNOW:-Snowf.nc}
CFORCSW=${CFORCSW:-SWdown.nc}
CFORCLW=${CFORCLW:-LWdown.nc}

RSIGORMIN=100.
RSIGORMAX=1000.

cat > "$OUTDIR/input" <<NAMELIST
&NAMCT01S
  NSTART=$NSTART           ! first timestep of model 0
  NSTOP=$NSTOP             ! last timestep of model 17520
  NFRPOS=$NFRPOS           ! frequency of post-processing events (time-steps)
  NFRRES=0                 ! frequency of writing intermediate restart files (time-steps)
  LNF=$LNF                 ! .T. = start, .F. = restart
  NCYCLE=1                 ! number of the experiment
  CNMEXP="${EXPVER}"       ! name of the experiment
  /
  &NAMDYN1S
  TSTEP=$OSMTSTEP          !  TSTEP   : length of the timestep in seconds
  NACCTYPE=2               ! =0  Forcing fluxes assument centered on timestamp (linear interp.)
                           ! =1  forward accumulation (starting at timestamp)
                           ! =2  backward accumulation (ending at timestamp)
  LSWINT=.FALSE.            ! SWdown solar angle interpolation if true
  LPREINT=${LPREINT:-.FALSE.} ! precipitation interpolation if true
  LFLXINT=.FALSE.          ! SWdown/LWdown linear interpolation if true
  TCOUPFREQ=${TCOUPFREQ}  ! Coupling frequency with CaMa-flood
  /
  &NAMDIM
  NLAT=$NLAT               ! number of latitudes
  NLON=$NLON               ! number of longitudes
  NDFORC=$NDFORC           ! namelist forcing dimension
  NPROMA=120               ! working dimension for grid-point computations
  NCSS=${NCSS:-4}          ! # of vertical layers in the soil
  NCSNEC=${NCSNEC:-1}      ! # of vertical layer in the snow
  /
  &NAMRIP
  NINDAT=${NINDAT}         ! run initial date in the form YYYYMMDD
  NSSSSS=0                 ! initial time in seconds (e.g. for 12h, 43200)
  /
  &NAM1S
  CFFORC='netcdf'          ! CHARACTER: IDENTIFIES THE FORCING DATA SET
  CFOUT='netcdf'           ! CHARACTER: IDENTIFIES THE OUTPUT DATA SET
  CFSURF='netcdf'          ! CHARACTER: IDENTIFIES THE SURFACE CLIMATOLOGY DATA SET
  CFINIT='netcdf'          ! CHARACTER: IDENTIFIES THE INITIALIZATION DATA SET
  CMODID='${IFS_CYCLE}'         ! CHARACTER: MODEL IDENTIFICATION
  CVERID=''                ! CHARACTER: VERSION IDENTIFICATION
  LACCUMW=.TRUE.           ! LOGICAL : WRITE OUT ACCUMULATED FLUXES (DEFAULT=TRUE)
  LRESET=.TRUE.            ! LOGICAL : RESET ACCUMULATION EVERY WRITE OUT TIME STEP
  NACCUR=1                 ! INTEGER : OUTPUT CDF ACCURACY: 1=SINGLE PREC, 2=DOUBLE PREC
  NDIMCDF=${NDIMCDF}       ! INTEGER : NR OF GRID DIMENSIONS
  NDLEVEL=${NDLEVEL}       ! INTEGER : Level of netcdf4 compression 0-9: 0== no compression -faster output
  NCDFTYPE=${NCDFTYPE}     ! type of netcdf output
  LNCSNC=.FALSE.           !  if true sync netcdf output every writting step (slows down run)
  LWRGG=$LPROD             ! logical, wrtie o_gg  - instantaneus prognostics
  LWRCLM=$LPROD            ! logical, write o_fix - fix soil properties
  LWRGGD=$LPROD            ! logical, write o_ggd - mean prognostic evolution
  LWREFL=$LPROD            ! logical, write o_efl - surface energy balance
  LWRWAT=$LPROD            ! logical, write o_wat - water balance
  LWRD2M=$LPROD            ! logical, write o_d2m - 2 meters diagnostics
  LWRSUS=$LPROD            ! logical, write o_sus - surface state variables (vegT,albedo, etc..)
  LWREVA=$LPROD            ! logical, write o_eva - evaporation components
  LWRCLD=$LPROD            ! logical, write o_cld - cold processes variables
  LWRCO2=$LPROD            ! logical, write o_co2 - cO2 fluxes
  LWRBIO=.FALSE.           ! logical, write o_bio - biomass
  LWRVEG=.FALSE.           ! logical, write o_veg - vegetation 2D high/low veg
  LWRVTY=$LPROD            ! logical, write o_vty - vegetation 2D high/low veg biomass
  LWREXT=$LPROD            ! logical, write o_ext - extra output with forcing
  LWRTIL=.FALSE.           ! logical, write o_til - tiles 2D (tile) state
  LWRLKE=.FALSE.           ! logical, write o_lke - lake variables
  LSEMISS=.FALSE.          ! LOGICAL : EMISSIVITY SET TO CONSTANT VALUE REMISS
  LDBGS1=$LDBGS1           ! LOGICAL : PRINT DEBUG INFO, EG FORCING DATA (DEFAULT=FALSE)
  IDBGS1=$IDBGS1                 ! Debug level : output printing
  /
  &NAMFORC
  ZPHISTA=${FCHEIGHT}      ! REFERENCE LEVEL (FOR T, Q) last model level ERAI
  ZUV=${FCHEIGHT}          ! REFERENCE LEVEL FOR WIND   last model level ERAI
  ZDTFORC=$ZDTFORC         ! FORCING TIME STEP     3h forcing from ERAI
  IFYYYY=$IFYYYY           ! REFERENCE YEAR
  IFMM=$IFMM               ! REFERENCE MONTH
  IFDD=$IFDD               ! REFERENCE DAY
  IFTIM=$IFTIM             ! REFERENCE TIME (HHMM)
  INSTFC=0                 ! NUMBER OF TIME STEPS TO BE READ (0 = ALL)
  NDIMFORC=${NDIMCDF}      ! NUMBER OF GRID DIMENSIONS in FORCING
  LOADIAB=.FALSE.          ! FLAG FOR APPLYING ADIABATIC HEIGHT CORRECTION
  CFORCV="$CFORCV"
  CFORCU="$CFORCU"
  CFORCT="Tair.nc"
  CFORCQ="Qair.nc"
  CFORCC="CO2air.nc"
  CFORCP="PSurf.nc"
  CFORCRAIN="Rainf.nc"
  CFORCSNOW="Snowf.nc"
  CFORCSW="SWdown.nc"
  CFORCLW="LWdown.nc"
  /
  &NAMPHY
  LEVGEN=$LEVGEN           ! LOGICAL : TURN THE VAN GENUCHTEN HYDROLOGY ON
  LESSRO=$LESSRO           ! LOGICAL : TURN THE SUB-GRID SURFACE RUNOFF ON
  LEFLAKE=$LEFLAKE         ! LOGICAL : TURN THE FLAKE ON
  LESN09=$LESN09           ! LOGICAL : TURN THE NEW SNOW PARAMETERIZATION ON
  LELAIV=$LELAIV           ! LOGICAL : TURN THE LAI SEASONAL ON
!  LEIRRIGATION=$LEIRRIGATION  ! LOGICAL : TURN THE IRRIGATION ON
  LECTESSEL=$LECTESSEL     ! LOGICAL : TURN CTESSEL ON
  LEAGS=$LEAGS             ! LOGICAL : TURN COUPLING OF EVAPORATION WITH PHOTOSYNTHESIS
  LEFARQUHAR=$LEFARQUHAR   ! LOGICAL : TURN ON FARQUHAR PHOTOSYNTHESIS (true: Farquhar; false: A-gs)
  LEOPTSURF=$LEOPTSURF     ! LOGICAL : USE FARQUHAR PARAMETERS FROM NAMELIST (OTHERWISE USE DEFAULT VALUES)
  LEAIRCO2COUP=$LEAIRCO2COUP ! LOGICAL : TURN ATM CO2 COUPLING WITH PHOTOSYNTHESIS
  LEC4MAP=$LEC4MAP         ! LOGICAL : Use C3/C4 photosynthesis pathway map from climate fields (if false it assigns C3/C4 according to PFT)
  RLAIINT=$RLAIINT         ! Coefecient for interactive LAI relaxation with clim (1 fully interactive; 0 fully clim)
  LECLIM10D=.$LCLIM10D.      ! LOGICAL : TURN usage of 10-day Climatology for Alb and LAI
  LBVOC_EMIS=$LBVOC_EMIS.      ! LOGICAL : TURN usage of online bvoc emission computation
  LESNML=$LESNML           ! LOGICAL : TURN THE MULTI-LAYER SNOW SCHEME
  LECMF1WAY=${LECMF1WAY:-false} ! Logical : Turn on Coupling with CaMa-Flood
  NCMF2LAKEC=${NCMF2LAKEC:-0} ! Integer: 2way coupling : 0 -> off, 1 -> replace , 2 -> add
  LESSDP_CALIB=${LESSDP_CALIB:-false} ! Logical : Turn on the calibration of the surface spatially distributed parameters
  NCWS=$NCWS               ! Number of layers to merge at the end for the soil water profile (for > 4layers)
  /
  &NAMOPTSURF
     OVR0VT=1.395E-07,1.332E-07,4.617E-07,4.334E-07,4.060E-07,
            3.208E-07,1.395E-07,1.450E-07,5.230E-07,0.557E-07,
            0.013E-07,1.450E-07,3.692E-07,1.450E-07,1.450E-07,
            1.328E-07,0.416E-07,2.107E-07,2.107E-07,2.700E-07,
            1.038E-07,0.302E-07

    OVCMAX25=49, 48.7, 62.2, 35, 41.9, 33.9, 49., -9999, 70, 60, 50, -9999, 48.6, -9999, -9999, 58.4, 44.5, 50, 50, -9999, 70.5,40.3
    OHUMREL=1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
    OA1=0.946, 0.888, 0.68, 0.85, 0.9775, 0.9775, 0.946, 0.85, 0.9775, 0.85, 0.72, 0.85, 0.919, 0.85, 0.85, 0.864, 0.9775, 0.85, 0.85, 0.85, 0.864,0.668
    OB1=0.13, 0.117, 0.168, 0.14, 0.112, 0.138, 0.13, 0.14, 0.112, 0.14, 0.2, 0.14, 0.126, 0.14, 0.14, 0.206, 0.112, 0.14 0.14, 0.14, 0.168,0.21
    OG0=0.00699, 0.00664, 0.00533, 0.00625, 0.007696, 0.007838, 0.00699, 0.00625, 0.008125, 0.00625, 0.01875, 0.00625, 0.00739, 0.00625, 0.00625, 0.0142, 0.00773, 0.00625, 0.00625, 0.00625, 0.0219,0.017
    OGM25=0.513, 0.657, 0.1, 0.4, 0.719, 0.387, 0.513, 0.4, 0.8, 0.4, 0.4, 0.4, 0.59, 0.4, 0.4, 0.4, 0.724, 0.404, 0.4, 0.4, 0.4,0.4
    OE_VCMAX=72801.3, 50059.1, 59880.2, 71513, 92966.9, 67706.09, 72801.3, 71513, 50059.1, 71513, 67300, 71513, 72906.6, 71513, 71513, 47110, 50059.1, 71513.0, 71513, 71513, 80090.2,47110
    OE_JMAX=64849.2, 41459.5, 35048.2, 49884, 34918.8, 34918.8, 64849.2, 49884, 34918.8, 49884, 77900, 49884, 34918.8, 49884, 49884, 54530, 52755.6, 49884.0, 49884, 49884, 101270, 54530
    /
  &NAMPHYOFF
  LEWBCHECK=${LEWBCHECK}
  LEWBCHECKAbort=${LEWBCHECKAbort}
  LESNCHECK=${LESNCHECK}
  LESNCHECKAbort=${LESNCHECKAbort}
  LEWBSOILFIX=${LEWBSOILFIX}
  LESKTI5=${LESKTI5}
  LESKTI8=${LESKTI8}
  LESOILCOND=${LESOILCOND}
  LESNWBCON=${LESNWBCON}
  LEROLAKE=${LEROLAKE:-true}
  /
  &NAMPARSNOW
  /
  &NAMPARSOIL
  RSIGORMIN=${RSIGORMIN}
  RSIGORMAX=${RSIGORMAX}
  LEUNIFORMROOT=${LEUNIFORMROOT}
  LEBEDROCKLIM=${LEBEDROCKLIM}
  LEGWRECHARGE=${LEGWRECHARGE}
  RWTDRECHARGE=${RWTDRECHARGE}
  /
  &NAMPARVEG
  /
  &NAMPARAGS
  /
  &NAMPARFLAKE
  /
  &NAMPAREXC
  /
  &NAMPARURB
  /
NAMELIST

echo "Created $OUTDIR/input"
echo "Grid: ${NLAT} x ${NLON} x ${NDFORC}"
echo "Run: ${START_DATE} ${START_TIME}:00 to ${END_DATE} ${END_TIME}:00"
echo "Timestep: ${OSMTSTEP}s; forcing interval: ${ZDTFORC}s"


