#!/usr/bin/env python3
"""Run eclandpy (Python/GT4Py physics) continuously over the LIAISE grid,
year by year with a real restart chain between years -- the eclandpy
counterpart of `run/run_liaise_ecland.sh`'s Fortran workflow (cold start
from soilinit in the first year, one calendar year per step, write a
restart, feed it into the next year).

Why a restart mechanism had to be built at all
------------------------------------------------
`ecland_porting.offline.driver.OfflineDriver` has no restart save/load of
its own (checked directly -- every eclandpy run before this one has been a
single one-shot `driver.run(nsteps)` call from a cold start). Its per-step
carried state is `OfflineState` (`offline/state.py`): a plain dataclass of
numpy arrays (`prog`, `veg`, `ptskti`, `ustrti`, `vstrti`), plus, for a
carbon-enabled driver, `driver._carbon_acc` (`pandayvt`/`panfmvt`). All of
that is trivially serializable -- `snapshot_state`/`restore_state` below
just pickle/reload it whole, one file per year boundary
(`restart/eclandpy_restart_<year>.pkl`), so:
  - the run is resumable (a 37-year chain is long; don't lose progress to a
    node failure or wall-time limit),
  - each year's restart can be diffed against the Fortran run's own
    `run/restart/<year>` for a real correctness check, independent of
    whatever eventually happens downstream in CaMa-Flood-GPU.

Each year is a genuinely fresh `adapter.build()` call (its own met_2dHT
file, `RunConfig.nstart` resets to 0) -- restoring the previous year's
`OfflineState` onto that fresh driver, in place, before calling `.run()`,
is what actually chains the physics; the driver's own cold-start seed from
`surfinit` is simply discarded for every year after the first.

Per-year outputs (mirroring the Fortran run's own o_wat/o_eva, o_gg
subset): `output/<year>/o_wat.nc` (Snowf/Rainf/Evap/Qs/Qsb/Qsm/Del* --
`WAT_VARS`), `output/<year>/o_eva.nc` (RootMoist etc -- `EVA_VARS`),
`output/<year>/o_gg.nc` (AvgSurfT/SoilTemp/SoilMoist/SWE -- the full o_gg
schema via `OutputRecorder`, used as this dashboard's T2m stand-in since
eclandpy has no T2m/D2m diagnostic yet -- see phase-plan notes,
"surfpp_ctl_mod.F90 2m diagnostics", not yet ported, diagnostic-only gap).
"""
from __future__ import annotations

import argparse
import calendar
import pickle
from pathlib import Path

import numpy as np

BRIDGE_ROOT = Path("/perm/pad/liaise-ecland/eclandpy_bridge")


def _add_latlon(nc_path: Path) -> None:
    """Inject lat/lon coordinate variables (copied from LIAISE's own surfclim) into an
    output file `DiagRecorder`/`OutputRecorder` wrote -- unlike the Fortran o_wat.nc etc.,
    these only carry lat/lon as bare dimensions, no coordinate variable. Needed so
    eclandpy's output is a genuine drop-in for any downstream tool built against the
    Fortran file's schema (e.g. cama_flood/prepare_liaise_runoff_for_cmfgpu.py, which reads
    `src.variables["lat"]` directly and KeyErrors without this)."""
    import netCDF4

    with netCDF4.Dataset("/perm/pad/liaise-ecland/init_clim/data/surfclim") as clim:
        lat, lon = clim.variables["lat"][:], clim.variables["lon"][:]
    with netCDF4.Dataset(nc_path, "a") as ds:
        if "lat" not in ds.variables:
            v = ds.createVariable("lat", "f8", ("lat",))
            v[:] = lat
            v.units = "degrees_north"
        if "lon" not in ds.variables:
            v = ds.createVariable("lon", "f8", ("lon",))
            v[:] = lon
            v.units = "degrees_east"


def snapshot_state(driver) -> dict:
    """Host (numpy) copy of everything the driver carries between steps.

    Generic over `OfflineState`'s dataclass fields rather than a hardcoded list: Christian's
    2026-09 main merge added `ahfsti`/`evapti` (previous-step tile fluxes) to the carried state,
    which a five-field snapshot silently dropped and a five-field restore then failed on. On
    the GPU backends the state lives on the device (cupy; `np.array()` on it raises), so go
    through `OfflineState.host()` / `to_host`; on CPU these are plain copies.
    """
    from dataclasses import fields

    from ecland_porting.utils.arrays import to_host

    def h(v):  # own host copy, never a view of a reusable storage
        return {k: np.array(to_host(x)) for k, x in v.items()} if isinstance(v, dict) else np.array(to_host(v))

    hs = driver.state.host()
    snap = {"state": {f.name: h(getattr(hs, f.name)) for f in fields(hs)}}
    if driver.carbon:
        snap["carbon_acc"] = h(driver._carbon_acc)
    return snap


def restore_state(driver, snap: dict) -> None:
    from dataclasses import fields

    from ecland_porting.offline.state import OfflineState

    want = [f.name for f in fields(OfflineState)]
    # pre-2026-09-14 snapshots (the CPU 1988-2014 chain in restart/) stored the five fields at
    # top level rather than under "state"; accept both, the missing-field check below decides.
    have = snap["state"] if "state" in snap else {k: v for k, v in snap.items() if k != "carbon_acc"}
    missing = [n for n in want if n not in have]
    if missing:  # a snapshot from an older OfflineState layout: refuse rather than half-restore
        raise RuntimeError(f"restart lacks carried fields {missing}; re-run from a cold start")
    driver.state = OfflineState(**{n: (dict(have[n]) if isinstance(have[n], dict) else have[n]) for n in want})
    if driver.carbon and "carbon_acc" in snap:
        driver._carbon_acc = dict(snap["carbon_acc"])


def run_one_year(
    year: int, restart_in: Path | None, restart_out: Path, out_dir: Path,
    max_steps: int | None = None,
) -> None:
    # ecland_porting imports MUST come after adapter.build() -- _io_shim.install() (which build()
    # calls first) must run before ecland_porting.setup is ever imported anywhere in the process,
    # or the shim's install() raises (hit this on the first real run of this script, 2026-09-13;
    # same ordering constraint documented in ecland_porting_adapter.py's own module docstring).
    from eclandpy.physics import ecland_porting_adapter as adapter

    physics_run = adapter.build(
        plumber2_root=str(BRIDGE_ROOT / "data"),
        site="LIAISE",
        initial_date=year * 10000 + 101,
        final_date=year * 10000 + 1231,
        group="LIAISE",
        forcing_type="2d",
    )
    driver = physics_run.driver

    from ecland_porting.offline.diag_output import WAT_VARS, EVA_VARS
    from ecland_porting.offline.diag_writer import DiagRecorder
    from ecland_porting.offline.writer import OutputRecorder

    if restart_in is not None:
        with open(restart_in, "rb") as f:
            restore_state(driver, pickle.load(f))

    ndays = 366 if calendar.isleap(year) else 365
    nsteps = ndays * 86400 // int(physics_run.run.tstep)
    if max_steps is not None:
        nsteps = min(nsteps, max_steps)  # --smoke-steps: fast multi-year loop smoke test

    wat_rec = DiagRecorder(physics_run.run, WAT_VARS, nfrpos=1)
    eva_rec = DiagRecorder(physics_run.run, EVA_VARS, nfrpos=1)
    gg_rec = OutputRecorder(physics_run.run, nfrpos=1)

    def on_diag(nstep, diag):
        wat_rec.accumulate(nstep, diag)
        eva_rec.accumulate(nstep, diag)

    driver.run(nsteps, on_step=gg_rec.maybe_record, on_diag=on_diag)

    out_dir.mkdir(parents=True, exist_ok=True)
    wat_path = out_dir / "o_wat.nc"
    eva_path = out_dir / "o_eva.nc"
    gg_path = out_dir / "o_gg.nc"
    wat_rec.write(str(wat_path))
    eva_rec.write(str(eva_path))
    gg_rec.write(str(gg_path))
    for p in (wat_path, eva_path, gg_path):
        _add_latlon(p)

    restart_out.parent.mkdir(parents=True, exist_ok=True)
    with open(restart_out, "wb") as f:
        pickle.dump(snapshot_state(driver), f)
    print(f"{year}: {nsteps} steps done, wrote {out_dir}, restart {restart_out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year-start", type=int, required=True)
    p.add_argument("--year-end", type=int, required=True)
    p.add_argument("--out-root", type=Path, default=BRIDGE_ROOT / "output")
    p.add_argument("--restart-root", type=Path, default=BRIDGE_ROOT / "restart")
    p.add_argument("--smoke-steps", type=int, default=None,
                    help="Truncate every year to this many steps -- fast multi-year loop smoke "
                         "test (e.g. confirming _io_shim.install() idempotency across years) "
                         "without paying the ~32min/year full-year cost. Omit for a real run.")
    args = p.parse_args()

    for year in range(args.year_start, args.year_end + 1):
        restart_in = args.restart_root / f"eclandpy_restart_{year - 1}.pkl"
        restart_out = args.restart_root / f"eclandpy_restart_{year}.pkl"
        run_one_year(
            year,
            restart_in=restart_in if restart_in.exists() else None,
            restart_out=restart_out,
            out_dir=args.out_root / str(year),
            max_steps=args.smoke_steps,
        )


if __name__ == "__main__":
    main()
