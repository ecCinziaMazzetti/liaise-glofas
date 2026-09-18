#!/usr/bin/env python3
"""Build the 'two chains' discharge-skill page from skill_benchmark_chains.py output.

Reuses the design of the 2026-09-13 "The LIAISE Correction" artifact (before/after
strip, per-gauge dumbbell of mean KGE, year-tab table) but is data-driven: pass the
JSON written by skill_benchmark_chains.py and, optionally, the 5-year benchmark JSON
for the "before" column.

    python3 build_chain_dashboard.py --results /perm/pad/liaise_discharge_compare/skill_benchmark_chains.json \
        --baseline /perm/pad/liaise_discharge_compare/skill_benchmark_results_v21fixdir3.json \
        --out /path/to/index.html
"""

import argparse
import json
from collections import defaultdict

import numpy as np

EXCLUDED = "RIO GUADALOPE, CASPE"
ORDER = ["RIO ARBA DE LUESIA, BIOTA", "RIO JILOCA, CALAMOCHA", "RIO CINCA, FRAGA", "RIO CINCA, LAFORTUNADA",
         "RIO VERO, LECINA DE BARCABO", "FORTANETE, RIO, PITARQUE", "RIO GUADALOPE, CASPE"]
AREA = {"RIO ARBA DE LUESIA, BIOTA": 275.4, "RIO JILOCA, CALAMOCHA": 2001.3, "RIO CINCA, FRAGA": 9678.3,
        "RIO CINCA, LAFORTUNADA": 604.1, "RIO VERO, LECINA DE BARCABO": 422.5, "FORTANETE, RIO, PITARQUE": 293.6,
        "RIO GUADALOPE, CASPE": 3858.4}


def summarise(rows):
    pairs = defaultdict(dict)
    for r in rows:
        pairs[(r["year"], r["station"])][r["model"]] = r
    both = [p for (y, s), p in pairs.items() if s != EXCLUDED and len(p) == 2]
    n = len(both)
    gpu_wins = sum(1 for p in both if p["GPU"]["kge"] > p["Fortran"]["kge"])
    med = lambda m, k: float(np.median([p[m][k] for p in both]))
    return {"n": n, "gpu_wins": gpu_wins, "years": sorted({y for (y, s) in pairs}),
            "f_kge": med("Fortran", "kge"), "g_kge": med("GPU", "kge"),
            "f_pb": med("Fortran", "pbias_pct"), "g_pb": med("GPU", "pbias_pct"),
            "f_r": med("Fortran", "r"), "g_r": med("GPU", "r")}


def data_block(rows):
    per = defaultdict(dict)
    for r in rows:
        per[r["station"]].setdefault(r["year"], {})[r["model"]] = r
    out = {}
    for s in ORDER:
        if s not in per:
            continue
        rs = []
        for y in sorted(per[s]):
            p = per[s][y]
            if len(p) < 2:
                continue
            rs.append({"y": y, "fk": round(p["Fortran"]["kge"], 3), "gk": round(p["GPU"]["kge"], 3),
                       "fp": round(p["Fortran"]["pbias_pct"], 1), "gp": round(p["GPU"]["pbias_pct"], 1)})
        out[s] = {"area": AREA.get(s, 0.0), "excluded": s == EXCLUDED, "rows": rs}
    return out


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--results", required=True)
ap.add_argument("--baseline", default="/perm/pad/liaise_discharge_compare/skill_benchmark_results_v21fixdir3.json")
ap.add_argument("--out", required=True)
ap.add_argument("--fortran-label", default="Fortran ecLand–CaMa-Flood chain")
ap.add_argument("--gpu-label", default="eclandpy → CaMa-Flood-GPU chain")
# Sites' hub lists sites, not the paths inside them, so a subpage is only
# reachable if a sibling page links to it.
ap.add_argument("--link", action="append", default=[], metavar="LABEL=URL",
                help="add a nav link to a companion page (repeatable), e.g. --link '37-year control=../'")
a = ap.parse_args()

nav = ""
if a.link:
    _items = []
    for _spec in a.link:
        _label, _, _url = _spec.partition("=")
        if not _url:
            raise SystemExit("--link needs LABEL=URL, got %r" % _spec)
        _items.append('<a href="%s">%s</a>' % (_url, _label))
    nav = '<nav class="nav">' + " ".join(_items) + "</nav>"

rows = json.load(open(a.results))
base = json.load(open(a.baseline))
S, B = summarise(rows), summarise(base)
years = S["years"]
span = f"{years[0]}–{years[-1]}"
win_pct = round(100 * S["gpu_wins"] / S["n"]) if S["n"] else 0
lead = "GPU" if S["gpu_wins"] * 2 > S["n"] else "Fortran"
fmt_pb = lambda v: ("+" if v > 0 else "−") + f"{abs(v):.1f}%"

html = f"""<title>Two Chains on the Ebro</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root{{ --bg:#F4F6F6; --surface:#FFFFFF; --surface-2:#EAF0EF; --ink:#14232A; --ink-soft:#48605E; --muted:#8AA09E;
    --border:#DCE6E4; --gridline:#E3EBE9; --accent:#1D5468; --fortran:#2A78D6; --gpu:#D9622A;
    --good:#0C8F3D; --good-bg:#E4F5E9; --bad:#B23A2E; --bad-bg:#FBEAE7;
    --shadow: 0 1px 2px rgba(20,35,42,0.04), 0 6px 20px rgba(20,35,42,0.06); }}
  @media (prefers-color-scheme: dark){{ :root:not([data-theme="light"]){{ --bg:#0C1414; --surface:#131E1E; --surface-2:#182524;
    --ink:#E7EFEE; --ink-soft:#9FB6B3; --muted:#5D7573; --border:#223231; --gridline:#1D2C2B; --accent:#5FB7CE;
    --fortran:#5B9EE8; --gpu:#E8895A; --good:#3BC26B; --good-bg:#14261B; --bad:#E06A5C; --bad-bg:#2A1917;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35); }} }}
  :root[data-theme="dark"]{{ --bg:#0C1414; --surface:#131E1E; --surface-2:#182524; --ink:#E7EFEE; --ink-soft:#9FB6B3; --muted:#5D7573;
    --border:#223231; --gridline:#1D2C2B; --accent:#5FB7CE; --fortran:#5B9EE8; --gpu:#E8895A; --good:#3BC26B; --good-bg:#14261B;
    --bad:#E06A5C; --bad-bg:#2A1917; --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35); }}
  *{{ box-sizing:border-box; }}
  body{{ margin:0; background:var(--bg); color:var(--ink); font-family:"IBM Plex Sans", system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
  .wrap{{ max-width:920px; margin:0 auto; padding-block:40px 80px; padding-inline:20px; }}
  a{{ color:var(--accent); }}
  .eyebrow{{ font-family:"IBM Plex Mono", monospace; font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .eyebrow .dot{{ width:5px; height:5px; border-radius:50%; background:var(--muted); }}
  .badge{{ font-family:"IBM Plex Mono", monospace; font-size:11px; letter-spacing:0.04em; color:var(--good); background:var(--good-bg); border-radius:20px; padding:3px 10px; text-transform:none; }}
  h1{{ font-family:"Fraunces", Georgia, serif; font-optical-sizing:auto; font-weight:600; font-size:clamp(28px,4.4vw,42px); line-height:1.12; letter-spacing:-0.01em; margin:14px 0 12px; text-wrap:balance; max-width:16ch; }}
  h1 em{{ font-style:italic; color:var(--accent); }}
  .lede{{ font-size:16px; line-height:1.6; color:var(--ink-soft); max-width:62ch; margin:0 0 32px; }}
  .lede code, .lede b{{ color:var(--ink); font-weight:600; }}
  code, .mono{{ font-family:"IBM Plex Mono", monospace; }}
  h2{{ font-family:"Fraunces", Georgia, serif; font-weight:600; font-size:22px; letter-spacing:-0.005em; margin:0 0 4px; }}
  .section-sub{{ font-size:13.5px; color:var(--ink-soft); margin:0 0 18px; max-width:60ch; }}
  section{{ margin-top:56px; }}
  .flip{{ display:grid; grid-template-columns:1fr auto 1fr; gap:18px; align-items:stretch; }}
  @media (max-width:640px){{ .flip{{ grid-template-columns:1fr; }} .flip .arrow{{ transform:rotate(90deg); margin:4px auto; }} }}
  .flip-col{{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:22px 22px 20px; box-shadow:var(--shadow); }}
  .flip-col.before{{ border-top:3px solid var(--muted); }} .flip-col.after{{ border-top:3px solid var(--accent); }}
  .flip-label{{ font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:14px; display:flex; align-items:center; gap:8px; }}
  .flip-col.before .flip-label{{ color:var(--muted); }} .flip-col.after .flip-label{{ color:var(--accent); }}
  .flip .arrow{{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:22px; }}
  .flip-stat{{ display:flex; justify-content:space-between; align-items:baseline; padding:9px 0; border-bottom:1px dashed var(--gridline); gap:10px; }}
  .flip-stat:last-child{{ border-bottom:none; }} .flip-stat .k{{ font-size:13px; color:var(--ink-soft); }}
  .flip-stat .v{{ font-family:"Fraunces",serif; font-weight:600; font-size:19px; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .flip-col.before .v{{ color:var(--ink-soft); }} .flip-col.after .v{{ color:var(--accent); }}
  .bugs{{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }} @media (max-width:640px){{ .bugs{{ grid-template-columns:1fr; }} }}
  .bug-card{{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:20px 20px 18px; box-shadow:var(--shadow); }}
  .bug-num{{ font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--accent); letter-spacing:0.06em; text-transform:uppercase; margin-bottom:6px; }}
  .bug-card h3{{ font-size:16.5px; margin:0 0 8px; font-weight:600; }} .bug-card p{{ font-size:13.5px; line-height:1.55; color:var(--ink-soft); margin:0 0 12px; }}
  .proof{{ font-size:12px; color:var(--ink-soft); border-top:1px solid var(--gridline); padding-top:10px; }} .proof b{{ color:var(--ink); font-family:"IBM Plex Mono",monospace; font-weight:500; }}
  .chart-card{{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:24px 24px 12px; box-shadow:var(--shadow); }}
  .legend{{ display:flex; gap:20px; margin-bottom:18px; font-size:12.5px; color:var(--ink-soft); flex-wrap:wrap; }} .legend span{{ display:inline-flex; align-items:center; gap:6px; }} .legend i{{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
  .dumbbell-grid{{ display:grid; grid-template-columns:150px 1fr 80px; align-items:center; }} @media (max-width:480px){{ .dumbbell-grid{{ grid-template-columns:104px 1fr 56px; }} }}
  .name{{ font-size:13px; font-weight:500; line-height:1.3; }} .area{{ font-size:11.5px; color:var(--muted); font-family:"IBM Plex Mono",monospace; }}
  .result{{ font-size:12px; text-align:right; font-family:"IBM Plex Mono",monospace; }} .result .win{{ color:var(--gpu); font-weight:600; }}
  svg text{{ font-family:"IBM Plex Mono", monospace; }}
  .axis-caption{{ display:flex; justify-content:space-between; font-size:11px; color:var(--muted); font-family:"IBM Plex Mono",monospace; padding:6px 0 18px; }}
  .tabs{{ display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; }}
  .tab{{ font-family:"IBM Plex Mono",monospace; font-size:12.5px; padding:7px 12px; border-radius:20px; border:1px solid var(--border); background:var(--surface); color:var(--ink-soft); cursor:pointer; }}
  .tab:hover{{ border-color:var(--accent); color:var(--ink); }} .tab.active{{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  .table-wrap{{ overflow-x:auto; border:1px solid var(--border); border-radius:14px; background:var(--surface); box-shadow:var(--shadow); }}
  table{{ border-collapse:collapse; width:100%; min-width:640px; font-size:13px; }}
  thead th{{ text-align:left; font-family:"IBM Plex Mono",monospace; font-weight:500; font-size:11px; letter-spacing:0.04em; text-transform:uppercase; color:var(--muted); padding:12px 14px; border-bottom:1px solid var(--border); position:sticky; top:0; background:var(--surface); }}
  thead th.num, td.num{{ text-align:right; font-variant-numeric:tabular-nums; }} tbody td{{ padding:11px 14px; border-bottom:1px solid var(--gridline); }} tbody tr:last-child td{{ border-bottom:none; }} tbody tr:hover{{ background:var(--surface-2); }}
  td.station{{ font-weight:500; }}
  .pill{{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11.5px; font-family:"IBM Plex Mono",monospace; }} .pill.gpu-win{{ background:var(--good-bg); color:var(--good); }} .pill.for-win{{ background:var(--bad-bg); color:var(--bad); }} .pill.tie{{ background:var(--surface-2); color:var(--muted); }}
  .excl-note{{ font-size:12px; color:var(--muted); padding:10px 14px; border-top:1px dashed var(--border); }}
  .nav{{ margin:18px 0 0; display:flex; flex-wrap:wrap; gap:14px; }}
  .nav a{{ font-size:13px; font-weight:600; text-decoration:none; color:var(--ink);
    border:1px solid var(--border); border-radius:999px; padding:5px 12px; }}
  .nav a:hover{{ border-color:var(--ink); }}
  footer{{ margin-top:64px; padding-top:24px; border-top:1px solid var(--border); font-size:12px; color:var(--muted); line-height:1.8; }} footer .path{{ color:var(--ink-soft); word-break:break-all; }}
</style>
<div class="wrap">
  <div class="eyebrow">LIAISE <span class="dot"></span> CaMa-Flood discharge benchmark <span class="badge">{span} · {S['n']} station-years</span></div>
  <h1>Two 37-year chains, scored on <em>every</em> gauged year.</h1>
  <p class="lede">The Fortran ecLand–CaMa-Flood coupled chain (<code>LECMF1WAY</code>, cold start 1988, restart-chained to 2024) and the
    eclandpy → CaMa-Flood-GPU chain, both on the same glb_15min network and WFDE5 forcing, against the 7 real GRDC gauges of the Ebro
    for {span}. The {"GPU" if lead=="GPU" else "Fortran"} chain leads on KGE in <b>{S['gpu_wins'] if lead=="GPU" else S['n']-S['gpu_wins']} of {S['n']}</b>
    station-years; median PBIAS is <b>{fmt_pb(S['f_pb'])}</b> (Fortran) vs <b>{fmt_pb(S['g_pb'])}</b> (GPU).</p>
  {nav}

  <section>
    <h2>From the 5-year benchmark to the full record</h2>
    <p class="section-sub">Left: the corrected 2026-09-13 benchmark (five 2-pass same-year runs, Fortran control runoff on both sides). Right: the continuous chains over every year with observations, {EXCLUDED.title()} excluded from both.</p>
    <div class="flip">
      <div class="flip-col before">
        <div class="flip-label">● 5 years · 2-pass spin-up · shared runoff</div>
        <div class="flip-stat"><span class="k">Station-years</span><span class="v">{B['n']}</span></div>
        <div class="flip-stat"><span class="k">GPU beats Fortran on KGE</span><span class="v">{B['gpu_wins']} / {B['n']}</span></div>
        <div class="flip-stat"><span class="k">Median KGE — Fortran · GPU</span><span class="v">{B['f_kge']:.3f} · {B['g_kge']:.3f}</span></div>
        <div class="flip-stat"><span class="k">Median PBIAS — Fortran · GPU</span><span class="v">{fmt_pb(B['f_pb'])} · {fmt_pb(B['g_pb'])}</span></div>
      </div>
      <div class="arrow">→</div>
      <div class="flip-col after">
        <div class="flip-label">● {len(years)} years · continuous chains · own runoff</div>
        <div class="flip-stat"><span class="k">Station-years</span><span class="v">{S['n']}</span></div>
        <div class="flip-stat"><span class="k">GPU beats Fortran on KGE</span><span class="v">{S['gpu_wins']} / {S['n']}</span></div>
        <div class="flip-stat"><span class="k">Median KGE — Fortran · GPU</span><span class="v">{S['f_kge']:.3f} · {S['g_kge']:.3f}</span></div>
        <div class="flip-stat"><span class="k">Median PBIAS — Fortran · GPU</span><span class="v">{fmt_pb(S['f_pb'])} · {fmt_pb(S['g_pb'])}</span></div>
      </div>
    </div>
  </section>

  <section>
    <h2>What differs between the two chains</h2>
    <p class="section-sub">Unlike the 5-year benchmark, the chains are not fed the same runoff: each land model produces its own.</p>
    <div class="bugs">
      <div class="bug-card">
        <div class="bug-num">Difference 1 · land model</div>
        <h3>Fortran ecLand vs eclandpy</h3>
        <p>The GPU chain is driven by eclandpy, the Python port. Over the 37 years its domain-mean runoff is 21 % below the Fortran control (160.8 vs 203.4 mm/yr, r = 0.85), so the two routers do not see the same water — a genuine model difference, not a set-up bug.</p>
        <div class="proof">Both routers were shown to agree to <b>0.23 pp</b> of bias when fed identical runoff (5-year benchmark).</div>
      </div>
      <div class="bug-card">
        <div class="bug-num">Difference 2 · spin-up</div>
        <h3>Continuous chain vs 2-pass same-year</h3>
        <p>Land and river storage now carry over year to year from a single 1988 cold start, the way a production run would, instead of each scored year being spun up on itself. 1988 is therefore a cold-start year on both sides.</p>
        <div class="proof">Naturalised (no reservoirs) on both sides: <b>LDAMOUT=.FALSE.</b>; bifurcation on.</div>
      </div>
    </div>
  </section>

  <section>
    <h2>Per-gauge skill, mean KGE over {len(years)} years</h2>
    <p class="section-sub">Closer to 1.0 is better; 0 is "no better than the mean observed flow". Regulated Caspe shown only in the table.</p>
    <div class="chart-card">
      <div class="legend"><span><i style="background:var(--fortran)"></i>{a.fortran_label}</span><span><i style="background:var(--gpu)"></i>{a.gpu_label}</span></div>
      <div id="dumbbell"></div>
      <div class="axis-caption"><span>← worse</span><span>KGE</span><span>better →</span></div>
    </div>
  </section>

  <section>
    <h2>Full results by year</h2>
    <p class="section-sub">Every gauge-year with ≥30 common valid days. KGE and PBIAS per chain; verdict by KGE.</p>
    <div class="tabs" id="tabs"></div>
    <div class="table-wrap">
      <table><thead><tr><th>Gauge</th><th class="num">Fortran KGE</th><th class="num">GPU KGE</th><th class="num">Fortran PBIAS</th><th class="num">GPU PBIAS</th><th>Verdict</th></tr></thead>
      <tbody id="tbody"></tbody></table>
      <div class="excl-note">KGE = Kling–Gupta Efficiency (1 = perfect). PBIAS = percent bias in total volume. Fortran <code>totout</code> (6-hourly) averaged to daily means before matching.</div>
    </div>
  </section>

  <footer>
    Data: <span class="path">{a.results}</span><br>
    Method: <span class="path">liaise-ecland/cama_flood/skill_benchmark_chains.py</span> · page: <span class="path">cama_flood/build_chain_dashboard.py</span><br>
    Runs: Fortran chain <span class="path">/perm/pad/liaise_cmf_1988_2024/</span> (job 37620761, 2026-09-16) · eclandpy chain <span class="path">liaise-ecland/eclandpy_bridge/cmfgpu_out_gpu_repro/</span>
  </footer>
</div>
<script>
const DATA = {json.dumps(data_block(rows))};
const YEARS = {json.dumps(years)};
const ORDER = {json.dumps([s for s in ORDER if s in data_block(rows)])};
function niceName(n){{ const m={{"RIO ARBA DE LUESIA, BIOTA":"Río Arba de Luesia, Biota","RIO JILOCA, CALAMOCHA":"Río Jiloca, Calamocha","RIO CINCA, FRAGA":"Río Cinca, Fraga","RIO CINCA, LAFORTUNADA":"Río Cinca, Lafortunada","RIO VERO, LECINA DE BARCABO":"Río Vero, Lecina de Barcabo","FORTANETE, RIO, PITARQUE":"Fortanete, Río, Pitarque","RIO GUADALOPE, CASPE":"Río Guadalope, Caspe"}}; return m[n]||n; }}
(function(){{
  const gauges = ORDER.filter(n => !DATA[n].excluded);
  const W=560, rowH=40, padTop=6, padBottom=6, H=gauges.length*rowH+padTop+padBottom, xMin=-1.15, xMax=0.75, xPad=8;
  const xScale = v => xPad + (Math.max(xMin,Math.min(xMax,v))-xMin)/(xMax-xMin)*(W-2*xPad); const zeroX=xScale(0);
  let svg = `<svg viewBox="0 0 ${{W}} ${{H}}" width="100%" height="${{H}}" role="img" aria-label="Mean KGE per gauge">`;
  svg += `<line x1="${{zeroX}}" y1="0" x2="${{zeroX}}" y2="${{H}}" stroke="var(--gridline)" stroke-width="1.5" stroke-dasharray="3,3"/>`;
  gauges.forEach((name,i)=>{{ const rows=DATA[name].rows; const fM=rows.reduce((s,r)=>s+r.fk,0)/rows.length, gM=rows.reduce((s,r)=>s+r.gk,0)/rows.length;
    const y=padTop+i*rowH+rowH/2, x1=xScale(fM), x2=xScale(gM);
    svg += `<line x1="${{x1}}" y1="${{y}}" x2="${{x2}}" y2="${{y}}" stroke="var(--muted)" stroke-width="2" opacity="0.55"/>`;
    svg += `<circle cx="${{x1}}" cy="${{y}}" r="6" fill="var(--fortran)" stroke="var(--surface)" stroke-width="1.5"/><circle cx="${{x2}}" cy="${{y}}" r="6" fill="var(--gpu)" stroke="var(--surface)" stroke-width="1.5"/>`;
    if (fM<xMin||gM<xMin) svg += `<text x="${{xScale(xMin)+10}}" y="${{y-11}}" font-size="10.5" fill="var(--muted)">actual: ${{fM.toFixed(2)}} → ${{gM.toFixed(2)}}</text>`; }});
  svg += `</svg>`;
  document.getElementById('dumbbell').innerHTML = `<div class="dumbbell-grid"><div>${{gauges.map(n=>`<div style="height:${{rowH}}px;display:flex;flex-direction:column;justify-content:center;"><div class="name">${{niceName(n)}}</div><div class="area">${{DATA[n].area.toLocaleString()}} km² · ${{DATA[n].rows.length}} yr</div></div>`).join('')}}</div><div>${{svg}}</div><div>${{gauges.map(n=>{{const rows=DATA[n].rows; const w=rows.filter(r=>r.gk>r.fk).length; return `<div style="height:${{rowH}}px;display:flex;align-items:center;justify-content:flex-end;"><span class="result"><span class="win">GPU ${{w}}/${{rows.length}}</span></span></div>`;}}).join('')}}</div></div>`;
}})();
let currentYear='all';
function renderTable(){{ let html=''; ORDER.forEach(name=>{{ DATA[name].rows.filter(r=>currentYear==='all'||r.y===currentYear).forEach(r=>{{
  const verdict = r.gk>r.fk ? '<span class="pill gpu-win">GPU</span>' : '<span class="pill for-win">Fortran</span>';
  html += `<tr><td class="station">${{niceName(name)}}${{DATA[name].excluded?' <span style="color:var(--muted);font-size:11px;">(excluded)</span>':''}}<div class="area">${{r.y}}</div></td><td class="num">${{r.fk.toFixed(3)}}</td><td class="num">${{r.gk.toFixed(3)}}</td><td class="num">${{r.fp.toFixed(1)}}%</td><td class="num">${{r.gp.toFixed(1)}}%</td><td>${{verdict}}</td></tr>`; }}); }});
  document.getElementById('tbody').innerHTML = html; }}
function renderTabs(){{ const tabs=document.getElementById('tabs'); const opts=[{{v:'all',l:'All years'}}].concat(YEARS.map(y=>({{v:y,l:String(y)}})));
  tabs.innerHTML = opts.map(o=>`<button class="tab ${{currentYear===o.v?'active':''}}" data-v="${{o.v}}">${{o.l}}</button>`).join('');
  tabs.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{{ const v=b.dataset.v; currentYear = v==='all'?'all':parseInt(v,10); renderTabs(); renderTable(); }})); }}
renderTabs(); renderTable();
</script>
"""
open(a.out, "w").write(html)
print(f"wrote {a.out}: {S['n']} station-years, {span}, GPU wins {S['gpu_wins']}/{S['n']}")
