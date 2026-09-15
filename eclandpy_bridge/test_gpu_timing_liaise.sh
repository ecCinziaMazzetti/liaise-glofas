#!/bin/bash
set -eu
module load gcc/11.2.0
module load cuda/12.6
export CC=$(which gcc) CXX=$(which g++) CUDAHOSTCXX=$(which g++)
export LD_LIBRARY_PATH=$(dirname "$(dirname "$(which gcc)")")/lib64:${LD_LIBRARY_PATH:-}
unset GT4PY_EXTRA_COMPILE_ARGS
cd /etc/ecmwf/nfs/dh2_perm_a/pad/eclandpy
source .venv-physics/bin/activate
export ECLAND_BACKEND=${ECLAND_BACKEND:-gt:gpu}
export ECLAND_PRECISION=double
echo "backend=$ECLAND_BACKEND  gpu stencils cached: $(ls .gt_cache/py311_1013/gtgpu/stencil_validation/stencil_gt4py/stencil/ | wc -l)"
python3 - <<'PY'
import time
from eclandpy.physics import ecland_porting_adapter as adapter
t0 = time.time()
pr = adapter.build(plumber2_root="/perm/pad/liaise-ecland/eclandpy_bridge/data", site="LIAISE",
                   initial_date=19880101, final_date=19881231, group="LIAISE", forcing_type="2d")
t1 = time.time()
pr.driver.run(48)            # warm-up: any residual lazy compiles land here
t2 = time.time()
pr.driver.run(240)           # measured: 5 days on the 16x23 LIAISE grid
t3 = time.time()
print(f"LIAISE 368pts: build {t1-t0:.0f}s | warm-up 48 steps {t2-t1:.1f}s | 240 steps {t3-t2:.1f}s = {(t3-t2)/240*1000:.0f} ms/step")
PY
