#!/usr/bin/env python3
"""Build the LIAISE Fortran-control dashboard as one self-contained index.html.

The control page (sites.ecmwf.int/<space>/<site>/) previously had no builder in
this repository -- it was made by hand, so a clone could not reproduce it. This
script closes that gap: it renders a control-only page straight from
run/extract_control_diagnostics.py's JSON, with no eclandpy or GPU inputs.

    # 1. diagnose a finished run (env-configurable paths)
    OUTPUT_ROOT=$RUN_ROOT/output START_YEAR=1988 END_YEAR=2024 \
        DIAGNOSTICS_JSON=$PERM/liaise_diagnostics/control_diagnostics.json \
        python3 run/extract_control_diagnostics.py

    # 2. render the page (needs python3/3.11+, not the default 3.6)
    python3 run/build_control_dashboard.py \
        --diagnostics $PERM/liaise_diagnostics/control_diagnostics.json \
        --out $PERM/liaise_dashboard/index.html

    # 3. publish (ECMWF Sites)
    module load sites
    sitesctl site --space <space> --name <site> content upload \
        --source $PERM/liaise_dashboard/index.html --destination / --force

Chart helpers (`lines_chart`, `bars_chart`, `load_annual`, `load_monthly`) are
imported from eclandpy_bridge/build_eclandpy_dashboard.py rather than copied, so
both pages stay visually consistent and there is one implementation to maintain.

Sign conventions, made explicit because the JSON's are not display conventions:
o_wat.nc's Evap and Qs+Qsb are stored as negative (water leaving the column), and
are shown here as POSITIVE evapotranspiration and total runoff. The loader's
`flip_runoff` does the runoff flip; `load_annual` already flips evaporation.

Colours are the validated categorical slots 1-3 (blue/orange/aqua) with their own
selected dark-mode steps, emitted as CSS custom properties so the SVG follows the
viewer's theme. The aqua slot sits just below 3:1 contrast on the light surface,
which obliges visible relief -- satisfied here by the legend chips, the value
tooltips and the full annual table.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
from pathlib import Path

import numpy as np

# --- reuse the eclandpy dashboard's chart helpers (single implementation) ---
_HELPERS = Path(__file__).resolve().parent.parent / "eclandpy_bridge" / "build_eclandpy_dashboard.py"
_spec = importlib.util.spec_from_file_location("_liaise_dash_helpers", _HELPERS)
_h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_h)   # safe: that module guards its own main()

lines_chart, bars_chart = _h.lines_chart, _h.bars_chart
load_annual, load_monthly = _h.load_annual, _h.load_monthly
MONTHS = _h.MONTHS

# Validated categorical slots 1-3; the SVG is written against these roles, not raw hex.
S1, S2, S3 = "var(--series-1)", "var(--series-2)", "var(--series-3)"

# (json key, label, display unit, decimals, trend unit). The trend unit is given
# explicitly rather than derived from the display unit: splitting "kg/m²" on "/"
# yields a wrong "kg/decade".
FIELDS = (
    ("precip", "Precipitation", "mm/yr", 0, "mm/decade"),
    ("evap", "Evapotranspiration", "mm/yr", 0, "mm/decade"),
    ("runoff", "Total runoff", "mm/yr", 0, "mm/decade"),
    ("t2m", "Mean 2 m temperature", "°C", 2, "°C/decade"),
    ("rootmoist", "Root-zone moisture", "kg/m²", 0, "kg/m²/decade"),
)


def trend_per_decade(years, values):
    """Least-squares linear trend, units per decade; None if under 10 points."""
    pairs = [(y, v) for y, v in zip(years, values) if v is not None]
    if len(pairs) < 10:
        return None
    ys = np.array([p[0] for p in pairs], dtype=float)
    vs = np.array([p[1] for p in pairs], dtype=float)
    return float(np.polyfit(ys, vs, 1)[0] * 10.0)


def build(args) -> str:
    ctl = load_annual(args.diagnostics, "runoff_mm", flip_runoff=True)
    if not ctl:
        raise SystemExit(f"no annual data in {args.diagnostics}")
    years = sorted(ctl)
    monthly = load_monthly(args.diagnostics)
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])

    def col(key):
        return [ctl[y][key] for y in years]

    def series(key, colour, label):
        return [(label, colour, {y: ctl[y][key] for y in years})]

    # ---- headline tiles: period mean, with observed range and (if long enough) trend
    tiles = []
    for key, label, unit, dec, tunit in FIELDS:
        vals = [v for v in col(key) if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        extra = f'<span class="rng">range {min(vals):.{dec}f} – {max(vals):.{dec}f}</span>'
        tr = trend_per_decade(years, col(key))
        if tr is not None:
            extra += f'<span class="rng">trend {tr:+.2f} {html.escape(tunit)}</span>'
        tiles.append(
            f'<div class="tile"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="val">{mean:.{dec}f} <span class="unit">{html.escape(unit)}</span></div>{extra}</div>')

    # ---- charts. One scale per chart: the three mm/yr fluxes share an axis,
    # temperature and moisture get their own (never a second y-axis).
    water = [
        ("Precipitation", S1, {y: ctl[y]["precip"] for y in years}),
        ("Evapotranspiration", S2, {y: ctl[y]["evap"] for y in years}),
        ("Total runoff", S3, {y: ctl[y]["runoff"] for y in years}),
    ]
    charts = [
        lines_chart("Annual water balance", "mm/yr", years, water),
        lines_chart("Annual mean 2 m temperature", "°C", years, series("t2m", S1, "T2m")),
        lines_chart("Root-zone soil moisture", "kg/m²", years, series("rootmoist", S3, "RootMoist")),
    ]

    seasonal = ""
    if monthly:
        ms = [("Precipitation", S1, [monthly[m]["precip_mm"] for m in range(1, 13)])]
        ts = [("T2m", S1, {m: monthly[m]["t2m_c"] for m in range(1, 13)})]
        seasonal = (bars_chart("Monthly precipitation climatology", "mm/month", MONTHS, ms)
                    + lines_chart("Monthly temperature climatology", "°C", list(range(1, 13)), ts,
                                  x_labels=MONTHS))

    # ---- annual table (also the accessibility relief for the light-mode contrast WARN)
    rows = []
    for y in years:
        r = ctl[y]
        f = lambda v, d=0: "–" if v is None else f"{v:.{d}f}"
        rows.append(f"<tr><td>{y}</td><td class=n>{f(r['precip'])}</td><td class=n>{f(r['evap'])}</td>"
                    f"<td class=n>{f(r['runoff'])}</td><td class=n>{f(r['t2m'],2)}</td>"
                    f"<td class=n>{f(r['rootmoist'])}</td></tr>")
    table = ('<div class="tablewrap"><table><thead><tr><th>Year</th><th class=n>Precip mm</th>'
             '<th class=n>ET mm</th><th class=n>Runoff mm</th><th class=n>T2m °C</th>'
             f'<th class=n>RootMoist kg/m²</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    prov = f'''<section class="panel prov"><div class="ph"><h2>Provenance</h2></div><p>
<b>Model:</b> {html.escape(args.model)}. <b>Forcing:</b> {html.escape(args.forcing)}.
<b>Period:</b> {span} ({len(years)} year{"s" if len(years) != 1 else ""}), year-by-year restart chain,
cold start from <code>soilinit</code> in {years[0]}.<br>
<b>Domain:</b> {html.escape(args.domain)}; every value is a spatial mean over the active land points.<br>
<b>Sign convention:</b> evapotranspiration and total runoff are plotted POSITIVE; <code>o_wat.nc</code>
stores <code>Evap</code> and <code>Qs+Qsb</code> as negative (water leaving the column). Annual depths come
from rates (kg m⁻² s⁻¹) multiplied by the output interval, not from pre-accumulated fields.<br>
<b>Source:</b> <code>{html.escape(str(args.diagnostics))}</code>, via
<code>run/extract_control_diagnostics.py</code>; rendered by <code>run/build_control_dashboard.py</code>.
{html.escape(args.note) if args.note else ""}</p></section>'''

    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(args.title)}</title>
<style>
:root{{--bg:#f7f6f2;--surface:#fcfcfb;--ink:#1c1b19;--ink2:#5a5750;--muted:#8a877f;--line:#e3e0d8;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--accent:#2a78d6;}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#161715;--surface:#1a1a19;--ink:#f1efe9;
--ink2:#c9c6bd;--muted:#8f8c83;--line:#33342f;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--accent:#3987e5;}}}}
:root[data-theme=dark]{{--bg:#161715;--surface:#1a1a19;--ink:#f1efe9;--ink2:#c9c6bd;--muted:#8f8c83;--line:#33342f;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--accent:#3987e5;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding-block:24px 48px;padding-inline:20px}}
header h1{{font-size:24px;margin:0 0 4px;letter-spacing:-.01em}} header p{{margin:0;color:var(--ink2);max-width:70ch}}
.eyebrow{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:22px 0}}
.tile{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.tile .lbl{{font-size:12px;color:var(--muted)}}
.tile .val{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;margin:4px 0 2px}}
.tile .unit,.chart .unit{{font-size:12px;color:var(--muted);font-weight:400}}
.tile .rng{{display:block;font-size:12px;color:var(--ink2)}}
.panel{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}}
.ph h2{{font-size:16px;margin:0 0 4px}} .sub{{margin:0 0 12px;color:var(--ink2);max-width:90ch}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}}
figure.chart{{margin:0}} figcaption{{font-size:13px;margin-bottom:4px;display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}}
.chip{{font-size:11px;color:var(--ink2);display:inline-flex;align-items:center;gap:5px}}
.chip i{{width:10px;height:10px;border-radius:2px;display:inline-block}}
svg{{width:100%;height:auto;display:block}} .grid{{stroke:var(--line);stroke-width:1}} .tick{{font-size:9.5px;fill:var(--muted)}}
.tablewrap{{overflow-x:auto;max-height:520px}} table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);position:sticky;top:0;background:var(--surface)}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.prov p{{color:var(--ink2);margin:0;max-width:100ch}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;background:var(--bg);padding:1px 4px;border-radius:4px}}
a{{color:var(--accent)}}
</style></head><body><div class="wrap">
<header><div class="eyebrow">{html.escape(args.eyebrow)}</div><h1>{html.escape(args.title)}</h1>
<p>{html.escape(args.subtitle)}</p></header>
<div class="tiles">{"".join(tiles)}</div>
<section class="panel"><div class="ph"><h2>Annual domain means</h2>
<p class="sub">Spatial mean over the active land points, one value per year. Hover any point for its value;
the full table is below. Evapotranspiration and runoff are shown positive.</p></div>
<div class="grid2">{"".join(charts)}</div></section>
{f'<section class="panel"><div class="ph"><h2>Seasonal cycle</h2><p class="sub">Climatology over {span}.</p></div><div class="grid2">{seasonal}</div></section>' if seasonal else ""}
<section class="panel"><div class="ph"><h2>Annual values</h2></div>{table}</section>
{prov}
</div></body></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--diagnostics", type=Path, required=True,
                   help="JSON from run/extract_control_diagnostics.py")
    p.add_argument("--out", type=Path, required=True, help="index.html to write")
    p.add_argument("--title", default="ecLand control on the LIAISE domain")
    p.add_argument("--subtitle", default="Land-surface-only ecLand control run over the Ebro basin, "
                                         "forced by WFDE5-CRU-GPCC and chained year by year through its own restarts.")
    p.add_argument("--eyebrow", default="LIAISE · Ebro basin · 23×16 grid · WFDE5-CRU-GPCC forcing")
    p.add_argument("--model", default="ecLand CY50R1, land surface only (LECMF1WAY=false)")
    p.add_argument("--forcing", default="WFDE5-CRU-GPCC, 0.5°, hourly")
    p.add_argument("--domain", default="LIAISE / Ebro basin, 0.5°, 23×16 grid, 235 active land points")
    p.add_argument("--note", default="")
    a = p.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(build(a))
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
