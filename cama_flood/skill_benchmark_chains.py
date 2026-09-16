#!/usr/bin/env python3
"""Multi-year discharge skill benchmark of two continuous chains vs the GRDC gauges.

Generalises skill_benchmark_fortran_vs_gpu.py (five 2-pass benchmark years) to
two *restart-chained* multi-year runs scored over every year that has GRDC
observations (1988-2014 in cama_flood/data/liaise_grdc_observations.nc):

  A ("Fortran"): the ecLand-CaMa-Flood coupled chain (LECMF1WAY, 1988->2024),
     run_liaise_ecland.sh output, one o_totout.nc per year. Written at
     IFRQ_OUT hours (6 h in namelist/input_cmf), so it is averaged to daily
     means here before matching -- the 2-pass benchmark files were daily.
  B ("GPU"): the eclandpy -> CaMa-Flood-GPU chain (eclandpy_bridge/), one
     eclandpy_liaise_<year>_discharge_daily.nc per year (catchment vector,
     matched by the exact glb_15min global grid index, as in the 5-year script).

Same metrics, same exclusion of RIO GUADALOPE, CASPE from the printed
aggregates, same JSON row schema as the 5-year benchmark, so the existing
dashboard code can consume it.

Usage
-----
    python3 skill_benchmark_chains.py                 # all years with both files
    python3 skill_benchmark_chains.py --years 1988-1999
"""

import argparse
import datetime
import json
import os
from collections import defaultdict

import netCDF4 as nc
import numpy as np

OBS_PATH = "/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/cama_flood/data/liaise_grdc_observations.nc"
FORTRAN_TMPL = "/perm/pad/liaise_cmf_1988_2024/output/{y}/o_totout.nc"
GPU_TMPL = ("/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/eclandpy_bridge/"
            "cmfgpu_out_gpu_repro/eclandpy_liaise_{y}_discharge_daily.nc")
OUT_DEFAULT = "/perm/pad/liaise_discharge_compare/skill_benchmark_chains.json"
GLOBAL_WEST, GLOBAL_NORTH, GLOBAL_DLON, GLOBAL_DLAT, GLOBAL_NY = -180.0, 90.0, 0.25, 0.25, 720
EXCLUDED = "RIO GUADALOPE, CASPE"


def nc_dates(var):
    cft = nc.num2date(var[:], units=var.units, calendar=getattr(var, "calendar", "standard"))
    return np.array([datetime.date(d.year, d.month, d.day) for d in cft])


def daily_mean(dates, series):
    """Average sub-daily records onto calendar days; pass daily data through."""
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


def parse_years(spec):
    if spec is None:
        return None
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(s) for s in spec.split(",")]


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--fortran-tmpl", default=FORTRAN_TMPL)
parser.add_argument("--gpu-tmpl", default=GPU_TMPL)
parser.add_argument("--years", default=None, help="e.g. 1988-2014 or 1988,1995; default: every year with both files")
parser.add_argument("--out", default=OUT_DEFAULT)
args = parser.parse_args()

obs_ds = nc.Dataset(OBS_PATH)
obs_disc = obs_ds.variables["discharge"]
obs_disc.set_auto_mask(True)
obs_dates = np.array([datetime.date(1970, 1, 1) + datetime.timedelta(days=int(t)) for t in obs_ds.variables["time"][:]])
names = obs_ds.variables["station_name"][:]
cama15_iy, cama15_ix = obs_ds.variables["cama15_iy"][:], obs_ds.variables["cama15_ix"][:]
cama15_lat, cama15_lon = obs_ds.variables["cama15_lat"][:], obs_ds.variables["cama15_lon"][:]
obs_years = sorted({d.year for d in obs_dates})

years = parse_years(args.years) or obs_years
years = [y for y in years if os.path.exists(args.fortran_tmpl.format(y=y)) and os.path.exists(args.gpu_tmpl.format(y=y))]
if not years:
    raise SystemExit("no year has both a Fortran and a GPU discharge file")
print(f"scoring {len(years)} years: {years[0]}-{years[-1]}")

results = []
for y in years:
    f_ds = nc.Dataset(args.fortran_tmpl.format(y=y))
    v = f_ds.variables["totout"]
    v.set_auto_mask(True)
    f_dates = nc_dates(f_ds.variables["time"])
    f_data = np.asarray(v[:].filled(np.nan))

    g_ds = nc.Dataset(args.gpu_tmpl.format(y=y))
    g_dates = nc_dates(g_ds.variables["time"])
    g_disc = np.asarray(g_ds.variables["discharge"][:])
    g_idx_of = {int(c): k for k, c in enumerate(np.asarray(g_ds.variables["catchment_id"][:]))}

    obs_mask = np.array([d.year == y for d in obs_dates])
    obs_year_dates = obs_dates[obs_mask]

    for i, name in enumerate(names):
        iy, ix = int(cama15_iy[i]), int(cama15_ix[i])
        ix_g = round((float(cama15_lon[i]) - GLOBAL_WEST - GLOBAL_DLON / 2) / GLOBAL_DLON)
        iy_g = round((GLOBAL_NORTH - float(cama15_lat[i]) - GLOBAL_DLAT / 2) / GLOBAL_DLAT)
        cid = ix_g * GLOBAL_NY + iy_g
        if cid not in g_idx_of:
            raise ValueError(f"{name}: catchment_id {cid} not in the GPU domain")

        f_daily = daily_mean(f_dates, f_data[:, iy, ix])
        g_daily = daily_mean(g_dates, g_disc[:, g_idx_of[cid]])
        o_series = np.asarray(obs_disc[obs_mask, i].filled(np.nan))
        o_daily = {d: o_series[k] for k, d in enumerate(obs_year_dates)}

        common = sorted(set(f_daily) & set(g_daily) & set(o_daily))
        f_al = np.array([f_daily[d] for d in common])
        g_al = np.array([g_daily[d] for d in common])
        o_al = np.array([o_daily[d] for d in common])
        valid = np.isfinite(f_al) & np.isfinite(g_al) & np.isfinite(o_al) & (o_al > 0)
        if valid.sum() < 30:
            continue
        f_v, g_v, o_v = f_al[valid], g_al[valid], o_al[valid]
        for model, sim in (("Fortran", f_v), ("GPU", g_v)):
            k, r, a, b = kge(sim, o_v)
            results.append({"year": y, "station": str(name), "model": model, "n_days": int(valid.sum()),
                            "match_dist_deg": 0.0, "kge": float(k), "r": float(r), "alpha": float(a),
                            "beta": float(b), "nse": float(nse(sim, o_v)), "pbias_pct": float(pbias(sim, o_v)),
                            "obs_mean": float(np.mean(o_v)), "sim_mean": float(np.mean(sim))})

with open(args.out, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"wrote {len(results)} rows -> {args.out}")

kept = [r for r in results if r["station"] != EXCLUDED]
pairs = {}
for r in kept:
    pairs.setdefault((r["year"], r["station"]), {})[r["model"]] = r
n = sum(1 for p in pairs.values() if len(p) == 2)
gpu_wins = sum(1 for p in pairs.values() if len(p) == 2 and p["GPU"]["kge"] > p["Fortran"]["kge"])
print(f"\nstation-years scored (excl. {EXCLUDED}): {n}   GPU beats Fortran on KGE: {gpu_wins}/{n}")
for model in ("Fortran", "GPU"):
    sub = [r for r in kept if r["model"] == model]
    print(f"  {model:8s} median KGE {np.median([r['kge'] for r in sub]):7.3f}  median r {np.median([r['r'] for r in sub]):6.3f}"
          f"  median PBIAS {np.median([r['pbias_pct'] for r in sub]):7.1f}%")
