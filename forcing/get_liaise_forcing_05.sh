#!/usr/bin/env bash
set -euo pipefail

# Download the LIAISE WFDE5-CRU-GPCC forcing at 0.5-degree resolution.
#
# Coverage: 1988-2014, inclusive.
#
# Place this script in:
#   liaise/forcing/get_liase_forcing_05.sh
#
# Files are downloaded under:
#   liaise/forcing/WFDE5_CRU_GPCC/
#
# The script can be rerun safely. wget resumes partial downloads.
#
# Optional year overrides:
#   START_YEAR=1990 END_YEAR=2000 ./get_liase_forcing_05.sh

START_YEAR=${START_YEAR:-1988}
END_YEAR=${END_YEAR:-2014}

BASE_URL="https://data.ipsl.fr/repository/liaise/WFDE5_CRU_GPCC"
OUTPUT_DIR="WFDE5_CRU_GPCC"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

command -v wget >/dev/null 2>&1 || {
    echo "ERROR: wget was not found in PATH." >&2
    exit 1
}

if (( END_YEAR < START_YEAR )); then
    echo "ERROR: END_YEAR must be >= START_YEAR." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Downloading WFDE5-CRU-GPCC forcing for ${START_YEAR}-${END_YEAR}"
echo "Output directory: ${SCRIPT_DIR}/${OUTPUT_DIR}"
echo

for year in $(seq "$START_YEAR" "$END_YEAR"); do
    filename="WFDE5_CRU_GPCC_${year}.nc"
    url="${BASE_URL}/${filename}"

    echo "[$year] $url"

    wget         --continue         --directory-prefix="$OUTPUT_DIR"         "$url"
done

echo
echo "WFDE5-CRU-GPCC download completed successfully."
