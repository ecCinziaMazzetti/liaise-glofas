#!/usr/bin/env python3
"""
Prepare annual LIAISE forcing files for ecLand.

For each year:
  1. Rebase the time coordinate to:
       hours since 1988-01-01 00:00:00
  2. Append one endpoint record:
       - normally the first timestep of the following year;
       - for the final requested year, optionally duplicate the final timestep
         and advance its time coordinate by one hour.

Example
-------
python3 prepare_liaise_forcing_ecland.py \
    --input-dir /perm/pad/liaise/forcing/WFDE5_CRU_GPCC \
    --output-dir /perm/pad/liaise/forcing/WFDE5_CRU_GPCC_ecland \
    --start-year 1988 \
    --end-year 2014 \
    --repeat-last-for-final-year
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, date2num, num2date


REFERENCE_UNITS = "hours since 1988-01-01 00:00:00"
REFERENCE_CALENDAR = "proleptic_gregorian"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebase and extend annual LIAISE forcing files for ecLand."
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--input-pattern",
        default="WFDE5_CRU_GPCC_{year}.nc",
    )
    parser.add_argument(
        "--output-pattern",
        default="WFDE5_CRU_GPCC_{year}_ecland.nc",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--repeat-last-for-final-year",
        action="store_true",
        help=(
            "For the final requested year only, if the following year's file "
            "is unavailable, duplicate the final forcing record and advance "
            "the appended timestamp by one hour."
        ),
    )
    return parser.parse_args()


def get_rebased_time(ds: Dataset, path: Path) -> tuple[np.ndarray, str, str]:
    if "time" not in ds.variables:
        raise ValueError(f"{path}: missing time variable")

    time_var = ds.variables["time"]
    units = getattr(time_var, "units", None)
    calendar = getattr(time_var, "calendar", REFERENCE_CALENDAR)

    if not units:
        raise ValueError(f"{path}: time variable has no units attribute")

    values = np.asarray(time_var[:], dtype=np.float64)
    if values.size < 2:
        raise ValueError(f"{path}: time axis has fewer than two records")

    dates = num2date(
        values,
        units=units,
        calendar=calendar,
        only_use_cftime_datetimes=True,
    )
    rebased = np.asarray(
        date2num(
            dates,
            units=REFERENCE_UNITS,
            calendar=REFERENCE_CALENDAR,
        ),
        dtype=np.float64,
    )

    increments = np.diff(rebased)
    if not np.allclose(increments, 1.0, atol=1.0e-8, rtol=0.0):
        raise ValueError(
            f"{path}: forcing is not strictly hourly; "
            f"increments={np.unique(np.round(increments, 10))[:20]}"
        )

    return rebased, units, calendar


def append_record_from_dataset(
    out_ds: Dataset,
    src_ds: Dataset,
    src_time_index: int,
    dst_time_index: int,
) -> None:
    for name, out_var in out_ds.variables.items():
        if name == "time" or "time" not in out_var.dimensions:
            continue
        if name not in src_ds.variables:
            raise ValueError(f"Source file is missing variable {name!r}")

        src_var = src_ds.variables[name]
        if out_var.dimensions != src_var.dimensions:
            raise ValueError(
                f"Dimension mismatch for {name}: "
                f"{out_var.dimensions} != {src_var.dimensions}"
            )

        time_axis = out_var.dimensions.index("time")

        src_slice = [slice(None)] * src_var.ndim
        src_slice[time_axis] = src_time_index

        dst_slice = [slice(None)] * out_var.ndim
        dst_slice[time_axis] = dst_time_index

        out_var[tuple(dst_slice)] = src_var[tuple(src_slice)]


def duplicate_last_record(out_ds: Dataset, dst_time_index: int) -> None:
    append_record_from_dataset(
        out_ds=out_ds,
        src_ds=out_ds,
        src_time_index=dst_time_index - 1,
        dst_time_index=dst_time_index,
    )


def prepare_year(
    *,
    year: int,
    final_year: int,
    input_dir: Path,
    output_dir: Path,
    input_pattern: str,
    output_pattern: str,
    overwrite: bool,
    repeat_last_for_final_year: bool,
) -> Path:
    current_path = input_dir / input_pattern.format(year=year)
    next_path = input_dir / input_pattern.format(year=year + 1)
    output_path = output_dir / output_pattern.format(year=year)

    if not current_path.is_file():
        raise FileNotFoundError(f"Missing current-year forcing: {current_path}")

    has_next_year = next_path.is_file()
    may_repeat_last = repeat_last_for_final_year and year == final_year

    if not has_next_year and not may_repeat_last:
        raise FileNotFoundError(
            f"Missing next-year forcing required for {year}: {next_path}"
        )

    if output_path.exists():
        if not overwrite:
            print(f"SKIP existing: {output_path}")
            return output_path
        output_path.unlink()

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_path, output_path)

    try:
        with Dataset(output_path, "r+") as out_ds:
            rebased_time, old_units, old_calendar = get_rebased_time(
                out_ds, current_path
            )

            if not out_ds.dimensions["time"].isunlimited():
                raise ValueError(
                    f"{current_path}: time dimension is not unlimited"
                )

            time_var = out_ds.variables["time"]
            old_count = rebased_time.size
            appended_time = rebased_time[-1] + 1.0

            time_var[:old_count] = rebased_time
            time_var[old_count] = appended_time
            time_var.units = REFERENCE_UNITS
            time_var.calendar = REFERENCE_CALENDAR

            if has_next_year:
                with Dataset(next_path, "r") as next_ds:
                    next_rebased, _, _ = get_rebased_time(next_ds, next_path)

                    if not np.isclose(
                        next_rebased[0], appended_time, atol=1.0e-8
                    ):
                        raise ValueError(
                            f"{next_path}: first timestamp is "
                            f"{next_rebased[0]}, expected {appended_time}"
                        )

                    append_record_from_dataset(
                        out_ds=out_ds,
                        src_ds=next_ds,
                        src_time_index=0,
                        dst_time_index=old_count,
                    )

                endpoint_description = (
                    f"appended first timestep from {next_path.name}"
                )
            else:
                duplicate_last_record(
                    out_ds=out_ds,
                    dst_time_index=old_count,
                )
                endpoint_description = (
                    "duplicated final timestep because next-year forcing "
                    "was unavailable"
                )

            out_ds.setncattr(
                "ecland_forcing_preparation",
                (
                    f"Time rebased from {old_units} ({old_calendar}) to "
                    f"{REFERENCE_UNITS}; {endpoint_description}"
                ),
            )

            print(
                f"CREATED {output_path}\n"
                f"  records: {old_count} -> {old_count + 1}\n"
                f"  time: {time_var[0]} .. {time_var[old_count]} "
                f"[{REFERENCE_UNITS}]\n"
                f"  endpoint: {endpoint_description}"
            )

    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return output_path


def main() -> None:
    args = parse_args()

    if "{year}" not in args.input_pattern:
        raise ValueError("--input-pattern must contain {year}")
    if "{year}" not in args.output_pattern:
        raise ValueError("--output-pattern must contain {year}")
    if args.end_year < args.start_year:
        raise ValueError("--end-year must be >= --start-year")

    print(f"Reference time: {REFERENCE_UNITS}")
    print(f"Years: {args.start_year}..{args.end_year}")
    print(f"Input: {args.input_dir}")
    print(f"Output: {args.output_dir}")

    for year in range(args.start_year, args.end_year + 1):
        prepare_year(
            year=year,
            final_year=args.end_year,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            input_pattern=args.input_pattern,
            output_pattern=args.output_pattern,
            overwrite=args.overwrite,
            repeat_last_for_final_year=args.repeat_last_for_final_year,
        )


if __name__ == "__main__":
    main()
