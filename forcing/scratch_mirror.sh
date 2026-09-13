#!/usr/bin/env bash

# Keep a working copy of the raw forcing on $SCRATCH for prepare_liaise_forcing_ecland.py,
# and bring back only the finished, ecLand-ready (clipped/regional) forcing.
#
# WHY. prepare_liaise_forcing_ecland.py rebases the time axis and duplicates the
# final-year endpoint across the whole requested year range in one pass, so
# extending the archive (e.g. adding 2015-2024) means re-reading and re-writing
# every year's file, not just the new ones -- genuinely I/O-heavy NetCDF work.
# $PERM is a single NFS filer; $SCRATCH is Lustre. See run/scratch_mirror.sh and
# the sibling plumber2-ecland repo's scripts/scratch_mirror.sh for the measured
# PERM-vs-SCRATCH throughput numbers (530 MB/s vs 4863 MB/s at 30 concurrent
# writers) -- the same rationale applies here, just for one job instead of many.
#
# $SCRATCH is pruned automatically and is not safe for anything you want to
# keep, so the two trees are duals: raw input and the heavy pass happen there,
# only the prepared result comes back.
#
#   push : $PERM -> $SCRATCH   raw forcing (forcing/WFDE5_CRU_GPCC) and the
#                              preparation script -- everything the pass needs,
#                              nothing it produces
#   pull : $SCRATCH -> $PERM   forcing/WFDE5_CRU_GPCC_ecland only -- the
#                              clipped, ecLand-ready forcing this whole pass is
#                              actually for
#   status: what exists on each side
#
# Usage
# -----
#   forcing/scratch_mirror.sh push
#   cd $SCRATCH/liaise-ecland/forcing
#   python3 prepare_liaise_forcing_ecland.py \
#       --input-dir WFDE5_CRU_GPCC --output-dir WFDE5_CRU_GPCC_ecland \
#       --start-year 1988 --end-year 2024 --repeat-last-for-final-year
#   cd -
#   forcing/scratch_mirror.sh pull

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
PERM_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
MIRROR="${MIRROR:-${SCRATCH:?SCRATCH is not set}/$(basename "${PERM_ROOT}")}"
DRY_RUN=false

PUSH_PATHS=(forcing/WFDE5_CRU_GPCC forcing/prepare_liaise_forcing_ecland.py)
PULL_PATHS=(forcing/WFDE5_CRU_GPCC_ecland)

usage() {
  cat <<EOF
Usage: $(basename "$0") {push|pull|status} [-n] [-M MIRROR]

  push        Copy raw forcing + the prep script to the mirror (${PUSH_PATHS[*]})
  pull        Copy the finished ecLand-ready forcing back (${PULL_PATHS[*]})
  status      Show both sides without copying anything

  -n          Dry run: print what rsync would transfer
  -M MIRROR   Override the mirror root (default: \$SCRATCH/$(basename "${PERM_ROOT}"))

Mirror root: ${MIRROR}
EOF
}

rsync_dir() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  local flags=(-a --info=stats1)
  $DRY_RUN && flags+=(--dry-run -v)
  rsync "${flags[@]}" "$src" "$dst"
}

do_push() {
  echo "Pushing to ${MIRROR} ..."
  for p in "${PUSH_PATHS[@]}"; do
    local src="${PERM_ROOT}/${p}"
    [[ -e "$src" ]] || { echo "  skip (not found): $p"; continue; }
    if [[ -d "$src" ]]; then
      rsync_dir "${src}/" "${MIRROR}/${p}/"
    else
      mkdir -p "$(dirname "${MIRROR}/${p}")"
      $DRY_RUN || cp -f "$src" "${MIRROR}/${p}"
      echo "  copied file: $p"
    fi
  done
}

do_pull() {
  echo "Pulling results from ${MIRROR} ..."
  for p in "${PULL_PATHS[@]}"; do
    local src="${MIRROR}/${p}"
    [[ -e "$src" ]] || { echo "  skip (not found on mirror): $p"; continue; }
    rsync_dir "${src}/" "${PERM_ROOT}/${p}/"
  done
}

do_status() {
  show_side() {
    local label="$1" root="$2"
    echo "--- ${label} (${root}) ---"
    for p in "${PUSH_PATHS[@]}" "${PULL_PATHS[@]}"; do
      local path="${root}/${p}"
      if [[ -d "$path" ]]; then
        printf '  %-45s %s files, %s\n' "$p" "$(find "$path" -type f | wc -l)" "$(du -sh "$path" 2>/dev/null | cut -f1)"
      elif [[ -f "$path" ]]; then
        printf '  %-45s file, %s\n' "$p" "$(du -sh "$path" 2>/dev/null | cut -f1)"
      else
        printf '  %-45s (absent)\n' "$p"
      fi
    done
  }
  show_side "PERM" "${PERM_ROOT}"
  show_side "SCRATCH" "${MIRROR}"
}

ACTION="${1:-}"
shift || true
while getopts ":nM:" opt; do
  case "$opt" in
    n) DRY_RUN=true ;;
    M) MIRROR="$OPTARG" ;;
    *) usage; exit 1 ;;
  esac
done

case "$ACTION" in
  push) do_push ;;
  pull) do_pull ;;
  status) do_status ;;
  *) usage; exit 1 ;;
esac
