#!/usr/bin/env python3
"""Extract river-gauge observations on the LIAISE (Ebro) network.

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

Provider sources and basin filtering:
  - `--providers` selects which Caravan sub-datasets to pull, matched against
    the CSV's `Provid` prefix (case-insensitive, before the first `_`).
    Default is `GRDC` only, matching the original (2026-09-12) extraction.
    Passing `--providers GRDC camelses` additionally pulls CAMELS-Spain
    stations (the CAMELS sub-dataset relevant to the Ebro basin -- other
    CAMELS regions, e.g. camelsde/camelsch/camelscl, do not overlap this
    domain and are filtered out by the basin match below regardless).
  - **Licensing differs by provider -- this matters for redistribution, not
    for internal use.** GRDC (Global Runoff Data Centre) stations are the
    ones ifs-riverbench's own `prepare_public_bundle.py` treats as safe to
    redistribute (public-domain, via the open-access GRDC-Caravan extension
    of Caravan). CAMELS-Spain and every other non-GRDC Caravan sub-dataset
    "carry their own separate licences" (that script's own docstring) --
    typically CC-BY-style attribution licences, not public-domain, and
    `prepare_public_bundle.py` explicitly excludes them from public bundles,
    replacing their obs payload with a `{"restricted": true}` marker. This
    script's own output is for internal ECMWF analysis (this repo has no
    public-redistribution requirement), but do not feed a CAMELS-inclusive
    output file into a public-facing pipeline (e.g. ifs-riverbench's own
    bundle) without re-checking that script's filter.
  - A lat/lon bounding box alone is NOT enough to select "LIAISE-relevant"
    stations: several stations that fall inside a naive Ebro-region box
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

    # GRDC + CAMELS-Spain, internal-analysis output (not redistributed):
    python3 extract_liaise_grdc_observations.py --providers GRDC camelses \\
        --station-csv /perm/pad/flood_cases/Stations/allstations_v1.3.csv \\
        --qobs /perm/pad/flood_cases/Stations/Qobs_24_1980-2025_withcaravan.zarr \\
        --ncdata data/ncdata.nc \\
        --start-date 1988-01-01 --end-date 2014-12-31 \\
        --out liaise_river_observations_grdc_camels.nc
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
    p.add_argument("--providers", nargs="+", default=["GRDC"],
                    help="Provid prefixes to keep (case-insensitive, matched before the first '_'), "
                         "e.g. 'GRDC camelses'. Default: GRDC only (public-domain, matches the original "
                         "2026-09-12 extraction). See the licensing note in this script's docstring "
                         "before adding non-GRDC providers to anything meant for redistribution.")
    p.add_argument("--start-date", default="1980-01-01")
    p.add_argument("--end-date", default="2025-12-31")
    p.add_argument("--caravan-timeseries-dir", type=Path, default=None,
                    help="raw per-station Caravan archive (ifs-riverbench convention: "
                         "netcdf_V1.1/<provider>/<provid>.nc, e.g. netcdf_V1.1/camelses/camelses_9002.nc), "
                         "used as a FALLBACK when a station's merged --qobs series is all-NaN. Needed for "
                         "camelses (CAMELS-Spain): as of this writing, "
                         "Qobs_24_1980-2025_withcaravan.zarr carries camelses station IDs but essentially "
                         "no populated discharge for them (checked: 266/269 stations entirely NaN, the "
                         "other 3 have exactly 1 valid day) -- a gap in that merged archive, not in the "
                         "underlying data, which exists in the raw per-station files as 'streamflow', "
                         "units mm/d (Caravan's area-normalized convention), converted here to m3/s using "
                         "the station's ProvArea (km2) from --station-csv.")
    p.add_argument("--out", required=True, type=Path, help="output NetCDF: station metadata + observed discharge")
    return p.parse_args()


def load_caravan_fallback(path: Path, area_km2: float, dates: np.ndarray) -> np.ndarray | None:
    """Read raw per-station Caravan streamflow (mm/d) and convert to m3/s on the given daily `dates`."""
    if not path.exists() or not area_km2:
        return None
    raw = xr.open_dataset(path)
    if "streamflow" not in raw.variables:
        return None
    q_mm_day = raw["streamflow"].values.astype("float64")
    # Q[m3/s] = depth[mm/d] * area[km2] * 1000[m3/mm/km2] / 86400[s/d] = depth * area / 86.4
    q_m3s = q_mm_day * area_km2 / 86.4
    raw_dates = raw["date"].values.astype("datetime64[D]")
    out = np.full(len(dates), np.nan, dtype="float64")
    pos = {d: i for i, d in enumerate(raw_dates)}
    for i, d in enumerate(dates.astype("datetime64[D]")):
        j = pos.get(d)
        if j is not None:
            out[i] = q_m3s[j]
    return out


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
    providers = {p.lower() for p in opts.providers}
    stations = []
    with open(opts.station_csv, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            try:
                slon, slat = float(row["StatLon"]), float(row["StatLat"])
            except (ValueError, KeyError):
                continue
            if not (lonW <= slon <= lonE and latS <= slat <= latN):
                continue
            provid = row.get("Provid", "")
            provider = provid.split("_")[0].lower() if provid else ""
            if not (row.get("Source") == "Caravan" and provider in providers):
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
                "id": row["Id"], "name": row["Name"].strip(), "provid": row["Provid"], "provider": provider,
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
        raise SystemExit(f"No stations from {opts.providers} matched the LIAISE domain's basin -- "
                          "check --ncdata/--liaise-cell/--providers.")

    print(f"Found {len(stations)} gauge(s) from {sorted({s['provider'] for s in stations})} "
          "on the LIAISE (Ebro) network:")
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

    if opts.caravan_timeseries_dir:
        n_fallback = 0
        for i, s in enumerate(stations):
            col = discharge[:, i]
            if np.sum(np.isfinite(col)) >= 30:
                continue  # merged archive already has usable data for this station
            area = float(s["provider_area_km2"]) if s["provider_area_km2"] else 0.0
            raw_path = opts.caravan_timeseries_dir / s["provider"] / f"{s['provid']}.nc"
            fallback = load_caravan_fallback(raw_path, area, time)
            if fallback is not None and np.sum(np.isfinite(fallback)) >= 30:
                discharge[:, i] = fallback
                n_fallback += 1
        if n_fallback:
            print(f"Filled {n_fallback} station(s) from the raw Caravan archive "
                  f"({opts.caravan_timeseries_dir}) -- merged --qobs had no usable series for them.")

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
        v = out.createVariable("provider", str, ("station",))
        v.long_name = "Caravan sub-dataset (Provid prefix): GRDC=public-domain, others carry their own licence"
        for i, s in enumerate(stations):
            v[i] = s["provider"]

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
        v.long_name = ("observed daily discharge (via Caravan; see 'provider' for the sub-dataset/licence). "
                        "Non-GRDC values sourced from the raw per-station archive and converted from the "
                        "Caravan mm/d convention to m3/s using each station's ProvArea where the merged "
                        "--qobs series had no usable data -- see load_caravan_fallback().")
        v[:] = discharge

        out.history = (
            f"Filtered from ifs-riverbench station metadata + Qobs archive: Source=Caravan, "
            f"Provid prefix in {sorted({p.lower() for p in opts.providers})}, basin-matched to the LIAISE (Ebro) network in "
            "cama_flood/data/ncdata.nc. See cama_flood/extract_liaise_grdc_observations.py. "
            "Non-GRDC providers carry their own licence -- see this script's docstring before "
            "redistributing this file outside internal ECMWF use."
        )

    print(f"\nSaved {len(stations)} stations x {len(time)} days to {opts.out}")


if __name__ == "__main__":
    main()
