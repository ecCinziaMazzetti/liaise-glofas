#!/usr/bin/env python3
"""Domain-mean land-surface diagnostics from an eclandpy LIAISE chain, for the dashboard --
the eclandpy counterpart of `run/extract_control_diagnostics.py` (same annual + monthly
climatology JSON shape, so the two dashboards can be built by one template).

Differences from the Fortran extractor, all deliberate:
  - T2m: eclandpy has no 2 m diagnostic (surfpp_ctl's per-tile 2 m scheme is unported), so the
    `t2m_mean_c`/`t2m_c` slots carry `AvgSurfT` (o_gg) instead; the JSON says so (`t2m_source`).
  - runoff: written as `-(Qs+Qsb)`, the total runoff ecLand hands CaMa-Flood (Qs>=0 surface,
    Qsb<=0 subsurface loss; see cama_flood/prepare_liaise_runoff_for_cmfgpu.py). The control
    extractor sums `Qs+Qsb` -- its value is also emitted (`runoff_ctrlformula_mm`) so the two
    conventions can be reconciled explicitly rather than silently.
  - land mask: domain means over cells where surfclim `Mask`>0 (the 16x23 box has sea/inactive
    cells; eclandpy writes fill values there) -- via `--surfclim`.
Rates (Rainf/Snowf/Qs/Qsb/Evap, kg m-2 s-1) x output interval (s) summed over the year = mm.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import netCDF4 as nc
import numpy as np


def _masked(arr, land):
    a = np.ma.masked_invalid(np.ma.filled(arr, np.nan))
    a = np.ma.masked_equal(a, 1.0e20)
    return np.ma.masked_array(a, mask=a.mask | ~land[None, :, :])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-root", type=Path, default=Path("/perm/pad/liaise-ecland/eclandpy_bridge/output_gpu"))
    p.add_argument("--surfclim", type=Path, default=Path("/perm/pad/liaise-ecland/init_clim/data/surfclim"))
    p.add_argument("--years", default="1988-2024", help="first-last, or a single year")
    p.add_argument("--out", type=Path, default=Path("/perm/pad/liaise_discharge_compare/eclandpy_run_diagnostics.json"))
    a = p.parse_args()
    y0, _, y1 = a.years.partition("-")
    years = list(range(int(y0), int(y1 or y0) + 1))

    with nc.Dataset(a.surfclim) as sc:
        land = np.asarray(sc["Mask"][:]) > 0

    annual, monthly = {}, {m: {"precip": [], "t2m": []} for m in range(1, 13)}
    for year in years:
        ydir = a.output_root / str(year)
        if not (ydir / "o_wat.nc").exists():
            print(f"{year}: missing, skipped")
            continue
        wat, eva, gg = (nc.Dataset(ydir / f) for f in ("o_wat.nc", "o_eva.nc", "o_gg.nc"))
        t = wat["time"]
        dt = float(t[1] - t[0]) if len(t) > 1 else 1800.0
        rainf, snowf = _masked(wat["Rainf"][:], land), _masked(wat["Snowf"][:], land)
        qs, qsb, evap = (_masked(wat[v][:], land) for v in ("Qs", "Qsb", "Evap"))
        surft = _masked(gg["AvgSurfT"][:], land)
        rootm = _masked(eva["RootMoist"][:], land)

        precip_mm = float((rainf + snowf).sum(axis=0).mean()) * dt
        runoff_mm = float((-(qs + qsb)).sum(axis=0).mean()) * dt
        runoff_ctrl_mm = float((qs + qsb).sum(axis=0).mean()) * dt
        evap_mm = float(evap.sum(axis=0).mean()) * dt
        annual[year] = {
            "precip_mm": round(precip_mm, 1),
            "evap_mm": round(evap_mm, 1),
            "runoff_mm": round(runoff_mm, 1),
            "runoff_ctrlformula_mm": round(runoff_ctrl_mm, 1),
            "t2m_mean_c": round(float(surft.mean()) - 273.15, 2),
            "rootmoist_mean": round(float(rootm.mean()), 2),
        }
        times = nc.num2date(t[:], units=t.units, calendar="standard")
        months = np.array([x.month for x in times])
        p_flat = (rainf + snowf).mean(axis=(1, 2)) * dt
        t_flat = surft.mean(axis=(1, 2))
        for m in range(1, 13):
            sel = months == m
            if sel.any():
                monthly[m]["precip"].append(float(p_flat[sel].sum()))
                monthly[m]["t2m"].append(float(t_flat[sel].mean()) - 273.15)
        for d in (wat, eva, gg):
            d.close()
        print(f"{year}: precip={precip_mm:.0f} evap={evap_mm:.0f} runoff={runoff_mm:.0f} "
              f"(ctrl-formula {runoff_ctrl_mm:.0f}) AvgSurfT={annual[year]['t2m_mean_c']:.1f}C "
              f"rootmoist={annual[year]['rootmoist_mean']:.2f}")

    out = {
        "model": "eclandpy (Python/GT4Py port, cy50r1 physics) + gt:gpu",
        "t2m_source": "AvgSurfT (eclandpy has no 2 m diagnostic)",
        "runoff_formula": "-(Qs+Qsb)",
        "annual": annual,
        "monthly_climatology": {
            m: {"precip_mm": round(float(np.mean(v["precip"])), 1) if v["precip"] else None,
                "t2m_c": round(float(np.mean(v["t2m"])), 2) if v["t2m"] else None}
            for m, v in monthly.items()
        },
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
