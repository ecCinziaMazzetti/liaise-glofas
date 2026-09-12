#!/usr/bin/env python3
"""Extract GRDC-sourced river-gauge observations on the LIAISE (Ebro) network.

Companion to the Fortran-vs-CaMa-Flood-GPU discharge comparison documented in
CLAUDE.md ("GPU-vs-Fortran discharge comparison") -- that comparison checked
the two models against each other; this script pulls in real observations so
either (or both) can be checked against gauge data too.

Source data (both "internal ECMWF assets" per ifs-riverbench's own README,
not redistributed there or here -- only this script's small filtered output
is):
  - Station metadata CSV (ifs-riverbench convention, e.g.
    /perm/pad/flood_cases/Stations/allstations_v1.3.csv): includes each
    station's pre-computed CaMa-Flood glb_15min lookup cell
    (Cama15lon/Cama15lat/Cama15area), so matching against our own
    cama_flood/data/*.nc grid needs no fuzzy nearest-neighbor search.
  - Qobs archive (Zarr or NetCDF, e.g.
    /perm/pad/flood_cases/Stations/Qobs_24_1980-2025_withcaravan.zarr):
    daily discharge per station, keyed by `statid` (matches the CSV's `Id`).

Why GRDC-only, and why basin-filtered:
  - GRDC (Global Runoff Data Centre) stations are the ones ifs-riverbench's
    own `prepare_public_bundle.py` already treats as safe to redistribute
    (public-domain, via the Caravan/GRDC-Caravan extension) -- identified the
    same way here: Source=="Caravan" and Provid starting with "GRDC_".
  - A lat/lon bounding box alone is NOT enough to select "LIAISE-relevant"
    stations: several GRDC stations that fall inside a naive Ebro-region box
    are actually on entirely separate river systems (Tagus, Turia, Jucar,
    Llobregat, Ter, Bidasoa all have gauges in the same rectangle). This
    script instead matches each station's Cama15lon/Cama15lat cell against
    `cama_flood/data/ncdata.nc`'s own `basin` field and keeps only stations
    CaMa-Flood's own glb_15min network considers connected to the LIAISE
    domain's own basin (found from `--liaise-cell`, a lat/lon known to sit on
    it -- default is the Ebro-mouth cell used in the Fortran/GPU discharge
    comparison). A few real-world Ebro tributaries with small catchments
    (e.g. under ~200 km2) don't survive this filter -- glb_15min's coarse
    river-network delineation doesn't always resolve them as connected to
    the main network; that's a genuine CaMa-Flood resolution limitation, not
    a bug in this filter.

Usage
-----
    python3 extract_liaise_grdc_observations.py \\
        --station-csv /perm/pad/flood_cases/Stations/allstations_v1.3.csv \\
        --qobs /perm/pad/flood_cases/Stations/Qobs_24_1980-2025_withcaravan.zarr \\
        --ncdata data/ncdata.nc \\
        --start-date 1988-01-01 --end-date 2014-12-31 \\
        --out liaise_grdc_observations.nc
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import xarray as xr
from netCDF4 import Dataset


def get_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--station-csv", required=True, type=Path, help="ifs-riverbench station metadata CSV")
    p.add_argument("--qobs", required=True, type=Path, help="Qobs archive (.zarr directory or .nc file)")
    p.add_argument("--ncdata", required=True, type=Path, help="cama_flood/data/ncdata.nc (for the basin filter)")
    p.add_argument("--liaise-cell", nargs=2, type=float, default=[40.625, 0.875], metavar=("LAT", "LON"),
                    help="a lat/lon known to sit on the LIAISE domain's river network "
                         "(default: the Ebro-mouth cell used in the Fortran/GPU comparison)")
    p.add_argument("--lon-window", nargs=2, type=float, default=[-2.5, 3.0], metavar=("WEST", "EAST"),
                    help="coarse pre-filter box, only to limit the CSV scan -- the real filter is the basin match")
    p.add_argument("--lat-window", nargs=2, type=float, default=[39.0, 43.5], metavar=("SOUTH", "NORTH"))
    p.add_argument("--start-date", default="1980-01-01")
    p.add_argument("--end-date", default="2025-12-31")
    p.add_argument("--out", required=True, type=Path, help="output NetCDF: station metadata + observed discharge")
    return p.parse_args()


def find_grdc_liaise_stations(opts: argparse.Namespace) -> list[dict]:
    with Dataset(opts.ncdata, "r") as nc:
        basin = np.asarray(nc.variables["basin"][:])
        lat = np.asarray(nc.variables["lat"][:])
        lon = np.asarray(nc.variables["lon"][:])

    liaise_lat, liaise_lon = opts.liaise_cell
    iy0 = int(np.argmin(np.abs(lat - liaise_lat)))
    ix0 = int(np.argmin(np.abs(lon - liaise_lon)))
    liaise_basin_id = basin[iy0, ix0]
    if np.ma.is_masked(liaise_basin_id):
        raise SystemExit(f"--liaise-cell ({liaise_lat},{liaise_lon}) is not an active river cell in {opts.ncdata}")

    lonW, lonE = opts.lon_window
    latS, latN = opts.lat_window
    stations = []
    with open(opts.station_csv, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            try:
                slon, slat = float(row["StatLon"]), float(row["StatLat"])
            except (ValueError, KeyError):
                continue
            if not (lonW <= slon <= lonE and latS <= slat <= latN):
                continue
            if not (row.get("Source") == "Caravan" and row.get("Provid", "").startswith("GRDC_")):
                continue
            try:
                clat, clon = float(row["Cama15lat"]), float(row["Cama15lon"])
            except (ValueError, KeyError):
                continue
            iy = int(np.argmin(np.abs(lat - clat)))
            ix = int(np.argmin(np.abs(lon - clon)))
            cell_basin = basin[iy, ix]
            if np.ma.is_masked(cell_basin) or cell_basin != liaise_basin_id:
                continue
            stations.append({
                "id": row["Id"], "name": row["Name"].strip(), "provid": row["Provid"],
                "station_lat": slat, "station_lon": slon,
                "cama15_lat": clat, "cama15_lon": clon,
                "cama15_iy": iy, "cama15_ix": ix,
                "provider_area_km2": row.get("ProvArea", ""),
            })
    return stations


def main() -> None:
    opts = get_args()
    stations = find_grdc_liaise_stations(opts)
    if not stations:
        raise SystemExit("No GRDC stations matched the LIAISE domain's basin -- check --ncdata/--liaise-cell.")

    print(f"Found {len(stations)} GRDC-sourced gauges on the LIAISE (Ebro) network:")
    for s in stations:
        print(f"  {s['provid']:15s} {s['name']:35s} area={s['provider_area_km2']:>10} km2"
              f"  cell=({s['cama15_lat']:.3f},{s['cama15_lon']:.3f})")

    qobs_path = str(opts.qobs)
    ds = xr.open_zarr(qobs_path) if qobs_path.endswith(".zarr") else xr.open_dataset(qobs_path)
    ds = ds.sel(time=slice(opts.start_date, opts.end_date))

    ids = np.array([float(s["id"]) for s in stations])
    statid = ds["statid"].values
    idx = np.array([np.where(statid == i)[0] for i in ids], dtype=object)
    missing = [s["id"] for s, m in zip(stations, idx) if len(m) == 0]
    if missing:
        print(f"WARNING: {len(missing)} station id(s) not found in Qobs archive: {missing}")
    keep = [i for i, m in enumerate(idx) if len(m) > 0]
    stations = [stations[i] for i in keep]
    station_positions = np.array([idx[i][0] for i in keep])

    discharge = ds["discharge"].isel(station=station_positions).values  # (time, station)
    time = ds["time"].values

    opts.out.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(opts.out, "w", format="NETCDF4") as out:
        out.createDimension("station", len(stations))
        out.createDimension("time", len(time))

        v = out.createVariable("time", "f8", ("time",))
        v.units = "days since 1970-01-01"
        v[:] = (time - np.datetime64("1970-01-01")) / np.timedelta64(1, "D")

        v = out.createVariable("station_id", "i8", ("station",))
        v[:] = [int(s["id"]) for s in stations]

        # Variable-length string type -- simpler and less error-prone than a
        # fixed-width char array (which needs careful byte-for-byte padding).
        v = out.createVariable("station_name", str, ("station",))
        for i, s in enumerate(stations):
            v[i] = s["name"]

        for key, ncname, units in [
            ("station_lat", "station_lat", "degrees_north"),
            ("station_lon", "station_lon", "degrees_east"),
            ("cama15_lat", "cama15_lat", "degrees_north"),
            ("cama15_lon", "cama15_lon", "degrees_east"),
        ]:
            v = out.createVariable(ncname, "f8", ("station",))
            v.units = units
            v[:] = [s[key] for s in stations]

        v = out.createVariable("cama15_iy", "i4", ("station",))
        v.long_name = "row index into cama_flood/data/*.nc's (lat, lon) grid"
        v[:] = [s["cama15_iy"] for s in stations]
        v = out.createVariable("cama15_ix", "i4", ("station",))
        v.long_name = "column index into cama_flood/data/*.nc's (lat, lon) grid"
        v[:] = [s["cama15_ix"] for s in stations]

        v = out.createVariable("discharge", "f4", ("time", "station"), fill_value=1.0e20)
        v.units = "m3 s-1"
        v.long_name = "observed daily discharge (GRDC via Caravan)"
        v[:] = discharge

        out.history = (
            "Filtered from ifs-riverbench station metadata + Qobs archive: "
            "Source=Caravan, Provid startswith GRDC_, basin-matched to the LIAISE "
            "(Ebro) network in cama_flood/data/ncdata.nc. See "
            "cama_flood/extract_liaise_grdc_observations.py."
        )

    print(f"\nSaved {len(stations)} stations x {len(time)} days to {opts.out}")


if __name__ == "__main__":
    main()
