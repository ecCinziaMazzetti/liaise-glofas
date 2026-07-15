#!/usr/bin/env bash
#SBATCH --job-name=liaise_ecland
#SBATCH --output=/perm/pad/liaise/run/logs/liaise_ecland_%j.out
#SBATCH --error=/perm/pad/liaise/run/logs/liaise_ecland_%j.err
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
# Usage:
#   sbatch run_liaise_ecland.slurm
#
# Override paths/settings through environment variables, e.g.:
#   ROOT=$HOME/Work/liaise \
#   ECLAND_EXE=$HOME/Work/ecland/build/bin/ecland-master \
#   sbatch run_liaise_ecland.slurm
# ----------------------------------------------------------------------

# -------------------------
# Paths
# -------------------------
WORK=${WORK:-${PERM:-/perm/$USER}}
ROOT=${ROOT:-$WORK/liaise}
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

RESTART_IN_NAME=${RESTART_IN_NAME:-restart_in.nc}
RESTART_OUT_NAME=${RESTART_OUT_NAME:-restartout.nc}

SURFCLIM_RUN_NAME=${SURFCLIM_RUN_NAME:-surfclim}
SOILINIT_RUN_NAME=${SOILINIT_RUN_NAME:-soilinit}
NAMELIST_RUN_NAME=${NAMELIST_RUN_NAME:-input}

FORCING_VARS=(Tair Qair PSurf Rainf Snowf SWdown LWdown Wind)

# -------------------------
# Runtime environment
# -------------------------
module purge
module load prgenv/intel
module load hpcx-openmpi/2.9.0
module load netcdf4

# Optional OpenMP settings
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-${SLURM_CPUS_PER_TASK:-4}}
export OMP_STACKSIZE=${OMP_STACKSIZE:-512M}

# -------------------------
# Validation
# -------------------------
for f in "$NAMELIST" "$ECLAND_EXE" "$SURFCLIM_SOURCE" "$SOILINIT_SOURCE"; do
    if [[ ! -e "$f" ]]; then
        echo "ERROR: required file not found: $f" >&2
        exit 1
    fi
done

if [[ ! -x "$ECLAND_EXE" ]]; then
    echo "ERROR: ecLand executable is not executable: $ECLAND_EXE" >&2
    exit 1
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
previous_restart=""

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
        cp -f "$previous_restart" "$RESTART_IN_NAME"
        ln -sf "$SOILINIT_SOURCE" "$SOILINIT_RUN_NAME"
        sed_inplace -e 's/^([[:space:]]*LNF[[:space:]]*=).*/\1 .FALSE./' "$NAMELIST_RUN_NAME"
        echo "Restart input: $previous_restart -> $RESTART_IN_NAME"
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
    srun \
        --ntasks="${SLURM_NTASKS:-1}" \
        --cpus-per-task="${SLURM_CPUS_PER_TASK:-${OMP_NUM_THREADS}}" \
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
done

echo
echo "All LIAISE years completed successfully."
echo "Outputs:  $OUTPUT_ROOT"
echo "Restarts: $RESTART_ROOT"
