#!/usr/bin/env python3
"""Non-comparative discharge skill of the Fortran ecLand-CaMa-Flood control chain.

Unlike skill_benchmark_chains.py (which scores the Fortran chain AGAINST the
eclandpy -> CaMa-Flood-GPU chain), this script scores the Fortran chain alone,
against every real gauge in an observation file -- GRDC and, optionally,
CAMELS-Spain (see extract_liaise_grdc_observations.py --providers). Output
feeds a "control" dashboard: per-gauge KGE / NSE / r / PBIAS with no second
model to compare against.

Scoring window note: this only scores years where
<fortran-tmpl>.format(y=year) actually exists on disk. The validated
1988-2024 coupled run's raw o_totout.nc was produced for all 37 years (see
CLAUDE.md, "37-year ecLand-CaMa-Flood coupled run"), but /perm/pad's copy was
partly cleaned up after the two-chains benchmark consumed it, so as of this
script's writing only 1988-1994 (7 years) remain on disk. Where a gauge was
already scored by skill_benchmark_chains.py against the fuller 1988-2014
window (the original 7 GRDC gauges), pass that JSON via --reuse-fortran-rows
to keep those richer results instead of recomputing against the smaller
window -- the JSON rows are a permanent record of a real computation, not
invalidated by the source file being cleaned up afterwards.

Usage
-----
    python3 skill_benchmark_control.py \\
        --obs data/liaise_river_observations_grdc_camels.nc \\
        --fortran-tmpl /perm/pad/liaise_cmf_1988_2024/output/{y}/o_totout.nc \\
        --reuse-fortran-rows /perm/pad/liaise_discharge_compare/skill_benchmark_chains.json \\
        --out /perm/pad/liaise_discharge_compare/skill_benchmark_control.json
"""

import argparse
import datetime
import json
import os
from collections import defaultdict

import netCDF4 as nc
import numpy as np


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


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--obs", required=True)
ap.add_argument("--fortran-tmpl", required=True)
ap.add_argument("--reuse-fortran-rows", default=None,
                 help="a skill_benchmark_chains.py (or this script's own) JSON whose Fortran rows, "
                      "for stations also present in --obs, are kept as-is instead of recomputed")
ap.add_argument("--min-days", type=int, default=30)
ap.add_argument("--out", required=True)
args = ap.parse_args()

obs_ds = nc.Dataset(args.obs)
obs_disc = obs_ds.variables["discharge"]
obs_disc.set_auto_mask(True)
obs_dates = np.array([datetime.date(1970, 1, 1) + datetime.timedelta(days=int(t))
                       for t in obs_ds.variables["time"][:]])
raw_names = [str(n) for n in obs_ds.variables["station_name"][:]]
station_ids = [int(s) for s in obs_ds.variables["station_id"][:]]
name_count = {n: raw_names.count(n) for n in raw_names}
seen = {}
names = []
for n, sid in zip(raw_names, station_ids):
    if name_count[n] > 1:
        seen[n] = seen.get(n, 0) + 1
        names.append(f"{n} [{sid}]")  # disambiguate distinct gauges sharing a display name
    else:
        names.append(n)
providers = [str(p) for p in obs_ds.variables["provider"][:]]
cama15_iy, cama15_ix = obs_ds.variables["cama15_iy"][:], obs_ds.variables["cama15_ix"][:]
obs_years = sorted({d.year for d in obs_dates})

reused_by_key = {}
if args.reuse_fortran_rows and os.path.exists(args.reuse_fortran_rows):
    with open(args.reuse_fortran_rows) as fh:
        prior = json.load(fh)
    for r in prior:
        if r.get("model") == "Fortran":
            reused_by_key[(r["station"], r["year"])] = r
    print(f"reusing up to {len(reused_by_key)} previously-scored Fortran station-years "
          f"from {args.reuse_fortran_rows} (only for station/year combos not freshly computed below)")

years = [y for y in obs_years if os.path.exists(args.fortran_tmpl.format(y=y))]
if not years:
    raise SystemExit(f"no year in {obs_years} has a Fortran o_totout.nc at {args.fortran_tmpl}")
print(f"scoring against {len(years)} year(s) with o_totout.nc on disk: {years}")

results = []
covered_keys = set()
for y in years:
    f_ds = nc.Dataset(args.fortran_tmpl.format(y=y))
    v = f_ds.variables["totout"]
    v.set_auto_mask(True)
    f_dates = nc_dates(f_ds.variables["time"])
    f_data = np.asarray(v[:].filled(np.nan))

    obs_mask = np.array([d.year == y for d in obs_dates])
    obs_year_dates = obs_dates[obs_mask]

    for i, name in enumerate(names):
        iy, ix = int(cama15_iy[i]), int(cama15_ix[i])
        f_daily = daily_mean(f_dates, f_data[:, iy, ix])
        o_series = np.asarray(obs_disc[obs_mask, i].filled(np.nan))
        o_daily = {d: o_series[k] for k, d in enumerate(obs_year_dates)}

        common = sorted(set(f_daily) & set(o_daily))
        f_al = np.array([f_daily[d] for d in common])
        o_al = np.array([o_daily[d] for d in common])
        valid = np.isfinite(f_al) & np.isfinite(o_al) & (o_al > 0)
        if valid.sum() < args.min_days:
            continue
        f_v, o_v = f_al[valid], o_al[valid]
        k, r, a, b = kge(f_v, o_v)
        results.append({"year": y, "station": name, "provider": providers[i], "model": "Fortran",
                        "n_days": int(valid.sum()), "kge": float(k), "r": float(r), "alpha": float(a),
                        "beta": float(b), "nse": float(nse(f_v, o_v)), "pbias_pct": float(pbias(f_v, o_v)),
                        "obs_mean": float(np.mean(o_v)), "sim_mean": float(np.mean(f_v))})
        covered_keys.add((name, y))

n_fresh = len(results)
for (name, y), row in reused_by_key.items():
    if (name, y) in covered_keys:
        continue  # a fresh computation for this station/year exists; don't also carry the reused one
    if name not in names:
        continue  # reused JSON may cover stations not in this --obs file
    results.append(row)

with open(args.out, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"wrote {len(results)} rows ({n_fresh} freshly computed, {len(results) - n_fresh} reused) -> {args.out}")

by_station = defaultdict(list)
for r in results:
    by_station[r["station"]].append(r)
print(f"\n{len(by_station)} stations scored, {len(results)} station-years total")
for name, rows in sorted(by_station.items()):
    yrs = sorted(r["year"] for r in rows)
    print(f"  {name:40s} n={len(rows):3d} years {yrs[0]}-{yrs[-1]:<6} "
          f"median KGE {np.median([r['kge'] for r in rows]):7.3f}")
