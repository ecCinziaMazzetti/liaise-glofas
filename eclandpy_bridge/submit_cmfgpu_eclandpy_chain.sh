#!/bin/bash
# LIAISE post-run pipeline for the eclandpy land chain -> CaMa-Flood-GPU, as one SLURM job.
# All the generic coupling lives in `eclandpy.cmfgpu` (eclandpy repo); this file is the LIAISE
# configuration of it -- which parameters.nc, which mapping, which gauges -- the way
# namelist/input_cmf configures the Fortran LECMF1WAY coupling.
#
#   1. output_gpu/<year>/o_wat.nc -> cmfgpu_runoff_gpu/runoff_<year>.nc    eclandpy.cmfgpu.runoff
#      total runoff -(Qs+Qsb): what ecLand's own coupling hands CaMa-Flood (not Qs-Qsb)
#   2. chained CaMa-Flood-GPU run, river storage carried 1988 -> 2024        eclandpy.cmfgpu.chain
#   3. hourly -> daily discharge per year, keyed by catchment_id/lon/lat    eclandpy.cmfgpu.discharge
#   4. GRDC gauge skill at the 7 LIAISE gauges (LIAISE-specific, cama_flood/skill_benchmark_*):
#      it reads the GPU side from a fixed template, so link ours in under suffix _eclandpy;
#      its "GPU" rows are then this chain, "Fortran" rows the control reference.
#
# Environment: the CaMa-Flood-GPU one (Python 3.13 + torch; eclandpy importable via PYTHONPATH or
# `pip install -e eclandpy[cmfgpu]` there), gcc/11.2.0 + cuda/12.6 for PyTorch's CUDA JIT.
# Reads only files the land run has finished writing: run it AFTER job eclpy_liaise_gpu ends.
#
# Usage: bash submit_cmfgpu_eclandpy_chain.sh [year_start] [year_end] [out_tag]

set -eu
set -o pipefail

BRIDGE_ROOT="/perm/pad/liaise-ecland/eclandpy_bridge"
ECLANDPY_SRC="/etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy/src"
CMF_INP="/perm/pad/CaMa-Flood-GPU-run/inp/liaise"
Y0="${1:-1988}"
Y1="${2:-2024}"
TAG="${3:-}"
OUT="${BRIDGE_ROOT}/cmfgpu_out_gpu${TAG}"

mkdir -p "${BRIDGE_ROOT}/logs" "${BRIDGE_ROOT}/cmfgpu_runoff_gpu" "${OUT}"

sbatch \
  --job-name="cmfgpu_eclpy" \
  --output="${BRIDGE_ROOT}/logs/cmfgpu_chain_gpu${TAG}.out" \
  --error="${BRIDGE_ROOT}/logs/cmfgpu_chain_gpu${TAG}.out" \
  --account=ecrdmocp --partition=gpu --qos=ng --gres=gpu:1 --mem=32G --time=04:00:00 \
  --nodes=1 --ntasks=1 --cpus-per-task=4 \
  --wrap="
    set -eu
    module load gcc/11.2.0
    module load cuda/12.6
    export CC=\$(which gcc) CXX=\$(which g++)
    export PYTHONPATH='${ECLANDPY_SRC}'
    cd '${BRIDGE_ROOT}'
    for y in \$(seq ${Y0} ${Y1}); do
      src=output_gpu/\$y/o_wat.nc; dst=cmfgpu_runoff_gpu/runoff_\$y.nc
      [ -f \"\$src\" ] || { echo \"MISSING \$src -- land run incomplete\"; exit 1; }
      [ -f \"\$dst\" ] || python3 -m eclandpy.cmfgpu.runoff --o-wat \"\$src\" --out \"\$dst\"
    done
    python3 -m eclandpy.cmfgpu.chain \
      --parameters '${CMF_INP}/parameters_liaise.nc' --mapping '${CMF_INP}/runoff_mapping_liaise.npz' \
      --runoff-dir cmfgpu_runoff_gpu --out-dir '${OUT}' --years ${Y0} ${Y1} --experiment eclandpy_liaise
    for y in \$(seq ${Y0} ${Y1}); do
      python3 -m eclandpy.cmfgpu.discharge \
        --hourly '${OUT}'/eclandpy_liaise_\$y/total_outflow_mean_rank0.nc \
        --parameters '${CMF_INP}/parameters_liaise.nc' \
        --out '${OUT}'/eclandpy_liaise_\$y\_discharge_daily.nc \
        --note 'eclandpy gt:gpu land run, -(Qs+Qsb), river storage chained from 1988 (eclandpy.cmfgpu)'
    done
    cd /perm/pad/liaise-ecland/cama_flood
    for y in 1988 1995 2000 2003 2005; do
      ln -sf '${OUT}'/eclandpy_liaise_\$y\_discharge_daily.nc \
        /perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_\$y\_discharge_daily_spunup_eclandpy${TAG}.nc
    done
    python3 skill_benchmark_fortran_vs_gpu.py --gpu-suffix _eclandpy${TAG}
  "

echo "Submitted. Check with: squeue -u \$USER -n cmfgpu_eclpy"
