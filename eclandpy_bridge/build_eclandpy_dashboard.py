#!/usr/bin/env python3
"""Build the eclandpy LIAISE dashboard (sites.ecmwf.int/pad/liaise/eclandpy/) as one
self-contained index.html -- the eclandpy counterpart of the Fortran control dashboard at
/pad/liaise/control/, drawn side by side with it wherever the control data exists.

Inputs (all optional except --eclandpy; panels appear only for what's present):
  --eclandpy   extract_eclandpy_diagnostics.py JSON (annual + monthly climatology)
  --control    run/extract_control_diagnostics.py JSON (Fortran 37-year control), same shape
  --grdc       skill_benchmark_fortran_vs_gpu.py results JSON (rows per year/station/model;
               its "GPU" rows are the eclandpy-driven CaMa-Flood-GPU chain when produced via
               submit_cmfgpu_eclandpy_chain.sh, "Fortran" rows the control reference)
  --discharge  glob of eclandpy_liaise_<y>_discharge_daily.nc (domain-mean discharge series)

No external assets: charts are inline SVG built here (the site is behind ECMWF SSO; keep it
one file). Runoff is shown as positive total runoff -(Qs+Qsb) for BOTH models (the control
JSON stores Qs+Qsb, negative). T2m for eclandpy is AvgSurfT (no 2 m diagnostic), labelled.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
from pathlib import Path

import numpy as np

ACCENT = "#2a6fb0"   # eclandpy (blue)
CTRL = "#8c8a84"     # Fortran control (warm grey)
GOOD = "#1a8f4b"
BAD = "#c0392b"

MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]


def _num(v):
    return None if v is None else float(v)


def load_annual(path: Path | None, runoff_key="runoff_mm", flip_runoff=False) -> dict[int, dict]:
    if not path or not Path(path).exists():
        return {}
    d = json.loads(Path(path).read_text())
    out = {}
    for y, r in d["annual"].items():
        r = dict(r)
        run = _num(r.get(runoff_key))
        if run is not None and flip_runoff:
            run = -run
        out[int(y)] = {
            "precip": _num(r.get("precip_mm")),
            "evap": -_num(r["evap_mm"]) if r.get("evap_mm") is not None else None,  # show as positive ET
            "runoff": run,
            "t2m": _num(r.get("t2m_mean_c")),
            "rootmoist": _num(r.get("rootmoist_mean")),
        }
    return out


def load_monthly(path: Path | None) -> dict[int, dict]:
    if not path or not Path(path).exists():
        return {}
    d = json.loads(Path(path).read_text()).get("monthly_climatology", {})
    return {int(m): v for m, v in d.items()}


# ---------- inline SVG helpers (one scale per chart, labels inside the viewBox) ----------

def _axes(W, H, ml, mr, mt, mb, ymin, ymax, x_labels, nticks=4):
    ih = H - mt - mb
    iw = W - ml - mr
    def sx(i, n):  # categorical x
        return ml + (i + 0.5) * iw / n
    def sy(v):
        return mt + ih * (1 - (v - ymin) / (ymax - ymin) if ymax > ymin else 0.5)
    g = []
    for k in range(nticks + 1):
        v = ymin + (ymax - ymin) * k / nticks
        y = sy(v)
        g.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        g.append(f'<text x="{ml-6}" y="{y+3.5:.1f}" class="tick" text-anchor="end">{v:.3g}</text>')
    n = len(x_labels)
    step = max(1, n // 8)
    for i, lab in enumerate(x_labels):
        if i % step == 0 or i == n - 1:
            g.append(f'<text x="{sx(i,n):.1f}" y="{H-mb+14}" class="tick" text-anchor="middle">{lab}</text>')
    return sx, sy, "\n".join(g)


def lines_chart(title, unit, years, series, W=420, H=220, x_labels=None):
    """series: list of (label, color, {year: value}); x_labels overrides str(year) (e.g. months)"""
    ml, mr, mt, mb = 44, 12, 14, 26
    vals = [v for _, _, s in series for v in s.values() if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 1.0
    ymin, ymax = lo - pad, hi + pad
    sx, sy, grid = _axes(W, H, ml, mr, mt, mb, ymin, ymax, x_labels or [str(y) for y in years])
    n = len(years)
    paths, dots = [], []
    for label, color, s in series:
        pts = [(sx(i, n), sy(s[y])) for i, y in enumerate(years) if s.get(y) is not None]
        if len(pts) > 1:
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            paths.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for (x, y), yr in zip(pts, [y for y in years if s.get(y) is not None]):
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{color}" stroke="var(--surface)" stroke-width="1.5"><title>{label} {yr}: {s[yr]:.1f} {unit}</title></circle>')
    legend = " ".join(f'<span class="chip"><i style="background:{c}"></i>{html.escape(l)}</span>' for l, c, _ in series)
    return f'''<figure class="chart">
  <figcaption><b>{html.escape(title)}</b> <span class="unit">{html.escape(unit)}</span> {legend}</figcaption>
  <svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">{grid}{"".join(paths)}{"".join(dots)}</svg>
</figure>'''


def bars_chart(title, unit, labels, series, W=420, H=200):
    """grouped bars; series: list of (label, color, [values...])"""
    ml, mr, mt, mb = 44, 12, 14, 24
    vals = [v for _, _, s in series for v in s if v is not None]
    if not vals:
        return ""
    ymin = min(0.0, min(vals))
    ymax = max(vals) * 1.08 if max(vals) > 0 else 1.0
    sx, sy, grid = _axes(W, H, ml, mr, mt, mb, ymin, ymax, labels)
    n, k = len(labels), len(series)
    slot = (W - ml - mr) / n
    bw = slot / (k + 1)
    bars = []
    for j, (label, color, s) in enumerate(series):
        for i, v in enumerate(s):
            if v is None:
                continue
            x = ml + i * slot + (j + 0.5) * bw
            y0, y1 = sy(max(v, 0)), sy(min(v, 0))
            bars.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw-2:.1f}" height="{max(y1-y0,1):.1f}" fill="{color}" rx="2"><title>{label} {labels[i]}: {v:.1f} {unit}</title></rect>')
    legend = " ".join(f'<span class="chip"><i style="background:{c}"></i>{html.escape(l)}</span>' for l, c, _ in series)
    return f'''<figure class="chart">
  <figcaption><b>{html.escape(title)}</b> <span class="unit">{html.escape(unit)}</span> {legend}</figcaption>
  <svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">{grid}{"".join(bars)}</svg>
</figure>'''


def build(args) -> str:
    ecl = load_annual(args.eclandpy, "runoff_mm")            # already -(Qs+Qsb), positive
    ctl = load_annual(args.control, "runoff_mm", flip_runoff=True)  # control stores Qs+Qsb (<0)
    years = sorted(set(ecl) | set(ctl))
    ecl_m, ctl_m = load_monthly(args.eclandpy), load_monthly(args.control)
    meta = json.loads(Path(args.eclandpy).read_text())

    def pair(key):
        s = [("eclandpy (GPU)", ACCENT, {y: ecl[y][key] for y in ecl})]
        if ctl:
            s.append(("Fortran control", CTRL, {y: ctl[y][key] for y in ctl}))
        return s

    # headline tiles: means over the years both have
    both = [y for y in years if y in ecl and y in ctl] or list(ecl)
    def mean(d, k):
        v = [d[y][k] for y in both if y in d and d[y][k] is not None]
        return sum(v) / len(v) if v else None
    tiles = []
    for key, label, unit, dec in (("precip", "Precipitation", "mm/yr", 0), ("evap", "Evapotranspiration", "mm/yr", 0),
                                  ("runoff", "Total runoff", "mm/yr", 0), ("t2m", "Surface T (AvgSurfT / T2m)", "°C", 2),
                                  ("rootmoist", "Root-zone moisture", "kg/m²", 0)):
        e, c = mean(ecl, key), mean(ctl, key)
        delta = "" if (e is None or c is None or c == 0) else f'<span class="delta">{(e-c)/abs(c)*100:+.1f}% vs control</span>'
        cval = "" if c is None else f'<span class="ctrl">control {c:.{dec}f}</span>'
        tiles.append(f'<div class="tile"><div class="lbl">{label}</div><div class="val">{"–" if e is None else f"{e:.{dec}f}"} <span class="unit">{unit}</span></div>{cval}{delta}</div>')

    charts = [
        lines_chart("Annual precipitation", "mm/yr", years, pair("precip")),
        lines_chart("Annual evapotranspiration", "mm/yr", years, pair("evap")),
        lines_chart("Annual total runoff  −(Qs+Qsb)", "mm/yr", years, pair("runoff")),
        lines_chart("Annual mean surface temperature", "°C", years, pair("t2m")),
        lines_chart("Root-zone soil moisture", "kg/m²", years, pair("rootmoist")),
    ]
    monthly = ""
    if ecl_m:
        ms = [("eclandpy (GPU)", ACCENT, [ecl_m[m]["precip_mm"] for m in range(1, 13)])]
        ts = [("eclandpy (GPU)", ACCENT, {m: ecl_m[m]["t2m_c"] for m in range(1, 13)})]
        if ctl_m:
            ms.append(("Fortran control", CTRL, [ctl_m[m]["precip_mm"] for m in range(1, 13)]))
            ts.append(("Fortran control", CTRL, {m: ctl_m[m]["t2m_c"] for m in range(1, 13)}))
        monthly = bars_chart("Monthly precipitation climatology", "mm/month", MONTHS, ms) + \
                  lines_chart("Monthly surface-temperature climatology", "°C", list(range(1, 13)), ts,
                              x_labels=MONTHS)

    # annual table (both models)
    rows = []
    for y in years:
        e, c = ecl.get(y, {}), ctl.get(y, {})
        f = lambda v, d=0: "–" if v is None else f"{v:.{d}f}"
        rows.append(f"<tr><td>{y}</td><td class=n>{f(e.get('precip'))}</td><td class=n>{f(e.get('evap'))}</td><td class=n>{f(e.get('runoff'))}</td><td class=n>{f(e.get('t2m'),2)}</td><td class=n>{f(e.get('rootmoist'))}</td>"
                    f"<td class='n c'>{f(c.get('precip'))}</td><td class='n c'>{f(c.get('evap'))}</td><td class='n c'>{f(c.get('runoff'))}</td><td class='n c'>{f(c.get('t2m'),2)}</td><td class='n c'>{f(c.get('rootmoist'))}</td></tr>")
    table = f'''<div class="tablewrap"><table><thead><tr><th rowspan=2>Year</th><th colspan=5>eclandpy (GPU)</th><th colspan=5 class=c>Fortran control</th></tr>
<tr><th>P</th><th>ET</th><th>R</th><th>Ts °C</th><th>RootM</th><th class=c>P</th><th class=c>ET</th><th class=c>R</th><th class=c>T2m °C</th><th class=c>RootM</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'''

    # GRDC gauge skill
    grdc = ""
    if args.grdc and Path(args.grdc).exists():
        res = json.loads(Path(args.grdc).read_text())
        res = res if isinstance(res, list) else res.get("results", [])
        excl = {"RIO GUADALOPE, CASPE"}
        by = {}
        for r in res:
            if r["station"] in excl:
                continue
            by.setdefault(r["station"], {}).setdefault(r["model"], []).append(r)
        def med(rs, k):
            v = [x[k] for x in rs if x.get(k) is not None]
            return float(np.median(v)) if v else None
        grows, wins = [], [0, 0]
        for st, models in sorted(by.items()):
            g, f = models.get("GPU", []), models.get("Fortran", [])
            kg, kf = med(g, "kge"), med(f, "kge")
            pg, pf = med(g, "pbias_pct"), med(f, "pbias_pct")
            if kg is not None and kf is not None:
                wins[0 if kg > kf else 1] += 1
            cls = "" if kg is None or kf is None else ("good" if kg > kf else "bad")
            fm = lambda v, d=2: "–" if v is None else f"{v:.{d}f}"
            grows.append(f"<tr><td>{html.escape(st)}</td><td class=n>{len(g)}</td><td class='n {cls}'>{fm(kg)}</td><td class='n c'>{fm(kf)}</td><td class=n>{fm(pg,1)}</td><td class='n c'>{fm(pf,1)}</td></tr>")
        grdc = f'''<section class="panel"><div class="ph"><h2>River discharge skill at GRDC gauges</h2>
<p class="sub">Median over the benchmark years (1988, 1995, 2000, 2003, 2005) of daily-discharge KGE and percent bias against observed flow at the LIAISE-domain gauges; eclandpy runoff routed by CaMa-Flood-GPU vs the Fortran ecLand+CaMa-Flood control. Rio Guadalope (Caspe) excluded (regulated river). eclandpy scores higher KGE at <b>{wins[0]}</b> of {sum(wins)} gauges.</p></div>
<div class="tablewrap"><table><thead><tr><th>Gauge</th><th>station-years</th><th>KGE eclandpy</th><th class=c>KGE control</th><th>PBIAS % eclandpy</th><th class=c>PBIAS % control</th></tr></thead><tbody>{"".join(grows)}</tbody></table></div></section>'''

    # domain discharge series
    disc = ""
    files = sorted(glob.glob(args.discharge)) if args.discharge else []
    if files:
        import netCDF4 as nc
        yrs, means = [], []
        for f in files:
            with nc.Dataset(f) as ds:
                q = np.ma.filled(ds["discharge"][:], np.nan)
                t = ds["time"]
                y = nc.num2date(t[0], units=t.units, calendar=getattr(t, "calendar", "standard")).year
            yrs.append(int(y)); means.append(float(np.nanmean(q)))
        disc = f'''<section class="panel"><div class="ph"><h2>Routed discharge</h2><p class="sub">Domain-mean daily discharge over all {'{:,}'.format(q.shape[1])} CaMa-Flood catchments of the LIAISE network, per year, from the eclandpy-driven CaMa-Flood-GPU chain (river storage carried 1988 → 2024).</p></div>
{lines_chart("Annual mean routed discharge", "m³/s", yrs, [("eclandpy → CaMa-Flood-GPU", ACCENT, dict(zip(yrs, means)))])}</section>'''

    n_years = len(ecl)
    span = f"{min(ecl)}–{max(ecl)}" if ecl else "–"
    prov = f'''<section class="panel prov"><div class="ph"><h2>Provenance</h2></div><p>
<b>Land surface:</b> eclandpy — Python/GT4Py port of ecLand (cy50r1 physics: RTF2, snow-cover fraction, vegetation tables ported on top of <code>ecland_porting</code>'s cy48r1 core; all 7 experimental hydrology flags off, as in the control), run on one NVIDIA A100 (<code>ECLAND_BACKEND=gt:gpu</code>, 32 ms/step for the 16×23 LIAISE grid, 37 with the output recorders; one CPU core does 24 ms/step on this 368-column grid — the GPU pays off only at scale) as a year-by-year restart chain, cold start from <code>soilinit</code> in 1988, WFDE5-CRU-GPCC forcing, {n_years} years ({span}).<br>
<b>River routing:</b> CaMa-Flood-GPU (Kang, Yin &amp; Yamazaki 2026) driven by eclandpy's total runoff −(Qs+Qsb) — the same formula ecLand's own LECMF1WAY coupling uses — with river storage chained forward across years.<br>
<b>Control:</b> the Fortran ecLand CY50R1 37-year LIAISE run at <a href="../control/">/pad/liaise/control/</a>, same forcing, same ancillaries.<br>
<b>Caveats:</b> eclandpy has no 2 m temperature diagnostic; its "surface T" is <code>AvgSurfT</code> (skin), the control's is T2m. Runoff for both is shown as positive total runoff; the control's JSON stores it as Qs+Qsb (negative). Source: <code>{html.escape(str(args.eclandpy))}</code>, generated by <code>eclandpy_bridge/build_eclandpy_dashboard.py</code>.</p></section>'''

    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIAISE eclandpy</title>
<style>
:root{{--bg:#f7f6f2;--surface:#ffffff;--ink:#1c1b19;--ink2:#5a5750;--muted:#8a877f;--line:#e3e0d8;--accent:{ACCENT};--ctrl:{CTRL};--good:{GOOD};--bad:{BAD};}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#161715;--surface:#1f201d;--ink:#f1efe9;--ink2:#c9c6bd;--muted:#8f8c83;--line:#33342f;--accent:#5b9be0;--ctrl:#a19e95;}}}}
:root[data-theme=dark]{{--bg:#161715;--surface:#1f201d;--ink:#f1efe9;--ink2:#c9c6bd;--muted:#8f8c83;--line:#33342f;--accent:#5b9be0;--ctrl:#a19e95;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding-block:24px 48px;padding-inline:20px}}
header h1{{font-size:24px;margin:0 0 4px;letter-spacing:-.01em}} header p{{margin:0;color:var(--ink2);max-width:70ch}}
.eyebrow{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:22px 0}}
.tile{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.tile .lbl{{font-size:12px;color:var(--muted)}} .tile .val{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;margin:4px 0 2px}}
.tile .unit,.chart .unit{{font-size:12px;color:var(--muted);font-weight:400}} .tile .ctrl{{display:block;font-size:12px;color:var(--ink2)}} .tile .delta{{display:block;font-size:12px;color:var(--ink2)}}
.panel{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}}
.ph h2{{font-size:16px;margin:0 0 4px}} .sub{{margin:0 0 12px;color:var(--ink2);max-width:90ch}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}}
figure.chart{{margin:0}} figcaption{{font-size:13px;margin-bottom:4px;display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}}
.chip{{font-size:11px;color:var(--ink2);display:inline-flex;align-items:center;gap:5px}} .chip i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
svg{{width:100%;height:auto;display:block}} .grid{{stroke:var(--line);stroke-width:1}} .tick{{font-size:9.5px;fill:var(--muted)}}
.tablewrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:12.5px}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}} td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}} .c{{color:var(--ink2)}}
td.good{{color:var(--good);font-weight:600}} td.bad{{color:var(--bad);font-weight:600}}
.prov p{{color:var(--ink2);margin:0;max-width:100ch}} code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;background:var(--bg);padding:1px 4px;border-radius:4px}}
a{{color:var(--accent)}}
</style></head><body><div class="wrap">
<header><div class="eyebrow">LIAISE · Ebro basin · 16×23 grid · WFDE5-CRU-GPCC forcing</div><h1>eclandpy on the LIAISE domain</h1>
<p>An all-Python land–river chain — eclandpy (GT4Py, GPU) for the land surface, CaMa-Flood-GPU for routing — run over the full LIAISE period and compared year by year with the Fortran ecLand control.</p></header>
<div class="tiles">{"".join(tiles)}</div>
<section class="panel"><div class="ph"><h2>Annual domain means</h2><p class="sub">Spatial mean over the active land points, each year; eclandpy in blue, the Fortran control in grey. Hover a point for its value.</p></div>
<div class="grid2">{"".join(charts)}</div></section>
{f'<section class="panel"><div class="ph"><h2>Seasonal cycle</h2><p class="sub">Climatology over all available years.</p></div><div class="grid2">{monthly}</div></section>' if monthly else ""}
{disc}{grdc}
<section class="panel"><div class="ph"><h2>Annual values</h2></div>{table}</section>
{prov}
</div></body></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eclandpy", type=Path, default=Path("/perm/pad/liaise_discharge_compare/eclandpy_run_diagnostics.json"))
    p.add_argument("--control", type=Path, default=Path("/perm/pad/liaise_discharge_compare/control_run_diagnostics.json"))
    p.add_argument("--grdc", type=Path, default=Path("/perm/pad/liaise_discharge_compare/skill_benchmark_results_eclandpy.json"))
    p.add_argument("--discharge", default="/perm/pad/liaise-ecland/eclandpy_bridge/cmfgpu_out_gpu/eclandpy_liaise_*_discharge_daily.nc")
    p.add_argument("--out", type=Path, default=Path("/perm/pad/liaise-ecland/eclandpy_bridge/dashboard_eclandpy/index.html"))
    a = p.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(build(a))
    print(f"wrote {a.out} ({a.out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
