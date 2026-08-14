#!/usr/bin/env bash
set -euo pipefail

# Download WFDE5-CRU-GPCC 0.5-degree forcing from the Copernicus Climate
# Data Store (CDS) for years not covered by get_liaise_forcing_05.sh's IPSL
# mirror (1988-2014).
#
# Requires: pip install cdsapi, and a configured ~/.cdsapirc
# (https://cds.climate.copernicus.eu/how-to-api).
#
# Output files land in the same place and layout as get_liaise_forcing_05.sh
# (WFDE5_CRU_GPCC_{year}.nc under forcing/WFDE5_CRU_GPCC/), so
# prepare_liaise_forcing_ecland.py needs no changes to consume them.
#
# Optional year overrides:
#   START_YEAR=2015 END_YEAR=2024 ./get_liaise_forcing_05_cds.sh

START_YEAR=${START_YEAR:-2015}
END_YEAR=${END_YEAR:-2024}
OUTPUT_DIR=${OUTPUT_DIR:-WFDE5_CRU_GPCC}
RAW_DIR=${RAW_DIR:-WFDE5_CRU_GPCC_cds_raw}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

python3 get_liaise_forcing_05_cds.py \
    --start-year "$START_YEAR" \
    --end-year "$END_YEAR" \
    --output-dir "$OUTPUT_DIR" \
    --raw-dir "$RAW_DIR"
