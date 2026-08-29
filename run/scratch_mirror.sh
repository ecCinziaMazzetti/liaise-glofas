#!/usr/bin/env bash

# Keep a working copy of this repository's run inputs on $SCRATCH and bring
# the results back.
#
# WHY. run_liaise_ecland.sh is I/O heavy relative to its tiny compute cost: a
# single sequential loop over up to 27 years, each year reading an hourly
# forcing file cover to cover and writing netCDF output/restarts, plus a
# fresh set of symlinks and namelist copies every year. $PERM is a single NFS
# filer; $SCRATCH is Lustre. Unlike plumber2-ecland's 30-way concurrent site
# runs, LIAISE's loop is single-process, so the concurrent-writer bottleneck
# that motivated that script's mirror doesn't apply here the same way -- but
# thousands of small sequential ops (hourly forcing reads x 27 years, annual
# symlink churn, the executable's own rpath'd shared-library demand-paging)
# still pay NFS's per-op latency one at a time, all of which Lustre answers
# faster. Adapted from plumber2-ecland/scripts/scratch_mirror.sh; see that
# script for the measured PERM-vs-SCRATCH throughput numbers.
#
# Unlike plumber2-ecland, raw output here is not disposable: run/output and
# (especially) run/restart are the actual deliverables -- each year's restart
# is load-bearing for the next year's run, not a regenerable derivative. So,
# opposite to that script, they are pulled back; only run/work (per-year
# scratch execution directories: symlinks, per-year namelist/forcing copies)
# is left on $SCRATCH to be pruned.
#
#   push : $PERM -> $SCRATCH   inputs and code a run needs, nothing it
#                              produces: prepared forcing, ancillary/CaMa-Flood
#                              static files, namelists, the run scripts, and
#                              the ecland executable (see ECLAND_BUILD below)
#   pull : $SCRATCH -> $PERM   results only (run/output, run/restart,
#                              run/logs) -- never run/work, which is
#                              regenerated fresh every year regardless
#   status: what exists on each side
#
# The mirror keeps this repository's layout, so run_liaise_ecland.sh works
# there unchanged given ROOT (and ECLAND_EXE, which lives outside this repo)
# pointed at the mirror -- see the push completion message for the exact
# invocation.
#
# Usage:
#   run/scratch_mirror.sh push
#   ROOT=$SCRATCH/liaise-ecland \
#     ECLAND_EXE=$SCRATCH/liaise-ecland/ecland-build/bin/ecland-master-dp \
#     ./run/run_liaise_ecland.sh
#   run/scratch_mirror.sh pull
#
# Run push/pull from a checkout of this repository (paths are resolved
# relative to this script's own location, like plumber2-ecland's).

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
PERM_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
MIRROR="${MIRROR:-${SCRATCH:?SCRATCH is not set}/$(basename "${PERM_ROOT}")}"
DRY_RUN=false

# Whole directories a run needs, copied as-is.
PUSH_DIRS=(forcing/WFDE5_CRU_GPCC_ecland cama_flood/data namelist)

# Individual files: init_clim/work/ also holds ~190MB of intermediate GRIB
# (clim_native.grb, month_alb, month_lai, ...) that run_liaise_ecland.sh
# never reads -- only soilinit/surfclim are runtime inputs, so those are
# named explicitly rather than mirroring the whole directory.
PUSH_FILES=(
  init_clim/work/soilinit
  init_clim/work/surfclim
  run/run_liaise_ecland.sh
  run/run_liaise_ecland.slurm
  run/postprocess_liaise_ecland.sh
)

# The executable counts as input. ecland-master-dp resolves its libraries
# through an $ORIGIN/../lib64 rpath (lib64 is itself a symlink to lib), so
# bin/ and lib/ have to travel together and keep their relative layout.
# Leaving them on $PERM means every year's process demand-pages program text
# and its shared objects over NFS -- the same latency this mirror otherwise
# removes, reintroduced through the loader. The build lives outside this
# repo (a sibling of liaise-ecland, matching ECLAND_EXE's own default), so
# it needs its own source variable rather than a path under PERM_ROOT.
ECLAND_BUILD="${ECLAND_BUILD:-${PERM:-/perm/${USER}}/ecland/build}"
BUILD_SUBDIRS=(bin lib lib64)
MIRROR_BUILD_REL="ecland-build"

# Results worth keeping. run/work (per-year execution directories, rebuilt
# from scratch every year by run_liaise_ecland.sh) is deliberately absent:
# it is pure scratch space, not a result.
PULL_DIRS=(run/output run/restart run/logs)

usage() {
  cat <<EOF
Usage: $(basename "$0") {push|pull|status} [-n] [-M MIRROR]

  push        Copy inputs and code to the mirror
  pull        Copy results back from the mirror (${PULL_DIRS[*]})
  status      Show both sides without copying anything

  -n          Dry run: print what rsync would transfer
  -M MIRROR   Mirror location (default: ${MIRROR})
  -h          Show this help

Deletions are never propagated: rsync runs without --delete in both
directions, so a stale file in the mirror is possible but losing a result on
pull is not.
EOF
}

ACTION="${1:-}"
[[ -n "${ACTION}" ]] && shift || true
case "${ACTION}" in
  push|pull|status) ;;
  -h|--help|help) usage; exit 0 ;;
  *) echo "ERROR: expected push, pull or status" >&2; usage >&2; exit 2 ;;
esac

while getopts ":hnM:" opt; do
  case "${opt}" in
    n) DRY_RUN=true ;;
    M) MIRROR="${OPTARG}" ;;
    h) usage; exit 0 ;;
    \?) echo "ERROR: invalid option -${OPTARG}" >&2; usage >&2; exit 2 ;;
    :) echo "ERROR: option -${OPTARG} requires an argument" >&2; usage >&2; exit 2 ;;
  esac
done

RSYNC=(rsync -a --human-readable --info=stats1 --exclude '.git' --exclude '__pycache__')
"${DRY_RUN}" && RSYNC+=(--dry-run --itemize-changes)

show_side() {
  local label=$1 root=$2 p
  echo "${label}: ${root}"
  [[ -d "${root}" ]] || { echo "  (does not exist)"; return; }
  for p in forcing/WFDE5_CRU_GPCC_ecland init_clim/work cama_flood/data \
           namelist run/output run/restart run/work run/logs \
           "${MIRROR_BUILD_REL}"; do
    if [[ -d "${root}/${p}" ]]; then
      printf '  %-30s %8s  %5s entries\n' "${p}" \
        "$(du -sh "${root}/${p}" 2>/dev/null | cut -f1)" \
        "$(find "${root}/${p}" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
    fi
  done
}

case "${ACTION}" in
  status)
    show_side "PERM   " "${PERM_ROOT}"
    echo
    show_side "SCRATCH" "${MIRROR}"
    ;;

  push)
    echo "push: ${PERM_ROOT} -> ${MIRROR}"
    mkdir -p "${MIRROR}"
    for p in "${PUSH_DIRS[@]}"; do
      if [[ ! -e "${PERM_ROOT}/${p}" ]]; then
        echo "  skip ${p} (absent here)"
        continue
      fi
      echo "  ${p}"
      mkdir -p "${MIRROR}/${p}"
      "${RSYNC[@]}" "${PERM_ROOT}/${p}/" "${MIRROR}/${p}/"
    done
    for p in "${PUSH_FILES[@]}"; do
      if [[ ! -e "${PERM_ROOT}/${p}" ]]; then
        echo "  skip ${p} (absent here)"
        continue
      fi
      echo "  ${p}"
      mkdir -p "${MIRROR}/$(dirname "${p}")"
      "${RSYNC[@]}" "${PERM_ROOT}/${p}" "${MIRROR}/${p}"
    done
    if [[ -d "${ECLAND_BUILD}" ]]; then
      echo "  ${MIRROR_BUILD_REL} (from ${ECLAND_BUILD})"
      for sub in "${BUILD_SUBDIRS[@]}"; do
        [[ -e "${ECLAND_BUILD}/${sub}" ]] || continue
        mkdir -p "${MIRROR}/${MIRROR_BUILD_REL}"
        "${RSYNC[@]}" "${ECLAND_BUILD}/${sub}" "${MIRROR}/${MIRROR_BUILD_REL}/"
      done
    else
      echo "  skip ${MIRROR_BUILD_REL} (no build at ${ECLAND_BUILD}; set ECLAND_BUILD)"
    fi
    echo
    echo "Mirror ready. Run from there, not here, e.g.:"
    echo "  cd ${MIRROR}"
    echo "  ROOT=${MIRROR} \\"
    echo "    ECLAND_EXE=${MIRROR}/${MIRROR_BUILD_REL}/bin/ecland-master-dp \\"
    echo "    ./run/run_liaise_ecland.sh"
    echo "Then pull results back with: $(basename "$0") pull"
    ;;

  pull)
    echo "pull: ${MIRROR} -> ${PERM_ROOT}"
    [[ -d "${MIRROR}" ]] || { echo "ERROR: no mirror at ${MIRROR}" >&2; exit 1; }
    n_found=0
    for p in "${PULL_DIRS[@]}"; do
      if [[ ! -d "${MIRROR}/${p}" ]]; then
        echo "  skip ${p} (not produced yet)"
        continue
      fi
      echo "  ${p}"
      mkdir -p "${PERM_ROOT}/${p}"
      "${RSYNC[@]}" "${MIRROR}/${p}/" "${PERM_ROOT}/${p}/"
      n_found=$((n_found + 1))
    done
    if [[ "${n_found}" -eq 0 ]]; then
      echo "Nothing to pull: the mirror holds no results yet." >&2
      exit 1
    fi
    echo
    echo "Results are on \$PERM. run/work stays on \$SCRATCH and will be pruned."
    ;;
esac
