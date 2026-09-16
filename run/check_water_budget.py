#!/usr/bin/env python3
"""Check water-balance closure of raw ecLand output, per site and network-wide.

Imported unmodified from the sibling plumber2-ecland repo's
scripts/check_water_budget.py -- works unchanged against this repo's own
run/output/<year>/o_*.nc layout, since each year subdirectory is structurally
identical to one PLUMBER2 "site": pass --output-dir run/output (or
run/output_depthtrilogy) and each year is scored as its own row.

For each site, integrates the terms in o_wat.nc over the whole run and reports
the residual of

    Rainf + Snowf + Evap + Qs + Qsb
      - DelIntercept - DelSoilMoist - DelSWE - DelAquifer

(Qs and Qsb are ADDED here, matching ecLand's own output sign convention --
subtracting them instead manufactures a spurious residual of exactly 2x their
value.) This is the budget /home/pad/check_water_budget.sc has used since 2007,
extended by the -DelAquifer term added alongside the Qrec/Qcap/DelAquifer
diagnostics (ecland e9db58d) so LEGWRECHARGE runs close exactly rather than
legitimately reading the recharge.

DelAquifer, Qrec and Qcap are read if present and silently treated as zero
otherwise, so this runs unchanged against output from a build that predates
those diagnostics (LEGWRECHARGE off, or an older ecLand). When they are
present, also reports "clamp loss" = (Qrec-Qcap)-DelAquifer: nonzero only
where the water-table's RGWTD_MIN/RDBEDROCK clamp overrides the raw
recharge/capillary-rise flux without a matching correction to what was
diverted from Qsb -- see ecland 2470a28 for the cold-start case this
diagnostic caught, and the commit's note on the smaller within-run case that
is not yet fixed.

Exits non-zero if any site's residual exceeds --tol-frac of its precipitation
(default 1%) AND --tol-abs in absolute terms (default 5 mm/yr) -- both must be
exceeded, so a bone-dry site's tiny precipitation total does not trip the
check on a fraction of nearly nothing. Intended to run right after a raw
ecLand run, before or alongside postproc_plumber2.py -- it reads o_wat.nc
directly, and DelSoilMoist/DelSWE/DelIntercept/Qrec/Qcap/DelAquifer do not
survive into the postprocessed PLUMBER2-schema files.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset

DEFAULT_OUTPUT_DIR = Path('output')
SECONDS_PER_YEAR = 365.25 * 86400.0


def read_site(site_dir: Path) -> dict | None:
    wat_path = site_dir / 'o_wat.nc'
    if not wat_path.exists():
        return None
    with Dataset(wat_path) as ds:
        if 'Qs' not in ds.variables:
            return None
        time = np.asarray(ds.variables['time'][:])
        dt = float(np.median(np.diff(time))) if len(time) > 1 else 1800.0
        n = ds.variables['Qs'].shape[0]
        years = n * dt / SECONDS_PER_YEAR

        def flux_total(name: str) -> float:
            # kg m-2 s-1, summed and converted to a run-total in kg m-2 (mm)
            return float(np.sum(np.asarray(ds.variables[name][:]))) * dt if name in ds.variables else 0.0

        def store_total(name: str) -> float:
            # kg m-2 per step already -- summed directly, no dt factor
            return float(np.sum(np.asarray(ds.variables[name][:]))) if name in ds.variables else 0.0

        rainf, snowf = flux_total('Rainf'), flux_total('Snowf')
        evap, qs, qsb = flux_total('Evap'), flux_total('Qs'), flux_total('Qsb')
        qrec, qcap = flux_total('Qrec'), flux_total('Qcap')
        dsm, dswe, dint = store_total('DelSoilMoist'), store_total('DelSWE'), store_total('DelIntercept')
        daq = store_total('DelAquifer')
        has_aquifer_diag = 'Qrec' in ds.variables and 'DelAquifer' in ds.variables

    precip = rainf + snowf
    residual = precip + evap + qs + qsb - dint - dsm - dswe - daq
    return {
        'site': site_dir.name,
        'years': years,
        'precip_mm_yr': precip / years,
        'residual_mm_yr': residual / years,
        'residual_pct_of_P': 100.0 * residual / precip if precip else float('nan'),
        'clamp_loss_mm_yr': (qrec - qcap - daq) / years if has_aquifer_diag else float('nan'),
        'has_aquifer_diag': has_aquifer_diag,
    }


def discover_sites(output_dir: Path, site_filter: set[str] | None) -> list[Path]:
    dirs = sorted(p for p in output_dir.iterdir() if p.is_dir() and (p / 'o_wat.nc').exists())
    if site_filter:
        dirs = [d for d in dirs if d.name.split('_')[0] in site_filter or d.name in site_filter]
    return dirs


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR,
                    help='Raw ecLand output root, one subdirectory per site (default: output/).')
    p.add_argument('--out-csv', type=Path, default=None,
                    help='Optional path to write the per-site table as CSV.')
    p.add_argument('--site', action='append', default=None, help='Optional site filter; repeatable.')
    p.add_argument('--tol-frac', type=float, default=1.0,
                    help='Residual tolerance as %% of precipitation (default: 1.0).')
    p.add_argument('--tol-abs', type=float, default=5.0,
                    help='Residual tolerance in mm/yr, combined with --tol-frac (default: 5.0).')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    site_filter = set(args.site) if args.site else None
    site_dirs = discover_sites(args.output_dir, site_filter)
    if not site_dirs:
        print(f'No site output found under {args.output_dir}')
        return 2

    rows = [r for d in site_dirs if (r := read_site(d)) is not None]
    df = pd.DataFrame(rows).sort_values('residual_mm_yr', key=lambda s: s.abs(), ascending=False)

    pd.set_option('display.width', 120)
    pd.set_option('display.float_format', lambda x: f'{x:9.4f}')
    print(df.to_string(index=False))
    print()
    print(f'{len(df)} sites.  |residual|: mean={df.residual_mm_yr.abs().mean():.4f}  '
          f'median={df.residual_mm_yr.abs().median():.4f}  max={df.residual_mm_yr.abs().max():.4f} mm/yr')
    n_diag = int(df.has_aquifer_diag.sum())
    if n_diag:
        print(f'{n_diag} sites carry Qrec/Qcap/DelAquifer.  |clamp loss| among them: '
              f'mean={df.loc[df.has_aquifer_diag, "clamp_loss_mm_yr"].abs().mean():.4f}  '
              f'max={df.loc[df.has_aquifer_diag, "clamp_loss_mm_yr"].abs().max():.4f} mm/yr')

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out_csv, index=False)
        print(f'Wrote {args.out_csv}')

    failing = df[(df.residual_mm_yr.abs() > args.tol_abs) & (df.residual_pct_of_P.abs() > args.tol_frac)]
    if len(failing):
        print(f'\nFAIL: {len(failing)} site(s) exceed both {args.tol_abs} mm/yr and {args.tol_frac}% of P:')
        print(failing[['site', 'residual_mm_yr', 'residual_pct_of_P']].to_string(index=False))
        return 1
    print(f'\nPASS: all sites within {args.tol_abs} mm/yr or {args.tol_frac}% of P.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
