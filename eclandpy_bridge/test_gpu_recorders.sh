#!/bin/bash
set -eu
module load gcc/11.2.0; module load cuda/12.6
export CC=$(which gcc) CXX=$(which g++) CUDAHOSTCXX=$(which g++)
export LD_LIBRARY_PATH=$(dirname "$(dirname "$(which gcc)")")/lib64:${LD_LIBRARY_PATH:-}
unset GT4PY_EXTRA_COMPILE_ARGS
cd /etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy; source .venv-physics/bin/activate
export ECLAND_BACKEND=gt:gpu ECLAND_PRECISION=double
rm -rf /perm/pad/liaise-ecland/eclandpy_bridge/scratch_gpu_test
python3 /perm/pad/liaise-ecland/eclandpy_bridge/run_eclandpy_liaise_control.py \
  --year-start 1988 --year-end 1989 --smoke-steps 96 \
  --out-root /perm/pad/liaise-ecland/eclandpy_bridge/scratch_gpu_test/output \
  --restart-root /perm/pad/liaise-ecland/eclandpy_bridge/scratch_gpu_test/restart
python3 - <<'PY'
import netCDF4, numpy as np, pickle
d = "/perm/pad/liaise-ecland/eclandpy_bridge/scratch_gpu_test"
ds = netCDF4.Dataset(f"{d}/output/1989/o_wat.nc"); qs = ds["Qs"][:]; qsb = ds["Qsb"][:]
print("o_wat 1989:", qs.shape, "Qs max", float(np.nanmax(qs)), "Qsb min", float(np.nanmin(qsb)), "lat var:", "lat" in ds.variables)
gg = netCDF4.Dataset(f"{d}/output/1989/o_gg.nc"); print("o_gg AvgSurfT mean", float(np.nanmean(gg["AvgSurfT"][:])))
snap = pickle.load(open(f"{d}/restart/eclandpy_restart_1989.pkl", "rb"))
print("restart types:", {k: type(v).__module__ for k, v in list(snap["prog"].items())[:3]})
print("GPU RECORDERS+RESTART OK")
PY
