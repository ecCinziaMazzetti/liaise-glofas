#!/usr/bin/env python3
"""Build the multi-experiment "Ebro Gauge Skill Map" page.

Generalises build_control_dashboard.py from one experiment to N: the page carries an
experiment selector (CaMa-Flood routing resolution: 15 / 6 / 3 arcmin) alongside the
metric selector (KGE, NSE, correlation, PBIAS, bias), so the same gauges can be
compared across resolutions by clicking rather than by opening separate pages.

Experiments are passed as repeatable LABEL=path.json pairs and rendered in the order
given, so a resolution that is still running can simply be added later without
touching this script:

    python3 build_resolution_dashboard.py \\
        --obs data/liaise_river_observations_grdc_camels.nc \\
        --ncdata data/ncdata.nc \\
        --experiment "15 arcmin=/perm/pad/liaise_discharge_compare/skill_resolution_15min.json" \\
        --experiment "6 arcmin=/perm/pad/liaise_discharge_compare/skill_resolution_06min.json" \\
        --pending "3 arcmin" \\
        --out /path/to/index.html

Input JSON schema: one row per (station, year), as written by
skill_benchmark_resolution.py -- station, year, kge, nse, r, pbias_pct, obs_mean,
sim_mean, n_days, and optionally bias (falls back to sim_mean - obs_mean).

Station geography (lat/lon, provider, catchment area) comes from --obs/--ncdata and is
shared across experiments; only the scores differ per experiment.
"""

import argparse
import json
import statistics
from collections import defaultdict

import netCDF4 as nc

from liaise_river_geometry import RIVER_SEGMENTS

# Colour-scale domains per metric. KGE/NSE/PBIAS/bias diverge about a meaningful zero
# (mean-flow benchmark for the skill scores, no-bias for the bias ones); correlation is
# a magnitude, so it gets a sequential ramp. Values outside the domain are clipped for
# colour only -- the real number is always shown in the panel and table. The bias domain
# is data-derived (see build_metric_domains) since m3/s spans orders of magnitude
# between the Ebro mainstem and a 100 km2 headwater.
METRICS = [
    {"key": "kge", "label": "KGE", "domain": [-1.2, 1.0], "diverging": True, "unit": ""},
    {"key": "nse", "label": "NSE", "domain": [-3.0, 1.0], "diverging": True, "unit": ""},
    {"key": "r", "label": "Correlation", "domain": [0.0, 1.0], "diverging": False, "unit": ""},
    {"key": "pbias", "label": "PBIAS", "domain": [-100.0, 100.0], "diverging": True, "unit": "%"},
    {"key": "bias", "label": "Bias", "domain": None, "diverging": True, "unit": " m³/s"},
]


def nanmedian(vals):
    vals = [v for v in vals if v is not None and v == v]
    return round(statistics.median(vals), 4) if vals else None


def load_station_geography(obs_path, ncdata_path):
    """lat/lon/provider/catchment area per station, shared by all experiments."""
    ds = nc.Dataset(obs_path)
    names = [str(n) for n in ds.variables["station_name"][:]]
    providers = [str(p) for p in ds.variables["provider"][:]]
    slat, slon = ds.variables["station_lat"][:], ds.variables["station_lon"][:]
    sid = [int(s) for s in ds.variables["station_id"][:]]
    iy, ix = ds.variables["cama15_iy"][:], ds.variables["cama15_ix"][:]
    name_count = {n: names.count(n) for n in names}

    uparea = nc.Dataset(ncdata_path).variables["uparea"][:]

    geo = {}
    for i, n in enumerate(names):
        disp = f"{n} [{sid[i]}]" if name_count[n] > 1 else n
        geo[disp] = {
            "name": disp, "lat": float(slat[i]), "lon": float(slon[i]),
            "provider": providers[i],
            "area_km2": round(float(uparea[iy[i], ix[i]]) / 1e6, 1),
        }
    return geo


def summarise_experiment(results_path):
    """{station: {median_<metric>, n_years, year_min, year_max, years: [...]}}"""
    with open(results_path) as fh:
        rows = json.load(fh)
    by_station = defaultdict(list)
    for r in rows:
        by_station[r["station"]].append(r)

    out = {}
    for name, yrows in by_station.items():
        yrows = sorted(yrows, key=lambda r: r["year"])
        years = []
        for r in yrows:
            bias = r.get("bias")
            if bias is None and r.get("sim_mean") is not None and r.get("obs_mean") is not None:
                bias = r["sim_mean"] - r["obs_mean"]
            years.append({
                "year": r["year"], "kge": r["kge"], "nse": r["nse"], "r": r["r"],
                "pbias": r["pbias_pct"], "bias": bias,
                "obs_mean": round(r["obs_mean"], 3) if r.get("obs_mean") is not None else None,
            })
        covered = [y["year"] for y in years]
        out[name] = {
            "median_kge": nanmedian([y["kge"] for y in years]),
            "median_nse": nanmedian([y["nse"] for y in years]),
            "median_r": nanmedian([y["r"] for y in years]),
            "median_pbias": nanmedian([y["pbias"] for y in years]),
            "median_bias": nanmedian([y["bias"] for y in years]),
            "n_years": len(years), "year_min": min(covered), "year_max": max(covered),
            "years": years,
        }
    return out


def build_metric_domains(stations):
    """Fill in the data-derived domains (currently just bias) symmetrically about zero.

    Uses the 90th percentile of |median bias| across all gauges and experiments, so one
    huge mainstem gauge doesn't flatten the colour scale for every headwater.
    """
    metrics = [dict(m) for m in METRICS]
    for m in metrics:
        if m["domain"] is not None:
            continue
        vals = []
        for s in stations:
            for exp_data in s["exp"].values():
                v = exp_data.get(f"median_{m['key']}")
                if v is not None and v == v:
                    vals.append(abs(v))
        if vals:
            vals.sort()
            p90 = vals[min(len(vals) - 1, int(0.9 * len(vals)))]
            lim = round(max(p90, 1e-3), 3)
        else:
            lim = 1.0
        m["domain"] = [-lim, lim]
    return metrics


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--obs", required=True)
ap.add_argument("--ncdata", required=True)
ap.add_argument("--experiment", action="append", required=True, metavar="LABEL=PATH",
                 help="repeatable; rendered in the order given")
ap.add_argument("--pending", action="append", default=[], metavar="LABEL",
                 help="repeatable; shown greyed out as 'still running'")
ap.add_argument("--caveat", action="append", default=[], metavar="STATION=REASON",
                 help="repeatable; station is still drawn and tabulated, but is excluded from the "
                      "headline medians and carries a visible warning (for gauges whose scores are a "
                      "known data artifact rather than a model result)")
ap.add_argument("--experiment-noun", default="Resolution",
                 help="label for the experiment selector (e.g. 'Resolution', 'Chain')")
ap.add_argument("--eyebrow", default="LIAISE \u00b7 CaMa-Flood routing resolution \u00b7 naturalised control")
ap.add_argument("--title", default="Does finer river-routing resolution improve discharge skill?")
ap.add_argument("--subtitle", default=(
    "The same 37-year (1988\u20132024) naturalised ecLand\u2013CaMa-Flood control run \u2014 identical land "
    "surface, identical forcing, identical restart chain \u2014 routed at different CaMa-Flood "
    "resolutions and scored against the same real river gauges. Pick a <b>resolution</b> and a "
    "<b>metric</b> to compare them gauge by gauge."))
ap.add_argument("--intro-html", default=None,
                 help="replaces the first footer paragraph (what is being compared)")
ap.add_argument("--out", required=True)
args = ap.parse_args()

caveats = {}
for spec in args.caveat:
    if "=" not in spec:
        raise SystemExit(f"--caveat must be STATION=REASON, got: {spec}")
    st, reason = spec.split("=", 1)
    caveats[st] = reason

geo = load_station_geography(args.obs, args.ncdata)

experiments = []
for spec in args.experiment:
    if "=" not in spec:
        raise SystemExit(f"--experiment must be LABEL=PATH, got: {spec}")
    label, path = spec.split("=", 1)
    experiments.append({"label": label, "summary": summarise_experiment(path), "path": path})

# One station list, each carrying its per-experiment scores.
all_names = set()
for e in experiments:
    all_names |= set(e["summary"])
stations = []
for name in all_names:
    if name not in geo:
        continue
    s = dict(geo[name])
    s["exp"] = {e["label"]: e["summary"][name] for e in experiments if name in e["summary"]}
    s["caveat"] = next((r for st, r in caveats.items() if st in name), None)
    if s["exp"]:
        stations.append(s)
stations.sort(key=lambda s: -s["area_km2"])

caveat_names = {s["name"] for s in stations if s["caveat"]}
if caveats and not caveat_names:
    raise SystemExit(f"--caveat matched no station; given {list(caveats)}")

metrics = build_metric_domains(stations)
exp_labels = [e["label"] for e in experiments]

# Headline numbers for the stat band, per experiment.
headline = {}
for e in experiments:
    scored = {n: v for n, v in e["summary"].items() if n not in caveat_names}
    kges = [v["median_kge"] for v in scored.values()
            if v["median_kge"] is not None and v["median_kge"] == v["median_kge"]]
    station_years = sum(v["n_years"] for v in scored.values())
    yrs = [v["year_min"] for v in scored.values()] + [v["year_max"] for v in scored.values()]
    headline[e["label"]] = {
        "n_stations": len(scored), "station_years": station_years,
        "median_kge": round(statistics.median(kges), 3) if kges else None,
        "positive_kge": sum(1 for k in kges if k > 0), "n_scored": len(kges),
        "year_min": min(yrs) if yrs else None, "year_max": max(yrs) if yrs else None,
        "n_caveat": len(e["summary"]) - len(scored),
    }

html = r'''<title>Ebro Gauge Skill Map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg: #FAF9F6; --surface: #FFFFFF; --surface-2: #F1F3F1;
    --ink: #14201F; --ink-muted: #5B6A67; --ink-faint: #8A9794; --border: #E1E6E3;
    --pos: #2A78D6; --neg: #D0453F; --neutral: #8A9794;
    --river: #B9CFCE; --grdc: #1D5468; --camels: #A66A1E;
    --shadow: 0 1px 2px rgba(20,32,31,0.06), 0 4px 16px rgba(20,32,31,0.06);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0F1917; --surface: #16211F; --surface-2: #1C2926;
      --ink: #EAF1EF; --ink-muted: #9FB3B0; --ink-faint: #6C7C79; --border: #24322F;
      --pos: #3987E5; --neg: #E06A5C; --neutral: #6C7C79;
      --river: #253634; --grdc: #5FB7CE; --camels: #D9A25C;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0F1917; --surface: #16211F; --surface-2: #1C2926; --ink: #EAF1EF;
    --ink-muted: #9FB3B0; --ink-faint: #6C7C79; --border: #24322F; --pos: #3987E5;
    --neg: #E06A5C; --neutral: #6C7C79; --river: #253634; --grdc: #5FB7CE; --camels: #D9A25C;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: "IBM Plex Sans", system-ui, sans-serif; padding: 28px 24px 48px; }
  .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
  .tnum { font-variant-numeric: tabular-nums; }
  .wrap { max-width: 1180px; margin: 0 auto; }
  header { margin-bottom: 22px; }
  .eyebrow { font-family: "IBM Plex Mono", monospace; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-muted); margin: 0 0 6px; }
  h1 { font-size: 26px; font-weight: 700; margin: 0 0 8px; letter-spacing: -.01em; text-wrap: balance; }
  .sub { font-size: 15px; color: var(--ink-muted); max-width: 70ch; line-height: 1.55; margin: 0; }
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
  .chip[disabled] { opacity: .45; cursor: not-allowed; border-style: dashed; }
  .chip[disabled]:hover { border-color: var(--border); color: var(--ink-muted); }
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
  .gauge-halo { fill: none; stroke-width: 1.5; opacity: .5; }
  .gauge-dot { stroke: var(--surface); stroke-width: 1.4; cursor: pointer; }
  .gauge-dot:hover { stroke: var(--ink); }
  .gauge-dot.nodata { fill: none !important; stroke: var(--ink-faint); stroke-dasharray: 2,2; }
  .axis-label { font-family: "IBM Plex Mono", monospace; font-size: 9.5px; fill: var(--ink-faint); }
  .grat { stroke: var(--border); stroke-width: 1; }
  .region-label { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .06em; fill: var(--ink-faint); }
  .map-foot { display: flex; justify-content: space-between; padding: 6px 16px 12px; font-size: 11px; color: var(--ink-faint); gap: 10px; flex-wrap: wrap; }

  .detail { padding: 16px 18px 18px; position: sticky; top: 20px; }
  .detail-empty { color: var(--ink-muted); font-size: 13.5px; line-height: 1.5; }
  .detail h2 { font-size: 15px; margin: 0 0 2px; font-weight: 600; }
  .detail .meta { font-size: 12px; color: var(--ink-muted); margin-bottom: 4px; }
  .provider-pill { display: inline-flex; align-items: center; gap: 6px; font-family: "IBM Plex Mono", monospace; font-size: 11px; font-weight: 600; padding: 3px 9px 3px 7px; border-radius: 999px; margin: 6px 0 10px; }
  .provider-pill.grdc { background: color-mix(in srgb, var(--grdc) 14%, var(--surface)); color: var(--grdc); }
  .provider-pill.camelses { background: color-mix(in srgb, var(--camels) 16%, var(--surface)); color: var(--camels); }
  .provider-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

  table.cmp { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 8px 0 12px; }
  table.cmp th { text-align: right; font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-faint); font-weight: 500; padding: 4px 6px; border-bottom: 1px solid var(--border); }
  table.cmp th:first-child { text-align: left; }
  table.cmp td { padding: 5px 6px; border-bottom: 1px solid var(--surface-2); text-align: right; font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }
  table.cmp td:first-child { text-align: left; font-family: "IBM Plex Sans", sans-serif; color: var(--ink-muted); }
  table.cmp tr.active td { background: var(--surface-2); }

  .spark-wrap { margin: 10px 0 12px; }
  .spark-label { font-size: 10.5px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }
  svg.spark { width: 100%; height: 54px; display: block; }
  .spark-legend { display: flex; gap: 12px; font-size: 10.5px; color: var(--ink-muted); margin-top: 4px; flex-wrap: wrap; }
  .spark-legend i { display: inline-block; width: 10px; height: 2px; vertical-align: middle; margin-right: 4px; }

  .table-wrap { overflow-x: auto; }
  table.main { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.main thead th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-faint); padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; position: sticky; top: 0; background: var(--surface); cursor: pointer; }
  table.main thead th.num, table.main tbody td.num { text-align: right; }
  table.main thead th:hover { color: var(--ink); }
  table.main tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; font-family: "IBM Plex Mono", monospace; }
  table.main tbody td.name { font-family: "IBM Plex Sans", sans-serif; }
  table.main tbody tr:hover { background: var(--surface-2); cursor: pointer; }
  .prov-tag { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }
  .prov-tag.grdc { background: color-mix(in srgb, var(--grdc) 14%, var(--surface)); color: var(--grdc); }
  .prov-tag.camelses { background: color-mix(in srgb, var(--camels) 16%, var(--surface)); color: var(--camels); }
  .prov-tag.caveat { background: color-mix(in srgb, var(--neg) 15%, var(--surface)); color: var(--neg); }
  .caveat-box { margin: 0 0 10px; padding: 8px 10px; background: color-mix(in srgb, var(--neg) 8%, var(--surface)); border-left: 3px solid var(--neg); border-radius: 6px; font-size: 11.5px; color: var(--ink-muted); line-height: 1.45; }
  footer { margin-top: 22px; font-size: 12px; color: var(--ink-faint); line-height: 1.65; }
  footer code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
  footer p { margin: 0 0 10px; }
  [hidden] { display: none !important; }
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">__EYEBROW__</p>
    <h1>__TITLE__</h1>
    <p class="sub">__SUBTITLE__</p>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <div class="control-group"><span class="flabel">__EXPNOUN__</span><div id="exp-chips"></div></div>
    <div class="control-group"><span class="flabel">Metric</span><div id="metric-chips"></div></div>
    <div class="control-group"><span class="flabel">Year</span><select class="yr mono" id="year-select"></select></div>
    <div class="view-toggle">
      <button class="chip" id="btn-map-view" aria-pressed="true">Map</button>
      <button class="chip" id="btn-table-view" aria-pressed="false">Table</button>
    </div>
  </div>

  <div id="map-view">
    <div class="grid">
      <div class="panel map-panel">
        <div class="map-head">
          <h2>Ebro basin &amp; tributaries — LIAISE domain</h2>
          <div class="legend" id="legend"></div>
        </div>
        <svg id="map" viewBox="0 0 720 560" role="img" aria-label="Map of river gauges coloured by model skill"></svg>
        <div class="map-foot">
          <span>Dot size = catchment area (log scale)</span>
          <span><span class="provider-dot" style="background:var(--grdc)"></span> GRDC &nbsp; <span class="provider-dot" style="background:var(--camels)"></span> CAMELS-Spain (ring)</span>
        </div>
      </div>
      <div class="panel detail" id="detail">
        <div class="detail-empty">Hover or click a gauge to see every resolution's scores side by side.</div>
      </div>
    </div>
  </div>

  <div id="table-view" hidden>
    <div class="panel table-wrap"><table class="main">
      <thead><tr id="table-head"></tr></thead>
      <tbody id="table-body"></tbody>
    </table></div>
  </div>

  <footer id="footer"></footer>
</div>

<script>
const STATIONS = __STATIONS_JSON__;
const RIVER_SEGMENTS = __RIVER_JSON__;
const METRICS = __METRICS_JSON__;
const EXPERIMENTS = __EXPERIMENTS_JSON__;
const PENDING = __PENDING_JSON__;
const HEADLINE = __HEADLINE_JSON__;
const CAVEAT_NAMES = __CAVEATS_JSON__;

// Per-metric "how many gauges are good" bar. Each metric needs its own: NSE > 0 is the
// classic "better than predicting the mean observed flow" test, but the equivalent bar
// for KGE is NOT 0 -- it is 1 - sqrt(2) ~= -0.41 (Knoben et al. 2019, HESS) -- so
// labelling KGE > 0 as "beats the mean-flow benchmark" would be wrong. KGE > 0 is
// reported here as its own, stricter and commonly used, bar.
// `test` gets (value, station, experiment, year) so a metric can be judged on a
// companion quantity where its own units have no sensible fixed bar -- see `bias`.
const METRIC_STATS = {
  kge:   { test: v => v > 0,             label: 'gauges with KGE &gt; 0' },
  nse:   { test: v => v > 0,             label: 'gauges with NSE &gt; 0' },
  r:     { test: v => v > 0.5,           label: 'gauges with r &gt; 0.5' },
  pbias: { test: v => Math.abs(v) <= 25, label: 'gauges within &plusmn;25% of observed volume' },
  // Bias is absolute m3/s and spans orders of magnitude across these gauges, so it has
  // no meaningful fixed threshold of its own. Judged on the same quantity expressed as a
  // fraction of observed flow -- which is exactly PBIAS -- at a looser bar than the PBIAS
  // tile, giving a strict (25%) and a ballpark (50%) reference rather than new information.
  bias:  { test: (v, s, exp, year) => {
             const pb = valueFor(s, exp, 'pbias', year);
             return pb !== null && pb !== undefined && !Number.isNaN(pb) && Math.abs(pb) <= 50;
           },
           label: 'gauges within &plusmn;50% of observed volume' },
};

let currentExp = EXPERIMENTS[0];
let currentMetric = METRICS[0].key;
let currentYear = 'all';

const BOUNDS = { lonW: -2.6, lonE: 2.9, latS: 39.5, latN: 43.6 };
const MEAN_LAT_COS = Math.cos(41.5 * Math.PI / 180);
const VB = { w: 720, h: 560, pad: 34 };
function project(lon, lat) {
  const spanX = (BOUNDS.lonE - BOUNDS.lonW) * MEAN_LAT_COS, spanY = BOUNDS.latN - BOUNDS.latS;
  const scale = Math.min((VB.w - VB.pad*2)/spanX, (VB.h - VB.pad*2)/spanY);
  return [VB.pad + (lon - BOUNDS.lonW)*MEAN_LAT_COS*scale, VB.h - VB.pad - (lat - BOUNDS.latS)*scale];
}
function metricDef(key) { return METRICS.find(m => m.key === key); }
function fmtMetric(v, key) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const m = metricDef(key);
  if (key === 'pbias') return (v > 0 ? '+' : '') + v.toFixed(0) + '%';
  if (key === 'bias') return (v > 0 ? '+' : '') + (Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)) + ' m³/s';
  return v.toFixed(2);
}
function lerp(a,b,t){ return a + (b-a)*t; }
function lerpColor(hexA, hexB, t) {
  const pa = [1,3,5].map(i => parseInt(hexA.slice(i,i+2),16));
  const pb = [1,3,5].map(i => parseInt(hexB.slice(i,i+2),16));
  const c = pa.map((v,i) => Math.round(lerp(v, pb[i], t)));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
const CSS = getComputedStyle(document.documentElement);
function cssVar(n){ return getComputedStyle(document.body).getPropertyValue(n).trim() || CSS.getPropertyValue(n).trim(); }
function colorFor(key, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return cssVar('--ink-faint');
  const m = metricDef(key), [lo, hi] = m.domain;
  const neg = cssVar('--neg'), pos = cssVar('--pos'), neutral = cssVar('--neutral');
  if (m.diverging) {
    if (value >= 0) return lerpColor(neutral, pos, Math.max(0, Math.min(1, value/hi)));
    return lerpColor(neutral, neg, Math.max(0, Math.min(1, value/lo)));
  }
  return lerpColor('#cde2fb', pos, Math.max(0, Math.min(1, (value-lo)/(hi-lo))));
}
function expData(s, exp) { return s.exp[exp]; }
function valueFor(s, exp, key, year) {
  const d = expData(s, exp);
  if (!d) return null;
  if (year === 'all') return d['median_' + key];
  const row = d.years.find(y => y.year === year);
  return row ? row[key] : null;
}

function renderStats() {
  const h = HEADLINE[currentExp];
  if (!h) { document.getElementById('stats').innerHTML = ''; return; }
  // Computed here rather than baked in at build time, so every tile follows the metric
  // and year selectors instead of being stuck on all-year KGE.
  const m = metricDef(currentMetric), spec = METRIC_STATS[currentMetric];
  const entries = [];
  STATIONS.forEach(s => {
    if (s.caveat || !s.exp[currentExp]) return;
    const v = valueFor(s, currentExp, currentMetric, currentYear);
    if (v !== null && v !== undefined && !Number.isNaN(v)) entries.push([v, s]);
  });
  const vals = entries.map(e => e[0]);
  const sorted = [...vals].sort((a, b) => a - b);
  const med = sorted.length
    ? (sorted.length % 2 ? sorted[(sorted.length - 1) / 2]
                         : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2)
    : null;
  const passing = entries.filter(([v, s]) => spec.test(v, s, currentExp, currentYear)).length;
  const yearLbl = currentYear === 'all' ? `${h.year_min}–${h.year_max}` : currentYear;
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="num tnum">${currentExp}</div><div class="lbl">__EXPNOUN_LOWER__</div></div>
    <div class="stat"><div class="num tnum">${vals.length}</div><div class="lbl">gauges scored, ${yearLbl}${h.n_caveat ? ` · ${h.n_caveat} flagged, excluded` : ''}</div></div>
    <div class="stat"><div class="num tnum">${currentYear === 'all' ? h.station_years : vals.length}</div><div class="lbl">${currentYear === 'all' ? 'station-years' : 'gauges with data this year'}</div></div>
    <div class="stat"><div class="num tnum">${med === null ? '—' : fmtMetric(med, currentMetric)}</div><div class="lbl">median ${m.label} across gauges</div></div>
    <div class="stat"><div class="num tnum">${vals.length ? passing + '/' + vals.length : '—'}</div><div class="lbl">${spec.label}</div></div>`;
}
function renderExpChips() {
  const el = document.getElementById('exp-chips');
  el.innerHTML = EXPERIMENTS.map(e =>
      `<button class="chip" data-e="${e}" aria-pressed="${currentExp===e}" style="margin-right:6px">${e}</button>`
    ).join('') + PENDING.map(p =>
      `<button class="chip" disabled title="still running">${p} · running</button>`
    ).join('');
  el.querySelectorAll('button[data-e]').forEach(b => b.addEventListener('click', () => {
    currentExp = b.dataset.e; renderAll();
  }));
}
function renderMetricChips() {
  const el = document.getElementById('metric-chips');
  el.innerHTML = METRICS.map(m =>
    `<button class="chip" data-m="${m.key}" aria-pressed="${currentMetric===m.key}" style="margin-right:6px">${m.label}</button>`
  ).join('');
  el.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    currentMetric = b.dataset.m; renderAll();
  }));
}
function renderYearSelect() {
  const years = Array.from(new Set(STATIONS.flatMap(s =>
    Object.values(s.exp).flatMap(d => d.years.map(y => y.year))))).sort((a,b)=>a-b);
  const sel = document.getElementById('year-select');
  sel.innerHTML = `<option value="all">All years (median)</option>` + years.map(y => `<option value="${y}">${y}</option>`).join('');
  sel.value = currentYear;
  sel.onchange = () => { currentYear = sel.value === 'all' ? 'all' : Number(sel.value); renderAll(); };
}
function renderLegend() {
  const m = metricDef(currentMetric), [lo, hi] = m.domain;
  const neg = cssVar('--neg'), pos = cssVar('--pos'), neutral = cssVar('--neutral');
  const gradient = m.diverging
    ? `linear-gradient(to right, ${neg}, ${neutral}, ${pos})`
    : `linear-gradient(to right, #cde2fb, ${pos})`;
  const fmtEnd = v => currentMetric === 'bias' ? v.toFixed(1) : (currentMetric === 'pbias' ? v.toFixed(0)+'%' : v.toFixed(1));
  const caption = currentMetric === 'pbias' || currentMetric === 'bias'
    ? 'under ← 0 → over' : (m.diverging ? 'worse ← 0 → better' : 'weaker → stronger');
  document.getElementById('legend').innerHTML =
    `<div class="legend-scale"><span>${fmtEnd(lo)}</span><div class="scale-bar" style="background:${gradient}"></div><span>${fmtEnd(hi)}</span></div><span>${caption}</span>`;
}

const svg = document.getElementById('map');
function areaRadius(a){ return Math.max(4, Math.min(16, 3 + 3.2*Math.log10(Math.max(1,a)))); }
function renderMap() {
  const parts = [];
  for (let lo = -2; lo <= 2.5; lo += 1) {
    const [x1,y1] = project(lo, BOUNDS.latS), [x2,y2] = project(lo, BOUNDS.latN);
    parts.push(`<line class="grat" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
    parts.push(`<text class="axis-label" x="${x1}" y="${VB.h-16}" text-anchor="middle">${lo}°</text>`);
  }
  for (let la = 40; la <= 43; la += 1) {
    const [x1,y1] = project(BOUNDS.lonW, la), [x2,y2] = project(BOUNDS.lonE, la);
    parts.push(`<line class="grat" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
    parts.push(`<text class="axis-label" x="16" y="${y1+3}">${la}°N</text>`);
  }
  parts.push(`<text class="region-label" x="${VB.w-14}" y="24" text-anchor="end">SPAIN · PRE-PYRENEES / EBRO BASIN</text>`);
  RIVER_SEGMENTS.forEach(([a,b,c,d]) => {
    const [x1,y1] = project(a,b), [x2,y2] = project(c,d);
    parts.push(`<line class="river-line" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
  });
  [...STATIONS].sort((a,b) => b.area_km2 - a.area_km2).forEach(s => {
    const idx = STATIONS.indexOf(s), [x,y] = project(s.lon, s.lat);
    const val = valueFor(s, currentExp, currentMetric, currentYear), r = areaRadius(s.area_km2);
    const ring = s.provider === 'camelses' ? 'var(--camels)' : 'var(--grdc)';
    if (val === null || val === undefined || Number.isNaN(val)) {
      parts.push(`<circle class="gauge-dot nodata" data-i="${idx}" cx="${x}" cy="${y}" r="${r}"></circle>`);
    } else {
      parts.push(`<circle class="gauge-halo" cx="${x}" cy="${y}" r="${r+3.5}" stroke="${ring}"></circle>`);
      parts.push(`<circle class="gauge-dot" data-i="${idx}" cx="${x}" cy="${y}" r="${r}" fill="${colorFor(currentMetric,val)}"></circle>`);
    }
  });
  svg.innerHTML = parts.join('');
  svg.querySelectorAll('.gauge-dot').forEach(el => {
    el.addEventListener('mouseenter', () => showDetail(STATIONS[+el.dataset.i]));
    el.addEventListener('click', () => showDetail(STATIONS[+el.dataset.i]));
  });
}

const SPARK_COLORS = ['var(--pos)', 'var(--camels)', 'var(--neg)'];
function sparkline(s, key) {
  const series = EXPERIMENTS.map((e,i) => {
    const d = expData(s, e); if (!d) return null;
    const rows = d.years.filter(y => y[key] !== null && y[key] !== undefined && !Number.isNaN(y[key]));
    return rows.length >= 2 ? { exp: e, rows, color: SPARK_COLORS[i % SPARK_COLORS.length] } : null;
  }).filter(Boolean);
  if (!series.length) return '<div style="font-size:11.5px;color:var(--ink-faint)">not enough years for a trend line</div>';
  const W = 260, H = 46, pad = 4;
  const allVals = series.flatMap(sr => sr.rows.map(r => r[key]));
  const allYears = series.flatMap(sr => sr.rows.map(r => r.year));
  const lo = Math.min(...allVals, 0), hi = Math.max(...allVals, 0), range = (hi-lo) || 1;
  const y0 = Math.min(...allYears), y1 = Math.max(...allYears), yspan = (y1-y0) || 1;
  const sx = yr => pad + (yr-y0)/yspan * (W-2*pad);
  const sy = v => H - pad - (v-lo)/range * (H-2*pad);
  let out = `<svg class="spark" viewBox="0 0 ${W} ${H}"><line x1="0" y1="${sy(0)}" x2="${W}" y2="${sy(0)}" stroke="var(--border)" stroke-dasharray="2,2"/>`;
  series.forEach(sr => {
    out += `<polyline points="${sr.rows.map(r => `${sx(r.year)},${sy(r[key])}`).join(' ')}" fill="none" stroke="${sr.color}" stroke-width="1.6"/>`;
  });
  out += `<text x="2" y="${H-2}" font-size="9" fill="var(--ink-faint)" font-family="IBM Plex Mono, monospace">${y0}</text>`;
  out += `<text x="${W-2}" y="${H-2}" text-anchor="end" font-size="9" fill="var(--ink-faint)" font-family="IBM Plex Mono, monospace">${y1}</text></svg>`;
  out += `<div class="spark-legend">${series.map(sr => `<span><i style="background:${sr.color}"></i>${sr.exp}</span>`).join('')}</div>`;
  return out;
}

function showDetail(s) {
  const rows = METRICS.map(m => {
    const cells = EXPERIMENTS.map(e => {
      const v = valueFor(s, e, m.key, currentYear);
      const col = v === null || v === undefined || Number.isNaN(v) ? 'var(--ink-faint)' : colorFor(m.key, v);
      return `<td style="color:${col}">${fmtMetric(v, m.key)}</td>`;
    }).join('');
    return `<tr class="${m.key===currentMetric?'active':''}"><td>${m.label}</td>${cells}</tr>`;
  }).join('');
  const covers = EXPERIMENTS.map(e => {
    const d = expData(s, e);
    return d ? `${e}: ${d.n_years} yr (${d.year_min}–${d.year_max})` : `${e}: —`;
  }).join(' · ');
  document.getElementById('detail').innerHTML = `
    <h2>${s.name}</h2>
    <div class="meta">${s.area_km2.toLocaleString()} km² catchment · ${s.lat.toFixed(3)}°N, ${s.lon.toFixed(3)}°E</div>
    <span class="provider-pill ${s.provider}"><span class="dot"></span>${s.provider === 'grdc' ? 'GRDC (public domain)' : 'CAMELS-Spain'}</span>
    ${s.caveat ? `<div class="caveat-box">⚠ Excluded from headline statistics — ${s.caveat}</div>` : ''}
    <table class="cmp"><thead><tr><th>${currentYear === 'all' ? 'Median' : currentYear}</th>${EXPERIMENTS.map(e => `<th>${e}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>
    <div class="meta" style="font-size:11px">${covers}</div>
    <div class="spark-wrap"><div class="spark-label">${metricDef(currentMetric).label} by year</div>${sparkline(s, currentMetric)}</div>`;
}

let sortKey = 'area_km2', sortDir = -1;
function renderTable() {
  document.getElementById('table-head').innerHTML =
    `<th data-k="name">Gauge</th><th class="num" data-k="area_km2">Area (km²)</th>` +
    EXPERIMENTS.map(e => `<th class="num" data-k="exp:${e}">${e}</th>`).join('') +
    (EXPERIMENTS.length > 1 ? `<th class="num" data-k="delta">Δ (${EXPERIMENTS[EXPERIMENTS.length-1]} − ${EXPERIMENTS[0]})</th>` : '') +
    `<th class="num" data-k="n_years">Years</th>`;
  const valOf = (s, k) => {
    if (k === 'name') return s.name;
    if (k === 'area_km2') return s.area_km2;
    if (k === 'n_years') { const d = expData(s, currentExp); return d ? d.n_years : null; }
    if (k === 'delta') {
      const a = valueFor(s, EXPERIMENTS[0], currentMetric, currentYear);
      const b = valueFor(s, EXPERIMENTS[EXPERIMENTS.length-1], currentMetric, currentYear);
      return (a === null || b === null || a === undefined || b === undefined) ? null : b - a;
    }
    if (k.startsWith('exp:')) return valueFor(s, k.slice(4), currentMetric, currentYear);
    return null;
  };
  const rows = [...STATIONS].sort((a,b) => {
    const av = valOf(a, sortKey), bv = valOf(b, sortKey);
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === 'string') return av.localeCompare(bv) * sortDir;
    return (av - bv) * sortDir;
  });
  document.getElementById('table-body').innerHTML = rows.map(s => {
    const expCells = EXPERIMENTS.map(e => {
      const v = valueFor(s, e, currentMetric, currentYear);
      const col = v === null || v === undefined || Number.isNaN(v) ? 'var(--ink-faint)' : colorFor(currentMetric, v);
      return `<td class="num tnum" style="color:${col}">${fmtMetric(v, currentMetric)}</td>`;
    }).join('');
    let deltaCell = '';
    if (EXPERIMENTS.length > 1) {
      const d = valOf(s, 'delta');
      const better = currentMetric === 'pbias' || currentMetric === 'bias'
        ? (d === null ? null : Math.abs(valueFor(s, EXPERIMENTS[EXPERIMENTS.length-1], currentMetric, currentYear)) < Math.abs(valueFor(s, EXPERIMENTS[0], currentMetric, currentYear)))
        : (d === null ? null : d > 0);
      const col = d === null ? 'var(--ink-faint)' : (better ? 'var(--pos)' : 'var(--neg)');
      deltaCell = `<td class="num tnum" style="color:${col}">${d === null ? '—' : (d > 0 ? '+' : '') + (Math.abs(d) >= 10 ? d.toFixed(1) : d.toFixed(2))}</td>`;
    }
    const d = expData(s, currentExp);
    return `<tr data-i="${STATIONS.indexOf(s)}">
      <td class="name">${s.name}<span class="prov-tag ${s.provider}">${s.provider === 'grdc' ? 'GRDC' : 'CAMELS'}</span>${s.caveat ? '<span class="prov-tag caveat" title="'+s.caveat.replace(/"/g,'&quot;')+'">flagged</span>' : ''}</td>
      <td class="num tnum">${s.area_km2.toLocaleString()}</td>${expCells}${deltaCell}
      <td class="num tnum">${d ? d.n_years : '—'}</td></tr>`;
  }).join('');
  document.querySelectorAll('#table-body tr').forEach(tr => tr.addEventListener('click', () => {
    document.getElementById('btn-map-view').click();
    showDetail(STATIONS[+tr.dataset.i]);
  }));
  document.querySelectorAll('#table-head th[data-k]').forEach(th => th.addEventListener('click', () => {
    const k = th.dataset.k;
    if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = k === 'name' ? 1 : -1; }
    renderTable();
  }));
}

document.getElementById('btn-map-view').addEventListener('click', () => {
  document.getElementById('map-view').hidden = false; document.getElementById('table-view').hidden = true;
  document.getElementById('btn-map-view').setAttribute('aria-pressed','true');
  document.getElementById('btn-table-view').setAttribute('aria-pressed','false');
});
document.getElementById('btn-table-view').addEventListener('click', () => {
  document.getElementById('map-view').hidden = true; document.getElementById('table-view').hidden = false;
  document.getElementById('btn-map-view').setAttribute('aria-pressed','false');
  document.getElementById('btn-table-view').setAttribute('aria-pressed','true');
});

document.getElementById('footer').innerHTML = __FOOTER_JSON__;

let lastDetail = null;
function renderAll() {
  renderStats(); renderExpChips(); renderMetricChips(); renderLegend(); renderMap(); renderTable();
  showDetail(lastDetail || STATIONS.find(s => s.name.includes('CINCA, FRAGA')) || STATIONS[0]);
}
const origShowDetail = showDetail;
showDetail = function(s) { lastDetail = s; origShowDetail(s); };
renderYearSelect();
renderAll();
</script>
'''

default_intro = (
    "<p><b>What is being compared</b>: the identical 37-year naturalised ecLand–CaMa-Flood control "
    "(same pinned executable, same <code>input_cmf1way</code> namelist, same WFDE5 forcing, same 1988 "
    "cold start and restart chain) routed through CaMa-Flood river networks of different resolution. "
    "Only the routing grid and its derived weights differ, so differences here are attributable to "
    "routing resolution rather than to the land surface.</p>")
footer = ((args.intro_html or default_intro) +
    "<p><b>Gauges</b>: GRDC (public domain, via the GRDC-Caravan extension of Caravan) and CAMELS-Spain "
    "(own separate licence — see <code>cama_flood/extract_liaise_grdc_observations.py</code> before "
    "redistributing). Each gauge is mapped to its own cell in each resolution's network using the "
    "station archive's pre-computed per-resolution allocations, not by reusing 15-arcmin indices. "
    "<code>RIO GUADALOPE, CASPE</code> is a regulated river whose near-zero baseflow sends "
    "variance-based scores to extreme values — a metric artifact, not a model failure. Colour scales "
    "are clipped at the legend bounds; the real number is always shown in the panel and table.</p>"
    "<p><b>The count tile</b> uses a bar appropriate to each metric, since they are not "
    "interchangeable: NSE &gt; 0 is the classic \"better than predicting the mean observed "
    "flow\" test; the equivalent bar for KGE is <i>not</i> 0 but 1&nbsp;&minus;&nbsp;&radic;2 "
    "&asymp; &minus;0.41 (Knoben et al. 2019), so KGE&nbsp;&gt;&nbsp;0 is reported as its own, "
    "stricter bar rather than being mislabelled as the mean-flow benchmark. Correlation uses "
    "r&nbsp;&gt;&nbsp;0.5 and PBIAS uses &plusmn;25% of observed volume. Bias is an absolute "
    "m³/s quantity spanning orders of magnitude between the Ebro main stem and a "
    "100&nbsp;km² headwater, so it has no meaningful fixed bar of its own; its tile judges "
    "the same quantity as a fraction of observed flow — which is exactly PBIAS — at a looser "
    "&plusmn;50%, so the two tiles give a strict and a ballpark reference rather than "
    "independent information. The median tile follows the selected metric and year.</p>"
    "<p>Method: <code>cama_flood/skill_benchmark_resolution.py</code> · page: "
    "<code>cama_flood/build_resolution_dashboard.py</code></p>"
)

html = html.replace("__EYEBROW__", args.eyebrow)
html = html.replace("__TITLE__", args.title)
html = html.replace("__SUBTITLE__", args.subtitle)
html = html.replace("__EXPNOUN__", args.experiment_noun)
html = html.replace("__EXPNOUN_LOWER__", args.experiment_noun.lower())
html = html.replace("__CAVEATS_JSON__", json.dumps(sorted(caveat_names)))
html = html.replace("__STATIONS_JSON__", json.dumps(stations))
html = html.replace("__RIVER_JSON__", json.dumps(RIVER_SEGMENTS))
html = html.replace("__METRICS_JSON__", json.dumps(metrics))
html = html.replace("__EXPERIMENTS_JSON__", json.dumps(exp_labels))
html = html.replace("__PENDING_JSON__", json.dumps(args.pending))
html = html.replace("__HEADLINE_JSON__", json.dumps(headline))
html = html.replace("__FOOTER_JSON__", json.dumps(footer))

with open(args.out, "w") as fh:
    fh.write(html)
print(f"wrote {args.out}: {len(stations)} gauges, experiments={exp_labels}, pending={args.pending}")
for label, h in headline.items():
    print(f"  {label}: {h['n_stations']} gauges, {h['station_years']} station-years, "
          f"median KGE {h['median_kge']}, {h['positive_kge']}/{h['n_scored']} positive")
