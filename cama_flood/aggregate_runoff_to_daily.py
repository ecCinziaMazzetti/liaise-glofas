#!/usr/bin/env python3
"""Aggregate hourly LIAISE runoff forcing to daily-mean, matching TCOUPFREQ=24.

Why this exists
----------------
Setup-difference audit (2026-09-13, see CLAUDE.md): the Fortran
`LECMF1WAY` reference couples ecLand to CaMa-Flood once every
`TCOUPFREQ=24` hours (`namelist/input`) -- CaMa-Flood receives one
runoff rate per day, then substeps adaptively (CFL, `LADPSTP=.TRUE.`)
within that fixed 24h window (`DT=86400` in `namelist/input_cmf`). The
GPU driver (`run_liaise_year_spinup.py`) instead fed genuinely hourly
runoff (`runoff_<year>.nc`, one value per hour, `RUNOFF_TIME_INTERVAL=
timedelta(hours=1)`) -- a real forcing-frequency mismatch, not just a
namelist artifact (confirmed both sides' runoff ultimately come from the
same ecLand `o_wat.nc`, just resampled differently before reaching each
router).

This script closes that gap: takes `prepare_liaise_runoff_for_cmfgpu.py`'s
existing hourly output and produces a daily-mean version with the SAME
rate (`kg m-2 s-1`) held constant across each day -- not a different
total depth, just coarser time resolution, matching what CaMa-Flood
actually receives from ecLand under `TCOUPFREQ=24` (a single rate per
coupling window, not an instantaneous hourly value).

Usage
-----
    python3 aggregate_runoff_to_daily.py \\
        --hourly /perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_2000.nc \\
        --out /perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_2000_daily.nc
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def aggregate(hourly_path: Path, out_path: Path) -> None:
    with Dataset(hourly_path, "r") as src:
        runoff = np.ma.filled(src.variables["Runoff"][:], 0.0).astype(np.float64)
        lat = np.asarray(src.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(src.variables["lon"][:], dtype=np.float64)
        time = np.asarray(src.variables["time"][:])
        time_units = src.variables["time"].units
        time_calendar = getattr(src.variables["time"], "calendar", "standard")

    n_hours = runoff.shape[0]
    if n_hours % 24 != 0:
        raise ValueError(
            f"{hourly_path}: {n_hours} hourly steps is not a multiple of "
            "24 -- can't cleanly aggregate to daily"
        )
    n_days = n_hours // 24

    daily = runoff.reshape(n_days, 24, *runoff.shape[1:]).mean(axis=1).astype(np.float32)
    # hydroforge's DatasetTimeline does EXACT datetime lookups (start_date
    # + n*time_interval decoded against this file's own `time` var via
    # num2date, not positional indexing) -- so this must land on exactly
    # midnight of each day (`start_date=datetime(year,1,1,0,0,0)`,
    # time_interval=24h), NOT the source file's own hour-1 label
    # (`time[0]==3600`, since the hourly file has no t=0 entry). Source
    # units are confirmed "seconds since <year>-01-01 00:00:00" for every
    # year here, so day i's midnight is exactly i*86400 in that same unit
    # -- not derived from the hourly file's own (offset-by-1h) timestamps.
    daily_time = np.arange(n_days, dtype=np.float64) * 86400.0

    with Dataset(out_path, "w", format="NETCDF4") as dst:
        dst.createDimension("time", n_days)
        dst.createDimension("lat", lat.size)
        dst.createDimension("lon", lon.size)

        tvar = dst.createVariable("time", "f8", ("time",))
        tvar[:] = daily_time
        tvar.units = time_units
        tvar.calendar = time_calendar

        latvar = dst.createVariable("lat", "f8", ("lat",))
        latvar[:] = lat
        latvar.units = "degrees_north"

        lonvar = dst.createVariable("lon", "f8", ("lon",))
        lonvar[:] = lon
        lonvar.units = "degrees_east"

        rvar = dst.createVariable(
            "Runoff", "f4", ("time", "lat", "lon"), zlib=True, complevel=4,
        )
        rvar[:, :, :] = daily
        rvar.units = "kg m-2 s-1"
        rvar.long_name = (
            "Total runoff (Qs - Qsb), daily mean -- matches TCOUPFREQ=24 "
            "coupling frequency in the Fortran LECMF1WAY reference"
        )
        rvar.source_file = str(hourly_path)

    # Volume-conservation check: daily-mean aggregation must not change
    # the total annual depth versus the hourly source.
    hourly_total = runoff.sum()
    daily_total = (daily.astype(np.float64) * 24).sum()
    rel_diff = abs(daily_total - hourly_total) / hourly_total
    print(f"Wrote {out_path}: {n_days} days x {lat.size} x {lon.size}")
    print(f"  volume check: hourly_sum={hourly_total:.6e} daily_sum*24={daily_total:.6e} "
          f"rel_diff={rel_diff:.2e}" + ("  OK" if rel_diff < 1e-6 else "  MISMATCH"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hourly", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    aggregate(args.hourly, args.out)


if __name__ == "__main__":
    main()
