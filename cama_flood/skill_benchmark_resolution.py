#!/usr/bin/env python3
"""Discharge skill of the ecLand-CaMa-Flood control chain at ONE routing resolution.

Same gauges, same metrics and the same filtering as skill_benchmark_control.py,
but parameterised by CaMa-Flood routing resolution so that the 15 / 6 / 3 arcmin
naturalised 1988-2024 runs can be scored with one identical code path and then
compared directly. Unlike skill_benchmark_control.py this script never reuses
previously-scored rows: every station-year is recomputed from the raw
o_totout.nc, because a mix of fresh and reused rows would make a
resolution-vs-resolution comparison apples-to-oranges.

The resolution-index subtlety
-----------------------------
The observation file carries `cama15_iy` / `cama15_ix`, which are grid indices
into the 15 arcmin (0.25 deg) network ONLY -- they are meaningless on the 6 or 3
arcmin grids, and using them there would silently score the wrong river cell.
So this script never uses them. Instead it takes each station's PRE-COMPUTED
per-resolution CaMa-Flood allocation from the ifs-riverbench station metadata CSV
(`Cama15lon/lat`, `Cama6lon/lat`, `Cama3lon/lat` -- an upstream product, not our
own snapping) and nearest-cell-matches it against the target resolution's own
`ncdata.nc` lat/lon arrays, the same pattern estimate_dam_q100.py's load_dams()
uses. Stations are joined to the CSV on `station_id` == CSV `Id`.

The mapping is sanity-checked, per station, against the CSV's own upstream-area
column for that resolution (`Cama15area`/`Cama6area`/`Cama3area`, km2) versus
`uparea` (m2) at the mapped cell: anything off by more than --area-tol, out of
grid, or missing from the CSV is reported and dropped. At the time of writing
all 53 stations pass at all three resolutions, and at 15 arcmin the derived
indices reproduce the observation file's own `cama15_iy`/`cama15_ix` exactly for
all 53 -- which is what validates the method for the other two.

Usage
-----
    python3 skill_benchmark_resolution.py --resolution 15min \\
        --obs data/liaise_river_observations_grdc_camels.nc \\
        --ncdata data/ncdata.nc \\
        --tmpl /perm/pad/liaise_cmf_1988_2024/output/{y}/o_totout.nc \\
        --out /perm/pad/liaise_discharge_compare/skill_resolution_15min.json

    python3 skill_benchmark_resolution.py --resolution 06min \\
        --obs data/liaise_river_observations_grdc_camels.nc \\
        --ncdata work_06min/ncdata.nc \\
        --tmpl /perm/pad/liaise_cmf_1988_2024_06min/output/{y}/o_totout.nc \\
        --out /perm/pad/liaise_discharge_compare/skill_resolution_06min.json

    # the 3 arcmin run, once it has finished:
    python3 skill_benchmark_resolution.py --resolution 03min \\
        --ncdata work_03min/ncdata.nc \\
        --tmpl /perm/pad/liaise_cmf_1988_2024_03min/output/{y}/o_totout.nc ...
"""

import argparse
import csv
import datetime
import json
import os
from collections import defaultdict

import netCDF4 as nc
import numpy as np

# resolution label -> (CSV lon column, CSV lat column, CSV upstream-area column in km2)
RESOLUTION_COLUMNS = {
    "15min": ("Cama15lon", "Cama15lat", "Cama15area"),
    "06min": ("Cama6lon", "Cama6lat", "Cama6area"),
    "03min": ("Cama3lon", "Cama3lat", "Cama3area"),
}


def nc_dates(var):
    cft = nc.num2date(var[:], units=var.units, calendar=getattr(var, "calendar", "standard"))
    return np.array([datetime.date(d.year, d.month, d.day) for d in cft])


def daily_mean(dates, series):
    acc, cnt = defaultdict(float), defaultdict(int)
    for d, v in zip(dates, series):
        if np.isfinite(v):
            acc[d] += float(v)
            cnt[d] += 1
    return {d: acc[d] / cnt[d] for d in acc}


def kge(sim, obs):
    r = np.corrcoef(sim, obs)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2), r, alpha, beta


def nse(sim, obs):
    return 1 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)


def pbias(sim, obs):
    return 100 * np.sum(sim - obs) / np.sum(obs)


def display_names(raw_names, station_ids):
    """Append " [station_id]" to any display name shared by more than one gauge."""
    name_count = {n: raw_names.count(n) for n in raw_names}
    return [f"{n} [{sid}]" if name_count[n] > 1 else n
            for n, sid in zip(raw_names, station_ids)]


def map_stations(stations_csv, ncdata_path, resolution, station_ids, names, area_tol):
    """station index -> (iy, ix) on this resolution's grid, plus a list of problems."""
    lon_col, lat_col, area_col = RESOLUTION_COLUMNS[resolution]
    wanted = set(station_ids)
    meta = {}
    with open(stations_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                sid = int(row["Id"])
            except (KeyError, ValueError):
                continue
            if sid in wanted:
                meta[sid] = row

    ds = nc.Dataset(ncdata_path)
    lat = np.asarray(ds.variables["lat"][:])
    lon = np.asarray(ds.variables["lon"][:])
    uparea = np.asarray(ds.variables["uparea"][:], dtype=float)
    uparea = np.where(uparea > 1e19, np.nan, uparea)  # CaMa-Flood fill -> nan
    dlat = abs(float(lat[1] - lat[0]))
    dlon = abs(float(lon[1] - lon[0]))

    cells, problems = {}, []
    for i, sid in enumerate(station_ids):
        row = meta.get(sid)
        if row is None:
            problems.append(f"{names[i]} [{sid}]: not in {os.path.basename(stations_csv)}")
            continue
        try:
            tlon, tlat = float(row[lon_col]), float(row[lat_col])
        except (KeyError, ValueError):
            problems.append(f"{names[i]} [{sid}]: no {lon_col}/{lat_col} allocation in the CSV")
            continue
        iy = int(np.argmin(np.abs(lat - tlat)))
        ix = int(np.argmin(np.abs(lon - tlon)))
        # nearest cell must actually contain the allocated point, not merely be the
        # closest edge cell of a domain the station falls outside of
        if abs(lat[iy] - tlat) > dlat or abs(lon[ix] - tlon) > dlon:
            problems.append(f"{names[i]} [{sid}]: allocation {tlat:.3f}N {tlon:.3f}E "
                            f"outside the {resolution} domain")
            continue
        area_grid = uparea[iy, ix] / 1e6  # m2 -> km2
        try:
            area_csv = float(row[area_col])
        except (KeyError, ValueError):
            area_csv = float("nan")
        if not np.isfinite(area_grid):
            problems.append(f"{names[i]} [{sid}]: no river cell (uparea missing) at the mapped "
                            f"{resolution} cell iy={iy} ix={ix}")
            continue
        if np.isfinite(area_csv) and area_csv > 0:
            rel = abs(area_grid - area_csv) / area_csv
            if rel > area_tol:
                problems.append(f"{names[i]} [{sid}]: upstream area mismatch at {resolution} -- "
                                f"grid {area_grid:.1f} km2 vs CSV {area_col} {area_csv:.1f} km2 "
                                f"({100 * rel:.0f}%)")
                continue
        cells[i] = (iy, ix)
    return cells, problems


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--resolution", required=True, choices=sorted(RESOLUTION_COLUMNS),
                help="CaMa-Flood routing resolution; picks the CSV allocation columns to use")
ap.add_argument("--obs", required=True, help="liaise_river_observations_*.nc")
ap.add_argument("--ncdata", required=True, help="this resolution's own CaMa-Flood ncdata.nc")
ap.add_argument("--tmpl", required=True, help="o_totout.nc path template containing {y}")
ap.add_argument("--stations-csv", default="/perm/pad/flood_cases/Stations/allstations_v1.3.csv")
ap.add_argument("--min-days", type=int, default=30)
ap.add_argument("--area-tol", type=float, default=0.2,
                help="max relative upstream-area disagreement between grid and CSV (default 0.2)")
ap.add_argument("--out", required=True)
args = ap.parse_args()

obs_ds = nc.Dataset(args.obs)
obs_disc = obs_ds.variables["discharge"]
obs_disc.set_auto_mask(True)
obs_dates = np.array([datetime.date(1970, 1, 1) + datetime.timedelta(days=int(t))
                      for t in obs_ds.variables["time"][:]])
raw_names = [str(n) for n in obs_ds.variables["station_name"][:]]
station_ids = [int(s) for s in obs_ds.variables["station_id"][:]]
names = display_names(raw_names, station_ids)
providers = [str(p) for p in obs_ds.variables["provider"][:]]
obs_years = sorted({d.year for d in obs_dates})

cells, problems = map_stations(args.stations_csv, args.ncdata, args.resolution,
                               station_ids, names, args.area_tol)
print(f"{args.resolution}: mapped {len(cells)} of {len(names)} stations onto {args.ncdata}")
for p in problems:
    print(f"  UNMAPPED/SUSPECT: {p}")
if not cells:
    raise SystemExit("no station could be mapped onto this resolution's grid")

years = [y for y in obs_years if os.path.exists(args.tmpl.format(y=y))]
if not years:
    raise SystemExit(f"no year in {obs_years[0]}-{obs_years[-1]} has an o_totout.nc at {args.tmpl}")
print(f"scoring {len(years)} year(s) with o_totout.nc on disk: {years[0]}-{years[-1]}")

results = []
for y in years:
    m_ds = nc.Dataset(args.tmpl.format(y=y))
    v = m_ds.variables["totout"]
    v.set_auto_mask(True)
    m_dates = nc_dates(m_ds.variables["time"])
    m_data = np.asarray(v[:].filled(np.nan))
    m_data[m_data > 1e19] = np.nan  # fill value, in case it was not declared as _FillValue

    obs_mask = np.array([d.year == y for d in obs_dates])
    obs_year_dates = obs_dates[obs_mask]

    for i, (iy, ix) in sorted(cells.items()):
        m_daily = daily_mean(m_dates, m_data[:, iy, ix])
        o_series = np.asarray(obs_disc[obs_mask, i].filled(np.nan))
        o_daily = {d: o_series[k] for k, d in enumerate(obs_year_dates)}

        common = sorted(set(m_daily) & set(o_daily))
        m_al = np.array([m_daily[d] for d in common])
        o_al = np.array([o_daily[d] for d in common])
        valid = np.isfinite(m_al) & np.isfinite(o_al) & (o_al > 0)
        if valid.sum() < args.min_days:
            continue
        m_v, o_v = m_al[valid], o_al[valid]
        k, r, a, b = kge(m_v, o_v)
        results.append({"year": y, "station": names[i], "provider": providers[i], "model": "Fortran",
                        "resolution": args.resolution, "n_days": int(valid.sum()),
                        "kge": float(k), "r": float(r), "alpha": float(a), "beta": float(b),
                        "nse": float(nse(m_v, o_v)), "pbias_pct": float(pbias(m_v, o_v)),
                        "obs_mean": float(np.mean(o_v)), "sim_mean": float(np.mean(m_v)),
                        "bias": float(np.mean(m_v) - np.mean(o_v))})
    m_ds.close()

with open(args.out, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"wrote {len(results)} rows -> {args.out}")

by_station = defaultdict(list)
for r in results:
    by_station[r["station"]].append(r)
print(f"\n{len(by_station)} stations scored, {len(results)} station-years total")
for name, rows in sorted(by_station.items()):
    yrs = sorted(r["year"] for r in rows)
    print(f"  {name:45s} n={len(rows):3d} years {yrs[0]}-{yrs[-1]:<6} "
          f"median KGE {np.median([r['kge'] for r in rows]):7.3f}  "
          f"median PBIAS {np.median([r['pbias_pct'] for r in rows]):8.1f}%")
