#!/bin/bash
# GPU (gt:gpu, one A100) variant of submit_eclandpy_liaise_control.sh: the full 37-year
# (1988-2024) eclandpy LIAISE control run as ONE SLURM job, year-by-year restart chain
# in-process (see run_eclandpy_liaise_control.py). Serial by construction (each year needs the
# previous year's restart), so one GPU, one process.
#
# Writes to output_gpu/ and restart_gpu/ -- NOT the output/ + restart/ of the CPU run
# (1988-2014 completed there, pre-merge cy50r1, gt:cpu_kfirst); keep the two apart.
#
# Environment (each line was needed, found the hard way on the A100 nodes, 2026-09-14):
#   gcc/11.2.0      nvcc's host compiler must be gcc 9..11 (system 8.5 too old for the C++17
#                   headers, nvcc 12.x rejects gcc > 11)
#   cuda/12.6       system default nvcc is 11.6; gt4py's gt:gpu needs a 12.x toolkit
#   LD_LIBRARY_PATH the .so gt4py builds with gcc 11 needs GLIBCXX_3.4.26 at load time;
#                   the system /lib64/libstdc++ (gcc 8.5) lacks it
#   unset GT4PY_EXTRA_COMPILE_ARGS  gt4py appends it verbatim to the nvcc line, which rejects
#                   the host-compiler -f flags the CPU runs use with icpx
#   --mem=64G       partition default is 8G; nvcc on the largest stencil (srfwexc_vg_phase4a)
#                   gets OOM-killed under it (nodes have 480G)
#   --qos=ng        the only QOS granted to ecrdmocp on the gpu partition (2-day cap)
# venv: .venv-physics with cupy-cuda12x==13.6.0 (14.x needs numpy>=2, which breaks
#   ifs-physics-common's numpy<2 pin) and nanobind==1.9.2 (pyproject's [gpu-cuda12x] extra).
#
# First job compiles every stencil for gt:gpu (slow, ~1h+, cached in .gt_cache/py311_1013/gtgpu
# on NFS, reused by later jobs). Do NOT edit /perm/pad/ecland-porting or reinstall the venv
# while this runs -- gt4py compiles lazily from on-disk source.
#
# Usage: bash submit_eclandpy_liaise_control_gpu.sh [year_start] [year_end]
#   e.g. `... 1998 2024` resumes a chain whose restart_gpu/eclandpy_restart_1997.pkl exists
#   (run_eclandpy_liaise_control.py restores year_start-1's restart if present).

set -eu
set -o pipefail

ECLANDPY_ROOT="/etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy"
BRIDGE_ROOT="/perm/pad/liaise-ecland/eclandpy_bridge"
Y0="${1:-1988}"
Y1="${2:-2024}"

mkdir -p "${BRIDGE_ROOT}/logs" "${BRIDGE_ROOT}/output_gpu" "${BRIDGE_ROOT}/restart_gpu"

sbatch \
  --job-name="eclpy_liaise_gpu" \
  --output="${BRIDGE_ROOT}/logs/control_run_gpu.out" \
  --error="${BRIDGE_ROOT}/logs/control_run_gpu.out" \
  --account=ecrdmocp \
  --partition=gpu \
  --qos=ng \
  --gres=gpu:1 \
  --mem=64G \
  --time=2-00:00:00 \
  --nodes=1 \
  --ntasks=1 \
  --cpus-per-task=4 \
  --wrap="
    set -eu
    module load gcc/11.2.0
    module load cuda/12.6
    export CC=\$(which gcc) CXX=\$(which g++) CUDAHOSTCXX=\$(which g++)
    export LD_LIBRARY_PATH=\$(dirname \"\$(dirname \"\$(which gcc)\")\")/lib64:\${LD_LIBRARY_PATH:-}
    unset GT4PY_EXTRA_COMPILE_ARGS
    cd '${ECLANDPY_ROOT}'
    source .venv-physics/bin/activate
    export ECLAND_BACKEND=gt:gpu
    export ECLAND_PRECISION=double
    export OMP_NUM_THREADS=4
    nvidia-smi -L
    python3 '${BRIDGE_ROOT}/run_eclandpy_liaise_control.py' \
      --year-start ${Y0} --year-end ${Y1} \
      --out-root '${BRIDGE_ROOT}/output_gpu' --restart-root '${BRIDGE_ROOT}/restart_gpu'
  "

echo "Submitted. Check with: squeue -u \$USER -n eclpy_liaise_gpu"
