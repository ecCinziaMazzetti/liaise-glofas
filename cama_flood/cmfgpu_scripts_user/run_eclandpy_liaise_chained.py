# LICENSE HEADER MANAGED BY add-license-header
# Copyright (c) 2025 Shengyu Kang (Wuhan University)
# Licensed under the Apache License, Version 2.0
# http://www.apache.org/licenses/LICENSE-2.0
#
"""LIAISE regional CaMa-Flood-GPU run, driven by eclandpy's (not Fortran
ecLand's) own Qs/Qsb runoff, chained continuously across a real multi-year
range -- the CaMa-Flood-GPU counterpart of
`/perm/pad/liaise-ecland/eclandpy_bridge/run_eclandpy_liaise_control.py`'s
land-surface restart chain.

Differs from `run_liaise_year_spinup.py` (this directory) in one way: that
script does a 2-PASS SAME-YEAR spin-up (run year Y twice, seeded from its
own end state) because it only ever had 5 independent comparison years of
Fortran-driven runoff. Here, eclandpy produces a genuine continuous
multi-year runoff series (1988-2024), so river storage is instead chained
FORWARD across real years -- `model.save_state()`'s end-of-year `InputProxy`
seeds the next calendar year directly, exactly mirroring how the land-
surface driver chains `OfflineState` across years. This is the more
physically correct spin-up: real antecedent river conditions from the
previous year, not an artificial repeat of the same year's forcing twice.

Runoff source: /perm/pad/liaise-ecland/eclandpy_bridge/cmfgpu_runoff/runoff_<year>.nc
(built by cama_flood/prepare_liaise_runoff_for_cmfgpu.py from eclandpy's own
o_wat.nc -- same -(Qs+Qsb) formula, same schema, as the Fortran-driven
runoff files this checkout's own scripts_user/*.py already consume).
"""
import argparse
from contextlib import nullcontext
from datetime import datetime, timedelta

import torch
import torch.distributed as dist
from hydroforge.data import InputProxy, setup_distributed
from hydroforge.data.datasets import NetCDFDataset
from torch.utils.data import DataLoader

from cmfgpu.models import CaMaFlood

OUTPUT_DIR = "/perm/pad/liaise-ecland/eclandpy_bridge/cmfgpu_out"
OPENED_MODULES = ("base", "adaptive_time", "bifurcation")
VARIABLES_TO_SAVE = {
    "mean": ["total_outflow"],
    "last": ["river_depth"],
}
UNIT_FACTOR = 1000.0  # kg m-2 s-1 -> m s-1
BLOCK_SIZE = 128
RUNOFF_DIR = "/perm/pad/liaise-ecland/eclandpy_bridge/cmfgpu_runoff"
RUNOFF_MAPPING_FILE = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_mapping_liaise.npz"
PARAMETERS = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc"


def _run_year(*, input_proxy: InputProxy, year: int, device,
              runoff_dir: str = RUNOFF_DIR, out_dir: str = OUTPUT_DIR) -> InputProxy:
    dataset = NetCDFDataset(
        base_dir=runoff_dir,
        start_date=datetime(year, 1, 1, 1, 0, 0),
        end_date=datetime(year, 12, 31, 23, 0, 0),
        time_interval=timedelta(hours=1),
        spin_up_cycles=0,
        model_step=timedelta(hours=1),
        unit_factor=UNIT_FACTOR,
        var_name="Runoff",
        prefix="runoff_",
        suffix=".nc",
        clip_negative=True,
    )
    schedule = dataset.simulation_schedule

    model = CaMaFlood(
        device=device,
        experiment_name=f"eclandpy_liaise_{year}",
        input_proxy=input_proxy,
        output_dir=out_dir,
        opened_modules=OPENED_MODULES,
        variables_to_save=VARIABLES_TO_SAVE,
        output_workers=2,
        BLOCK_SIZE=BLOCK_SIZE,
        output_split_by_year=False,
        simulation_schedule=schedule,
        checkpoint_netcdf_options={},  # see run_liaise_year_spinup.py: Blosc small-buffer fix
    )
    local_mapping = dataset.build_local_mapping(
        mapping_file=RUNOFF_MAPPING_FILE,
        desired_catchment_ids=model.base.catchment_id.to("cpu").numpy(),
        device=device,
    )
    loader = DataLoader(dataset, batch_size=None, shuffle=False, num_workers=0,
                         pin_memory=device.type == "cuda")
    stream_ctx = (torch.cuda.stream(torch.cuda.Stream(device=device))
                  if device.type == "cuda" else nullcontext())
    for runoff_chunk in loader:
        with stream_ctx:
            runoff_chunk = dataset.shard_forcing(
                runoff_chunk.to(device, non_blocking=device.type == "cuda"), local_mapping,
            )
            for runoff in runoff_chunk:
                model.set_inputs(runoff=runoff)
                model.step_advance(num_sub_steps=None)
    end_state = model.save_state()
    model.close()
    dataset.close()
    return end_state


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year-start", type=int, required=True)
    p.add_argument("--year-end", type=int, required=True)
    p.add_argument("--runoff-dir", default=RUNOFF_DIR,
                   help="dir of runoff_<year>.nc from prepare_liaise_runoff_for_cmfgpu.py")
    p.add_argument("--out-dir", default=OUTPUT_DIR, help="CaMa-Flood-GPU output_dir")
    p.add_argument("--parameters", default=PARAMETERS, help="regional parameters.nc")
    args = p.parse_args()

    distributed = setup_distributed(allowed_devices=("cuda", "mps", "cpu"))
    device = distributed.device

    state = InputProxy.from_nc(args.parameters)
    for year in range(args.year_start, args.year_end + 1):
        print(f"[eclandpy-cmfgpu] year={year} device={device}")
        state = _run_year(input_proxy=state, year=year, device=device,
                          runoff_dir=args.runoff_dir, out_dir=args.out_dir)

    if distributed.world_size > 1:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
