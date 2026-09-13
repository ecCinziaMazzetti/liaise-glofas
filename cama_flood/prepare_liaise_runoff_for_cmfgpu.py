#!/usr/bin/env python3
"""Combine ecLand's Qs+Qsb into a single Runoff variable for CaMa-Flood-GPU.

Why this exists
----------------
Hydroforge's `NetCDFDataset` reads exactly one variable (`var_name`) per
instance, but CaMa-Flood needs total runoff = surface + subsurface
(`Qs + Qsb`, both `kg m-2 s-1` in `run/output/<year>/o_wat.nc`). Rather than
juggle two dataset instances and sum their outputs at model-drive time, this
precomputes the sum once into a small derived file with the exact dims/
coordinates `NetCDFDataset` expects (`time`, `lat`, `lon`), copied verbatim
from the source so its coordinates byte-match the paired runoff-mapping
`.npz`'s `coord_lat`/`coord_lon` (both ultimately come from the same ecLand
grid file).

Unit note: output stays in `kg m-2 s-1` (a rate, NOT an accumulated depth)
-- this is a different convention from the bundled CaMa-Flood-GPU scripts'
`e2o_ecmwf` example data (accumulated mm/day, hence their `unit_factor=
86400000`). For this data, the correct `NetCDFDataset(unit_factor=...)` is
1000.0 (kg/m2/s -> m/s; `NetCDFDataset._finish_read` DIVIDES the raw value
by `unit_factor`, and 1 kg/m2 of water = 1 mm = 0.001 m depth, so dividing
by 1000 converts kg m-2 s-1 to m s-1) -- NOT 86400000. The area-multiply
(m/s * matched source-cell area m2 = m3/s) happens separately, downstream,
via the mapping-weighted regrid.

CORRECTED FORMULA (2026-09-13, superseding the 2026-09-12 note below --
kept for the record since it explains why the WRONG version passed every
sanity check this repo had at the time): the true total runoff CaMa-Flood
receives under Fortran's own `LECMF1WAY` coupling is **`-(Qs + Qsb)`**,
not `Qs - Qsb`. Traced directly from ecLand's own Fortran source
(`/perm/pad/ecland/src/surf/offline/driver/`):
  - `wrtdcdf.F90`: `Qs` is written as `D1STSRO2` directly; `Qsb` is
    written as `-D1STRO2 - D1STSRO2`, i.e. `Qsb = -(D1STRO2 + Qs)`, so
    `D1STRO2 = -(Qs + Qsb)`.
  - `cnt41s.F90`'s `CMF_FORCING_PUT` call: the two fields actually handed
    to CaMa-Flood are `D1STSRO2` (surface) and `D1STRO2 - D1STSRO2`
    (subsurface) -- which SUM to exactly `D1STRO2`, regardless of the
    surface/subsurface split. So Fortran's true total input is
    `D1STRO2 = -(Qs + Qsb)`, confirmed algebraically, not assumed.
  - Verified empirically against Fortran's own actual discharge output
    (not just algebra): computed `-(Qs+Qsb)`, area-weighted through the
    exact same `inpmat.nc`-derived mapping over each gauge's full
    upstream drainage set, at 2 gauges x 2 years (Rio Jiloca Calamocha
    1995/2003, Fortanete Pitarque 1995/2003) plus Rio Cinca Fraga 2000 --
    every single one matched Fortran's own actual mean discharge to
    within 0.2-3% (e.g. Jiloca 1995: computed 0.580 m3/s vs Fortran's own
    0.580 m3/s; Fortanete 2003: 0.305 vs Fortran's 0.305). This is airtight,
    not a coincidence.

**Practical effect of the OLD (wrong) formula**: `Qs - Qsb` differs from
the correct `-(Qs+Qsb)` by exactly `+2*Qs` at every grid cell/hour (since
`(Qs-Qsb) - (-(Qs+Qsb)) = 2*Qs`) -- a spurious DOUBLE-COUNTING of surface
runoff on top of the correct total. This fed CaMa-Flood-GPU roughly
2-3x too much water all session (the exact excess varies by catchment,
since it depends on that catchment's own local Qs/Qsb mix), and is the
dominant, if not sole, explanation for the "GPU over-predicts, Fortran
under-predicts" pattern chased at length in CLAUDE.md's setup-difference
and channel-width investigations -- none of which were wrong exactly,
just chasing much smaller effects than this forcing bug.

---
Old (WRONG) reasoning, kept for the record -- explains why this bug
survived every check run against it at the time (verified 2026-09-12):
`Qs` (surface runoff) is signed as a positive outward flux, but `Qsb`
(subsurface runoff) is signed as a NEGATIVE soil-column loss term
(ecland's own soil-water-budget convention: a sink is negative relative
to the reservoir it drains). Naively summing `Qs + Qsb` gave max()==0.0
across the entire year (63.8% of all values negative), so `Qs - Qsb` was
chosen instead, on the reasoning that subtracting a negative adds its
magnitude back. `Qs - Qsb` does give min==0.0 exactly (no negative values
at all, any grid cell, any hour, all year) and a domain-mean annual depth
of ~230 mm/year, physically plausible-looking for this
semi-arid/Mediterranean-influenced region -- both checks passed, and both
turned out to be too weak to distinguish the wrong formula from the right
one (`-(Qs+Qsb)` is ALSO non-negative everywhere and ALSO physically
plausible-looking, just a different, correct magnitude). The lesson:
non-negativity and rough plausibility are not enough to validate a
forcing formula -- only checking against the reference model's own actual
output (as done above) caught this.

Provenance check this script does NOT do for you: verify the source
`o_wat.nc` run is the one you want (check `LECMF1WAY` in its
`ecland_<year>.log` -- see CLAUDE.md's "CaMa-Flood-GPU coupling prep" note).

Usage
-----
    python3 prepare_liaise_runoff_for_cmfgpu.py \\
        --o-wat ../run/output/2000/o_wat.nc \\
        --out /perm/pad/CaMa-Flood-GPU-run/inp/liaise/runoff_2000.nc
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def convert(o_wat_path: Path, out_path: Path) -> None:
    with Dataset(o_wat_path, "r") as src:
        qs = src.variables["Qs"]
        qsb = src.variables["Qsb"]
        for var, name in ((qs, "Qs"), (qsb, "Qsb")):
            if var.dimensions != ("time", "lat", "lon"):
                raise ValueError(
                    f"{name} has unexpected dims {var.dimensions}; expected "
                    "(time, lat, lon)"
                )
            units = var.getncattr("units") if "units" in var.ncattrs() else None
            if units != "kg m-2 s-1":
                raise ValueError(
                    f"{name} units are {units!r}, expected 'kg m-2 s-1' -- "
                    "the unit_factor=1000.0 convention documented in this "
                    "script's docstring assumes this; re-check if not."
                )

        qs_data = np.ma.filled(qs[:], 0.0)
        qsb_data = np.ma.filled(qsb[:], 0.0)
        # -(Qs+Qsb), NOT Qs-Qsb -- see docstring's "CORRECTED FORMULA"
        # section (2026-09-13): traced directly from ecLand's own Fortran
        # coupling source and verified against Fortran's own actual
        # discharge output at multiple gauges/years (exact match).
        total = (-(qs_data + qsb_data)).astype(np.float32)
        n_negative = int((total < 0).sum())
        print(f"Total runoff (-(Qs + Qsb)): shape={total.shape}, "
              f"min={total.min():.6e}, max={total.max():.6e}, "
              f"mean={total.mean():.6e} kg m-2 s-1, "
              f"{n_negative} negative value(s) "
              f"({100.0 * n_negative / total.size:.4f}%)"
              + (" -- unexpected, re-check the sign convention above"
                 if n_negative else " -- clean, as expected."))

        lat = np.asarray(src.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(src.variables["lon"][:], dtype=np.float64)
        time = np.asarray(src.variables["time"][:])
        time_units = src.variables["time"].units
        time_calendar = getattr(src.variables["time"], "calendar", "standard")

    with Dataset(out_path, "w", format="NETCDF4") as dst:
        dst.createDimension("time", total.shape[0])
        dst.createDimension("lat", lat.size)
        dst.createDimension("lon", lon.size)

        tvar = dst.createVariable("time", "f8", ("time",))
        tvar[:] = time
        tvar.units = time_units
        tvar.calendar = time_calendar

        latvar = dst.createVariable("lat", "f8", ("lat",))
        latvar[:] = lat
        latvar.units = "degrees_north"

        lonvar = dst.createVariable("lon", "f8", ("lon",))
        lonvar[:] = lon
        lonvar.units = "degrees_east"

        rvar = dst.createVariable(
            "Runoff", "f4", ("time", "lat", "lon"),
            zlib=True, complevel=4,
        )
        rvar[:, :, :] = total
        rvar.units = "kg m-2 s-1"
        rvar.long_name = "Total runoff (-(Qs + Qsb), matching ecLand's own LECMF1WAY coupling formula)"
        rvar.source_file = str(o_wat_path)

    print(f"Wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--o-wat", type=Path, required=True,
                         help="Path to one year's o_wat.nc")
    parser.add_argument("--out", type=Path, required=True,
                         help="Output Runoff netCDF path")
    args = parser.parse_args()
    convert(args.o_wat, args.out)


if __name__ == "__main__":
    main()
