#!/usr/bin/env python3
"""Aggregate a CaMa-Flood-GPU LIAISE run's hourly discharge to daily means.

Companion to `subset_parameters_for_liaise.py` / `run_liaise_2000.py`
(the driver script lives in the CaMa-Flood-GPU checkout's `scripts_user/`,
since that directory is that repo's own gitignored personal-work
convention -- see its README). Produces a small, comparison-friendly
netCDF keyed by `catchment_id`, `longitude`, `latitude` for matching against
the Fortran run's own discharge output (e.g. `o_totout.nc`).

Usage
-----
    python3 export_liaise_daily_discharge.py \\
        --hourly /perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_2000/total_outflow_mean_rank0.nc \\
        --parameters /perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc \\
        --out /perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_2000_discharge_daily.nc \\
        --note "base+adaptive_time modules only, no bifurcation"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def export(
    hourly_path: Path, parameters_path: Path, out_path: Path, note: str,
) -> None:
    with Dataset(hourly_path, "r") as hourly:
        catchment_id = np.asarray(
            hourly.variables["catchment_id"][:], dtype=np.int64,
        )
        discharge = np.asarray(hourly.variables["total_outflow_mean"][:])
        time_units = hourly.variables["time"].units
        time_calendar = getattr(hourly.variables["time"], "calendar", "standard")
        time_hours = np.asarray(hourly.variables["time"][:])
        n_negative = int((discharge < 0).sum())
        n_total = int(discharge.size)

    with Dataset(parameters_path, "r") as params:
        p_catchment_id = np.asarray(
            params.variables["catchment_id"][:], dtype=np.int64,
        )
        p_lon = np.asarray(params.variables["longitude"][:])
        p_lat = np.asarray(params.variables["latitude"][:])

    id_to_lonlat = {
        int(c): (lo, la) for c, lo, la in zip(p_catchment_id, p_lon, p_lat)
    }
    missing = [int(c) for c in catchment_id if int(c) not in id_to_lonlat]
    if missing:
        raise ValueError(
            f"{len(missing)} catchment id(s) in the hourly output are not "
            f"in the parameters file; examples={missing[:5]}"
        )
    lon = np.array([id_to_lonlat[int(c)][0] for c in catchment_id])
    lat = np.array([id_to_lonlat[int(c)][1] for c in catchment_id])

    n_hours, n_catch = discharge.shape
    n_days = n_hours // 24
    if n_hours % 24:
        print(f"Note: {n_hours} hours is not a multiple of 24; dropping the "
              f"trailing {n_hours % 24} hour(s) from the daily aggregation.")
    trimmed = discharge[: n_days * 24]
    daily = trimmed.reshape(n_days, 24, n_catch).mean(axis=1)
    day_time = time_hours[: n_days * 24 : 24]

    with Dataset(out_path, "w", format="NETCDF4") as out:
        out.createDimension("catchment", n_catch)
        out.createDimension("time", n_days)

        cvar = out.createVariable("catchment_id", "i8", ("catchment",))
        cvar[:] = catchment_id
        cvar.long_name = (
            "CaMa-Flood-GPU catchment id (ix_global*global_ny + iy_global)"
        )

        lonvar = out.createVariable("longitude", "f4", ("catchment",))
        lonvar[:] = lon
        lonvar.units = "degrees_east"

        latvar = out.createVariable("latitude", "f4", ("catchment",))
        latvar[:] = lat
        latvar.units = "degrees_north"

        tvar = out.createVariable("time", "f8", ("time",))
        tvar[:] = day_time
        tvar.units = time_units
        tvar.calendar = time_calendar
        tvar.long_name = "day (timestamp of first hour in each daily mean)"

        dvar = out.createVariable(
            "discharge", "f4", ("time", "catchment"), zlib=True, complevel=4,
        )
        dvar[:, :] = daily.astype(np.float32)
        dvar.units = "m3 s-1"
        dvar.long_name = (
            "Daily-mean total_outflow (river + flood), from hourly "
            "CaMa-Flood-GPU output"
        )
        dvar.source = str(hourly_path)

        out.n_negative_hourly_values = n_negative
        out.n_hourly_values_total = n_total
        out.note = note

    print(f"Wrote {out_path}: {n_days} days x {n_catch} catchments")
    print(f"discharge stats: min={daily.min():.3f}, max={daily.max():.3f}, "
          f"mean={daily.mean():.3f} m3/s")
    print(f"hourly negative-value rate: {n_negative}/{n_total} "
          f"({100.0 * n_negative / n_total:.4f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hourly", type=Path, required=True,
                         help="Path to total_outflow_mean_rank0.nc")
    parser.add_argument("--parameters", type=Path, required=True,
                         help="Regional parameters.nc (for longitude/latitude)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--note", type=str, default="",
                         help="Free-text note stored as a global attribute")
    args = parser.parse_args()
    export(args.hourly, args.parameters, args.out, args.note)


if __name__ == "__main__":
    main()
