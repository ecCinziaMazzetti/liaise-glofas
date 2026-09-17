#!/usr/bin/env bash
#SBATCH --job-name=liaise_ecland
#SBATCH --output=/perm/pad/liaise-ecland/run/logs/liaise_ecland_%j.out
#SBATCH --error=/perm/pad/liaise-ecland/run/logs/liaise_ecland_%j.err
#SBATCH --qos=nf
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
set -euo pipefail

# ----------------------------------------------------------------------
# LIAISE ecLand annual driver for ECMWF HPC/Slurm
#
# The script:
#   1. discovers all yearly forcing files;
#   2. runs one year at a time;
#   3. uses soilinit/surfclim for the first year;
#   4. copies each restart output into the next year's restart input;
#   5. stores annual outputs and restarts separately.
#
# If the ecLand namelist has LECMF1WAY (CaMa-Flood 1-way coupling) turned
# on, the script also stages the CaMa-Flood static files derived by
# cama_flood/derive_cmf_weights.sh, generates and patches a per-year
# CaMa-Flood namelist, and chains the CaMa-Flood restart across years the
# same way it already does for ecLand's own restart. CaMa-Flood itself is
# not a separate process: ecland-master calls into it in-process when
# LECMF1WAY is set (see src/surf/offline/driver/cnt01s.F90 in the ecland
# repo), so no separate executable or launch step is needed.
#
# Usage:
#   sbatch run_liaise_ecland.slurm
#
# Override paths/settings through environment variables, e.g.:
#   ROOT=$HOME/Work/liaise-ecland \
#   ECLAND_EXE=$HOME/Work/ecland/build/bin/ecland-master \
#   sbatch run_liaise_ecland.slurm
# ----------------------------------------------------------------------

# -------------------------
# Paths
# -------------------------
WORK=${WORK:-${PERM:-/perm/$USER}}
ROOT=${ROOT:-$WORK/liaise-ecland}
FORCING_DIR=${FORCING_DIR:-${ROOT}/forcing/WFDE5_CRU_GPCC_ecland}
STATIC_DIR=${STATIC_DIR:-${ROOT}/init_clim/work}
NAMELIST=${NAMELIST:-${ROOT}/namelist/input}
ECLAND_EXE=${ECLAND_EXE:-$WORK/ecland/build/bin/ecland-master-dp}

RUN_ROOT=${RUN_ROOT:-${ROOT}/run}
LOG_DIR=${LOG_DIR:-${RUN_ROOT}/logs}
OUTPUT_ROOT=${OUTPUT_ROOT:-${RUN_ROOT}/output}
RESTART_ROOT=${RESTART_ROOT:-${RUN_ROOT}/restart}
WORK_ROOT=${WORK_ROOT:-${RUN_ROOT}/work}

mkdir -p "$LOG_DIR" "$OUTPUT_ROOT" "$RESTART_ROOT" "$WORK_ROOT"

# -------------------------
# Files expected by ecLand
# -------------------------
SURFCLIM_SOURCE=${SURFCLIM_SOURCE:-${STATIC_DIR}/surfclim}
SOILINIT_SOURCE=${SOILINIT_SOURCE:-${STATIC_DIR}/soilinit}

# Optional: seed the very first forcing year's restart, for a spin-up pass
# (e.g. re-running the same year twice, or picking up land-surface state
# already spun up by a separate long continuous run) rather than always
# cold-starting from SOILINIT_SOURCE. Left empty (default), behaviour is
# unchanged: the first year uses SOILINIT_SOURCE and LNF stays as the
# namelist has it (normally .TRUE., cold start).
INITIAL_RESTART=${INITIAL_RESTART:-}
INITIAL_RESTART_CMF=${INITIAL_RESTART_CMF:-}

RESTART_IN_NAME=${RESTART_IN_NAME:-restart_in.nc}
RESTART_OUT_NAME=${RESTART_OUT_NAME:-restartout.nc}

SURFCLIM_RUN_NAME=${SURFCLIM_RUN_NAME:-surfclim}
SOILINIT_RUN_NAME=${SOILINIT_RUN_NAME:-soilinit}
NAMELIST_RUN_NAME=${NAMELIST_RUN_NAME:-input}

FORCING_VARS=(Tair Qair PSurf Rainf Snowf SWdown LWdown Wind)

# -------------------------
# CaMa-Flood coupling (optional; activated by LECMF1WAY in $NAMELIST)
# -------------------------
CMF_STATIC_DIR=${CMF_STATIC_DIR:-${ROOT}/cama_flood/data}
CMF_NAMELIST=${CMF_NAMELIST:-${ROOT}/namelist/input_cmf}
CMF_NAMELIST_RUN_NAME=${CMF_NAMELIST_RUN_NAME:-input_cmf.nam}
CMF_RESTART_IN_NAME=${CMF_RESTART_IN_NAME:-restartin_cmf.nc}
# Files referenced by namelist/input_cmf's NMAP/NDIMTIME/NFORCE blocks;
# already named to match what CaMa-Flood expects at runtime.
CMF_STATIC_FILES=(inpmat.nc rivpar.nc rivclim.nc mpireg.nc bifprm.txt diminfo.txt ${CMF_STATIC_FILES_EXTRA:-})  # extra files (e.g. dam_param.csv) via env var, staged from CMF_STATIC_DIR like the rest

# -------------------------
# Runtime environment
# -------------------------
module purge
module load prgenv/intel
module load hpcx-openmpi/2.9.0
module load netcdf4

# Optional OpenMP settings
# Thread count. Measured 2026-09-17 on the LIAISE domain, 3 identical years each:
#
#   glb_15min (1,405 river cells):  1 thread 168 s/yr | 4 threads 274 s/yr  -> 1.6x SLOWER
#   glb_03min (34,137 river cells): 1 thread ~36 min/yr | 4 threads ~2x faster
#
# So threading is NOT a universal win: at the coarse resolution the OpenMP regions are
# too small to pay back their synchronisation cost, and only the fine resolutions
# benefit. Default is therefore 1 -- which is also what every validated run in this
# repo actually used -- and finer resolutions opt in with OMP_THREADS=4.
#
# Do NOT write ${OMP_NUM_THREADS:-...} here: ECMWF's shell profile exports
# OMP_NUM_THREADS=1 and `sbatch --export=ALL` propagates it, so `:-` never fires and the
# setting silently becomes whatever the submitting shell had. That hid the single-
# threading above for the entire project until it was caught by inspecting a live
# process. The value is echoed at startup so this cannot regress unnoticed.
#
# Threading is not bit-reproducible despite LBITSAFE=.TRUE. (1% of cell-times differ),
# but the differences are confined to already-unstable estuary/bifurcation cells with
# near-zero or negative discharge: median difference 4e-4 m3/s, and gauge skill scores
# are identical to 4 decimal places. Mixing thread counts across years of one run is
# therefore acceptable, if untidy.
export OMP_NUM_THREADS=${OMP_THREADS:-1}
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS (OMP_THREADS=${OMP_THREADS:-unset}, cpus-per-task=${SLURM_CPUS_PER_TASK:-unset})"
export OMP_STACKSIZE=${OMP_STACKSIZE:-512M}

# -------------------------
# Helpers (defined before Validation/main loop, both of which use them)
# -------------------------
is_leap_year() {
    local year=$1
    if (( year % 400 == 0 )); then
        return 0
    elif (( year % 100 == 0 )); then
        return 1
    elif (( year % 4 == 0 )); then
        return 0
    else
        return 1
    fi
}

sed_inplace() {
    if sed --version >/dev/null 2>&1; then
        sed -i -E "$@"
    else
        sed -i '' -E "$@"
    fi
}

# Read a "KEY = value ! comment" style namelist entry, tolerant of
# whitespace around "=" and a trailing inline comment.
nml_value() {
    local key=$1 file=$2
    awk -v key="$key" '
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            line = $0
            sub(/!.*/, "", line)
            sub(/^[^=]*=/, "", line)
            gsub(/[[:space:],]/, "", line)
            print line
            exit
        } ' "$file"
}

patch_namelist_for_year() {
    local file=$1
    local year=$2
    local days=365

    if is_leap_year "$year"; then
        days=366
    fi

    local tstep
    tstep=$(awk '
        /^[[:space:]]*TSTEP[[:space:]]*=/ {
            line = $0
            sub(/!.*/, "", line)          # remove Fortran inline comment
            sub(/^[^=]*=/, "", line)      # remove everything through "="
            gsub(/[[:space:],]/, "", line)
            print line
            exit
        } ' "$file")

    if [[ -z "$tstep" ]]; then
        echo "ERROR: could not read TSTEP from $file" >&2
        return 1
    fi

    local nsteps=$((days * 86400 / tstep))
    local nstop=$nsteps

    sed_inplace \
    -e "s/^([[:space:]]*NSTART[[:space:]]*=).*/\1 0/" \
    -e "s/^([[:space:]]*NSTOP[[:space:]]*=).*/\1 ${nstop}/" \
    -e "s/^([[:space:]]*NINDAT[[:space:]]*=).*/\1 ${year}0101/" \
    -e "s/^([[:space:]]*IFYYYY[[:space:]]*=).*/\1 ${year}/" \
    -e "s/^([[:space:]]*IFMM[[:space:]]*=).*/\1 1/" \
    -e "s/^([[:space:]]*IFDD[[:space:]]*=).*/\1 1/" \
    -e "s/^([[:space:]]*IFTIM[[:space:]]*=).*/\1 0000/" \
    "$file"

    echo "Configured namelist for year $year (${days} days, full-year endpoint included, NSTOP=${nstop})"
}

patch_cmf_namelist_for_year() {
    local file=$1
    local year=$2
    local tcoupfreq=$3

    # CaMa-Flood's own NSIMTIME, independent of ecLand's NINDAT/NSTOP:
    # run the full calendar year, 00Z Jan 1 through 00Z Dec 31 (EHOUR
    # stays 00, from the template, and is not patched here). This mirrors
    # ecLand's own per-year NSTOP (see patch_namelist_for_year): the
    # forcing's extra endpoint at next-year 01-01 00Z is not stepped.
    #
    # IFRQ_INP/DROFUNIT are derived from ecLand's own TCOUPFREQ (hours)
    # rather than left as static template values, so the two namelists
    # can't silently drift out of sync with each other.
    local drofunit=$((tcoupfreq * 3600))

    sed_inplace \
    -e "s/^([[:space:]]*SYEAR[[:space:]]*=).*/\1 ${year}/" \
    -e "s/^([[:space:]]*SMON[[:space:]]*=).*/\1 01/" \
    -e "s/^([[:space:]]*SDAY[[:space:]]*=).*/\1 01/" \
    -e "s/^([[:space:]]*EYEAR[[:space:]]*=).*/\1 ${year}/" \
    -e "s/^([[:space:]]*EMON[[:space:]]*=).*/\1 12/" \
    -e "s/^([[:space:]]*EDAY[[:space:]]*=).*/\1 31/" \
    -e "s/^([[:space:]]*IFRQ_INP[[:space:]]*=).*/\1 ${tcoupfreq}/" \
    -e "s/^([[:space:]]*DROFUNIT[[:space:]]*=).*/\1 ${drofunit}./" \
    -e "s/^([[:space:]]*DT[[:space:]]*=).*/\1 ${drofunit}/" \
    "$file"

    echo "Configured CaMa-Flood namelist for year $year (${year}0101-${year}1231, IFRQ_INP=${tcoupfreq}h)"
}

# -------------------------
# Validation
# -------------------------
[[ -f "$NAMELIST" ]] || { echo "ERROR: required file not found: $NAMELIST" >&2; exit 1; }

RUN_CMF=false
if grep -qiE '^[[:space:]]*LECMF1WAY[[:space:]]*=[[:space:]]*\.?true\.?' "$NAMELIST"; then
    RUN_CMF=true
    echo "LECMF1WAY is on in $NAMELIST: CaMa-Flood coupling enabled."
fi

required_files=("$NAMELIST" "$ECLAND_EXE" "$SURFCLIM_SOURCE" "$SOILINIT_SOURCE")
if [[ "$RUN_CMF" == "true" ]]; then
    required_files+=("$CMF_NAMELIST")
    for f in "${CMF_STATIC_FILES[@]}"; do
        required_files+=("${CMF_STATIC_DIR}/${f}")
    done
fi

for f in "${required_files[@]}"; do
    if [[ ! -e "$f" ]]; then
        echo "ERROR: required file not found: $f" >&2
        exit 1
    fi
done

if [[ ! -x "$ECLAND_EXE" ]]; then
    echo "ERROR: ecLand executable is not executable: $ECLAND_EXE" >&2
    exit 1
fi

CMF_TCOUPFREQ=""
if [[ "$RUN_CMF" == "true" ]]; then
    # TCOUPFREQ (hours): how often ecLand hands accumulated runoff off to
    # CaMa-Flood. This is unrelated to ecLand's own TSTEP -- CaMa-Flood
    # substeps adaptively (LADPSTP=.TRUE. in namelist/input_cmf) between
    # coupling exchanges. IFRQ_INP/DROFUNIT in the CaMa-Flood namelist
    # must track it, so it's read once here and applied per year in
    # patch_cmf_namelist_for_year rather than kept in sync by hand.
    CMF_TCOUPFREQ=$(nml_value TCOUPFREQ "$NAMELIST")
    if [[ -z "$CMF_TCOUPFREQ" ]]; then
        echo "ERROR: could not read TCOUPFREQ from $NAMELIST" >&2
        exit 1
    fi
fi

shopt -s nullglob
forcing_files=("${FORCING_DIR}"/WFDE5_CRU_GPCC_????_ecland.nc)
shopt -u nullglob

if (( ${#forcing_files[@]} == 0 )); then
    echo "ERROR: no forcing files found under $FORCING_DIR" >&2
    exit 1
fi

IFS=$'\n' forcing_files=($(printf '%s\n' "${forcing_files[@]}" | sort))
unset IFS

# START_YEAR/END_YEAR: restrict the annual loop to a sub-range, for resuming
# a run that hit its time limit partway through without redoing already-
# completed years. Pair with INITIAL_RESTART(_CMF) pointing at the last
# completed year's restart so the resumed run continues the same chain
# rather than cold-starting. Both default to unrestricted (all years found),
# so this changes nothing for a normal from-scratch run.
if [[ -n "${START_YEAR:-}" || -n "${END_YEAR:-}" ]]; then
    filtered=()
    for f in "${forcing_files[@]}"; do
        b=$(basename "$f")
        [[ "$b" =~ ^WFDE5_CRU_GPCC_([0-9]{4})_ecland\.nc$ ]] || continue
        y="${BASH_REMATCH[1]}"
        (( y >= ${START_YEAR:-0} )) || continue
        (( y <= ${END_YEAR:-9999} )) || continue
        filtered+=("$f")
    done
    forcing_files=("${filtered[@]}")
    if (( ${#forcing_files[@]} == 0 )); then
        echo "ERROR: START_YEAR/END_YEAR filter (${START_YEAR:-<none>}-${END_YEAR:-<none>}) matched no forcing files" >&2
        exit 1
    fi
fi

echo "Found ${#forcing_files[@]} annual forcing files:"
printf '  %s\n' "${forcing_files[@]}"

# -------------------------
# Helpers
# -------------------------
is_leap_year() {
    local year=$1
    if (( year % 400 == 0 )); then
        return 0
    elif (( year % 100 == 0 )); then
        return 1
    elif (( year % 4 == 0 )); then
        return 0
    else
        return 1
    fi
}

sed_inplace() {
    if sed --version >/dev/null 2>&1; then
        sed -i -E "$@"
    else
        sed -i '' -E "$@"
    fi
}

patch_namelist_for_year() {
    local file=$1
    local year=$2
    local days=365

    if is_leap_year "$year"; then
        days=366
    fi

    local tstep
    tstep=$(awk '
        /^[[:space:]]*TSTEP[[:space:]]*=/ {
            line = $0
            sub(/!.*/, "", line)          # remove Fortran inline comment
            sub(/^[^=]*=/, "", line)      # remove everything through "="
            gsub(/[[:space:],]/, "", line)
            print line
            exit
        } ' "$file")

    if [[ -z "$tstep" ]]; then
        echo "ERROR: could not read TSTEP from $file" >&2
        return 1
    fi

    local nsteps=$((days * 86400 / tstep))
    local nstop=$nsteps

    sed_inplace \
    -e "s/^([[:space:]]*NSTART[[:space:]]*=).*/\1 0/" \
    -e "s/^([[:space:]]*NSTOP[[:space:]]*=).*/\1 ${nstop}/" \
    -e "s/^([[:space:]]*NINDAT[[:space:]]*=).*/\1 ${year}0101/" \
    -e "s/^([[:space:]]*IFYYYY[[:space:]]*=).*/\1 ${year}/" \
    -e "s/^([[:space:]]*IFMM[[:space:]]*=).*/\1 1/" \
    -e "s/^([[:space:]]*IFDD[[:space:]]*=).*/\1 1/" \
    -e "s/^([[:space:]]*IFTIM[[:space:]]*=).*/\1 0000/" \
    "$file"

    echo "Configured namelist for year $year (${days} days, full-year endpoint included, NSTOP=${nstop})"
}

# -------------------------
# Main annual loop
# -------------------------
previous_restart="$INITIAL_RESTART"
previous_restart_cmf="$INITIAL_RESTART_CMF"

for forcing_file in "${forcing_files[@]}"; do
    base=$(basename "$forcing_file")

    if [[ "$base" =~ ^WFDE5_CRU_GPCC_([0-9]{4})_ecland\.nc$ ]]; then
        year="${BASH_REMATCH[1]}"
    else
        year=""
    fi

    if [[ ! "$year" =~ ^[0-9]{4}$ ]]; then
        echo "WARNING: cannot determine year from $base; skipping" >&2
        continue
    fi

    year_work="${WORK_ROOT}/${year}"
    year_out="${OUTPUT_ROOT}/${year}"
    year_restart="${RESTART_ROOT}/${year}"

    rm -rf "$year_work"
    mkdir -p "$year_work" "$year_out" "$year_restart"

    echo
    echo "================================================================"
    echo "Running LIAISE ecLand year ${year}"
    echo "Forcing:  $forcing_file"
    echo "Namelist: $NAMELIST"
    echo "Work:     $year_work"
    echo "================================================================"

    cd "$year_work"

    ln -sf "$SURFCLIM_SOURCE" "$SURFCLIM_RUN_NAME"
    cp -f "$NAMELIST" "$NAMELIST_RUN_NAME"
    patch_namelist_for_year "$NAMELIST_RUN_NAME" "$year"

    if [[ -z "$previous_restart" ]]; then
        ln -sf "$SOILINIT_SOURCE" "$SOILINIT_RUN_NAME"
        echo "Initial state: $SOILINIT_SOURCE"
    else
        # Continue from the previous year's restart by using it AS the
        # initial-state file (ecland_run_model.sh's RLOOP mechanism). The
        # restartin.nc + LNF=.FALSE. path is only honoured when NSTART /= 0,
        # which this script never sets, so it silently cold-started every
        # year from SOILINIT_SOURCE (found 2026-09-16). See run_liaise_ecland.sh.
        ln -sf "$previous_restart" "$SOILINIT_RUN_NAME"
        echo "Initial state (restart chain): $previous_restart -> $SOILINIT_RUN_NAME"
    fi

    if [[ "$RUN_CMF" == "true" ]]; then
        for f in "${CMF_STATIC_FILES[@]}"; do
            ln -sf "${CMF_STATIC_DIR}/${f}" "${f}"
        done
        cp -f "$CMF_NAMELIST" "$CMF_NAMELIST_RUN_NAME"
        patch_cmf_namelist_for_year "$CMF_NAMELIST_RUN_NAME" "$year" "$CMF_TCOUPFREQ"

        if [[ -z "$previous_restart_cmf" ]]; then
            sed_inplace -e 's/^([[:space:]]*LRESTART[[:space:]]*=).*/\1 false/' "$CMF_NAMELIST_RUN_NAME"
            echo "CaMa-Flood initial state: cold start"
        else
            cp -f "$previous_restart_cmf" "$CMF_RESTART_IN_NAME"
            sed_inplace -e 's/^([[:space:]]*LRESTART[[:space:]]*=).*/\1 true/' "$CMF_NAMELIST_RUN_NAME"
            echo "CaMa-Flood restart input: $previous_restart_cmf -> $CMF_RESTART_IN_NAME"
        fi
    fi

    for var in "${FORCING_VARS[@]}"; do
        ln -sf "$forcing_file" "${var}.nc"
    done

    if [[ -n "${CO2_FILE:-}" ]]; then
        ln -sf "$CO2_FILE" CO2air.nc
    fi

    log_file="${LOG_DIR}/ecland_${year}.log"
    echo Log file: $log_file

    echo "Starting ecLand at $(date -u '+%Y-%m-%dT%H:%M:%SZ')" |
    tee "$log_file"

    set +e
    # Run directly rather than via srun: this script is itself the sbatch
    # job (single task, single node -- see #SBATCH above), and launching a
    # further srun step from inside it does not reliably inherit this
    # shell's module-loaded environment (observed: the job step lands on
    # its allocated node without hpcx-openmpi's LD_LIBRARY_PATH, so
    # ECLAND_EXE fails to find libmpi even with --export=ALL).
    "$ECLAND_EXE" >> "$log_file" 2>&1
    status=$?
    set -e

    echo "ecLand finished with status $status at $(date -u '+%Y-%m-%dT%H:%M:%SZ')" |
        tee -a "$log_file"

    if (( status != 0 )); then
        echo
        echo "Last 60 lines of the ecLand log:" >&2
        tail -60 "$log_file" >&2
        cp -f "$log_file" "$year_out/"
        echo "ERROR: ecLand failed for $year with status $status" >&2
        exit "$status"
    fi

    find . -maxdepth 1 -type f \
        ! -name "$NAMELIST_RUN_NAME" \
        ! -name "$CMF_NAMELIST_RUN_NAME" \
        -exec cp -f {} "$year_out/" \;

    cp -f "$log_file" "$year_out/"

    if [[ -f "$RESTART_OUT_NAME" ]]; then
        final_restart="${year_restart}/restart_${year}1231.nc"
        cp -f "$RESTART_OUT_NAME" "$final_restart"
    else
        candidates=()
        while IFS= read -r candidate; do
            candidates+=("$candidate")
        done < <(
            find . -maxdepth 1 -type f \
                \( -iname '*restart*.nc' -o -iname '*restart*' -o -iname 'soilinit*out*' \) \
                ! -name "$RESTART_IN_NAME" | sort
        )

        if (( ${#candidates[@]} == 1 )); then
            final_restart="${year_restart}/restart_${year}1231.nc"
            cp -f "${candidates[0]}" "$final_restart"
            echo "Detected restart output: ${candidates[0]}"
        elif (( ${#candidates[@]} == 0 )); then
            echo "ERROR: no restart output found for year $year." >&2
            echo "Set RESTART_OUT_NAME to the actual ecLand restart filename." >&2
            exit 1
        else
            echo "ERROR: multiple possible restart files found for year $year:" >&2
            printf '  %s\n' "${candidates[@]}" >&2
            echo "Set RESTART_OUT_NAME explicitly." >&2
            exit 1
        fi
    fi

    previous_restart="$final_restart"
    echo "Saved annual restart: $previous_restart"

    if [[ "$RUN_CMF" == "true" ]]; then
        # CaMa-Flood names its own restart file from the (patched) EYEAR/
        # EMON/EDAY/EHOUR fields it was just run with, independently of
        # ecLand's RESTART_OUT_NAME.
        cmf_eyear=$(nml_value EYEAR "$CMF_NAMELIST_RUN_NAME")
        cmf_emon=$(nml_value EMON "$CMF_NAMELIST_RUN_NAME")
        cmf_eday=$(nml_value EDAY "$CMF_NAMELIST_RUN_NAME")
        cmf_ehour=$(nml_value EHOUR "$CMF_NAMELIST_RUN_NAME")
        cmf_restart_produced="restart${cmf_eyear}${cmf_emon}${cmf_eday}${cmf_ehour}.nc"

        if [[ ! -f "$cmf_restart_produced" ]]; then
            echo "ERROR: expected CaMa-Flood restart output not found: $cmf_restart_produced" >&2
            echo "Check EYEAR/EMON/EDAY/EHOUR in $CMF_NAMELIST_RUN_NAME against the actual output." >&2
            exit 1
        fi

        final_restart_cmf="${year_restart}/restart_cmf_${year}1231.nc"
        cp -f "$cmf_restart_produced" "$final_restart_cmf"
        previous_restart_cmf="$final_restart_cmf"
        echo "Saved annual CaMa-Flood restart: $previous_restart_cmf"
    fi
done

echo
echo "All LIAISE years completed successfully."
echo "Outputs:  $OUTPUT_ROOT"
echo "Restarts: $RESTART_ROOT"
