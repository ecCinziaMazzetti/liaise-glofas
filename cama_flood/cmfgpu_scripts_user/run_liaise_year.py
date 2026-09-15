# LICENSE HEADER MANAGED BY add-license-header
# Copyright (c) 2025 Shengyu Kang (Wuhan University)
# Licensed under the Apache License, Version 2.0
# http://www.apache.org/licenses/LICENSE-2.0
#

"""LIAISE regional run for an arbitrary year, driven by ecLand's own
Qs-Qsb runoff. Generalizes run_liaise_2000.py (kept as-is) to take
--year, for the multi-year GRDC skill benchmark.

See /perm/pad/liaise-ecland/CLAUDE.md ("CaMa-Flood coupling" ->
"CaMa-Flood-GPU coupling prep") for the full pipeline this depends on.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    year = args.year

    ### Configuration Start ###
    experiment_name = f"liaise_{year}"
    input_file = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc"
    output_dir = "/perm/pad/CaMa-Flood-GPU-run/out/liaise"
    opened_modules = ("base", "adaptive_time", "bifurcation")
    num_sub_steps = None
    variables_to_save = {
        "mean": ["total_outflow"],
        "last": ["river_depth"],
    }
    loader_workers = 0
    output_workers = 2
    unit_factor = 1000.0  # kg m-2 s-1 -> m s-1; see prepare_liaise_runoff_for_cmfgpu.py
    BLOCK_SIZE = 128
    save_state = False

    # See run_liaise_2000.py's comment: stop one hour before the shared
    # year-boundary endpoint, regardless of leap year.
    start_date = datetime(year, 1, 1, 1, 0, 0)
    end_date = datetime(year, 12, 31, 23, 0, 0)
    runoff_dir = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise"
    runoff_mapping_file = "/perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_mapping_liaise.npz"
    runoff_time_interval = timedelta(hours=1)
    prefix = "runoff_"
    suffix = ".nc"
    var_name = "Runoff"
    output_split_by_year = False

    spin_up_cycles = 0
    ### Configuration End ###

    distributed = setup_distributed(
        allowed_devices=("cuda", "mps"),
    )
    world_size = distributed.world_size
    device = distributed.device

    input_proxy = InputProxy.from_nc(input_file)

    dataset = NetCDFDataset(
        base_dir=runoff_dir,
        start_date=start_date,
        end_date=end_date,
        time_interval=runoff_time_interval,
        spin_up_cycles=spin_up_cycles,
        model_step=runoff_time_interval,
        unit_factor=unit_factor,
        var_name=var_name,
        prefix=prefix,
        suffix=suffix,
        clip_negative=True,
    )
    schedule = dataset.simulation_schedule

    model = CaMaFlood(
        device=device,
        experiment_name=experiment_name,
        input_proxy=input_proxy,
        output_dir=output_dir,
        opened_modules=opened_modules,
        variables_to_save=variables_to_save,
        output_workers=output_workers,
        BLOCK_SIZE=BLOCK_SIZE,
        output_split_by_year=output_split_by_year,
        simulation_schedule=schedule,
    )
    local_mapping = dataset.build_local_mapping(
        mapping_file=runoff_mapping_file,
        desired_catchment_ids=model.base.catchment_id.to("cpu").numpy(),
        device=device,
    )

    loader = DataLoader(
        dataset,
        batch_size=None,
        shuffle=False,
        num_workers=loader_workers,
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
                runoff_chunk.to(
                    device,
                    non_blocking=device.type == "cuda",
                ),
                local_mapping,
            )
            for runoff in runoff_chunk:
                model.set_inputs(runoff=runoff)
                model.step_advance(
                    num_sub_steps=num_sub_steps,
                )
    if save_state:
        model.save_state()
    model.close()
    if world_size > 1:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
