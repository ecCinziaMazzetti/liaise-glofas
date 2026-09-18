#!/usr/bin/env python3
"""Verify that a multi-year ecLand run is genuinely restart-chained.

Why this exists: the annual restart chain can fail *silently*. Before upstream's
4f0ad4e, run_liaise_ecland.{sh,slurm} staged the previous year's restart as
restartin.nc and set LNF=.FALSE., but the offline driver only calls RDRES when
NSTART /= 0 and the script always starts each year at NSTART=0 -- so the staged
restart was never read and every year cold-started from soilinit, with no error
message and no obvious signature in the output.

Do NOT try to diagnose this from the namelist: the signature is counter-
intuitive and inverting it is easy. `LNF=.TRUE.` with no restart_in.nc is the
FIXED configuration (the previous restart is linked *as* soilinit); `LNF=.FALSE.`
with a staged restart_in.nc is the BROKEN one. Test the model state instead,
which is unambiguous:

  1. January states across years: a cold-started run begins every year from the
     same soilinit, so its 1 January fields are near-identical year to year. A
     chained run's differ, because each year inherits the previous December.
  2. Year-boundary continuity: 31 December -> 1 January is one hour, so a
     chained run is continuous there. A cold-started run jumps.

Both are unit-free ratios of the same field, so no unit conversion is needed.

    python3 run/verify_restart_chain.py --run-root $PERM/liaise_ctl_1988_2024
    python3 run/verify_restart_chain.py --run-root A --run-root B   # compare runs

Exit status is 0 if every run checked is chained, 1 otherwise, so this can gate
a pipeline.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import netCDF4 as nc
import numpy as np

# Thresholds. The gap between chained and cold-started is ~2 orders of
# magnitude on this domain (0.04 vs 270 for continuity; 410 vs 5 for the
# January spread), so these are deliberately loose rather than tuned.
CONTINUITY_MAX = 1.0      # 31 Dec -> 1 Jan must be below this to count as continuous
JANUARY_SPREAD_MIN = 50.0  # January states must differ by more than this


def _field(run_root: Path, year: int, index: int, var: str):
    p = run_root / "output" / str(year) / "o_ggd.nc"
    if not p.exists():
        raise FileNotFoundError(p)
    return np.ma.masked_invalid(nc.Dataset(p)[var][index])


def check_run(run_root: Path, years: list[int], var: str = "SoilMoist") -> dict:
    """years: [first, mid, late] -- first is the cold-start year, the rest sampled."""
    first, mid, late = years
    jan_a = _field(run_root, first + 1, 0, var)
    jan_b = _field(run_root, mid, 0, var)
    jan_c = _field(run_root, late, 0, var)
    dec = _field(run_root, first, -1, var)

    spread_ab = float(np.abs(jan_a - jan_b).max())
    spread_ac = float(np.abs(jan_a - jan_c).max())
    continuity = float(np.abs(jan_a - dec).max())
    chained = continuity < CONTINUITY_MAX and spread_ab > JANUARY_SPREAD_MIN
    return {
        "run_root": str(run_root),
        "january_spread_%d_vs_%d" % (first + 1, mid): spread_ab,
        "january_spread_%d_vs_%d" % (first + 1, late): spread_ac,
        "continuity_%d_dec_to_%d_jan" % (first, first + 1): continuity,
        "chained": chained,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-root", action="append", required=True, type=Path,
                    help="RUN_ROOT of a finished run (repeatable, to compare runs)")
    ap.add_argument("--years", default="1988,1995,2010",
                    help="first,mid,late sample years (default 1988,1995,2010); "
                         "'first' must be the run's cold-start year")
    ap.add_argument("--var", default="SoilMoist", help="o_ggd.nc field to test")
    a = ap.parse_args()
    years = [int(y) for y in a.years.split(",")]
    if len(years) != 3:
        ap.error("--years needs exactly three comma-separated years")

    all_ok = True
    for root in a.run_root:
        try:
            r = check_run(root, years, a.var)
        except Exception as exc:  # missing year, missing field: report, do not crash
            print("%s\n   ERROR: %s\n" % (root, exc))
            all_ok = False
            continue
        print("%s" % r["run_root"])
        for k, v in r.items():
            if k in ("run_root", "chained"):
                continue
            print("   %-34s %10.4f" % (k, v))
        print("   VERDICT: %s\n" % ("CHAINED" if r["chained"] else "COLD-STARTING (invalid as a multi-year run)"))
        all_ok &= r["chained"]
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
