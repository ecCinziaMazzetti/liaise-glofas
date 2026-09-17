#!/usr/bin/env python3
"""Estimate per-dam annual mean/max discharge and the 100-year flood (Q100) for the
45 GRanD reservoirs draining to the Ebro within the LIAISE domain.

Step 2+3 of the "Ebro Reservoir Operation" activation pipeline
(https://claude.ai/artifact/V5ZZxE3K4jFS6tsds5JiP3, section 3) -- the CaMa-Flood v4.20
dam module (`cmf_ctrl_damout_mod.F90`, already in `ecland`, currently off via
`LDAMOUT=.FALSE.`) needs a `dam_param.csv` with, per reservoir: normal/flood discharge
derived from the naturalised annual mean and the Gumbel-fit 100-year flood.

Dam allocation, not re-run here: `GRanD_allocated.csv` (from the CaMa-Flood v4.20
package) ships each dam ALREADY allocated to the global glb_15min river network
(`lat_alloc`/`lon_alloc`), so no Fortran `allocate_dam` build/run is needed -- this
script just nearest-cell-matches those coordinates against our own regional
`cama_flood/data/ncdata.nc` grid (same 0.25deg glb_15min grid, confirmed identical
topology across CaMa-Flood package vintages elsewhere in this project) and keeps
whichever dams fall in the same `basin` id as a known Ebro cell. Matches the
feasibility artifact's own count exactly: 45 dams, 7.77 km3 total capacity.

Naturalised discharge source, two options (pass one or both):
  --fortran-tmpl   the Fortran ecLand-CaMa-Flood coupled run's own o_totout.nc
                   (LECMF1WAY=true, LDAMOUT=.FALSE. by construction -- naturalised).
                   As of 2026-09-16 only a subset of the full 37 years remains on
                   disk (see PLAN.md) -- uses whatever years exist, flags if <30.
  --gpu-tmpl       the eclandpy -> CaMa-Flood-GPU chain's discharge_daily.nc, complete
                   for all 37 years but driven by eclandpy's runoff, ~21% below the
                   Fortran control (documented in CLAUDE.md) -- a "first look" series
                   per the artifact, not the final parameter source.

Gumbel fit via L-moments (probability-weighted moments / Hosking 1990), the method
the CaMa-Flood reservoir manual specifies for p02 -- no external stats package needed:
    L1 = mean(x)
    b1 = mean_i[ (rank_i - 1)/(n - 1) * x_i ]   (x sorted ascending, rank 1..n)
    L2 = 2*b1 - L1
    beta  = L2 / ln(2)                          (Gumbel scale)
    xi    = L1 - 0.5772156649 * beta            (Gumbel location, Euler-Mascheroni)
    Q(T)  = xi - beta * ln(-ln(1 - 1/T))         (T-year return period)

Usage
-----
    python3 estimate_dam_q100.py \\
        --grand-csv /perm/pad/cmf_v420_pkg_20240430/map/data/GRanD_allocated.csv \\
        --ncdata data/ncdata.nc \\
        --fortran-tmpl /perm/pad/liaise_cmf_1988_2024/output/{y}/o_totout.nc \\
        --gpu-tmpl "eclandpy_bridge/cmfgpu_out_gpu_repro/eclandpy_liaise_{y}_discharge_daily.nc" \\
        --out /perm/pad/liaise_discharge_compare/ebro_dam_q100.csv
"""

import argparse
import csv
import math
from collections import defaultdict

import netCDF4 as nc
import numpy as np

EULER_MASCHERONI = 0.5772156649015329
GLOBAL_WEST, GLOBAL_NORTH, GLOBAL_DLON, GLOBAL_DLAT, GLOBAL_NY = -180.0, 90.0, 0.25, 0.25, 720


def load_dams(grand_csv, ncdata_path, liaise_cell):
    ds = nc.Dataset(ncdata_path)
    lat = np.asarray(ds.variables["lat"][:])
    lon = np.asarray(ds.variables["lon"][:])
    basin = np.asarray(ds.variables["basin"][:])
    uparea = np.asarray(ds.variables["uparea"][:])

    liaise_lat, liaise_lon = liaise_cell
    iy0 = int(np.argmin(np.abs(lat - liaise_lat)))
    ix0 = int(np.argmin(np.abs(lon - liaise_lon)))
    target_basin = basin[iy0, ix0]

    dams = []
    with open(grand_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                dlat, dlon = float(row["lat_alloc"]), float(row["lon_alloc"])
            except ValueError:
                continue
            if not (lat.min() - 0.5 <= dlat <= lat.max() + 0.5 and lon.min() - 0.5 <= dlon <= lon.max() + 0.5):
                continue
            iy = int(np.argmin(np.abs(lat - dlat)))
            ix = int(np.argmin(np.abs(lon - dlon)))
            b = basin[iy, ix]
            if np.ma.is_masked(b) or b != target_basin:
                continue
            dams.append({
                "name": row["DamName"], "river": row["RiverName"], "cap_mcm": float(row["CAP_MCM"]),
                "year": row["YEAR"], "ix": ix, "iy": iy, "lat": float(lat[iy]), "lon": float(lon[ix]),
                "uparea_km2": float(uparea[iy, ix]) / 1e6,
            })
    return dams, target_basin


def nc_dates(var):
    cft = nc.num2date(var[:], units=var.units, calendar=getattr(var, "calendar", "standard"))
    import datetime
    return np.array([datetime.date(d.year, d.month, d.day) for d in cft])


def fortran_annual_stats(tmpl, cells):
    """cells: set of (ix, iy). Returns {(ix,iy): {year: {"mean":.., "max":..}}}"""
    import os
    out = defaultdict(dict)
    years_found = []
    y = 1980
    while y <= 2030:
        path = tmpl.format(y=y)
        if os.path.exists(path):
            years_found.append(y)
        y += 1
    for y in years_found:
        ds = nc.Dataset(tmpl.format(y=y))
        v = ds.variables["totout"]
        v.set_auto_mask(True)
        dates = nc_dates(ds.variables["time"])
        data = np.asarray(v[:].filled(np.nan))  # (time, ny, nx)
        day_mask = np.array([d.year == y for d in dates])
        for (ix, iy) in cells:
            series = data[day_mask, iy, ix]
            series = series[np.isfinite(series)]
            if series.size < 300:  # require most of the year present
                continue
            out[(ix, iy)][y] = {"mean": float(np.mean(series)), "max": float(np.max(series))}
    return out, years_found


def gpu_annual_stats(tmpl, dam_latlon):
    """dam_latlon: {(ix,iy): (lat, lon)}. Returns {(ix,iy): {year: {"mean":.., "max":..}}}"""
    out = defaultdict(dict)
    import os
    years_found = []
    y = 1980
    while y <= 2030:
        if os.path.exists(tmpl.format(y=y)):
            years_found.append(y)
        y += 1
    for y in years_found:
        ds = nc.Dataset(tmpl.format(y=y))
        disc = np.asarray(ds.variables["discharge"][:])
        cid_of = {int(c): k for k, c in enumerate(np.asarray(ds.variables["catchment_id"][:]))}
        for (ix, iy), (dlat, dlon) in dam_latlon.items():
            ix_g = round((dlon - GLOBAL_WEST - GLOBAL_DLON / 2) / GLOBAL_DLON)
            iy_g = round((GLOBAL_NORTH - dlat - GLOBAL_DLAT / 2) / GLOBAL_DLAT)
            cid = ix_g * GLOBAL_NY + iy_g
            k = cid_of.get(cid)
            if k is None:
                continue
            series = disc[:, k]
            series = series[np.isfinite(series)]
            if series.size < 300:
                continue
            out[(ix, iy)][y] = {"mean": float(np.mean(series)), "max": float(np.max(series))}
    return out, years_found


def gumbel_lmoments(annual_max):
    """Fit Gumbel via L-moments (Hosking PWM). annual_max: 1D array of annual maxima."""
    x = np.sort(np.asarray(annual_max, dtype=float))
    n = len(x)
    if n < 3:
        return None
    ranks = np.arange(1, n + 1)
    b1 = np.mean((ranks - 1) / (n - 1) * x)
    L1 = np.mean(x)
    L2 = 2 * b1 - L1
    if L2 <= 0:
        return None
    beta = L2 / math.log(2)
    xi = L1 - EULER_MASCHERONI * beta

    def q(t):
        return xi - beta * math.log(-math.log(1 - 1 / t))

    return {"xi": xi, "beta": beta, "n_years": n, "q10": q(10), "q50": q(50), "q100": q(100)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grand-csv", default="/perm/pad/cmf_v420_pkg_20240430/map/data/GRanD_allocated.csv")
    ap.add_argument("--ncdata", default="data/ncdata.nc")
    ap.add_argument("--liaise-cell", nargs=2, type=float, default=[40.625, 0.875])
    ap.add_argument("--fortran-tmpl", default=None)
    ap.add_argument("--gpu-tmpl", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dams, basin_id = load_dams(args.grand_csv, args.ncdata, args.liaise_cell)
    print(f"{len(dams)} GRanD dams matched to basin {basin_id} (Ebro), "
          f"total capacity {sum(d['cap_mcm'] for d in dams)/1000:.2f} km3")

    cells = sorted({(d["ix"], d["iy"]) for d in dams})
    print(f"{len(cells)} unique grid cells (some dams share a 0.25deg cell)")

    fortran_stats, fortran_years = ({}, [])
    if args.fortran_tmpl:
        fortran_stats, fortran_years = fortran_annual_stats(args.fortran_tmpl, cells)
        print(f"Fortran naturalised series: {len(fortran_years)} years on disk ({fortran_years[0]}-{fortran_years[-1]} "
              f"if any)" if fortran_years else "Fortran naturalised series: none found")

    gpu_stats, gpu_years = ({}, [])
    if args.gpu_tmpl:
        dam_latlon = {(d["ix"], d["iy"]): (d["lat"], d["lon"]) for d in dams}
        gpu_stats, gpu_years = gpu_annual_stats(args.gpu_tmpl, dam_latlon)
        print(f"eclandpy/GPU series: {len(gpu_years)} years")

    rows = []
    for d in dams:
        cell = (d["ix"], d["iy"])
        row = dict(d)
        row["basin_id"] = basin_id

        f = fortran_stats.get(cell, {})
        if len(f) >= 3:
            means = [v["mean"] for v in f.values()]
            maxes = [v["max"] for v in f.values()]
            fit = gumbel_lmoments(maxes)
            row["fortran_n_years"] = len(f)
            row["fortran_q_mean"] = round(float(np.mean(means)), 2)
            row["fortran_q_max_mean"] = round(float(np.mean(maxes)), 2)
            if fit:
                row["fortran_q100"] = round(fit["q100"], 2)
                row["fortran_q10"] = round(fit["q10"], 2)
        else:
            row["fortran_n_years"] = len(f)

        g = gpu_stats.get(cell, {})
        if len(g) >= 3:
            means = [v["mean"] for v in g.values()]
            maxes = [v["max"] for v in g.values()]
            fit = gumbel_lmoments(maxes)
            row["gpu_n_years"] = len(g)
            row["gpu_q_mean"] = round(float(np.mean(means)), 2)
            row["gpu_q_max_mean"] = round(float(np.mean(maxes)), 2)
            if fit:
                row["gpu_q100"] = round(fit["q100"], 2)
                row["gpu_q10"] = round(fit["q10"], 2)
        else:
            row["gpu_n_years"] = len(g)

        rows.append(row)

    fieldnames = ["name", "river", "cap_mcm", "year", "ix", "iy", "lat", "lon", "uparea_km2", "basin_id",
                  "fortran_n_years", "fortran_q_mean", "fortran_q_max_mean", "fortran_q10", "fortran_q100",
                  "gpu_n_years", "gpu_q_mean", "gpu_q_max_mean", "gpu_q10", "gpu_q100"]
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: -r["cap_mcm"]):
            w.writerow(r)
    print(f"\nwrote {len(rows)} dams -> {args.out}")

    print(f"\n{'Dam':22s} {'River':18s} {'CAP_MCM':>8s} {'F_years':>7s} {'F_Qmean':>8s} {'F_Q100':>8s} "
          f"{'G_years':>7s} {'G_Qmean':>8s} {'G_Q100':>8s}")
    for r in sorted(rows, key=lambda r: -r["cap_mcm"]):
        print(f"{r['name']:22s} {r['river']:18s} {r['cap_mcm']:8.1f} "
              f"{r.get('fortran_n_years', 0):7d} {r.get('fortran_q_mean', float('nan')):8.1f} "
              f"{r.get('fortran_q100', float('nan')):8.1f} "
              f"{r.get('gpu_n_years', 0):7d} {r.get('gpu_q_mean', float('nan')):8.1f} "
              f"{r.get('gpu_q100', float('nan')):8.1f}")


if __name__ == "__main__":
    main()
