#!/bin/bash
# Post-run pipeline for the eclandpy GPU LIAISE chain -> CaMa-Flood-GPU, as one SLURM job:
#   1. output_gpu/<year>/o_wat.nc  ->  cmfgpu_runoff_gpu/runoff_<year>.nc   (all years present)
#      via cama_flood/prepare_liaise_runoff_for_cmfgpu.py: total runoff = -(Qs+Qsb), the formula
#      ecLand's own LECMF1WAY coupling hands CaMa-Flood (verified vs Fortran discharge by a
#      parallel session, 2026-09-13 -- NOT the earlier Qs-Qsb).
#   2. scripts_user/run_eclandpy_liaise_chained.py (CaMa-Flood-GPU checkout): river storage
#      chained forward across all years via model.save_state(); ~1 min/year on one A100.
# Toolchain: gcc/11.2.0 + cuda/12.6 (PyTorch's CUDA JIT: gcc must be 9..11, CUDA >= 12.4 for the
# conditional-graph APIs) -- see the cmfgpu-hpc-toolchain memory / test_cmfgpu.sh.
# Reads only files the land run has finished writing: run it AFTER job eclpy_liaise_gpu ends.
#
# Usage: bash submit_cmfgpu_eclandpy_chain.sh [year_start] [year_end]

set -eu
set -o pipefail

BRIDGE_ROOT="/perm/pad/liaise-ecland/eclandpy_bridge"
CMF_ROOT="/perm/pad/CaMa-Flood-GPU"
Y0="${1:-1988}"
Y1="${2:-2024}"

mkdir -p "${BRIDGE_ROOT}/logs" "${BRIDGE_ROOT}/cmfgpu_runoff_gpu" "${BRIDGE_ROOT}/cmfgpu_out_gpu"

sbatch \
  --job-name="cmfgpu_eclpy" \
  --output="${BRIDGE_ROOT}/logs/cmfgpu_chain_gpu.out" \
  --error="${BRIDGE_ROOT}/logs/cmfgpu_chain_gpu.out" \
  --account=ecrdmocp \
  --partition=gpu \
  --qos=ng \
  --gres=gpu:1 \
  --mem=32G \
  --time=04:00:00 \
  --nodes=1 --ntasks=1 --cpus-per-task=4 \
  --wrap="
    set -eu
    module load gcc/11.2.0
    module load cuda/12.6
    export CC=\$(which gcc) CXX=\$(which g++)
    cd /perm/pad/liaise-ecland/cama_flood
    for y in \$(seq ${Y0} ${Y1}); do
      src='${BRIDGE_ROOT}'/output_gpu/\$y/o_wat.nc
      dst='${BRIDGE_ROOT}'/cmfgpu_runoff_gpu/runoff_\$y.nc
      if [ ! -f \"\$src\" ]; then echo \"MISSING \$src -- land run incomplete\"; exit 1; fi
      [ -f \"\$dst\" ] || python3 prepare_liaise_runoff_for_cmfgpu.py --o-wat \"\$src\" --out \"\$dst\"
    done
    cd '${CMF_ROOT}'
    python3 scripts_user/run_eclandpy_liaise_chained.py --year-start ${Y0} --year-end ${Y1} \
      --runoff-dir '${BRIDGE_ROOT}/cmfgpu_runoff_gpu' --out-dir '${BRIDGE_ROOT}/cmfgpu_out_gpu'
    # 3. hourly -> daily discharge per year, keyed by catchment_id/lon/lat (dashboard + GRDC scoring)
    cd /perm/pad/liaise-ecland/cama_flood
    for y in \$(seq ${Y0} ${Y1}); do
      python3 export_liaise_daily_discharge.py \
        --hourly '${BRIDGE_ROOT}'/cmfgpu_out_gpu/eclandpy_liaise_\$y/total_outflow_mean_rank0.nc \
        --parameters /perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc \
        --out '${BRIDGE_ROOT}'/cmfgpu_out_gpu/eclandpy_liaise_\$y\_discharge_daily.nc \
        --note 'eclandpy gt:gpu land run (job 36970286), -(Qs+Qsb), river storage chained 1988->'
    done
    # 4. GRDC gauge skill (KGE/NSE/PBIAS) at the 7 LIAISE gauges, 5 benchmark years, reusing
    #    skill_benchmark_fortran_vs_gpu.py unmodified: it reads the GPU side from a fixed template
    #    liaise_{y}_discharge_daily_spunup{suffix}.nc, so link ours in under suffix _eclandpy.
    #    Its \"GPU\" rows are then the eclandpy-driven chain; Fortran rows are the control reference.
    for y in 1988 1995 2000 2003 2005; do
      ln -sf '${BRIDGE_ROOT}'/cmfgpu_out_gpu/eclandpy_liaise_\$y\_discharge_daily.nc \
        /perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_\$y\_discharge_daily_spunup_eclandpy.nc
    done
    python3 skill_benchmark_fortran_vs_gpu.py --gpu-suffix _eclandpy
  "

echo "Submitted. Check with: squeue -u \$USER -n cmfgpu_eclpy"
