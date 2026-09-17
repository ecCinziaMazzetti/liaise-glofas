#!/usr/bin/env python3
"""Build the non-comparative "Ebro Gauge Skill Map" page from skill_benchmark_control.py output.

Data-driven counterpart of build_chain_dashboard.py, but for skill_benchmark_control.py's
single-model (Fortran control only) results: a map of every real gauge in --obs, colored by
whichever of KGE/NSE/r/PBIAS is selected, with a year picker and a sortable table.

    python3 build_control_dashboard.py \\
        --obs data/liaise_river_observations_grdc_camels.nc \\
        --results /perm/pad/liaise_discharge_compare/skill_benchmark_control.json \\
        --ncdata data/ncdata.nc \\
        --out /path/to/index.html
"""

import argparse
import json
import statistics
from collections import defaultdict

import netCDF4 as nc

# Ebro/LIAISE-domain river network geometry (glb_15min active river cells), shared with the
# earlier "Ebro Discharge Skill Map" artifact -- same domain, same background context.
RIVER_SEGMENTS = [[-1.375, 43.375, -1.625, 43.625], [-1.125, 43.375, -1.125, 43.625], [-0.875, 43.375, -1.125, 43.625], [-0.625, 43.375, -0.875, 43.375], [-0.375, 43.375, -0.625, 43.375], [-0.125, 43.375, 0.125, 43.375], [0.125, 43.375, 0.125, 43.625], [0.375, 43.375, 0.375, 43.625], [0.625, 43.375, 0.625, 43.875], [0.875, 43.375, 0.875, 43.625], [1.125, 43.375, 1.375, 43.625], [1.375, 43.375, 1.375, 43.625], [1.625, 43.375, 1.375, 43.375], [1.875, 43.375, 1.625, 43.625], [2.125, 43.375, 2.375, 43.375], [2.375, 43.375, 2.375, 43.125], [2.625, 43.375, 2.375, 43.625], [-2.125, 43.125, -2.125, 43.375], [-1.625, 43.125, -1.875, 43.375], [-1.375, 43.125, -1.375, 43.375], [-1.125, 43.125, -1.375, 43.125], [-0.875, 43.125, -0.875, 43.375], [-0.625, 43.125, -0.875, 43.375], [-0.125, 43.125, -0.375, 43.375], [0.125, 43.125, 0.125, 43.625], [0.625, 43.125, 0.875, 43.125], [0.875, 43.125, 1.125, 43.125], [1.125, 43.125, 1.125, 43.375], [1.375, 43.125, 1.375, 43.375], [1.625, 43.125, 1.625, 43.375], [1.875, 43.125, 1.625, 43.125], [2.125, 43.125, 2.375, 43.125], [2.375, 43.125, 2.625, 43.125], [2.625, 43.125, 2.875, 43.125], [2.875, 43.125, 3.125, 43.125], [-2.375, 42.875, -2.125, 43.125], [-2.125, 42.875, -1.875, 42.875], [-1.875, 42.875, -1.875, 42.625], [-1.625, 42.875, -1.875, 42.875], [-1.375, 42.875, -1.125, 42.875], [-1.125, 42.875, -1.375, 42.625], [-0.875, 42.875, -1.125, 42.625], [-0.625, 42.875, -0.625, 43.125], [-0.375, 42.875, -0.625, 43.125], [-0.125, 42.875, -0.125, 43.125], [0.125, 42.875, -0.125, 42.875], [0.375, 42.875, 0.625, 43.125], [0.625, 42.875, 0.625, 43.125], [1.125, 42.875, 0.875, 43.125], [1.375, 42.875, 1.625, 42.875], [1.625, 42.875, 1.625, 43.375], [1.875, 42.875, 1.875, 43.125], [2.125, 42.875, 2.125, 43.125], [2.375, 42.875, 2.875, 42.875], [2.625, 42.875, 2.875, 42.875], [-2.375, 42.625, -2.125, 42.625], [-2.125, 42.625, -1.875, 42.375], [-1.875, 42.625, -1.875, 42.125], [-1.625, 42.625, -1.625, 42.375], [-1.375, 42.625, -1.375, 42.375], [-1.125, 42.625, -1.375, 42.625], [-0.875, 42.625, -1.125, 42.625], [-0.625, 42.625, -0.875, 42.625], [-0.375, 42.625, -0.375, 42.375], [-0.125, 42.625, 0.125, 42.375], [0.125, 42.625, 0.125, 42.375], [0.375, 42.625, 0.375, 42.375], [0.875, 42.625, 0.625, 42.875], [1.125, 42.625, 1.125, 42.375], [1.375, 42.625, 1.125, 42.375], [1.625, 42.625, 1.375, 42.375], [1.875, 42.625, 1.625, 42.875], [2.125, 42.625, 2.125, 42.875], [2.375, 42.625, 2.625, 42.625], [2.625, 42.625, 2.875, 42.625], [-2.375, 42.375, -2.125, 42.375], [-2.125, 42.375, -1.875, 42.375], [-1.875, 42.375, -1.875, 42.125], [-1.625, 42.375, -1.875, 42.125], [-1.375, 42.375, -1.625, 42.375], [-0.875, 42.375, -1.125, 42.125], [-0.625, 42.375, -0.625, 42.125], [-0.375, 42.375, -0.625, 42.375], [-0.125, 42.375, -0.125, 42.125], [0.125, 42.375, 0.125, 42.125], [0.375, 42.375, 0.375, 42.125], [0.625, 42.375, 0.625, 42.125], [1.125, 42.375, 0.875, 42.125], [1.375, 42.375, 1.375, 42.125], [1.625, 42.375, 1.375, 42.375], [1.875, 42.375, 1.625, 42.375], [2.125, 42.375, 2.125, 42.125], [-2.375, 42.125, -1.875, 42.375], [-2.125, 42.125, -1.875, 42.125], [-1.875, 42.125, -1.625, 42.125], [-1.625, 42.125, -1.375, 41.875], [-1.375, 42.125, -1.125, 42.125], [-1.125, 42.125, -1.375, 41.875], [-0.875, 42.125, -0.875, 41.875], [-0.625, 42.125, -0.875, 42.125], [-0.375, 42.125, -0.375, 41.875], [-0.125, 42.125, -0.125, 41.875], [0.125, 42.125, 0.125, 41.875], [0.375, 42.125, 0.125, 42.125], [0.625, 42.125, 0.625, 41.875], [0.875, 42.125, 0.875, 41.875], [1.375, 42.125, 1.125, 41.875], [1.625, 42.125, 1.625, 41.875], [1.875, 42.125, 1.875, 41.875], [2.125, 42.125, 2.125, 41.875], [2.375, 42.125, 2.375, 41.875], [2.875, 42.125, 3.125, 42.125], [-2.375, 41.875, -2.375, 41.625], [-2.125, 41.875, -2.125, 42.125], [-1.625, 41.875, -1.625, 42.125], [-1.375, 41.875, -1.125, 41.875], [-1.125, 41.875, -0.875, 41.625], [-0.875, 41.875, -0.875, 41.625], [-0.625, 41.875, -0.875, 41.875], [-0.375, 41.875, -0.125, 41.625], [-0.125, 41.875, -0.125, 41.625], [0.125, 41.875, 0.125, 41.625], [0.375, 41.875, 0.375, 41.625], [0.625, 41.875, 0.625, 41.625], [0.875, 41.875, 0.625, 41.875], [1.125, 41.875, 0.875, 41.875], [1.375, 41.875, 1.125, 41.875], [1.625, 41.875, 1.875, 41.625], [1.875, 41.875, 1.875, 41.625], [2.125, 41.875, 2.375, 42.125], [2.375, 41.875, 2.625, 41.875], [2.625, 41.875, 2.875, 42.125], [-2.375, 41.625, -2.625, 41.375], [-2.125, 41.625, -2.375, 41.625], [-1.625, 41.625, -1.375, 41.625], [-1.375, 41.625, -1.125, 41.625], [-1.125, 41.625, -1.125, 41.875], [-0.875, 41.625, -0.625, 41.625], [-0.625, 41.625, -0.375, 41.375], [-0.125, 41.625, 0.125, 41.625], [0.125, 41.625, 0.375, 41.625], [0.375, 41.625, 0.375, 41.375], [0.625, 41.625, 0.375, 41.375], [0.875, 41.625, 0.625, 41.875], [1.375, 41.625, 1.625, 41.625], [1.625, 41.625, 1.875, 41.375], [1.875, 41.625, 2.125, 41.375], [2.375, 41.625, 2.125, 41.625], [2.625, 41.625, 2.875, 41.625], [-2.375, 41.375, -2.625, 41.375], [-2.125, 41.375, -1.875, 41.375], [-1.875, 41.375, -1.625, 41.375], [-1.625, 41.375, -1.625, 41.625], [-1.375, 41.375, -1.375, 41.625], [-1.125, 41.375, -0.875, 41.625], [-0.875, 41.375, -0.375, 41.375], [-0.625, 41.375, -0.375, 41.375], [-0.375, 41.375, -0.125, 41.375], [-0.125, 41.375, 0.125, 41.375], [0.125, 41.375, 0.375, 41.375], [0.375, 41.375, 0.375, 41.125], [0.875, 41.375, 0.625, 41.625], [1.125, 41.375, 1.125, 41.125], [1.875, 41.375, 2.125, 41.375], [-2.375, 41.125, -2.125, 41.375], [-2.125, 41.125, -1.875, 41.375], [-1.875, 41.125, -1.875, 41.375], [-1.625, 41.125, -1.875, 41.125], [-1.375, 41.125, -1.625, 41.375], [-1.125, 41.125, -1.125, 41.375], [-0.875, 41.125, -0.875, 41.375], [-0.625, 41.125, -0.375, 41.125], [-0.375, 41.125, -0.375, 41.375], [-0.125, 41.125, -0.125, 41.375], [0.125, 41.125, 0.375, 41.125], [0.375, 41.125, 0.625, 41.125], [0.625, 41.125, 0.375, 40.875], [0.875, 41.125, 0.625, 41.125], [-2.375, 40.875, -2.375, 40.625], [-2.125, 40.875, -2.375, 40.875], [-1.875, 40.875, -2.125, 40.875], [-1.375, 40.875, -1.375, 41.125], [-1.125, 40.875, -1.375, 40.875], [-0.875, 40.875, -0.625, 40.875], [-0.625, 40.875, -0.625, 41.125], [-0.375, 40.875, -0.125, 40.875], [-0.125, 40.875, -0.125, 41.125], [0.125, 40.875, 0.125, 41.125], [0.375, 40.875, 0.625, 40.875], [0.625, 40.875, 0.875, 40.625], [-2.375, 40.625, -2.625, 40.625], [-2.125, 40.625, -2.125, 40.875], [-1.875, 40.625, -2.125, 40.625], [-1.625, 40.625, -1.875, 40.875], [-1.375, 40.625, -1.375, 40.875], [-1.125, 40.625, -1.125, 40.375], [-0.875, 40.625, -1.125, 40.625], [-0.625, 40.625, -0.375, 40.875], [-0.125, 40.625, -0.375, 40.875], [0.125, 40.625, 0.125, 40.875], [-2.375, 40.375, -2.625, 40.375], [-2.125, 40.375, -2.375, 40.375], [-1.875, 40.375, -2.125, 40.125], [-1.625, 40.375, -1.375, 40.375], [-1.375, 40.375, -1.125, 40.375], [-1.125, 40.375, -1.125, 40.125], [-0.875, 40.375, -0.875, 40.125], [-0.625, 40.375, -0.625, 40.625], [-0.375, 40.375, -0.125, 40.125], [-2.375, 40.125, -2.625, 40.125], [-2.125, 40.125, -2.125, 39.875], [-1.875, 40.125, -1.875, 39.875], [-1.625, 40.125, -1.625, 39.875], [-1.375, 40.125, -1.125, 39.875], [-1.125, 40.125, -1.375, 40.125], [-0.875, 40.125, -0.625, 40.125], [-0.625, 40.125, -0.375, 40.125], [-0.125, 40.125, -0.375, 40.125], [-2.375, 39.875, -2.125, 39.625], [-2.125, 39.875, -2.375, 39.875], [-1.875, 39.875, -1.625, 39.625], [-1.625, 39.875, -1.875, 39.875], [-1.375, 39.875, -1.625, 39.625], [-1.125, 39.875, -1.125, 39.625], [-0.875, 39.875, -0.875, 39.625], [-0.625, 39.875, -0.375, 39.875], [-0.375, 39.875, -0.125, 39.625], [-2.375, 39.625, -2.375, 39.375], [-2.125, 39.625, -2.125, 39.375], [-1.875, 39.625, -1.875, 39.375], [-1.625, 39.625, -1.375, 39.375], [-1.375, 39.625, -0.625, 39.375], [-1.125, 39.625, -0.875, 39.625], [-0.875, 39.625, -0.625, 39.625], [-0.625, 39.625, -0.375, 39.375], [2.875, 39.625, 3.125, 39.875]]


def nanmedian(vals):
    vals = [v for v in vals if v is not None and v == v]
    return round(statistics.median(vals), 4) if vals else None


def build_stations(obs_path, results_path, ncdata_path):
    ds = nc.Dataset(obs_path)
    names = [str(n) for n in ds.variables["station_name"][:]]
    providers = [str(p) for p in ds.variables["provider"][:]]
    slat, slon = ds.variables["station_lat"][:], ds.variables["station_lon"][:]
    sid = [int(s) for s in ds.variables["station_id"][:]]
    iy, ix = ds.variables["cama15_iy"][:], ds.variables["cama15_ix"][:]
    name_count = {n: names.count(n) for n in names}

    uparea = nc.Dataset(ncdata_path).variables["uparea"][:]

    meta = {}
    for i, n in enumerate(names):
        disp = f"{n} [{sid[i]}]" if name_count[n] > 1 else n
        meta[disp] = {
            "lat": float(slat[i]), "lon": float(slon[i]), "provider": providers[i],
            "area_km2": round(float(uparea[iy[i], ix[i]]) / 1e6, 1),
        }

    with open(results_path) as fh:
        rows = json.load(fh)
    by_station = defaultdict(list)
    for r in rows:
        by_station[r["station"]].append(r)

    stations = []
    for name, yrows in by_station.items():
        m = meta.get(name)
        if m is None:
            continue
        yrows = sorted(yrows, key=lambda r: r["year"])
        years_covered = [r["year"] for r in yrows]
        stations.append({
            "name": name, "lat": m["lat"], "lon": m["lon"], "provider": m["provider"],
            "area_km2": m["area_km2"],
            "median_kge": nanmedian([r["kge"] for r in yrows]),
            "median_nse": nanmedian([r["nse"] for r in yrows]),
            "median_r": nanmedian([r["r"] for r in yrows]),
            "median_pbias": nanmedian([r["pbias_pct"] for r in yrows]),
            "n_years": len(yrows), "year_min": min(years_covered), "year_max": max(years_covered),
            "years": [{"year": r["year"], "kge": r["kge"], "nse": r["nse"], "r": r["r"],
                       "pbias": r["pbias_pct"], "obs_mean": round(r["obs_mean"], 3)} for r in yrows],
        })
    stations.sort(key=lambda s: -s["area_km2"])
    return stations


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--obs", required=True)
ap.add_argument("--results", required=True)
ap.add_argument("--ncdata", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--n-excluded", type=int, default=6,
                 help="stations matched to the basin but dropped for insufficient overlap (footer text only)")
args = ap.parse_args()

STATIONS = build_stations(args.obs, args.results, args.ncdata)
n_total = len(STATIONS)
n_station_years = sum(s["n_years"] for s in STATIONS)
n_grdc = sum(1 for s in STATIONS if s["provider"] == "grdc")
n_camels = sum(1 for s in STATIONS if s["provider"] == "camelses")

html = r'''<title>Ebro Gauge Skill Map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg: #FAF9F6;
    --surface: #FFFFFF;
    --surface-2: #F1F3F1;
    --ink: #14201F;
    --ink-muted: #5B6A67;
    --ink-faint: #8A9794;
    --border: #E1E6E3;
    --pos: #2A78D6;
    --pos-tint: #E5EFFA;
    --neg: #D0453F;
    --neg-tint: #FBEAE8;
    --neutral: #8A9794;
    --river: #B9CFCE;
    --river-strong: #8FB3B1;
    --grdc: #1D5468;
    --camels: #A66A1E;
    --shadow: 0 1px 2px rgba(20,32,31,0.06), 0 4px 16px rgba(20,32,31,0.06);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0F1917;
      --surface: #16211F;
      --surface-2: #1C2926;
      --ink: #EAF1EF;
      --ink-muted: #9FB3B0;
      --ink-faint: #6C7C79;
      --border: #24322F;
      --pos: #3987E5;
      --pos-tint: #17263A;
      --neg: #E06A5C;
      --neg-tint: #2E1B18;
      --neutral: #6C7C79;
      --river: #253634;
      --river-strong: #33473F;
      --grdc: #5FB7CE;
      --camels: #D9A25C;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0F1917; --surface: #16211F; --surface-2: #1C2926; --ink: #EAF1EF; --ink-muted: #9FB3B0;
    --ink-faint: #6C7C79; --border: #24322F; --pos: #3987E5; --pos-tint: #17263A; --neg: #E06A5C;
    --neg-tint: #2E1B18; --neutral: #6C7C79; --river: #253634; --river-strong: #33473F;
    --grdc: #5FB7CE; --camels: #D9A25C; --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }

  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: "IBM Plex Sans", system-ui, -apple-system, sans-serif; padding: 28px 24px 48px; }
  a { color: var(--pos); }
  .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
  .tnum { font-variant-numeric: tabular-nums; }
  .wrap { max-width: 1180px; margin: 0 auto; }

  header { margin-bottom: 22px; }
  .eyebrow { font-family: "IBM Plex Mono", monospace; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-muted); margin: 0 0 6px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  h1 { font-size: 26px; font-weight: 700; margin: 0 0 8px; letter-spacing: -0.01em; text-wrap: balance; }
  .sub { font-size: 15px; color: var(--ink-muted); max-width: 68ch; line-height: 1.55; margin: 0; }
  .sub b { color: var(--ink); font-weight: 600; }

  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin: 20px 0 22px; }
  .stat { background: var(--surface); padding: 16px 18px; }
  .stat .num { font-family: "IBM Plex Mono", monospace; font-size: 26px; font-weight: 600; line-height: 1.1; color: var(--ink); }
  .stat .lbl { font-size: 12.5px; color: var(--ink-muted); margin-top: 4px; }

  .controls { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; margin-bottom: 16px; }
  .control-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .flabel { font-size: 12px; color: var(--ink-muted); margin-right: 2px; }
  .chip { font-family: "IBM Plex Mono", monospace; font-size: 12.5px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink-muted); cursor: pointer; transition: border-color .12s, color .12s, background .12s; }
  .chip:hover { border-color: var(--ink-faint); color: var(--ink); }
  .chip[aria-pressed="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
  select.yr { font-family: "IBM Plex Mono", monospace; font-size: 12.5px; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer; }
  .view-toggle { margin-left: auto; display: flex; gap: 8px; }

  .grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
  @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); }
  .map-panel { padding: 4px; }
  .map-head { display: flex; justify-content: space-between; align-items: baseline; padding: 14px 16px 4px; flex-wrap: wrap; gap: 8px; }
  .map-head h2 { font-size: 14px; margin: 0; font-weight: 600; }
  .legend { display: flex; gap: 14px; font-size: 11.5px; color: var(--ink-muted); align-items: center; flex-wrap: wrap; }
  .legend-scale { display: flex; align-items: center; gap: 6px; }
  .scale-bar { width: 96px; height: 10px; border-radius: 5px; }
  .provider-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }

  svg#map { display: block; width: 100%; height: auto; }
  .river-line { stroke: var(--river); stroke-width: 1.3; fill: none; }
  .gauge-halo { fill: none; stroke-width: 1.5; opacity: 0.5; }
  .gauge-dot { stroke: var(--surface); stroke-width: 1.4; cursor: pointer; }
  .gauge-dot:hover { stroke: var(--ink); }
  .gauge-dot.nodata { fill: none !important; stroke: var(--ink-faint); stroke-dasharray: 2,2; }
  .gauge-label { font-family: "IBM Plex Mono", monospace; font-size: 9.5px; fill: var(--ink-muted); pointer-events: none; }
  .axis-label { font-family: "IBM Plex Mono", monospace; font-size: 9.5px; fill: var(--ink-faint); }
  .grat { stroke: var(--border); stroke-width: 1; }
  .region-label { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: 0.06em; fill: var(--ink-faint); }
  .map-foot { display: flex; justify-content: space-between; padding: 6px 16px 12px; font-size: 11px; color: var(--ink-faint); gap: 10px; flex-wrap: wrap; }

  .detail { padding: 16px 18px 18px; position: sticky; top: 20px; }
  .detail-empty { color: var(--ink-muted); font-size: 13.5px; line-height: 1.5; }
  .detail h2 { font-size: 15px; margin: 0 0 2px; font-weight: 600; }
  .detail .meta { font-size: 12px; color: var(--ink-muted); margin-bottom: 4px; }
  .provider-pill { display: inline-flex; align-items: center; gap: 6px; font-family: "IBM Plex Mono", monospace; font-size: 11px; font-weight: 600; padding: 3px 9px 3px 7px; border-radius: 999px; margin: 6px 0 14px; }
  .provider-pill.grdc { background: color-mix(in srgb, var(--grdc) 14%, var(--surface)); color: var(--grdc); }
  .provider-pill.camelses { background: color-mix(in srgb, var(--camels) 16%, var(--surface)); color: var(--camels); }
  .provider-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

  .metric-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px; }
  .mcard { border: 1px solid var(--border); border-radius: 10px; padding: 9px 11px; background: var(--surface-2); }
  .mcard .mk { font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-muted); }
  .mcard .mv { font-family: "IBM Plex Mono", monospace; font-size: 18px; font-weight: 600; margin-top: 2px; }

  .spark-wrap { margin: 10px 0 12px; }
  .spark-label { font-size: 10.5px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }
  svg.spark { width: 100%; height: 54px; display: block; }

  .caveat { margin-top: 12px; padding: 10px 12px; background: var(--surface-2); border-radius: 8px; font-size: 12px; color: var(--ink-muted); line-height: 1.5; }

  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-faint); padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; position: sticky; top: 0; background: var(--surface); cursor: pointer; }
  thead th.num, tbody td.num { text-align: right; }
  thead th:hover { color: var(--ink); }
  tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; font-family: "IBM Plex Mono", monospace; }
  tbody td.name { font-family: "IBM Plex Sans", sans-serif; }
  tbody tr:hover { background: var(--surface-2); cursor: pointer; }
  .prov-tag { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }
  .prov-tag.grdc { background: color-mix(in srgb, var(--grdc) 14%, var(--surface)); color: var(--grdc); }
  .prov-tag.camelses { background: color-mix(in srgb, var(--camels) 16%, var(--surface)); color: var(--camels); }

  footer { margin-top: 22px; font-size: 12px; color: var(--ink-faint); line-height: 1.65; }
  footer code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
  footer p { margin: 0 0 10px; }
  [hidden] { display: none !important; }
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">LIAISE &middot; CaMa-Flood control skill <span class="mono">&middot;</span> non-comparative</p>
    <h1>How well does the control chain match real gauges across the Ebro?</h1>
    <p class="sub">
      The Fortran ecLand&ndash;CaMa-Flood coupled chain (<code class="mono">LECMF1WAY</code>, restart-chained 1988&ndash;2024)
      scored against <b>__N_TOTAL__ real gauges</b> &mdash; __N_GRDC__ GRDC (public-domain) and __N_CAMELS__ CAMELS-Spain &mdash;
      spanning the whole monitored Ebro network, not just the 7-gauge subset used in the earlier Fortran-vs-GPU comparison.
      This is the control alone: no second model, just how its own KGE, NSE, correlation and bias look gauge by gauge.
    </p>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <div class="control-group">
      <span class="flabel">Metric</span>
      <div id="metric-chips"></div>
    </div>
    <div class="control-group">
      <span class="flabel">Year</span>
      <select class="yr mono" id="year-select"></select>
    </div>
    <div class="view-toggle">
      <button class="chip" id="btn-map-view" aria-pressed="true">Map</button>
      <button class="chip" id="btn-table-view" aria-pressed="false">Table</button>
    </div>
  </div>

  <div id="map-view">
    <div class="grid">
      <div class="panel map-panel">
        <div class="map-head">
          <h2>Ebro basin &amp; tributaries &mdash; LIAISE domain</h2>
          <div class="legend" id="legend"></div>
        </div>
        <svg id="map" viewBox="0 0 720 560" role="img" aria-label="Map of real river gauges on the Ebro network, colored by control-chain skill"></svg>
        <div class="map-foot">
          <span>Dot size = catchment area (log scale)</span>
          <span><span class="provider-dot" style="background:var(--grdc)"></span> GRDC &nbsp; <span class="provider-dot" style="background:var(--camels)"></span> CAMELS-Spain (ring)</span>
        </div>
      </div>

      <div class="panel detail" id="detail">
        <div class="detail-empty">Hover or click a gauge on the map to see its full skill record.</div>
      </div>
    </div>
  </div>

  <div id="table-view" hidden>
    <div class="panel table-wrap">
      <table>
        <thead>
          <tr>
            <th data-k="name">Gauge</th>
            <th class="num" data-k="area_km2">Area (km&sup2;)</th>
            <th class="num" data-k="median_kge">KGE</th>
            <th class="num" data-k="median_nse">NSE</th>
            <th class="num" data-k="median_r">r</th>
            <th class="num" data-k="median_pbias">PBIAS</th>
            <th class="num" data-k="n_years">Years</th>
          </tr>
        </thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
  </div>

  <footer>
    <p><b>Data</b>: __N_STATION_YEARS__ station-years across __N_TOTAL__ gauges (__N_EXCLUDED__ further CAMELS-Spain gauges were
    matched to the LIAISE basin but excluded &mdash; fewer than 30 days overlap with the years scored below). GRDC gauges
    (public-domain, via the GRDC-Caravan extension of Caravan) retain their full 1988&ndash;2014 record, scored earlier in this
    project. CAMELS-Spain gauges (own separate licence &mdash; see <code>extract_liaise_grdc_observations.py</code> before
    redistributing this file) are scored against whichever years of the 37-year run's raw <code>o_totout.nc</code> remain on disk
    after the two-chains benchmark's own output was cleaned up &mdash; <b>scoring windows differ by gauge</b>; each gauge's own
    years are shown in its detail panel and the table.</p>
    <p><b>Caveats</b>: CAMELS-Spain streamflow ships in Caravan's mm/d convention, converted here to m3/s via each station's provider
    catchment area (cross-checked: the CAMELS-Spain and GRDC records for the same physical gauge at Pitarque/Fortanete agree to
    within 2%). <code>RIO GUADALOPE, CASPE</code> is a regulated river with near-zero real baseflow in several years, which sends
    KGE/NSE/PBIAS to extreme values &mdash; a metric artifact of dividing by near-zero variance/mean, not a model failure; shown
    as-is but color-clipped on the map. Method: <code>cama_flood/skill_benchmark_control.py</code>, observations:
    <code>cama_flood/extract_liaise_grdc_observations.py --providers GRDC camelses</code>.</p>
  </footer>
</div>

<script>
const STATIONS = __STATIONS_JSON__;
const RIVER_SEGMENTS = __RIVER_JSON__;

const BOUNDS = { lonW: -2.6, lonE: 2.9, latS: 39.5, latN: 43.6 };
const MEAN_LAT_COS = Math.cos(41.5 * Math.PI / 180);
const VB = { w: 720, h: 560, pad: 34 };

function project(lon, lat) {
  const spanX = (BOUNDS.lonE - BOUNDS.lonW) * MEAN_LAT_COS;
  const spanY = (BOUNDS.latN - BOUNDS.latS);
  const scale = Math.min((VB.w - VB.pad * 2) / spanX, (VB.h - VB.pad * 2) / spanY);
  const x = VB.pad + (lon - BOUNDS.lonW) * MEAN_LAT_COS * scale;
  const y = VB.h - VB.pad - (lat - BOUNDS.latS) * scale;
  return [x, y];
}

function fmt(v, d = 2) { return (v === null || v === undefined || Number.isNaN(v)) ? '&mdash;' : v.toFixed(d); }
function fmtSigned(v, d = 0, suf = '') { if (v === null || v === undefined || Number.isNaN(v)) return '&mdash;'; return (v > 0 ? '+' : '') + v.toFixed(d) + suf; }

const METRICS = {
  kge:   { label: 'KGE',   domain: [-1.2, 1],   diverging: true,  fmt: v => fmt(v, 2) },
  nse:   { label: 'NSE',   domain: [-3, 1],      diverging: true,  fmt: v => fmt(v, 2) },
  r:     { label: 'r',     domain: [0, 0.8],     diverging: false, fmt: v => fmt(v, 2) },
  pbias: { label: 'PBIAS', domain: [-100, 100],  diverging: true,  fmt: v => fmtSigned(v, 0, '%') },
};
let currentMetric = 'kge';
let currentYear = 'all';

function lerp(a, b, t) { return a + (b - a) * t; }
function lerpColor(hexA, hexB, t) {
  const pa = [1,3,5].map(i => parseInt(hexA.slice(i,i+2),16));
  const pb = [1,3,5].map(i => parseInt(hexB.slice(i,i+2),16));
  const c = pa.map((v,i) => Math.round(lerp(v, pb[i], t)));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

const CSS = getComputedStyle(document.documentElement);
function cssVar(name) { return getComputedStyle(document.body).getPropertyValue(name).trim() || CSS.getPropertyValue(name).trim(); }

function colorFor(metricKey, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return cssVar('--ink-faint');
  const m = METRICS[metricKey];
  const [lo, hi] = m.domain;
  const neg = cssVar('--neg'), pos = cssVar('--pos'), neutral = cssVar('--neutral');
  if (m.diverging) {
    if (value >= 0) { const t = Math.max(0, Math.min(1, value / hi)); return lerpColor(neutral, pos, t); }
    else { const t = Math.max(0, Math.min(1, value / lo)); return lerpColor(neutral, neg, t); }
  } else {
    const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
    return lerpColor('#cde2fb', pos, t);
  }
}

function valueFor(station, metricKey, year) {
  if (year === 'all') return station['median_' + metricKey];
  const row = station.years.find(y => y.year === year);
  return row ? row[metricKey] : null;
}

const validKge = STATIONS.map(s => s.median_kge).filter(v => v !== null && !Number.isNaN(v));
const posKge = validKge.filter(v => v > 0).length;
const totalYears = STATIONS.reduce((a,s) => a + s.n_years, 0);

document.getElementById('stats').innerHTML = `
  <div class="stat"><div class="num tnum">__N_TOTAL__</div><div class="lbl">real gauges scored (GRDC + CAMELS-Spain)</div></div>
  <div class="stat"><div class="num tnum">${totalYears}</div><div class="lbl">station-years, 1988&ndash;2014</div></div>
  <div class="stat"><div class="num tnum">${posKge}/${validKge.length}</div><div class="lbl">gauges with positive median KGE</div></div>
  <div class="stat"><div class="num tnum">${(100*posKge/validKge.length).toFixed(0)}%</div><div class="lbl">beat the mean-flow benchmark</div></div>
`;

const chipsEl = document.getElementById('metric-chips');
function renderMetricChips() {
  chipsEl.innerHTML = Object.entries(METRICS).map(([k,m]) =>
    `<button class="chip" data-m="${k}" aria-pressed="${currentMetric===k}" style="margin-right:6px">${m.label}</button>`
  ).join('');
  chipsEl.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    currentMetric = b.dataset.m; renderMetricChips(); renderLegend(); renderMap(); renderTable();
  }));
}

const allYears = Array.from(new Set(STATIONS.flatMap(s => s.years.map(y => y.year)))).sort((a,b)=>a-b);
const yearSel = document.getElementById('year-select');
function renderYearSelect() {
  yearSel.innerHTML = `<option value="all">All years (median)</option>` +
    allYears.map(y => `<option value="${y}">${y}</option>`).join('');
  yearSel.value = currentYear;
  yearSel.addEventListener('change', () => { currentYear = yearSel.value === 'all' ? 'all' : Number(yearSel.value); renderMap(); renderTable(); });
}

function renderLegend() {
  const m = METRICS[currentMetric];
  const [lo, hi] = m.domain;
  const neg = cssVar('--neg'), pos = cssVar('--pos'), neutral = cssVar('--neutral');
  let gradient;
  if (m.diverging) gradient = `linear-gradient(to right, ${neg}, ${neutral}, ${pos})`;
  else gradient = `linear-gradient(to right, #cde2fb, ${pos})`;
  document.getElementById('legend').innerHTML = `
    <div class="legend-scale"><span>${lo}</span><div class="scale-bar" style="background:${gradient}"></div><span>${hi}</span></div>
    <span>${m.diverging ? (currentMetric==='pbias' ? 'under-predict &larr; 0 &rarr; over-predict' : 'worse &larr; 0 &rarr; better') : 'weaker &rarr; stronger'}</span>
  `;
}

const svg = document.getElementById('map');
function areaRadius(area) { return Math.max(4, Math.min(16, 3 + 3.2 * Math.log10(Math.max(1, area)))); }

function renderMap() {
  const parts = [];
  for (let lo = -2; lo <= 2.5; lo += 1) {
    const [x1,y1] = project(lo, BOUNDS.latS), [x2,y2] = project(lo, BOUNDS.latN);
    parts.push(`<line class="grat" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
    parts.push(`<text class="axis-label" x="${x1}" y="${VB.h-16}" text-anchor="middle">${lo}&deg;</text>`);
  }
  for (let la = 40; la <= 43; la += 1) {
    const [x1,y1] = project(BOUNDS.lonW, la), [x2,y2] = project(BOUNDS.lonE, la);
    parts.push(`<line class="grat" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
    parts.push(`<text class="axis-label" x="16" y="${y1+3}">${la}&deg;N</text>`);
  }
  parts.push(`<text class="region-label" x="${VB.w-14}" y="24" text-anchor="end">SPAIN &middot; PRE-PYRENEES / EBRO BASIN</text>`);
  RIVER_SEGMENTS.forEach(([lon1, lat1, lon2, lat2]) => {
    const [x1,y1] = project(lon1, lat1), [x2,y2] = project(lon2, lat2);
    parts.push(`<line class="river-line" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
  });

  const sorted = [...STATIONS].sort((a,b) => b.area_km2 - a.area_km2);
  sorted.forEach((s) => {
    const idx = STATIONS.indexOf(s);
    const [x, y] = project(s.lon, s.lat);
    const val = valueFor(s, currentMetric, currentYear);
    const r = areaRadius(s.area_km2);
    const isCamels = s.provider === 'camelses';
    if (val === null || val === undefined || Number.isNaN(val)) {
      parts.push(`<circle class="gauge-dot nodata" data-i="${idx}" cx="${x}" cy="${y}" r="${r}"></circle>`);
    } else {
      const color = colorFor(currentMetric, val);
      const ringColor = isCamels ? 'var(--camels)' : 'var(--grdc)';
      parts.push(`<circle class="gauge-halo" cx="${x}" cy="${y}" r="${r+3.5}" stroke="${ringColor}"></circle>`);
      parts.push(`<circle class="gauge-dot" data-i="${idx}" cx="${x}" cy="${y}" r="${r}" fill="${color}"></circle>`);
    }
  });

  svg.innerHTML = parts.join('');
  svg.querySelectorAll('.gauge-dot').forEach(el => {
    el.addEventListener('mouseenter', () => showDetail(STATIONS[+el.dataset.i]));
    el.addEventListener('click', () => showDetail(STATIONS[+el.dataset.i]));
  });
}

function sparkline(station, metricKey) {
  const rows = station.years.filter(y => y[metricKey] !== null && y[metricKey] !== undefined && !Number.isNaN(y[metricKey]));
  if (rows.length < 2) return '<div style="font-size:11.5px;color:var(--ink-faint)">not enough years for a trend line</div>';
  const W = 260, H = 46, pad = 4;
  const vals = rows.map(r => r[metricKey]);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
  const range = (hi - lo) || 1;
  const sx = i => pad + i * (W - 2*pad) / (rows.length - 1);
  const sy = v => H - pad - (v - lo) / range * (H - 2*pad);
  const zeroY = sy(0);
  const pts = rows.map((r,i) => `${sx(i)},${sy(r[metricKey])}`).join(' ');
  const last = rows[rows.length-1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}">
    <line x1="0" y1="${zeroY}" x2="${W}" y2="${zeroY}" stroke="var(--border)" stroke-dasharray="2,2"/>
    <polyline points="${pts}" fill="none" stroke="var(--pos)" stroke-width="1.6"/>
    <circle cx="${sx(rows.length-1)}" cy="${sy(last[metricKey])}" r="2.6" fill="var(--pos)"/>
    <text x="2" y="${H-2}" font-size="9" fill="var(--ink-faint)" font-family="IBM Plex Mono, monospace">${rows[0].year}</text>
    <text x="${W-2}" y="${H-2}" text-anchor="end" font-size="9" fill="var(--ink-faint)" font-family="IBM Plex Mono, monospace">${rows[rows.length-1].year}</text>
  </svg>`;
}

function showDetail(s) {
  document.getElementById('detail').innerHTML = `
    <h2>${s.name}</h2>
    <div class="meta">${s.area_km2.toLocaleString()} km&sup2; catchment &middot; ${s.lat.toFixed(3)}&deg;N, ${s.lon.toFixed(3)}&deg;E</div>
    <span class="provider-pill ${s.provider}"><span class="dot"></span>${s.provider === 'grdc' ? 'GRDC (public domain)' : 'CAMELS-Spain'}</span>
    <div class="meta" style="margin-top:-8px">Scored ${s.n_years} year${s.n_years===1?'':'s'}, ${s.year_min}&ndash;${s.year_max}</div>
    <div class="metric-cards" style="margin-top:12px">
      <div class="mcard"><div class="mk">KGE</div><div class="mv" style="color:${colorFor('kge', s.median_kge)}">${fmt(s.median_kge)}</div></div>
      <div class="mcard"><div class="mk">NSE</div><div class="mv" style="color:${colorFor('nse', s.median_nse)}">${fmt(s.median_nse)}</div></div>
      <div class="mcard"><div class="mk">Correlation r</div><div class="mv" style="color:${colorFor('r', s.median_r)}">${fmt(s.median_r)}</div></div>
      <div class="mcard"><div class="mk">PBIAS</div><div class="mv" style="color:${colorFor('pbias', s.median_pbias)}">${fmtSigned(s.median_pbias,0,'%')}</div></div>
    </div>
    <div class="spark-wrap">
      <div class="spark-label">${METRICS[currentMetric].label} by year</div>
      ${sparkline(s, currentMetric)}
    </div>
    ${s.name.includes('GUADALOPE') ? '<div class="caveat">Regulated river (dam/irrigation controlled) &mdash; real discharge is near-zero for long stretches, which sends KGE/NSE/PBIAS to extreme values. Read this gauge&rsquo;s numbers with that in mind.</div>' : ''}
  `;
}

let sortKey = 'area_km2', sortDir = -1;
function renderTable() {
  function valueForSort(s) {
    if (sortKey === 'name') return s.name;
    return s[sortKey];
  }
  const rows = [...STATIONS].sort((a,b) => {
    const av = valueForSort(a), bv = valueForSort(b);
    if (av === null || av === undefined) return 1; if (bv === null || bv === undefined) return -1;
    if (typeof av === 'string') return av.localeCompare(bv) * sortDir;
    return (av - bv) * sortDir;
  });
  document.getElementById('table-body').innerHTML = rows.map(s => `
    <tr data-i="${STATIONS.indexOf(s)}">
      <td class="name">${s.name}<span class="prov-tag ${s.provider}">${s.provider === 'grdc' ? 'GRDC' : 'CAMELS'}</span></td>
      <td class="num tnum">${s.area_km2.toLocaleString()}</td>
      <td class="num tnum" style="color:${colorFor('kge', s.median_kge)}">${fmt(s.median_kge)}</td>
      <td class="num tnum" style="color:${colorFor('nse', s.median_nse)}">${fmt(s.median_nse)}</td>
      <td class="num tnum" style="color:${colorFor('r', s.median_r)}">${fmt(s.median_r)}</td>
      <td class="num tnum" style="color:${colorFor('pbias', s.median_pbias)}">${fmtSigned(s.median_pbias,0,'%')}</td>
      <td class="num tnum">${s.n_years} <span style="color:var(--ink-faint)">(${s.year_min}&ndash;${s.year_max})</span></td>
    </tr>`).join('');
  document.querySelectorAll('#table-body tr').forEach(tr => tr.addEventListener('click', () => {
    document.getElementById('btn-map-view').click();
    showDetail(STATIONS[+tr.dataset.i]);
  }));
}
document.querySelectorAll('thead th[data-k]').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = k === 'name' ? 1 : -1; }
  renderTable();
}));

document.getElementById('btn-map-view').addEventListener('click', () => {
  document.getElementById('map-view').hidden = false;
  document.getElementById('table-view').hidden = true;
  document.getElementById('btn-map-view').setAttribute('aria-pressed', 'true');
  document.getElementById('btn-table-view').setAttribute('aria-pressed', 'false');
});
document.getElementById('btn-table-view').addEventListener('click', () => {
  document.getElementById('map-view').hidden = true;
  document.getElementById('table-view').hidden = false;
  document.getElementById('btn-map-view').setAttribute('aria-pressed', 'false');
  document.getElementById('btn-table-view').setAttribute('aria-pressed', 'true');
});

renderMetricChips();
renderYearSelect();
renderLegend();
renderMap();
renderTable();
showDetail(STATIONS.find(s => s.name.includes('CINCA, FRAGA')));
</script>
'''

html = html.replace("__N_TOTAL__", str(n_total))
html = html.replace("__N_GRDC__", str(n_grdc))
html = html.replace("__N_CAMELS__", str(n_camels))
html = html.replace("__N_STATION_YEARS__", str(n_station_years))
html = html.replace("__N_EXCLUDED__", str(args.n_excluded))
html = html.replace("__STATIONS_JSON__", json.dumps(STATIONS))
html = html.replace("__RIVER_JSON__", json.dumps(RIVER_SEGMENTS))

with open(args.out, "w") as fh:
    fh.write(html)
print(f"wrote {args.out}: {n_total} gauges ({n_grdc} GRDC, {n_camels} CAMELS-Spain), {n_station_years} station-years")
