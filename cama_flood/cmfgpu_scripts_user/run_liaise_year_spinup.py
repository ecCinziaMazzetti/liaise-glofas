# LICENSE HEADER MANAGED BY add-license-header
# Copyright (c) 2025 Shengyu Kang (Wuhan University)
# Licensed under the Apache License, Version 2.0
# http://www.apache.org/licenses/LICENSE-2.0
#

"""LIAISE regional run with a 2-pass river-storage spin-up.

`run_liaise_year.py` always starts CaMa-Flood-GPU's `river_storage`/
`river_depth` from zero (`parameters_liaise.nc`'s `init_state` fields are
all zero, since it's sliced from a freshly-built global `parameters.nc`
with no restart mechanism). The land-surface forcing driving it
(`run/output/<year>/o_wat.nc`) comes from ecLand's own continuous
1988-2014 restart chain, so it's already realistically spun up by any
given year -- but CaMa-Flood's OWN river storage was not, in every
per-year run so far. Matches the same gap the paired Fortran
`LECMF1WAY` runs had for ecLand's own land state (fixed there via
`INITIAL_RESTART`/`INITIAL_RESTART_CMF`), just on the CaMa-Flood side here.

Fix: run the SAME year twice in one process. Pass 1 starts from zero
(like `run_liaise_year.py`); `model.save_state()` returns a complete
`InputProxy` (topology + params + end-of-run state) that gets fed directly
into a second `CaMaFlood` construction for pass 2, which is what actually
gets scored. No restart file needs to be written/re-read from disk for
this -- `save_state()`'s returned proxy is reused in-process directly.
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

OUTPUT_DIR = "/perm/pad/CaMa-Flood-GPU-run/out/liaise"
OPENED_MODULES = ("base", "adaptive_time", "bifurcation")
VARIABLES_TO_SAVE = {
    "mean": ["total_outflow"],
    "last": ["river_depth"],
}
UNIT_FACTOR = 1000.0  # kg m-2 s-1 -> m s-1
BLOCK_SIZE = 128
RUNOFF_DIR = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise"
RUNOFF_MAPPING_FILE = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_mapping_liaise.npz"


def _build_dataset(
    year: int, *, time_interval: timedelta, suffix: str,
) -> NetCDFDataset:
    # Hourly: runoff_<year>.nc, first sample at hour 1 (no t=0 entry),
    # so start/end bracket 01:00 Jan 1 .. 23:00 Dec 31 (see
    # run_liaise_2000.py). Daily: runoff_<year>_daily.nc
    # (aggregate_runoff_to_daily.py), midnight-anchored, so start/end
    # bracket 00:00 Jan 1 .. 00:00 Dec 31 instead -- hydroforge's
    # DatasetTimeline does EXACT datetime lookups against each file's own
    # `time` values (not positional indexing), so these two conventions
    # must not be mixed.
    is_hourly = time_interval == timedelta(hours=1)
    end_date = datetime(year, 12, 31, 23, 0, 0) if is_hourly \
        else datetime(year, 12, 31, 0, 0, 0)
    start_date = datetime(year, 1, 1, 1, 0, 0) if is_hourly \
        else datetime(year, 1, 1, 0, 0, 0)
    return NetCDFDataset(
        base_dir=RUNOFF_DIR,
        start_date=start_date,
        end_date=end_date,
        time_interval=time_interval,
        spin_up_cycles=0,
        model_step=time_interval,
        unit_factor=UNIT_FACTOR,
        var_name="Runoff",
        prefix="runoff_",
        suffix=suffix,
        clip_negative=True,
    )


def _run_pass(
    *, input_proxy: InputProxy, experiment_name: str, year: int, device,
    time_interval: timedelta, suffix: str,
) -> InputProxy:
    dataset = _build_dataset(year, time_interval=time_interval, suffix=suffix)
    schedule = dataset.simulation_schedule

    model = CaMaFlood(
        device=device,
        experiment_name=experiment_name,
        input_proxy=input_proxy,
        output_dir=OUTPUT_DIR,
        opened_modules=OPENED_MODULES,
        variables_to_save=VARIABLES_TO_SAVE,
        output_workers=2,
        BLOCK_SIZE=BLOCK_SIZE,
        output_split_by_year=False,
        simulation_schedule=schedule,
        # Default checkpoint compression (blosc_zstd) fails with a
        # "Buffer is uncompressible" HDF error on the small bifurcation
        # arrays (36 elements) added once that module is open -- a known
        # Blosc small-buffer edge case, not specific to this data. These
        # checkpoint files are tiny either way, so just skip compression.
        checkpoint_netcdf_options={},
    )
    local_mapping = dataset.build_local_mapping(
        mapping_file=RUNOFF_MAPPING_FILE,
        desired_catchment_ids=model.base.catchment_id.to("cpu").numpy(),
        device=device,
    )

    loader = DataLoader(
        dataset, batch_size=None, shuffle=False, num_workers=0,
        pin_memory=device.type == "cuda",
    )
    stream_ctx = (
        torch.cuda.stream(torch.cuda.Stream(device=device))
        if device.type == "cuda"
        else nullcontext()
    )
    for runoff_chunk in loader:
        with stream_ctx:
            runoff_chunk = dataset.shard_forcing(
                runoff_chunk.to(device, non_blocking=device.type == "cuda"),
                local_mapping,
            )
            for runoff in runoff_chunk:
                model.set_inputs(runoff=runoff)
                model.step_advance(num_sub_steps=None)

    end_state = model.save_state()
    model.close()
    dataset.close()
    return end_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--parameters", type=str,
        default="/perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc",
        help="Regional parameters.nc to drive (varies by map-package vintage)",
    )
    parser.add_argument(
        "--tag", type=str, default="",
        help="Suffix for experiment_name/output dirs, e.g. '_v420', to keep "
             "runs from different map-package vintages from overwriting "
             "each other (default: none, matches the original v4.30 runs)",
    )
    parser.add_argument(
        "--runoff-interval-hours", type=int, default=1,
        help="Coupling interval, hours (default: 1, hourly forcing -- "
             "reads runoff_<year>.nc). Pass 24 to match the Fortran "
             "reference's TCOUPFREQ=24 (daily coupling, reads "
             "runoff_<year>_daily.nc via aggregate_runoff_to_daily.py) -- "
             "see CLAUDE.md's setup-difference audit, 2026-09-13.",
    )
    args = parser.parse_args()
    year = args.year
    tag = args.tag
    time_interval = timedelta(hours=args.runoff_interval_hours)
    # yearly_time_to_key (NetCDFDataset's default) builds each read as
    # f"{prefix}{year}{suffix}" -- folding "_daily" into suffix reproduces
    # "runoff_<year>_daily.nc" exactly (see aggregate_runoff_to_daily.py).
    suffix = ".nc" if time_interval == timedelta(hours=1) else "_daily.nc"

    distributed = setup_distributed(allowed_devices=("cuda", "mps"))
    world_size = distributed.world_size
    device = distributed.device

    print(f"[spinup] year={year} tag={tag!r} runoff_interval={time_interval} "
          f"pass 1: zero initial river storage")
    pass1_state = _run_pass(
        input_proxy=InputProxy.from_nc(args.parameters),
        experiment_name=f"liaise_{year}{tag}_pass1",
        year=year, device=device,
        time_interval=time_interval, suffix=suffix,
    )

    print(f"[spinup] year={year} tag={tag!r} runoff_interval={time_interval} "
          f"pass 2: seeded from pass 1's end state")
    _run_pass(
        input_proxy=pass1_state,
        experiment_name=f"liaise_{year}{tag}_pass2",
        year=year, device=device,
        time_interval=time_interval, suffix=suffix,
    )

    if world_size > 1:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
