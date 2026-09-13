#!/usr/bin/env python3
"""5-year discharge skill benchmark: Fortran vs CaMa-Flood-GPU vs real GRDC gauges.

Scores both LIAISE CaMa-Flood implementations against the 7 real gauges in
cama_flood/data/liaise_grdc_observations.nc, for 5 years spanning the
observed flow range (1988 wettest, 2003 2nd-wettest, 2000 near-normal, 1995
dry, 2005 driest -- picked from the GRDC data itself, see CLAUDE.md).

Inputs (both outside this repo, paths hard-coded below -- see CLAUDE.md for
how to regenerate them):
  - Fortran: run_liaise_ecland.sh's o_totout.nc, one per year, each a
    2-pass run (INITIAL_RESTART from the already-spun-up
    run/output/<year>/restart_in.nc for land, INITIAL_RESTART_CMF from a
    same-year spin-up pass for CaMa-Flood's own river storage).
  - GPU: CaMa-Flood-GPU's own equivalent 2-pass (same-year, in-process
    save_state()/restore) spin-up, run by a parallel session -- see
    CLAUDE.md's "CaMa-Flood-GPU river-storage spin-up" section.

Matching: each gauge's exact Fortran grid cell is already known
(cama15_iy/cama15_ix in the observations file, direct index -- no
nearest-neighbor needed). The GPU catchment is matched by an EXACT global
grid-index computation from the same cama15_lat/cama15_lon lookup cell
(catchment_id = ix_global*ny + iy_global on the shared glb_15min grid --
exact because both sides use the identical static_network_nc_v2.1 network
as of the 2026-09-13 FIXDIR rebuild, see CLAUDE.md).

BUG FOUND AND FIXED 2026-09-13: this used to be a "nearest lat/lon" search
against the GPU output's own longitude/latitude fields -- which come from
lonlat.bin's per-catchment OUTLET-PIXEL coordinate (can sit anywhere
within, or even outside, the nominal 0.25deg grid-cell-center Fortran's
cama15_lat/lon represents), not the grid-cell center itself. Geographic
"nearest" is not the same as "same grid cell", let alone "same river-
network position" -- verified this silently matched the WRONG catchment
at 5 of 7 gauges, with match_dist_deg looking deceptively small (0.08-
0.26 deg, ~9-29 km -- easily one grid cell at 0.25deg resolution) every
time. Worst case: RIO CINCA, FRAGA's true upstream_area is 9678 km2
(matches the real GRDC-reported ~9637 km2 almost exactly); the old
nearest-lat/lon match landed on a catchment with upstream_area=488 km2 --
a 20x-too-small tributary stub ~30 km away, not the gauge's own river.
This affected every GPU comparison run this session (v4.30, v4.20,
v21fixdir, v21fixdir2 alike, since the bug was in this shared matching
logic, not particular to any one parameters.nc) -- re-score anything
that depended on the old per-gauge GPU numbers, not just the aggregates.

Excludes RIO GUADALOPE, CASPE from aggregate statistics: real discharge
there is near-zero for long stretches (a regulated river, dam/irrigation
controlled), which breaks variance-based metrics (KGE/NSE denominators
blow up) -- not a genuine model-skill signal. Left in the raw results
JSON, just excluded from the printed summaries.

Usage
-----
    # default: no-bifurcation GPU run (the original comparison)
    python3 skill_benchmark_fortran_vs_gpu.py

    # bifurcation-enabled GPU run (2026-09-12 rerun, see CLAUDE.md) --
    # confirmed to change ~48% of domain-wide GPU discharge but only
    # ~1e-5 to 3e-4 m3/s (float noise) at these 7 gauges specifically,
    # none of which sit near one of the domain's 36 bifurcation paths
    python3 skill_benchmark_fortran_vs_gpu.py --gpu-suffix _bif
"""

import argparse
import datetime
import json

import netCDF4 as nc
import numpy as np

YEARS = [1988, 1995, 2000, 2003, 2005]
OBS_PATH = "/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/cama_flood/data/liaise_grdc_observations.nc"
FORTRAN_TMPL = "/perm/pad/liaise_discharge_compare/run_root_fortran_{y}_final/output/{y}/o_totout.nc"
GPU_TMPL = "/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_{{y}}_discharge_daily_spunup{suffix}.nc"
# glb_15min global grid convention (cmfgpu.params.merit_map.MERITMap):
# catchment_id = ix_global*GLOBAL_NY + iy_global.
GLOBAL_WEST, GLOBAL_NORTH = -180.0, 90.0
GLOBAL_DLON, GLOBAL_DLAT = 0.25, 0.25
GLOBAL_NY = 720


def nc_time_to_dates(var):
    raw = var[:]
    units = var.units
    calendar = getattr(var, "calendar", "standard")
    cft = nc.num2date(raw, units=units, calendar=calendar)
    return np.array([datetime.date(d.year, d.month, d.day) for d in cft])


def kge(sim, obs):
    r = np.corrcoef(sim, obs)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2), r, alpha, beta


def nse(sim, obs):
    return 1 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)


def pbias(sim, obs):
    return 100 * np.sum(sim - obs) / np.sum(obs)


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--gpu-suffix", default="",
                     help="appended to the GPU discharge filename before .nc, e.g. _bif")
args = parser.parse_args()
gpu_tmpl = GPU_TMPL.format(suffix=args.gpu_suffix)
results_path = f"/perm/pad/liaise_discharge_compare/skill_benchmark_results{args.gpu_suffix}.json"

# --- load observations ---
obs_ds = nc.Dataset(OBS_PATH)
obs_disc = obs_ds.variables["discharge"]
obs_disc.set_auto_mask(True)
obs_dates = np.array(
    [datetime.date(1970, 1, 1) + datetime.timedelta(days=int(t)) for t in obs_ds.variables["time"][:]]
)
station_ids = obs_ds.variables["station_id"][:]
station_names = obs_ds.variables["station_name"][:]
cama15_iy = obs_ds.variables["cama15_iy"][:]
cama15_ix = obs_ds.variables["cama15_ix"][:]
cama15_lat = obs_ds.variables["cama15_lat"][:]
cama15_lon = obs_ds.variables["cama15_lon"][:]
n_stations = len(station_ids)

results = []  # one row per (year, station, model)

for y in YEARS:
    # --- Fortran ---
    f_fortran = nc.Dataset(FORTRAN_TMPL.format(y=y))
    v_fortran = f_fortran.variables["totout"]
    v_fortran.set_auto_mask(True)
    fortran_dates = nc_time_to_dates(f_fortran.variables["time"])
    fortran_data = np.asarray(v_fortran[:].filled(np.nan))  # (time, lat, lon)

    # --- GPU ---
    f_gpu = nc.Dataset(gpu_tmpl.format(y=y))
    gpu_dates = nc_time_to_dates(f_gpu.variables["time"])
    gpu_disc = np.asarray(f_gpu.variables["discharge"][:])  # (time, catchment)
    gpu_catchment_id = np.asarray(f_gpu.variables["catchment_id"][:])
    gpu_cid_to_idx = {int(c): k for k, c in enumerate(gpu_catchment_id)}

    for i in range(n_stations):
        name = station_names[i]
        iy, ix = int(cama15_iy[i]), int(cama15_ix[i])

        # GPU: EXACT global grid-index match (see module docstring for why
        # this replaced a nearest-lat/lon search).
        ix_g = round((float(cama15_lon[i]) - GLOBAL_WEST - GLOBAL_DLON / 2) / GLOBAL_DLON)
        iy_g = round((GLOBAL_NORTH - float(cama15_lat[i]) - GLOBAL_DLAT / 2) / GLOBAL_DLAT)
        exact_cid = ix_g * GLOBAL_NY + iy_g
        if exact_cid not in gpu_cid_to_idx:
            raise ValueError(
                f"{name}: exact catchment_id {exact_cid} (from cama15_lat="
                f"{cama15_lat[i]}, cama15_lon={cama15_lon[i]}) is not in "
                f"the GPU domain -- domain clipping or grid convention "
                f"mismatch, investigate before trusting this comparison"
            )
        gidx = gpu_cid_to_idx[exact_cid]
        match_dist_deg = 0.0  # exact grid-index match, not nearest-neighbor

        fortran_series = fortran_data[:, iy, ix]
        gpu_series = gpu_disc[:, gidx]

        obs_year_mask = np.array([dt.year == y for dt in obs_dates])
        obs_series = np.asarray(obs_disc[obs_year_mask, i].filled(np.nan))
        obs_year_dates = obs_dates[obs_year_mask]

        # align all three on common calendar dates
        common = sorted(set(fortran_dates) & set(gpu_dates) & set(obs_year_dates))
        if len(common) < 30:
            continue
        f_idx = {d: k for k, d in enumerate(fortran_dates)}
        g_idx = {d: k for k, d in enumerate(gpu_dates)}
        o_idx = {d: k for k, d in enumerate(obs_year_dates)}

        f_al = np.array([fortran_series[f_idx[d]] for d in common])
        g_al = np.array([gpu_series[g_idx[d]] for d in common])
        o_al = np.array([obs_series[o_idx[d]] for d in common])

        valid = np.isfinite(f_al) & np.isfinite(g_al) & np.isfinite(o_al) & (o_al > 0)
        if valid.sum() < 30:
            continue
        f_v, g_v, o_v = f_al[valid], g_al[valid], o_al[valid]

        for model_name, sim in [("Fortran", f_v), ("GPU", g_v)]:
            k, r, alpha, beta = kge(sim, o_v)
            results.append({
                "year": y, "station": name, "model": model_name,
                "n_days": int(valid.sum()), "match_dist_deg": match_dist_deg,
                "kge": float(k), "r": float(r), "alpha": float(alpha), "beta": float(beta),
                "nse": float(nse(sim, o_v)), "pbias_pct": float(pbias(sim, o_v)),
                "obs_mean": float(np.mean(o_v)), "sim_mean": float(np.mean(sim)),
            })

with open(results_path, "w") as fh:
    json.dump(results, fh, indent=2)

# --- summary ---
print(f"{'Year':>5} {'Station':30s} {'Model':8s} {'KGE':>7} {'NSE':>7} {'r':>6} {'PBIAS%':>8} {'n':>4}")
for row in results:
    print(f"{row['year']:>5} {row['station'][:30]:30s} {row['model']:8s} "
          f"{row['kge']:7.3f} {row['nse']:7.3f} {row['r']:6.3f} {row['pbias_pct']:8.1f} {row['n_days']:>4}")

print("\n=== Median skill by model, across all station-years ===")
for model_name in ["Fortran", "GPU"]:
    sub = [r for r in results if r["model"] == model_name]
    for metric in ["kge", "nse", "r", "pbias_pct"]:
        vals = [r[metric] for r in sub]
        print(f"  {model_name:8s} {metric:10s} median={np.median(vals):7.3f}  mean={np.mean(vals):7.3f}")

print("\n=== Median skill by model, per year ===")
for y in YEARS:
    for model_name in ["Fortran", "GPU"]:
        sub = [r for r in results if r["model"] == model_name and r["year"] == y]
        if not sub:
            continue
        kges = [r["kge"] for r in sub]
        pbiases = [r["pbias_pct"] for r in sub]
        print(f"  {y} {model_name:8s} median_KGE={np.median(kges):7.3f}  median_PBIAS%={np.median(pbiases):7.1f}  n_stations={len(sub)}")
