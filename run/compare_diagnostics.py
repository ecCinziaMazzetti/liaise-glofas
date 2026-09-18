#!/usr/bin/env python3
"""Compare two extract_control_diagnostics.py JSONs field by field.

The reproduction check for a LIAISE control run: does this run agree with a
reference, and if not, where and by how much. Reports the 37-year mean of each
field on both sides, the relative difference, and the worst single year.

    python3 run/compare_diagnostics.py --a mine.json --b reference.json

Reading the result: precipitation is forcing-driven and must agree to 0.0% in
any correct comparison of runs sharing the same forcing -- it is the control
that tells you only the model state differs. Runoff and root-zone moisture are
the sensitive fields; a restart-chain difference shows up there (measured on
this domain: runoff +22.5%, root-zone moisture -8.8% between a cold-started and
a correctly chained 37-year run) while precipitation stays exactly equal.

Caution: a reference JSON on a shared filesystem can be regenerated under you.
This has happened -- /perm/pad/liaise_discharge_compare/control_run_diagnostics.json
held cold-start values on 2026-09-13 and post-fix values by 2026-09-17, so an
identical comparison gave opposite verdicts on consecutive days. Record the
reference's mtime alongside any result you intend to quote; --show-mtime does it
for you.

Exit status is 0 when every field agrees within --tol, else 1.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

FIELDS = ["precip_mm", "evap_mm", "runoff_mm", "t2m_mean_c", "rootmoist_mean"]


def annual(path: Path) -> dict:
    return json.loads(path.read_text())["annual"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, type=Path, help="this run's diagnostics JSON")
    ap.add_argument("--b", required=True, type=Path, help="reference diagnostics JSON")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--tol", type=float, default=0.0,
                    help="max |difference| per field-year still counted as agreement "
                         "(default 0.0: exact to the JSON's rounded precision)")
    ap.add_argument("--show-mtime", action="store_true",
                    help="print each JSON's modification time (recommended when quoting a result)")
    a = ap.parse_args()

    ya, yb = annual(a.a), annual(a.b)
    years = sorted(set(ya) & set(yb), key=int)
    if not years:
        print("no common years between the two JSONs", file=sys.stderr)
        return 1

    if a.show_mtime:
        for p, lab in ((a.a, a.label_a), (a.b, a.label_b)):
            ts = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            print("%-10s %s   mtime %s" % (lab, p, ts.strftime("%Y-%m-%d %H:%M")))
        print()

    print("%s  vs  %s   (%d common years: %s-%s)"
          % (a.label_a, a.label_b, len(years), years[0], years[-1]))
    ok = True
    n_diff = 0
    for k in FIELDS:
        absd = [abs(ya[y][k] - yb[y][k]) for y in years]
        mean_a = sum(ya[y][k] for y in years) / len(years)
        mean_b = sum(yb[y][k] for y in years) / len(years)
        rel = 100 * (mean_a - mean_b) / abs(mean_b) if mean_b else float("nan")
        worst = max(absd)
        worst_year = years[absd.index(worst)]
        n_diff += sum(1 for d in absd if d > a.tol)
        ok &= worst <= a.tol
        print("  %-16s mean %10.2f vs %10.2f  (%+7.2f%%)   max|diff| %9.3f (%s)"
              % (k, mean_a, mean_b, rel, worst, worst_year))
    total = len(years) * len(FIELDS)
    print("\n  %d of %d field-years differ by more than %g" % (n_diff, total, a.tol))
    print("  VERDICT: %s" % ("AGREE" if ok else "DIFFER"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
