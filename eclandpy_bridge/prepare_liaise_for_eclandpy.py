#!/usr/bin/env python3
"""Repackage LIAISE's Fortran-offline-driver ancillary/forcing files into the
single-consolidated-file convention `ecland_porting` (eclandpy's Python/GT4Py
physics core) expects, so eclandpy can run on the LIAISE regional grid --
never attempted before this script: every eclandpy run so far (PLUMBER2 sites,
`ecland_porting`'s own "TE-001" practical) has been a single (lat=1, lon=1)
point. LIAISE is (lat=16, lon=23).

Why a conversion is needed at all
----------------------------------
The real Fortran offline driver (this repo's `run/run_liaise_ecland.sh`) reads
one file per forcing variable (`namelist/input`'s `CFORCT="Tair.nc"` etc.) plus
`init_clim/data/surfclim`/`soilinit`. `ecland_porting.ui_options.UIOptions`
instead expects exactly three consolidated files per `(group, site, iyear,
fyear)`:
    surfclim_<site>_<iyear>-<fyear>.nc
    surfinit_<site>_<iyear>-<fyear>.nc
    met_<forcing_type>HT_<site>_<iyear>-<fyear>.nc
(see `ecland-porting/src/ecland_porting/ui_options.py::__post_init__`). This
is the same convention plumber2-ecland already builds its own PLUMBER2 site
files in -- reused here unmodified, just pointed at LIAISE's own ancillary/
forcing data instead of a single flux-tower record.

`forcing_type="2d"` chosen deliberately, not "insitu": grepping
`ecland_porting/setup/**/*.py` for `forcing_type`/`ftype` shows exactly ONE
branch in the whole setup pipeline (`level3/yomgf1s.py:62`, `if ftype ==
"insitu"`), which only affects two scalar reference-height fields (`ralt`/
`rzuv`) -- for any other forcing_type they default to 10.0, which is exactly
LIAISE's own namelist default (`NAMFORC` `ZPHISTA=ZUV=10.0`). So "2d" (not
"insitu") is both simpler (no zuv/rzuv field needed in surfclim) and the
textbook-correct choice for a gridded, non-flux-tower domain -- matches the
Fortran side's own `NDIMFORC=2`.

Field-by-field mapping (verified against LIAISE's real files + the full
`get_field(...)` call-site list grepped from `ecland_porting/setup/`):
  - surfclim: every field LIAISE's `init_clim/data/surfclim` already has
    matches ecland_porting's own names 1:1 (CLAKE, Ctype, LDEPTH, Malbedo,
    Mask, Mlaih, Mlail, cu, cvh, cvl, fwet, geopot, landsea, lz0h, sdor,
    sotype, sst, tvh, tvl, z0m) -- copied through verbatim, plus LIAISE's own
    extra fields (cell_area, glacierMask, glm, sdfor), harmless since
    ecland_porting looks fields up by name and ignores what it doesn't ask
    for. `r0vt` is genuinely absent from LIAISE's file, but confirmed
    optional: `yomgpd1s.py:277` defaults it to `0.145e-6` when
    `get_field("r0vt")` returns None, and LIAISE's namelist runs
    `LEAGS=.FALSE.` (A-gs off, Farquhar on) so this constant barely matters
    here anyway.
  - surfinit: same story, one real rename needed -- LIAISE spells the
    lake/sea-ice temperature field `iceTemp`, ecland_porting's setup looks
    for lowercase `icetemp` (`get_field("icetemp")`) -- added as an extra
    variable (not a rename, so nothing downstream that might read the
    original name breaks).
  - met_2dHT: LIAISE's consolidated `WFDE5_CRU_GPCC_<year>_ecland.nc` already
    has Tair/Qair/PSurf/Rainf/Snowf/SWdown/LWdown/Wind/lat/lon/time matching
    ecland_porting's names exactly (LIAISE uses scalar `Wind`, matching
    PLUMBER2's own convention, not the split `Wind_E`/`Wind_N` the TE-001
    "era5" fixture uses -- `yomgf1s.py` and friends read whichever fields are
    present). `CO2air` is absent from LIAISE's forcing (the real Fortran run
    gets it from a separate namelist-referenced `CO2air.nc` this script
    doesn't have); synthesized here as a flat constant (369 ppm, a
    reasonable global-mean value for year 2000) since LIAISE's namelist runs
    `LEAIRCO2COUP=.FALSE.` (CO2 forcing doesn't feed back into photosynthesis
    coupling), so this constant has no material effect on the Qs/Qsb runoff
    this bridge is being built to validate.

Not yet validated by running anything -- this script only builds the input
files. See run_eclandpy_liaise.py (this directory) for the actual first run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import netCDF4
import numpy as np

SURFCLIM_SRC = "/perm/pad/liaise-ecland/init_clim/data/surfclim"
SOILINIT_SRC = "/perm/pad/liaise-ecland/init_clim/data/soilinit"
FORCING_SRC_TMPL = "/perm/pad/liaise-ecland/forcing/WFDE5_CRU_GPCC_ecland/WFDE5_CRU_GPCC_{year}_ecland.nc"

CO2AIR_PPM = 369.0


def _copy_all(src: netCDF4.Dataset, dst: netCDF4.Dataset) -> None:
    for name, dim in src.dimensions.items():
        dst.createDimension(name, (len(dim) if not dim.isunlimited() else None))
    for name, var in src.variables.items():
        out = dst.createVariable(name, var.dtype, var.dimensions)
        out.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
        out[:] = var[:]


def build_surfclim(out_path: Path) -> None:
    with netCDF4.Dataset(SURFCLIM_SRC) as src, netCDF4.Dataset(out_path, "w") as dst:
        _copy_all(src, dst)
    print(f"wrote {out_path}")


def build_surfinit(out_path: Path) -> None:
    with netCDF4.Dataset(SOILINIT_SRC) as src, netCDF4.Dataset(out_path, "w") as dst:
        _copy_all(src, dst)
        # ecland_porting looks up lowercase "icetemp"; LIAISE's file spells it "iceTemp".
        # Add it as an extra field (not a rename) so nothing that might read the original
        # capitalisation breaks.
        if "iceTemp" in src.variables and "icetemp" not in dst.variables:
            v = src.variables["iceTemp"]
            out = dst.createVariable("icetemp", v.dtype, v.dimensions)
            out[:] = v[:]
    print(f"wrote {out_path}")


def build_met(out_path: Path, year: int, days: int | None) -> None:
    src_path = FORCING_SRC_TMPL.format(year=year)
    with netCDF4.Dataset(src_path) as src, netCDF4.Dataset(out_path, "w") as dst:
        ntime_full = len(src.dimensions["time"])
        # LIAISE forcing is hourly (ZDTFORC=3600); truncate to the first `days` days for a
        # cheap first attempt, matching this project's established "bounded look first"
        # pattern rather than committing to a full year immediately.
        # +1: interp_forcing linearly interpolates between the record AT ztimcur and the
        # NEXT one, so the last real timestep still needs one more record past it -- same
        # "extra endpoint" convention this repo's own Fortran forcing files use (see
        # README: "an additional endpoint at 00 UTC on 1 January of the following year").
        # Hit this as an off-by-one IndexError on the first real run attempt (i1=121 >
        # nstpfc=120 for a naive `days * 24`), 2026-09-13.
        ntime = min(ntime_full, days * 24 + 1) if days is not None else ntime_full
        for name, dim in src.dimensions.items():
            size = ntime if name == "time" else len(dim)
            dst.createDimension(name, size)
        for name, var in src.variables.items():
            out = dst.createVariable(name, var.dtype, var.dimensions)
            out.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
            if name == "time":
                # ecland_porting's forcing reader (offline/forcing.py) wants time as
                # SECONDS SINCE THE RUN'S OWN INITIAL DATE, starting at 0 (confirmed against
                # a working PLUMBER2 met_insituHT file: "seconds since <site's own start
                # date>", values [0, 1800, 3600, ...]) -- not LIAISE's raw archive-relative
                # "hours since 1988-01-01" axis. Rewrite it rather than copy it verbatim, or
                # `_lerp_indices` computes a nonsense huge index and IndexErrors immediately
                # (hit this on the first real run attempt, 2026-09-13).
                out.units = f"seconds since {year}-01-01 00:00:00"
                out[:] = np.arange(ntime, dtype=var.dtype) * 3600.0  # LIAISE forcing is hourly (ZDTFORC=3600)
            elif "time" in var.dimensions:
                out[:] = var[:ntime]
            else:
                out[:] = var[:]
        # Synthesize CO2air (absent from LIAISE's forcing) as a flat constant -- see module
        # docstring for why this is safe (LEAIRCO2COUP=.FALSE. in LIAISE's namelist).
        lat_n, lon_n = len(src.dimensions["lat"]), len(src.dimensions["lon"])
        co2 = dst.createVariable("CO2air", "f4", ("time", "lat", "lon"))
        co2.units = "ppm"
        co2[:] = np.full((ntime, lat_n, lon_n), CO2AIR_PPM, dtype="f4")
    print(f"wrote {out_path} ({ntime}/{ntime_full} timesteps)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, required=True, help="Year to prepare (matches a WFDE5_CRU_GPCC_<year>_ecland.nc file).")
    p.add_argument("--days", type=int, default=None, help="Truncate forcing to the first N days (omit for the full year).")
    p.add_argument("--out-root", type=Path, default=Path("/perm/pad/liaise-ecland/eclandpy_bridge/data"),
                    help="Root dir; files are written to <out-root>/{forcing,clim}/LIAISE/.")
    p.add_argument("--site", default="LIAISE")
    args = p.parse_args()

    iyear = fyear = args.year
    forcing_dir = args.out_root / "forcing" / "LIAISE"
    clim_dir = args.out_root / "clim" / "LIAISE"
    forcing_dir.mkdir(parents=True, exist_ok=True)
    clim_dir.mkdir(parents=True, exist_ok=True)

    build_surfclim(clim_dir / f"surfclim_{args.site}_{iyear}-{fyear}.nc")
    build_surfinit(clim_dir / f"surfinit_{args.site}_{iyear}-{fyear}.nc")
    build_met(forcing_dir / f"met_2dHT_{args.site}_{iyear}-{fyear}.nc", args.year, args.days)


if __name__ == "__main__":
    main()
