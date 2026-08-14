#!/usr/bin/env bash
set -euo pipefail

# Post-process LIAISE ecLand daily station files.
#
# Required convention:
#   EcLand_WFDE5_CRU_GPCC_19890901_20131231_1D_<Variable>.nc
#
# Each physical variable is stored in a separate NetCDF file. Inside each
# file, the station time series are variables named STxxxxxxx.
#
# Usage:
#   ./postprocess_liaise_ecland.sh [INPUT_DIR] [OUTPUT_DIR]
#
# Example:
#   ./postprocess_liaise_ecland.sh \
#       /path/to/ecLand/files \
#       /path/to/LIAISE/TS_DA
#
# Environment options:
#   OVERWRITE=1   replace existing output files (default: 0)
#   CHECK_TIME=1  require time dimension length 8888 (default: 1)

INPUT_DIR=${1:-.}
OUTPUT_DIR=${2:-./TS_DA}
OVERWRITE=${OVERWRITE:-0}
CHECK_TIME=${CHECK_TIME:-1}

MODEL="EcLand"
EXPERIMENT="WFDE5_CRU_GPCC"
START_DATE="19890901"
END_DATE="20131231"
SAMPLING="1D"
EXPECTED_TIME=8888

VARIABLES=(
    ESoil
    Evap
    fldfrc
    LWnet
    PotEvap
    Qh
    Qle
    Qsb
    Qs
    RadTmax
    RadTmin
    RadT
    Rainf
    Snowf
    SubSnow
    SWE
    SWnet
    TVeg
)

# Variables whose station-series units must follow the ALMA convention
# used by the original processing script.
MASS_FLUX_VARIABLES=(
    ESoil
    Evap
    PotEvap
    Qsb
    Qs
    Rainf
    Snowf
    SubSnow
    TVeg
)

for command in ncdump ncatted cp mkdir awk grep sed; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "ERROR: required command not found: ${command}" >&2
        exit 1
    fi
done

mkdir -p "${OUTPUT_DIR}"

is_mass_flux_variable() {
    local wanted=$1
    local item
    for item in "${MASS_FLUX_VARIABLES[@]}"; do
        [[ ${item} == "${wanted}" ]] && return 0
    done
    return 1
}

extract_station_variables() {
    # Extract data-variable declarations such as:
    #   double ST6124441(ST6124441) ;
    # and print only the variable names.
    awk '
        /^variables:/ { in_variables=1; next }
        in_variables && /^[[:space:]]*(byte|short|int|int64|float|double|char|string)[[:space:]]+ST[0-9]+\(/ {
            line=$0
            sub(/^[[:space:]]*(byte|short|int|int64|float|double|char|string)[[:space:]]+/, "", line)
            sub(/\(.*/, "", line)
            print line
        }
    '
}

normalise_mass_flux_units() {
    local file=$1
    local header station_var
    local -a edits=()
    local chunk_size=100

    header=$(ncdump -h "${file}")

    while IFS= read -r station_var; do
        [[ -n ${station_var} ]] || continue
        edits+=( -a "units,${station_var},o,c,kg m-2 s-1" )

        # Keep command lines compact for files containing hundreds of stations.
        if (( ${#edits[@]} >= chunk_size * 2 )); then
            ncatted -O -h "${edits[@]}" "${file}"
            edits=()
        fi
    done < <(printf '%s\n' "${header}" | extract_station_variables)

    if (( ${#edits[@]} > 0 )); then
        ncatted -O -h "${edits[@]}" "${file}"
    fi
}

processed=0
missing=0

for variable in "${VARIABLES[@]}"; do
    filename="${MODEL}_${EXPERIMENT}_${START_DATE}_${END_DATE}_${SAMPLING}_${variable}.nc"
    source_file="${INPUT_DIR}/${filename}"
    output_file="${OUTPUT_DIR}/${filename}"

    echo "==> ${variable}"

    if [[ ! -f ${source_file} ]]; then
        echo "    WARNING: missing input file: ${source_file}" >&2
        ((missing += 1))
        continue
    fi

    if [[ -e ${output_file} && ${OVERWRITE} != 1 ]]; then
        echo "    SKIP: output exists (set OVERWRITE=1 to replace it)"
        continue
    fi

    header=$(ncdump -h "${source_file}")

    station_count=$(printf '%s\n' "${header}" | extract_station_variables | awk 'END { print NR+0 }')
    if (( station_count == 0 )); then
        echo "    ERROR: no STxxxxxxx station variables found" >&2
        exit 1
    fi

    time_length=$(printf '%s\n' "${header}" |
        sed -nE 's/^[[:space:]]*time[[:space:]]*=[[:space:]]*([0-9]+)[[:space:]]*;.*/\1/p' |
        head -n 1)

    if [[ -z ${time_length} ]]; then
        echo "    ERROR: could not determine the time dimension" >&2
        exit 1
    fi

    if [[ ${CHECK_TIME} == 1 && ${time_length} -ne ${EXPECTED_TIME} ]]; then
        echo "    ERROR: time dimension is ${time_length}; expected ${EXPECTED_TIME}" >&2
        exit 1
    fi

    cp -f -- "${source_file}" "${output_file}"

    if is_mass_flux_variable "${variable}"; then
        echo "    normalising units of ${station_count} station variables to kg m-2 s-1"
        normalise_mass_flux_units "${output_file}"
    else
        echo "    preserving existing units for ${station_count} station variables"
    fi

    # Verify that the resulting file remains readable.
    ncdump -h "${output_file}" >/dev/null

    echo "    wrote: ${output_file}"
    ((processed += 1))
done

echo
echo "Post-processing complete"
echo "  processed : ${processed}"
echo "  missing   : ${missing}"
echo "  output    : ${OUTPUT_DIR}"

if (( missing > 0 )); then
    exit 2
fi
