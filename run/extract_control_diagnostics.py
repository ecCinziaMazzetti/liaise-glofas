#!/usr/bin/env python3
"""Extract domain-mean land-surface diagnostics from the 37-year LIAISE
control run (run/output/<year>/{o_wat,o_d2m,o_eva}.nc) for the dashboard."""
import json
import os
import numpy as np
import netCDF4 as nc
from pathlib import Path

# Paths/years are environment-configurable so a run other than the original
# /perm/pad 37-year control can be diagnosed; defaults reproduce that run.
OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", "/perm/pad/liaise-ecland/run/output"))
START_YEAR = int(os.environ.get("START_YEAR", 1988))
END_YEAR = int(os.environ.get("END_YEAR", 2024))
YEARS = list(range(START_YEAR, END_YEAR + 1))

def masked_mean(arr):
    a = np.ma.masked_invalid(np.ma.filled(arr, np.nan))
    a = np.ma.masked_equal(a, 1.0e20)
    return a

annual = {}
monthly_sum = {m: {"precip": [], "t2m": []} for m in range(1, 13)}

for year in YEARS:
    ydir = OUTPUT_ROOT / str(year)
    wat = nc.Dataset(ydir / "o_wat.nc")
    d2m = nc.Dataset(ydir / "o_d2m.nc")
    eva = nc.Dataset(ydir / "o_eva.nc")

    # o_wat: accumulated fluxes per output step (LACCUMW+LRESET), kg/m2 = mm
    # per step; sum over time -> mm/year domain totals (spatial mean of the
    # active-land-point domain, then temporal sum).
    # Rainf/Snowf/Qs/Qsb/Evap are RATES (kg m-2 s-1), not accumulated depth
    # per step -- multiply by the output interval (seconds) before summing
    # to get an annual depth (mm/year = kg/m2/year).
    time_var_dt = wat.variables["time"]
    dt_seconds = float(time_var_dt[1] - time_var_dt[0]) if len(time_var_dt) > 1 else 3600.0

    rainf = masked_mean(wat.variables["Rainf"][:])
    snowf = masked_mean(wat.variables["Snowf"][:])
    qs = masked_mean(wat.variables["Qs"][:])
    qsb = masked_mean(wat.variables["Qsb"][:])
    evap = masked_mean(wat.variables["Evap"][:])

    precip_mm = float((rainf + snowf).sum(axis=0).mean()) * dt_seconds
    runoff_mm = float((qs + qsb).sum(axis=0).mean()) * dt_seconds
    evap_mm = float(evap.sum(axis=0).mean()) * dt_seconds

    t2m = masked_mean(d2m.variables["T2m"][:])
    t2m_mean_c = float(t2m.mean()) - 273.15

    rootmoist = masked_mean(eva.variables["RootMoist"][:])
    rootmoist_mean = float(rootmoist.mean())

    annual[year] = {
        "precip_mm": round(precip_mm, 1),
        "evap_mm": round(evap_mm, 1),
        "runoff_mm": round(runoff_mm, 1),
        "t2m_mean_c": round(t2m_mean_c, 2),
        "rootmoist_mean": round(rootmoist_mean, 2),
    }

    # Monthly climatology inputs: reconstruct calendar month per timestep
    # from the time variable (seconds since YYYY-01-01 00:00:00).
    time_var = wat.variables["time"]
    times = nc.num2date(time_var[:], units=time_var.units, calendar="standard")
    months = np.array([t.month for t in times])

    rainf_flat = (rainf + snowf).mean(axis=(1, 2)) * dt_seconds  # domain-mean mm/step
    t2m_flat = t2m.mean(axis=(1, 2))
    for m in range(1, 13):
        sel = months == m
        if sel.sum() == 0:
            continue
        monthly_sum[m]["precip"].append(float(rainf_flat[sel].sum()))
        monthly_sum[m]["t2m"].append(float(t2m_flat[sel].mean()) - 273.15)

    wat.close(); d2m.close(); eva.close()
    print(f"{year}: precip={precip_mm:.0f}mm evap={evap_mm:.0f}mm runoff={runoff_mm:.0f}mm "
          f"T2m={t2m_mean_c:.1f}C rootmoist={rootmoist_mean:.2f}")

monthly_clim = {
    m: {
        "precip_mm": round(float(np.mean(monthly_sum[m]["precip"])), 1),
        "t2m_c": round(float(np.mean(monthly_sum[m]["t2m"])), 2),
    }
    for m in range(1, 13)
}

out = {"annual": annual, "monthly_climatology": monthly_clim}
outpath = Path(os.environ.get("DIAGNOSTICS_JSON",
                              "/perm/pad/liaise_discharge_compare/control_run_diagnostics.json"))
outpath.parent.mkdir(parents=True, exist_ok=True)
outpath.write_text(json.dumps(out, indent=2))
print(f"\nWrote {outpath}")
