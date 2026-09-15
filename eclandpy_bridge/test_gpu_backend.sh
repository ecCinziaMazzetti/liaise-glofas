#!/bin/bash
set -eu
module load gcc/11.2.0
module load cuda/12.6
export CC=$(which gcc) CXX=$(which g++)
export CUDAHOSTCXX=$(which g++)
export LD_LIBRARY_PATH=$(dirname "$(dirname "$(which gcc)")")/lib64:${LD_LIBRARY_PATH:-}  # runtime libstdc++ must match the gcc that built the .so (GLIBCXX_3.4.26)
cd /etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy
source .venv-physics/bin/activate
python3 -c "import cupy; print('cupy sees', cupy.cuda.runtime.getDeviceCount(), 'GPU(s):', cupy.cuda.runtime.getDeviceProperties(0)['name'])"
export ECLAND_BACKEND=gt:gpu
export ECLAND_PRECISION=double
# gcc-compatible (the clang-only -fbracket-depth/-fconstexpr-steps used with icpx would fail g++)
unset GT4PY_EXTRA_COMPILE_ARGS  # passed verbatim to nvcc, which rejects host -f flags
python3 - <<'PY'
import time
from eclandpy.physics import ecland_porting_adapter as adapter
t0 = time.time()
physics_run = adapter.build(
    plumber2_root="/perm/pad/plumber2-ecland", site="AR-SLu",
    initial_date=20100101, final_date=20100102, group="PLUMBER2", forcing_type="insitu",
)
t1 = time.time()
physics_run.driver.run(48)
t2 = time.time()
print(f"GPU BACKEND SMOKE TEST OK: build {t1-t0:.0f}s (incl. CUDA compile), 48 steps {t2-t1:.2f}s")
PY
