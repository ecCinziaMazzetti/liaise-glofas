#!/usr/bin/env python3
"""Estimate per-dam annual mean/max discharge and the 100-year flood (Q100) for the
45 GRanD reservoirs draining to the Ebro within the LIAISE domain.

Step 2+3 of the "Ebro Reservoir Operation" activation pipeline
(https://claude.ai/artifact/V5ZZxE3K4jFS6tsds5JiP3, section 3) -- the CaMa-Flood v4.20
dam module (`cmf_ctrl_damout_mod.F90`, already in `ecland`, currently off via
`LDAMOUT=.FALSE.`) needs a `dam_param.csv` with, per reservoir: normal/flood discharge
derived from the naturalised annual mean and the Gumbel-fit 100-year flood.

Dam allocation: AREA-AWARE, not nearest-cell (fixed 2026-09-17 -- see below).
`GRanD_allocated.csv` (from the CaMa-Flood v4.20 package) ships each dam already
allocated on the package's own river network, recording both the allocated
coordinates (`lat_alloc`/`lon_alloc`) and, crucially, the upstream area that
allocation drains (`area_alloc`). That allocation is excellent -- `area_alloc`
matches each dam's real reported catchment (`area_ori`) to a median 1.00x, zero
dams off by more than 2x.

Earlier versions of this script assumed `lat_alloc`/`lon_alloc` were snapped to
the glb_15min grid and simply nearest-cell-matched them. **They are not snapped
to any regular grid** (checked 2026-09-17: 0% of the 7320 global dams' coordinates
sit at a cell centre at 1/3/6/15 arcmin), so nearest-cell matching put small
tributary dams on whatever large river dominates the coarse cell -- it reproduced
the allocator's own `area_alloc` for only 3 of 45 Ebro dams, with errors up to 21x
(Ordunte: 47 km2 real catchment, matched to a 987 km2 cell). Same class of bug as
the GRDC gauge-matching one in CLAUDE.md: geographic "nearest" is not the same
position on the river network.

The fix: search a small neighbourhood (`--alloc-radius`, default 0.30 deg) around
the allocated coordinates and take the cell whose own `uparea` best matches
`area_alloc` in log space, restricted to the target basin. Allocation quality is
reported per dam (`uparea_err_pct` in the output CSV) and summarised at the end --
never assume it worked, check the number.

Resolution matters here and is not a detail: within 20% of `area_alloc`, this
allocates 19/45 dams at glb_15min, 43/45 at glb_06min and 45/45 at glb_03min.
Most of these reservoirs are simply not siteable on a 0.25deg grid at all (a
28 km2 catchment cannot exist where the smallest cell drains ~770 km2), so
per-dam Q100 at glb_15min is structurally limited no matter how good the code is.

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


def _unmask(var):
    a = var[:]
    return np.asarray(a.filled(-1)) if np.ma.isMaskedArray(a) else np.asarray(a)


def find_target_basin(lat, lon, basin, uparea, mouth_box=(40.4, 41.0, 0.5, 1.2)):
    """Basin id of the Ebro, found by network position rather than a fixed cell.

    A hardcoded lat/lon (the old `--liaise-cell`) is masked/off-network at
    glb_06min and glb_03min, where that exact coordinate is not a river cell --
    so it silently yielded no dams at all at finer resolutions. Taking the basin
    of the largest-upstream-area cell near the Ebro mouth works at every
    resolution tried (15/06/03 arcmin all return basin id 4, mouth uparea
    ~84,737 km2, matching the real Ebro).
    """
    s, n, w, e = mouth_box
    iys = np.where((lat >= s) & (lat <= n))[0]
    ixs = np.where((lon >= w) & (lon <= e))[0]
    if iys.size == 0 or ixs.size == 0:
        raise SystemExit(f"mouth box {mouth_box} lies outside this grid")
    sub = uparea[np.ix_(iys, ixs)]
    j = np.unravel_index(np.argmax(sub), sub.shape)
    return basin[iys[j[0]], ixs[j[1]]], float(sub.max()) / 1e6


def allocate_cell(lat, lon, basin, uparea, target_basin, dlat, dlon, area_alloc, radius):
    """Cell within `radius` whose uparea best matches the allocator's own area_alloc.

    Returns (ix, iy, uparea_km2, err_pct) or None.

    Two questions get answered separately here, and conflating them produces
    garbage in both directions (both failure modes were hit on 2026-09-17):

    1. *Which river system is this dam on?* -> decided by the caller from the
       nearest valid river cell (proximity). Searching all basins for the best
       AREA match instead wrongly dropped 14 genuine Ebro reservoirs -- the Ebro
       dam itself, Bubal, Eugui, Irabia, Ullivarri, Urrunaga and others, all with
       18-467 km2 catchments that no 0.25 deg Ebro cell can represent, so a
       neighbouring basin's headwater cell won on area alone. Conversely,
       restricting the area search to the target basin dragged IN 17 non-Ebro
       dams from across the divide (Duero's AguilardeCampoo/CuerdadelPozo, the
       French Ariege's Naguilhes/Matemale), because at 0.25 deg a 0.30 deg radius
       reaches over the watershed.
    2. *Which cell should its Q100 be read from?* -> that, and only that, is what
       the area match decides, within the already-chosen basin.

    Basin assignment near the Pyrenean divide is genuinely unresolvable at
    glb_15min (a 0.25 deg cell straddles it), so a few French-slope dams remain
    assigned to the Ebro there; they resolve correctly at finer resolutions.
    """
    if not (area_alloc > 0):
        return None
    best = None
    for iy in np.where(np.abs(lat - dlat) <= radius)[0]:
        for ix in np.where(np.abs(lon - dlon) <= radius)[0]:
            if basin[iy, ix] != target_basin:
                continue
            a = float(uparea[iy, ix]) / 1e6
            if a <= 0:
                continue
            err = abs(math.log(a / area_alloc))
            if best is None or err < best[0]:
                best = (err, int(ix), int(iy), a)
    if best is None:
        return None
    _, ix, iy, a = best
    return ix, iy, a, abs(a - area_alloc) / area_alloc * 100.0


def load_dams(grand_csv, ncdata_path, radius=0.30):
    ds = nc.Dataset(ncdata_path)
    lat = np.asarray(ds.variables["lat"][:])
    lon = np.asarray(ds.variables["lon"][:])
    basin = _unmask(ds.variables["basin"])
    uparea = _unmask(ds.variables["uparea"])

    target_basin, mouth_area = find_target_basin(lat, lon, basin, uparea)
    print(f"target basin id {target_basin} (mouth uparea {mouth_area:.0f} km2), "
          f"grid {len(lat)}x{len(lon)}, allocation radius {radius} deg")

    dams, unallocated = [], []
    with open(grand_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                dlat, dlon = float(row["lat_alloc"]), float(row["lon_alloc"])
                area_alloc = float(row["area_alloc"])
            except ValueError:
                continue
            if not (lat.min() - 0.5 <= dlat <= lat.max() + 0.5 and lon.min() - 0.5 <= dlon <= lon.max() + 0.5):
                continue
            # Step 1: basin membership, from the nearest river cell (proximity).
            iy_n = int(np.argmin(np.abs(lat - dlat)))
            ix_n = int(np.argmin(np.abs(lon - dlon)))
            if basin[iy_n, ix_n] != target_basin:
                continue
            # Step 2: which cell to read Q100 from, by drainage-area match.
            hit = allocate_cell(lat, lon, basin, uparea, target_basin, dlat, dlon, area_alloc, radius)
            if hit is None:
                continue
            ix, iy, ua_km2, err_pct = hit
            dams.append({
                "name": row["DamName"], "river": row["RiverName"], "cap_mcm": float(row["CAP_MCM"]),
                "year": row["YEAR"], "ix": ix, "iy": iy, "lat": float(lat[iy]), "lon": float(lon[ix]),
                "uparea_km2": ua_km2, "area_alloc_km2": area_alloc, "uparea_err_pct": err_pct,
            })
            if err_pct > 20.0:
                unallocated.append((row["DamName"], area_alloc, ua_km2, err_pct))

    errs = np.array([d["uparea_err_pct"] for d in dams])
    if errs.size:
        print(f"allocation quality: {int((errs <= 20).sum())}/{len(dams)} dams within 20% of "
              f"area_alloc, median error {np.median(errs):.1f}%")
    if unallocated:
        print(f"  {len(unallocated)} dam(s) worse than 20% -- their Q100 is NOT trustworthy "
              f"at this resolution:")
        for name, aa, ua_km2, e in sorted(unallocated, key=lambda t: -t[3])[:10]:
            print(f"    {name:<20} wanted {aa:>8.0f} km2, best cell drains {ua_km2:>8.0f} km2 ({e:.0f}% off)")
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
    ap.add_argument("--alloc-radius", type=float, default=0.30,
                    help="search radius (deg) for area-aware dam allocation; "
                         "the cell with the closest uparea to area_alloc wins")
    ap.add_argument("--fortran-tmpl", default=None)
    ap.add_argument("--gpu-tmpl", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dams, basin_id = load_dams(args.grand_csv, args.ncdata, args.alloc_radius)
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

    fieldnames = ["name", "river", "cap_mcm", "year", "ix", "iy", "lat", "lon", "uparea_km2",
                  "area_alloc_km2", "uparea_err_pct", "basin_id",
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
