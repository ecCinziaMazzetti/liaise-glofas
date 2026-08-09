#!/usr/bin/env bash
set -euo pipefail

# Install the pre-generated LIAISE ecLand ancillary files.
#
# This avoids regenerating soilinit and surfclim from MARS when running
# outside ECMWF, for example on macOS.
#
# Git LFS stores the validated files under:
#   data/soilinit
#   data/surfclim
#
# This script copies them into:
#   work/soilinit
#   work/surfclim
#
# Paths are resolved relative to this script, so it can be called from
# anywhere in the repository.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DATA_DIR="${SCRIPT_DIR}/data"
WORK_DIR="${SCRIPT_DIR}/work"

for name in soilinit surfclim; do
    file="${DATA_DIR}/${name}"
    if [[ ! -f "$file" ]]; then
        echo "ERROR: ${file} not found." >&2
        echo "Run 'git lfs pull' to retrieve the ancillary data." >&2
        exit 1
    fi
    # An unresolved Git LFS file is a small text pointer, not the real
    # binary payload. Catch that case rather than silently installing it.
    if head -c 40 "$file" | grep -q "^version https://git-lfs.github.com"; then
        echo "ERROR: ${file} is an unresolved Git LFS pointer, not the actual data." >&2
        echo "Run 'git lfs pull' to retrieve the ancillary data." >&2
        exit 1
    fi
done

mkdir -p "$WORK_DIR"

echo "Installing LIAISE ecLand ancillary files"
echo "  from: ${DATA_DIR}"
echo "  to:   ${WORK_DIR}"

cp -p "${DATA_DIR}/soilinit" "${WORK_DIR}/soilinit"
cp -p "${DATA_DIR}/surfclim" "${WORK_DIR}/surfclim"

echo
echo "Installed:"
ls -lh "${WORK_DIR}/soilinit" "${WORK_DIR}/surfclim"

echo
echo "LIAISE ancillary files are ready."
