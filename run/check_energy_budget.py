#!/usr/bin/env python3
"""Check surface energy-balance closure of raw ecLand output, per site and network-wide.

Imported unmodified from the sibling plumber2-ecland repo's
scripts/check_energy_budget.py -- works unchanged against this repo's own
run/output/<year>/o_*.nc layout, since each year subdirectory is structurally
identical to one PLUMBER2 "site": pass --output-dir run/output (or
run/output_depthtrilogy) and each year is scored as its own row.

For each site, integrates over the whole run the terms in o_efl.nc's own sign
convention (Qh, Qle and Qg are positive DOWNWARD here -- verified empirically:
SWnet+LWnet+Qh+Qle+Qg closes to <1e-4 W/m2 at every timestep on a snow-free
site -- this is NOT the ALMA upward-positive convention the PLUMBER2-schema
postprocessed files use):

    SWnet + LWnet + Qh + Qle  +  DelSoilHeat + DelColdCont

and reports the run-mean residual in W/m2. Rearranged, this is checking that
the energy available at the surface after turbulent exchange is fully
accounted for by the change in soil + snow internal energy content.

DelSoilHeat and DelColdCont are read from o_efl.nc if present, but in every
build/config checked so far they are identically zero: DelSoilHeat's source
value (D1SDSH in upddiag.F90) is hardcoded to 0 ("DelSoilHeat of skin layer
(0)"), and DelColdCont's (PDHTSS(:,1,15) in srfsn_lwexp_mod.F90) is populated
only inside the debug-only LESNCHECK path -- the line that would set it during
a normal run is commented out. Both are therefore reconstructed independently
here from state variables rather than trusted from the file:

  * Soil: srfene_mod.F90's own "apparent energy" formula, using the actual
    per-layer field capacity/porosity ecLand writes to o_fix.nc (SoilFC,
    SoilSat) -- RRCSOILM3D = (1-SoilSat)*RCGDRY + SoilFC*RGH2O exactly (see
    susdp_deriv_ctl_mod.F90 / susdp_dflt_ctl_mod.F90) -- and the model's own
    temperature-only freezing curve (RTF1/RTF2 namelist defaults). Verified
    against the true surface-flux integral on a snow-free site to <0.01%.

  * Snow: no equivalent internal formula exists in the standard diagnostic
    output (see above), so this uses a standard ice+liquid specific-heat
    enthalpy formulation over the multi-layer state (SWEML/slwML/SnowTML),
    with ecLand's own ice-vs-water heat capacity convention (ice = 0.5x
    water's -- see ZGICE in srfrcg_mod.F90). This is a physically-standard
    approximation, not a replica of internal model arithmetic (unlike the
    soil term above).

Even with both storage terms, this does not close to the same precision as
check_water_budget.py's water balance. This is NOT a model energy-conservation
bug: every individual tile's own surface balance closes by construction. It is
a genuine property of how the offline diagnostics are defined: Qg (via ZSURFL
in srft_mod.F90) sums SWnet/LWnet/turbulent flux only over the NON-snow tiles,
substituting PGSN (conduction through the snowpack into the soil) for the two
snow tiles instead -- while the o_efl.nc SWnet/LWnet/Qh/Qle are true full-grid
means that DO include the snow tiles (PDIFTS, PFTLHEV+PFTLHSB in upddiag.F90).
Working through each tile's own closing balance shows

    SWnet + LWnet + Qh + Qle + Qg  ==  dE_snow/dt  (exactly, by construction)

i.e. that non-cancellation IS the (otherwise unreported) instantaneous snow
heat-storage tendency, not a missing flux term -- adding Qgsn/Qfsn on top (an
earlier hypothesis) does not fix it because those are unrelated quantities.
What's left after including this script's own (approximate) dE_snow is a
genuine approximation gap: the two-term ice+liquid enthalpy formula used here
does not replicate the real multi-layer scheme's layer-by-layer melt/
refreeze/percolation bookkeeping (srfsn_lwexp_mod.F90). This residual runs
order 1-3 W/m2 (run-mean) on typical snow-heavy multi-decade sites (FI-Hyy,
CH-Dav, US-Ha1) and confirmed near-zero (<0.01 W/m2) on snow-free sites; it
reflects a script-side formula limitation, not a namelist-fixable output gap
and not a model defect. A short run starting far from thermal equilibrium can
also show a similar-sized residual as its soil column drifts toward balance.
Default tolerance is set loose enough to not flag this normal, explained
residual while still catching an actual regression (which would be expected
to shift Qh/Qle/Qg by far more than a few W/m2 -- e.g. the interception bug
fixed this session shifted the water budget by mm/yr-scale amounts, not the
sub-percent noise floor this script is tuned around).

Exits non-zero if any site's |residual| exceeds --tol-wm2 (default 5.0 W/m2).
Intended to run right after a raw ecLand run, before or alongside
postproc_plumber2.py -- it reads o_efl.nc/o_gg.nc/o_fix.nc/o_vty.nc directly,
none of which survive into the postprocessed PLUMBER2-schema files in the form
needed here.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset

DEFAULT_OUTPUT_DIR = Path('output')
SECONDS_PER_YEAR = 365.25 * 86400.0

# ecLand soil/snow thermal constants -- see src/surf/module/sussoil_mod.F90,
# srfene_mod.F90, srfrcg_mod.F90, susdp_dflt_ctl_mod.F90. RTF1/RTF2 are the
# rdnml_params.F90 namelist defaults (274.16/272.16 K); overridable in
# principle but essentially never overridden in practice.
RCGDRY = 1.6e6    # dry-soil-grain volumetric heat capacity, J K-1 m-3 (Peters-Lidard et al. 1998)
RGH2O = 4.18e6    # volumetric heat capacity of water, J K-1 m-3
RHOH2O = 1000.0   # density of water, kg m-3
RLMLT = 0.3337e6  # latent heat of fusion, J kg-1 (RLSTT - RLVTT)
RTF1, RTF2 = 274.16, 272.16
RTF3 = 0.5 * (RTF1 + RTF2)
RTF4 = np.pi / (RTF1 - RTF2)
CI_SNOW = 0.5 * RGH2O / RHOH2O  # ice specific heat, J kg-1 K-1 (ecLand's own ZGICE convention)
CW_SNOW = RGH2O / RHOH2O        # liquid water specific heat, J kg-1 K-1


def _frozen_fraction(t: np.ndarray) -> np.ndarray:
    return np.where(t <= RTF2, 1.0, np.where(t < RTF1, 0.5 * (1.0 - np.sin(RTF4 * (t - RTF3))), 0.0))


def _soil_energy(t: np.ndarray, soilfc: np.ndarray, soilsat: np.ndarray, soilthick: np.ndarray, cv: float) -> float:
    rrcsoil = (1.0 - soilsat) * RCGDRY + soilfc * RGH2O
    f = _frozen_fraction(t)
    return float(np.sum((rrcsoil * t - RLMLT * RHOH2O * cv * soilfc * f) * soilthick))


def _snow_energy(swe: np.ndarray, slw: np.ndarray, t: np.ndarray) -> float:
    ice = swe - slw
    return float(np.sum(CI_SNOW * ice * t + CW_SNOW * slw * t + RLMLT * slw))


def read_site(site_dir: Path) -> dict | None:
    efl_path, gg_path = site_dir / 'o_efl.nc', site_dir / 'o_gg.nc'
    fix_path, vty_path = site_dir / 'o_fix.nc', site_dir / 'o_vty.nc'
    if not all(p.exists() for p in (efl_path, gg_path, fix_path, vty_path)):
        return None

    with Dataset(efl_path) as ds:
        if 'SWnet' not in ds.variables:
            return None
        time = np.asarray(ds.variables['time'][:])
        dt = float(np.median(np.diff(time))) if len(time) > 1 else 1800.0
        n = ds.variables['SWnet'].shape[0]
        years = n * dt / SECONDS_PER_YEAR
        swnet = np.asarray(ds.variables['SWnet'][:]).ravel()
        lwnet = np.asarray(ds.variables['LWnet'][:]).ravel()
        qh = np.asarray(ds.variables['Qh'][:]).ravel()
        qle = np.asarray(ds.variables['Qle'][:]).ravel()
    surf_avail = float(np.sum(swnet + lwnet + qh + qle)) * dt
    rnet_mean_abs = float(np.mean(np.abs(swnet + lwnet)))

    with Dataset(fix_path) as ds:
        soilthick = np.asarray(ds.variables['SoilThick'][:]).ravel()
        soilfc = np.asarray(ds.variables['SoilFC'][:]).ravel()
        soilsat = np.asarray(ds.variables['SoilSat'][:]).ravel()

    with Dataset(vty_path) as ds:
        vtfr0 = np.asarray(ds.variables['vtfr'][0]).ravel()
    cv = float(vtfr0[0] + vtfr0[1])  # low+high vegetation cover; static over the run

    with Dataset(gg_path) as ds:
        t0 = np.asarray(ds.variables['SoilTemp'][0]).ravel()
        t1 = np.asarray(ds.variables['SoilTemp'][-1]).ravel()
        has_ml_snow = 'SWEML' in ds.variables and 'slwML' in ds.variables and 'SnowTML' in ds.variables
        dE_snow = 0.0
        if has_ml_snow:
            swe0, swe1 = np.asarray(ds.variables['SWEML'][0]).ravel(), np.asarray(ds.variables['SWEML'][-1]).ravel()
            slw0, slw1 = np.asarray(ds.variables['slwML'][0]).ravel(), np.asarray(ds.variables['slwML'][-1]).ravel()
            snt0, snt1 = np.asarray(ds.variables['SnowTML'][0]).ravel(), np.asarray(ds.variables['SnowTML'][-1]).ravel()
            dE_snow = _snow_energy(swe1, slw1, snt1) - _snow_energy(swe0, slw0, snt0)

    dE_soil = _soil_energy(t1, soilfc, soilsat, soilthick, cv) - _soil_energy(t0, soilfc, soilsat, soilthick, cv)

    residual = surf_avail + dE_soil + dE_snow
    residual_wm2 = residual / (years * SECONDS_PER_YEAR)
    return {
        'site': site_dir.name,
        'years': years,
        'rnet_mean_wm2': rnet_mean_abs,
        'dE_soil_MJ_m2': dE_soil / 1.0e6,
        'dE_snow_MJ_m2': dE_snow / 1.0e6,
        'residual_wm2': residual_wm2,
        'residual_pct_of_Rnet': 100.0 * residual_wm2 / rnet_mean_abs if rnet_mean_abs else float('nan'),
        'has_ml_snow': has_ml_snow,
    }


def discover_sites(output_dir: Path, site_filter: set[str] | None) -> list[Path]:
    dirs = sorted(p for p in output_dir.iterdir() if p.is_dir() and (p / 'o_efl.nc').exists())
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
    p.add_argument('--tol-wm2', type=float, default=5.0,
                    help='Residual tolerance in run-mean W/m2 (default: 5.0).')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    site_filter = set(args.site) if args.site else None
    site_dirs = discover_sites(args.output_dir, site_filter)
    if not site_dirs:
        print(f'No site output found under {args.output_dir}')
        return 2

    rows = [r for d in site_dirs if (r := read_site(d)) is not None]
    df = pd.DataFrame(rows).sort_values('residual_wm2', key=lambda s: s.abs(), ascending=False)

    pd.set_option('display.width', 120)
    pd.set_option('display.float_format', lambda x: f'{x:9.4f}')
    print(df.to_string(index=False))
    print()
    print(f'{len(df)} sites.  |residual|: mean={df.residual_wm2.abs().mean():.4f}  '
          f'median={df.residual_wm2.abs().median():.4f}  max={df.residual_wm2.abs().max():.4f} W/m2')

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out_csv, index=False)
        print(f'Wrote {args.out_csv}')

    failing = df[df.residual_wm2.abs() > args.tol_wm2]
    if len(failing):
        print(f'\nFAIL: {len(failing)} site(s) exceed {args.tol_wm2} W/m2:')
        print(failing[['site', 'residual_wm2', 'residual_pct_of_Rnet']].to_string(index=False))
        return 1
    print(f'\nPASS: all sites within {args.tol_wm2} W/m2.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
