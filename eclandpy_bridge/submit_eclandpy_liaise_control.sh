#!/bin/bash
# Submits the full 37-year (1988-2024) eclandpy LIAISE control run as one SLURM job.
# run_eclandpy_liaise_control.py loops over years itself, chaining restarts in-process --
# this is inherently serial (each year depends on the previous year's restart), so there's
# no parallel-workers pattern to use here (unlike the PLUMBER2 42/170-site campaigns).
#
# Measured cost: ~32-33 min/year on 1 CPU core (gt:cpu_kfirst backend), tested on 1988 (cold
# start) and 1989 (restarted) -- ~20h for the full 37 years.
#
# Usage: bash submit_eclandpy_liaise_control.sh

set -eu
set -o pipefail

ECLANDPY_ROOT="/etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy"
BRIDGE_ROOT="/perm/pad/liaise-ecland/eclandpy_bridge"

mkdir -p "${BRIDGE_ROOT}/logs"

sbatch \
  --job-name="eclpy_liaise" \
  --output="${BRIDGE_ROOT}/logs/control_run.out" \
  --error="${BRIDGE_ROOT}/logs/control_run.out" \
  --account=ecrdmocp \
  --partition=par \
  --time=30:00:00 \
  --nodes=1 \
  --ntasks=1 \
  --cpus-per-task=1 \
  --wrap="
    set -eu
    module load python3/3.11.10-01
    cd '${ECLANDPY_ROOT}'
    source .venv-physics/bin/activate
    export CXX=icpx CC=icx
    export GT4PY_EXTRA_COMPILE_ARGS='-fbracket-depth=65536 -fconstexpr-steps=2000000000 -fconstexpr-depth=4096'
    export ECLAND_BACKEND=gt:cpu_kfirst
    export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

    python3 '${BRIDGE_ROOT}/run_eclandpy_liaise_control.py' --year-start 1988 --year-end 2024
  "

echo "Submitted. Check with: squeue -u \$USER"
