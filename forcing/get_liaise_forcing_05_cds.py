#!/usr/bin/env python3
"""
Download and assemble WFDE5-CRU-GPCC 0.5-degree forcing from the Copernicus
Climate Data Store (CDS), for years not covered by the IPSL mirror used by
get_liaise_forcing_05.sh (1988-2014).

For each requested year, this script:
  1. requests all forcing variables for that year from the CDS
     "derived-near-surface-meteorological-variables" (WFDE5) dataset,
     pre-cropped to the LIAISE bounding box via the "area" request key;
  2. extracts the downloaded archive;
  3. concatenates each variable's monthly records in time, then re-crops to
     the exact LIAISE grid used by the existing WFDE5_CRU_GPCC files;
  4. merges all variables into a single annual file, adds the fixed
     reference-height scalars (Height_Lev1=2 m, Height_Levuv=10 m), and
     writes WFDE5_CRU_GPCC_{year}.nc -- the same name and layout produced by
     get_liaise_forcing_05.sh, so prepare_liaise_forcing_ecland.py can
     consume it unmodified.

Requires:
  pip install cdsapi
  a configured ~/.cdsapirc (https://cds.climate.copernicus.eu/how-to-api)

Example
-------
python3 get_liaise_forcing_05_cds.py \
    --start-year 2015 \
    --end-year 2024 \
    --output-dir WFDE5_CRU_GPCC

Notes (confirmed against the live CDS API on 2026-08-14)
---------------------------------------------------------
- The dataset's process schema only accepts six request keys: product,
  variable, reference_dataset, year, month, version. There is no "area"
  key, so requests are always global 0.5-degree; the LIAISE crop happens
  locally after download. A single variable/month is already ~160 MB
  (global, hourly, 0.5deg), so a full 9-variable/12-month/10-year pull is
  a genuinely large download.
- "product": "wfde5" is required (omitting it, as in an earlier draft of
  this request, produces a 400 "invalid request").
- Per the dataset's declared constraints, reference_dataset="cru_and_gpcc"
  is only a valid combination with variable in {rainfall_flux,
  snowfall_flux}; every other variable (including grid_point_altitude)
  requires reference_dataset="cru". Requesting all 9 variables under one
  reference_dataset in a single call always fails with a 400 "invalid
  combination of values". This script therefore issues two requests per
  year: one reference_dataset="cru" request for the 6 dynamic
  non-precipitation variables plus grid_point_altitude, and one
  reference_dataset="cru_and_gpcc" request for rainfall_flux/
  snowfall_flux -- see build_requests().
- version="3_0" must be passed explicitly; omitting it (relying on the
  schema's advertised default) also produces a 400.
- Downloaded archives are zips containing one NetCDF file per
  variable-month, and the in-file variable name is already the short
  WFDE5 name (e.g. "Tair", "Rainf") -- confirmed for both the "cru" and
  "cru_and_gpcc" blocks. identify_variable() still matches both short and
  long CDS names defensively.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, date2num, num2date

DATASET = "derived-near-surface-meteorological-variables"

# LIAISE domain bounding box, matching the crop already applied to the
# existing WFDE5_CRU_GPCC_*.nc files (see their "history" attribute).
LIAISE_LON_MIN = -5.75
LIAISE_LON_MAX = 5.25
LIAISE_LAT_MIN = 39.25
LIAISE_LAT_MAX = 46.75

# Reference grid coordinates of the existing WFDE5_CRU_GPCC files, used to
# validate that the CDS-delivered grid lines up exactly.
LIAISE_LAT_VALUES = np.round(
    np.arange(LIAISE_LAT_MIN, LIAISE_LAT_MAX + 1.0e-6, 0.5), 2
)
LIAISE_LON_VALUES = np.round(
    np.arange(LIAISE_LON_MIN, LIAISE_LON_MAX + 1.0e-6, 0.5), 2
)

# Fixed WFDE5 reference heights (not distributed as CDS variables).
HEIGHT_LEV1 = 2.0  # m, near-surface scalar variables (Tair, Qair)
HEIGHT_LEVUV = 10.0  # m, near-surface wind

MONTHS = [f"{m:02d}" for m in range(1, 13)]

# CDS variable name -> short WFDE5 name used in the existing forcing files.
# Split by the reference_dataset value the CDS constraints require for each
# (see module docstring): "cru_and_gpcc" is only valid for the two
# precipitation variables; everything else, including the static
# grid_point_altitude, requires "cru".
CDS_VARIABLES_CRU = {
    "grid_point_altitude": "ASurf",
    "near_surface_air_temperature": "Tair",
    "near_surface_specific_humidity": "Qair",
    "near_surface_wind_speed": "Wind",
    "surface_air_pressure": "PSurf",
    "surface_downwelling_longwave_radiation": "LWdown",
    "surface_downwelling_shortwave_radiation": "SWdown",
}
CDS_VARIABLES_CRU_GPCC = {
    "rainfall_flux": "Rainf",
    "snowfall_flux": "Snowf",
}
CDS_VARIABLES = {**CDS_VARIABLES_CRU, **CDS_VARIABLES_CRU_GPCC}
STATIC_VARIABLES = {"ASurf"}
SHORT_NAMES = set(CDS_VARIABLES.values())

# Some CDS deliveries use the short WFDE5 name directly as the in-file
# variable name; others may use the long CDS name. Recognise both.
NAME_LOOKUP = {short: short for short in SHORT_NAMES}
NAME_LOOKUP.update(CDS_VARIABLES)

# Output attributes, matching the existing WFDE5_CRU_GPCC_*.nc files exactly
# (units/long_name are required for consistency; CDS-delivered attributes
# are not trusted verbatim).
VARIABLE_ATTRS = {
    "Rainf": ("kg m-2 s-1", "Rainfall Flux"),
    "Snowf": ("kg m-2 s-1", "Snowfall Flux"),
    "Tair": ("K", "Near-Surface Air Temperature"),
    "Qair": ("kg kg-1", "Near-Surface Specific Humidity"),
    "PSurf": ("Pa", "Surface Air Pressure"),
    "SWdown": ("W m-2", "Surface Downwelling Shortwave Radiation"),
    "LWdown": ("W m-2", "Surface Downwelling Longwave Radiation"),
    "Wind": ("m s-1", "Near-Surface Wind Speed"),
    "ASurf": ("m", "Surface Altitude"),
}

OUTPUT_TIME_UNITS = "hours since 1900-01-01 00:00:00"
OUTPUT_CALENDAR = "proleptic_gregorian"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download WFDE5-CRU-GPCC forcing from CDS and assemble annual "
            "files matching the existing LIAISE WFDE5_CRU_GPCC layout."
        )
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("WFDE5_CRU_GPCC"),
        help="Where to write WFDE5_CRU_GPCC_{year}.nc (default: %(default)s)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("WFDE5_CRU_GPCC_cds_raw"),
        help="Scratch dir for downloads/extraction (default: %(default)s)",
    )
    parser.add_argument(
        "--version",
        default="3_0",
        help=(
            "CDS 'version' request key (default: %(default)s). Must be "
            "given explicitly -- omitting it causes CDS to reject the "
            "request despite the schema advertising a default."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep downloaded/extracted files in --raw-dir after assembly.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help=(
            "Assume --raw-dir/{year}/ is already populated with extracted "
            "NetCDF files and skip calling CDS (useful when iterating on "
            "the assembly step)."
        ),
    )
    return parser.parse_args()


def build_requests(year: int, version: str) -> list[dict]:
    # Two calls: CDS rejects a single request mixing reference_dataset
    # values, and "cru_and_gpcc" is only a valid combination with the two
    # precipitation variables (see module docstring).
    return [
        {
            "product": "wfde5",
            "variable": sorted(CDS_VARIABLES_CRU.keys()),
            "reference_dataset": "cru",
            "version": version,
            "year": [str(year)],
            "month": MONTHS,
        },
        {
            "product": "wfde5",
            "variable": sorted(CDS_VARIABLES_CRU_GPCC.keys()),
            "reference_dataset": "cru_and_gpcc",
            "version": version,
            "year": [str(year)],
            "month": MONTHS,
        },
    ]


def download_request(client, year: int, index: int, raw_dir: Path, request: dict) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"cds_{year}_{index}.download"
    print(f"[{year}] CDS request {index}: {request}")
    result = client.retrieve(DATASET, request)
    downloaded = result.download(str(target))
    return Path(downloaded)


def extract_archive(downloaded_path: Path, extract_dir: Path) -> list[Path]:
    if zipfile.is_zipfile(downloaded_path):
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(downloaded_path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".nc")]
            zf.extractall(extract_dir)
        # Return only the files this archive contains -- extract_dir is
        # shared across the multiple requests issued per year, so rglob'ing
        # the whole directory here would also pick up files extracted by
        # earlier requests into the same directory.
        return sorted(extract_dir / name for name in names)

    extract_dir.mkdir(parents=True, exist_ok=True)
    single_path = extract_dir / downloaded_path.with_suffix(".nc").name
    shutil.copy2(downloaded_path, single_path)
    return [single_path]


def identify_variable(nc_path: Path) -> str:
    with Dataset(nc_path) as ds:
        coord_names = {"time", "lat", "lon", "latitude", "longitude", "bnds"}
        data_vars = [v for v in ds.variables if v not in coord_names]
    for candidate in data_vars:
        if candidate in NAME_LOOKUP:
            return NAME_LOOKUP[candidate]
    raise ValueError(
        f"{nc_path}: could not identify a known forcing variable "
        f"among {data_vars}"
    )


def crop_to_liaise(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_idx = np.where(
        (lat >= LIAISE_LAT_MIN - 1.0e-6) & (lat <= LIAISE_LAT_MAX + 1.0e-6)
    )[0]
    lon_idx = np.where(
        (lon >= LIAISE_LON_MIN - 1.0e-6) & (lon <= LIAISE_LON_MAX + 1.0e-6)
    )[0]
    return lat_idx, lon_idx


def rebase_time(values: np.ndarray, units: str, calendar: str) -> np.ndarray:
    dates = num2date(values, units=units, calendar=calendar, only_use_cftime_datetimes=True)
    return np.asarray(
        date2num(dates, units=OUTPUT_TIME_UNITS, calendar=OUTPUT_CALENDAR),
        dtype=np.float64,
    )


def load_timevarying(paths: list[Path], short_name: str) -> dict:
    chunks = []
    for path in sorted(paths):
        with Dataset(path) as ds:
            time_var = ds.variables["time"]
            time_values = rebase_time(
                np.asarray(time_var[:], dtype=np.float64),
                time_var.units,
                getattr(time_var, "calendar", OUTPUT_CALENDAR),
            )
            lat = np.asarray(ds.variables["lat"][:])
            lon = np.asarray(ds.variables["lon"][:])
            lat_idx, lon_idx = crop_to_liaise(lat, lon)
            data = ds.variables[short_name][:, lat_idx, lon_idx]
            chunks.append((time_values, lat[lat_idx], lon[lon_idx], np.asarray(data)))

    chunks.sort(key=lambda c: c[0][0])

    ref_lat, ref_lon = chunks[0][1], chunks[0][2]
    for time_values, lat, lon, _ in chunks:
        if lat.shape != ref_lat.shape or not np.allclose(lat, ref_lat):
            raise ValueError(f"{short_name}: inconsistent latitude grid across files")
        if lon.shape != ref_lon.shape or not np.allclose(lon, ref_lon):
            raise ValueError(f"{short_name}: inconsistent longitude grid across files")

    time_values = np.concatenate([c[0] for c in chunks])
    data = np.concatenate([c[3] for c in chunks], axis=0)

    order = np.argsort(time_values)
    time_values = time_values[order]
    data = data[order]

    increments = np.diff(time_values)
    if not np.allclose(increments, 1.0, atol=1.0e-6, rtol=0.0):
        raise ValueError(
            f"{short_name}: concatenated time axis is not strictly hourly; "
            f"increments={np.unique(np.round(increments, 6))[:20]}"
        )

    return {
        "time": time_values,
        "lat": ref_lat,
        "lon": ref_lon,
        "data": data.astype(np.float32),
    }


def load_static(paths: list[Path], short_name: str) -> dict:
    with Dataset(sorted(paths)[0]) as ds:
        lat = np.asarray(ds.variables["lat"][:])
        lon = np.asarray(ds.variables["lon"][:])
        lat_idx, lon_idx = crop_to_liaise(lat, lon)
        var = ds.variables[short_name]
        if "time" in var.dimensions:
            time_axis = var.dimensions.index("time")
            data = np.take(var[:], 0, axis=time_axis)
        else:
            data = var[:]
        data = data[np.ix_(lat_idx, lon_idx)]
    return {"lat": lat[lat_idx], "lon": lon[lon_idx], "data": data.astype(np.float32)}


def assemble_year(year: int, nc_paths: list[Path], output_path: Path) -> None:
    files_by_var: dict[str, list[Path]] = {}
    for nc_path in nc_paths:
        short_name = identify_variable(nc_path)
        files_by_var.setdefault(short_name, []).append(nc_path)

    missing = SHORT_NAMES - files_by_var.keys()
    if missing:
        raise RuntimeError(f"[{year}] missing variables in download: {sorted(missing)}")

    dynamic = {}
    for short_name in sorted(SHORT_NAMES - STATIC_VARIABLES):
        print(f"[{year}] loading {short_name} ({len(files_by_var[short_name])} file(s))")
        dynamic[short_name] = load_timevarying(files_by_var[short_name], short_name)

    static = {}
    for short_name in sorted(STATIC_VARIABLES):
        print(f"[{year}] loading {short_name} (static)")
        static[short_name] = load_static(files_by_var[short_name], short_name)

    ref = next(iter(dynamic.values()))
    ref_time = ref["time"]
    ref_lat = ref["lat"]
    ref_lon = ref["lon"]

    for short_name, payload in dynamic.items():
        if payload["time"].shape != ref_time.shape or not np.allclose(
            payload["time"], ref_time
        ):
            raise ValueError(f"[{year}] {short_name}: time axis does not match other variables")
        if payload["lat"].shape != ref_lat.shape or not np.allclose(payload["lat"], ref_lat):
            raise ValueError(f"[{year}] {short_name}: latitude grid does not match other variables")
        if payload["lon"].shape != ref_lon.shape or not np.allclose(payload["lon"], ref_lon):
            raise ValueError(f"[{year}] {short_name}: longitude grid does not match other variables")

    if ref_lat.shape != LIAISE_LAT_VALUES.shape or not np.allclose(
        np.round(ref_lat, 2), LIAISE_LAT_VALUES
    ):
        raise ValueError(
            f"[{year}] cropped latitude grid {ref_lat} does not match the "
            f"expected LIAISE grid {LIAISE_LAT_VALUES}"
        )
    if ref_lon.shape != LIAISE_LON_VALUES.shape or not np.allclose(
        np.round(ref_lon, 2), LIAISE_LON_VALUES
    ):
        raise ValueError(
            f"[{year}] cropped longitude grid {ref_lon} does not match the "
            f"expected LIAISE grid {LIAISE_LON_VALUES}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    try:
        with Dataset(output_path, "w", format="NETCDF4_CLASSIC") as out_ds:
            out_ds.createDimension("time", None)
            out_ds.createDimension("lat", ref_lat.size)
            out_ds.createDimension("lon", ref_lon.size)

            lat_var = out_ds.createVariable("lat", "f4", ("lat",))
            lat_var[:] = ref_lat
            lat_var.units = "degrees_north"

            lon_var = out_ds.createVariable("lon", "f4", ("lon",))
            lon_var[:] = ref_lon
            lon_var.units = "degrees_east"

            time_var = out_ds.createVariable("time", "f8", ("time",))
            time_var[:] = ref_time
            time_var.units = OUTPUT_TIME_UNITS
            time_var.calendar = OUTPUT_CALENDAR

            for short_name, payload in dynamic.items():
                units, long_name = VARIABLE_ATTRS[short_name]
                var = out_ds.createVariable(
                    short_name, "f4", ("time", "lat", "lon"), fill_value=1.0e20
                )
                var[:] = payload["data"]
                var.units = units
                var.long_name = long_name

            for short_name, payload in static.items():
                units, long_name = VARIABLE_ATTRS[short_name]
                var = out_ds.createVariable(short_name, "f4", ("lat", "lon"))
                var[:] = payload["data"]
                var.units = units
                var.long_name = long_name

            height1 = out_ds.createVariable("Height_Lev1", "f4")
            height1[...] = HEIGHT_LEV1
            height1.units = "m"
            height1.long_name = "Height_scalar_variables"

            heightuv = out_ds.createVariable("Height_Levuv", "f4")
            heightuv[...] = HEIGHT_LEVUV
            heightuv.units = "m"
            heightuv.long_name = "Height_wind"

            out_ds.Conventions = "CF-1.7"
            out_ds.source = "CDS derived-near-surface-meteorological-variables (WFDE5)"
            out_ds.comment = (
                "Downloaded via get_liaise_forcing_05_cds.py, cropped to the "
                "LIAISE domain and merged to match the layout of the "
                "IPSL-mirrored WFDE5_CRU_GPCC files."
            )

        print(
            f"CREATED {output_path}\n"
            f"  records: {ref_time.size}\n"
            f"  time: {ref_time[0]} .. {ref_time[-1]} [{OUTPUT_TIME_UNITS}]\n"
            f"  grid: {ref_lat.size} x {ref_lon.size}"
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def main() -> None:
    args = parse_args()

    if args.end_year < args.start_year:
        raise ValueError("--end-year must be >= --start-year")

    client = None
    if not args.skip_download:
        import cdsapi

        client = cdsapi.Client()

    for year in range(args.start_year, args.end_year + 1):
        output_path = args.output_dir / f"WFDE5_CRU_GPCC_{year}.nc"
        if output_path.exists() and not args.overwrite:
            print(f"SKIP existing: {output_path}")
            continue

        raw_year_dir = args.raw_dir / str(year)

        if args.skip_download:
            nc_paths = sorted(raw_year_dir.rglob("*.nc"))
            if not nc_paths:
                raise FileNotFoundError(
                    f"--skip-download given but no .nc files found under {raw_year_dir}"
                )
        else:
            nc_paths = []
            for index, request in enumerate(build_requests(year, args.version)):
                downloaded = download_request(client, year, index, args.raw_dir, request)
                nc_paths.extend(extract_archive(downloaded, raw_year_dir))

        assemble_year(year, nc_paths, output_path)

        if not args.keep_raw:
            shutil.rmtree(raw_year_dir, ignore_errors=True)
            downloaded_glob = list(args.raw_dir.glob(f"cds_{year}_*.download*"))
            for path in downloaded_glob:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
