"""Diagnostic: does running MORE than 2 same-year passes change anything?

Answers a direct question: is the 2-pass spin-up (pass1 zero-start ->
pass2 scored) actually converged, or would NLOOP>2 keep shifting the
annual-mean discharge / PBIAS? Runs 4 passes on year 2000, v21fixdir
parameters, and reports annual-mean total_outflow + end-of-year
river_depth summary stats after each pass.
"""

import numpy as np
import torch
from hydroforge.data import InputProxy, setup_distributed

from scripts_user.run_liaise_year_spinup import _run_pass

PARAMS = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise_v21fixdir.nc"
YEAR = 2000
N_PASSES = 4


def main():
    distributed = setup_distributed(allowed_devices=("cuda", "mps"))
    device = distributed.device

    state = InputProxy.from_nc(PARAMS)
    for i in range(1, N_PASSES + 1):
        state = _run_pass(
            input_proxy=state,
            experiment_name=f"liaise_{YEAR}_nloop_pass{i}",
            year=YEAR, device=device,
        )
        rd = state.get("river_depth")
        rd_np = rd.detach().to("cpu").numpy() if hasattr(rd, "detach") else np.asarray(rd)
        print(
            f"[pass {i}] end-of-year river_depth: mean={rd_np.mean():.6f} "
            f"std={rd_np.std():.6f} max={rd_np.max():.6f}"
        )


if __name__ == "__main__":
    main()
