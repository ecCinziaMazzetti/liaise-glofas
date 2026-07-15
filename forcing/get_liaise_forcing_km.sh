#!/usr/bin/env bash
set -euo pipefail

# Download the kilometre-scale LIAISE forcing datasets and grid metadata.
#
# Products:
#   ETHZ_Avg
#   IPSL_Alt
#   IPSL_Avg
#
# Coverage: 1988-2014, inclusive.
# Approximate forcing resolution: 3 km.
#
# Place this script in:
#   liaise/forcing/get_liase_forcing_km.sh
#
# Files are downloaded under:
#   liaise/forcing/gridinfo_km/
#   liaise/forcing/ETHZ_Avg/
#   liaise/forcing/IPSL_Alt/
#   liaise/forcing/IPSL_Avg/
#
# The script can be rerun safely. wget resumes partial downloads.
#
# Optional year overrides:
#   START_YEAR=1990 END_YEAR=2000 ./get_liase_forcing_km.sh

START_YEAR=${START_YEAR:-1988}
END_YEAR=${END_YEAR:-2014}

BASE_URL="https://data.ipsl.fr/repository/liaise"
GRIDINFO_URL="${BASE_URL}/GridInfo/"
GRIDINFO_DIR="gridinfo_km"

PRODUCTS=(
    "ETHZ_Avg"
    "IPSL_Alt"
    "IPSL_Avg"
)

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

mkdir -p "$GRIDINFO_DIR"

echo "Downloading kilometre-scale LIAISE grid information"
echo "Source: $GRIDINFO_URL"
echo "Output: ${SCRIPT_DIR}/${GRIDINFO_DIR}"
echo

wget     --recursive     --no-parent     --no-host-directories     --cut-dirs=3     --reject="index.html*"     --continue     --directory-prefix="$GRIDINFO_DIR"     "$GRIDINFO_URL"

echo
echo "Downloading kilometre-scale forcing for ${START_YEAR}-${END_YEAR}"
echo

for product in "${PRODUCTS[@]}"; do
    mkdir -p "$product"

    echo "Product: $product"

    for year in $(seq "$START_YEAR" "$END_YEAR"); do
        filename="${product}_${year}.nc"
        url="${BASE_URL}/${product}/${filename}"

        echo "  [$year] $url"

        wget             --continue             --directory-prefix="$product"             "$url"
    done

    echo
done

echo "Kilometre-scale LIAISE forcing download completed successfully."
