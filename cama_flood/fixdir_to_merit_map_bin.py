#!/usr/bin/env python3
"""Convert a CaMa-Flood FIXDIR bundle (ncdata.nc + rivpar.nc) into the raw
`.bin` MERIT-map directory format `cmfgpu.params.merit_map.MERITMap` reads.

Why this exists
----------------
Every earlier CaMa-Flood-GPU run in this investigation (v4.20, v4.30) was
built from an UPSTREAM CaMa-Flood map package's own `rivwth_gwdlr.bin` --
found (2026-09-12) to be byte-identical between those two package
versions, and NOT the source of ECMWF's Fortran `LECMF1WAY` reference's own
channel width (`static_network_nc_v2.1`'s `rivpar.nc`, built via ECMWF's
own `calc_rivpar.py` pipeline -- see CLAUDE.md's "channel-width vintage"
discussion). To get a genuine apples-to-apples comparison with NO
physiographic-parameter difference at all, CaMa-Flood-GPU needs to be built
from EXACTLY the same source data the Fortran run uses -- the FIXDIR
`build_global_cmf_fixdir.sh` produces from `static_network_nc_v2.1`
directly, not any upstream package's own bundled maps.

`MERITMap`/`make_map_params.py` only reads a raw `.bin` map directory
(`nextxy.bin`, `rivlen.bin`, ... -- see `cmfgpu/params/merit_map.py`), not
FIXDIR's consolidated NetCDF (`ncdata.nc`/`rivpar.nc`). This script bridges
that gap losslessly -- every field it writes comes directly from FIXDIR's
own data, no re-derivation or re-estimation.

Field mapping (verified against the real files, 2026-09-13)
-------------------------------------------------------------
  nextxy.bin       <- ncdata.nc: nextx, nexty (confirmed 1-based, exact
                      match to MERITMap's own convention: verified all
                      229256 non-mouth links resolve to a valid basin cell
                      when interpreted as 1-based, zero mismatches)
  rivlen.bin       <- ncdata.nc: rivlen
  elevtn.bin       <- ncdata.nc: elevtn
  ctmare.bin       <- ncdata.nc: ctmare
  uparea.bin       <- ncdata.nc: uparea
  nxtdst.bin       <- ncdata.nc: nxtdst
  lonlat.bin       <- ncdata.nc: lonp, latp (the "outlet pixel" lon/lat --
                      confirmed this session to be lonlat.bin's actual
                      semantics, a per-catchment representative point, NOT
                      a plain grid-cell-center formula)
  fldhgt.bin       <- ncdata.nc: fldhgt (lev,lat,lon) -> transposed to
                      MERITMap's (nx,ny,lev) convention
  width.bin        <- ncdata.nc: width ("chanel width GWD-LR - satellite")
  rivhgt.bin       <- rivpar.nc: rivhgt
  rivwth_gwdlr.bin <- rivpar.nc: rivwth ("Channel width merged with gwdlr"
                      -- THIS is the field that differed from upstream
                      CaMa-Flood's own rivwth_gwdlr.bin; this script
                      reroutes MERITMap to read the FIXDIR/ECMWF-pipeline
                      version instead)
  mapdim.txt       <- derived from nx/ny/num_flood_levels
  bifori.txt       <- reused AS-IS from the source CMFDIR (gunzipped, not
                      regenerated) -- this is the raw per-path bifurcation
                      table MERITMap's own `bifori_file` reads directly and
                      re-merges itself (bif_levels_to_keep); it is NOT the
                      same format as rivpar.nc's build's own `bifprm.txt`
                      output (Fortran CaMa-Flood's runtime-ready table),
                      which MERITMap does not consume.
  GRDC_alloc.txt   <- reused AS-IS from the source CMFDIR

Not converted: `rivman` (Manning roughness) -- MERITMap has no `rivman.bin`
read path at all (confirmed by reading merit_map.py); it always uses its
own pydantic default (0.03) for `river_manning`, so there is nothing to
route through regardless of what rivpar.nc contains for that field.

Usage
-----
    python3 fixdir_to_merit_map_bin.py \\
        --ncdata work_global/glb_15min/ncdata.nc \\
        --rivpar work_global/glb_15min/rivpar.nc \\
        --source-cmfdir /home/rdx/data/50r1/camaflood/static_network_nc_v2.1/glb_15min \\
        --out-dir /perm/pad/cmf_v21_fixdir_map/glb_15min
"""

from __future__ import annotations

import argparse
import gzip
import shutil
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def _write_fortran_bin(path: Path, arr: np.ndarray, dtype: str) -> None:
    """Write an array so a Fortran-order (`order='F'`) memmap reads it back
    correctly, regardless of the array's own current memory layout."""

    np.asarray(arr, dtype=dtype).flatten(order="F").tofile(path)


def convert(
    ncdata_path: Path,
    rivpar_path: Path,
    source_cmfdir: Path,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with Dataset(ncdata_path, "r") as ds:
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)
        ny, nx = lat.size, lon.size
        n_flood_levels = ds.dimensions["lev"].size

        def var2d(name: str, fill: float = 0.0) -> np.ndarray:
            # netCDF dims are (lat, lon) = (ny, nx); MERITMap wants (nx, ny).
            raw = ds.variables[name][:]
            filled = np.ma.filled(raw, fill).astype(np.float64)
            return filled.T  # -> (nx, ny)

        nextx = np.ma.filled(ds.variables["nextx"][:], -9999).astype(np.int64).T
        nexty = np.ma.filled(ds.variables["nexty"][:], -9999).astype(np.int64).T

        rivlen = var2d("rivlen")
        elevtn = var2d("elevtn")
        ctmare = var2d("ctmare")
        uparea = var2d("uparea")
        nxtdst = var2d("nxtdst")
        lonp = var2d("lonp", fill=-9999.0)
        latp = var2d("latp", fill=-9999.0)
        width = var2d("width")

        fldhgt_raw = np.ma.filled(ds.variables["fldhgt"][:], 0.0).astype(np.float64)
        # (lev, lat, lon) -> (lon, lat, lev) = (nx, ny, lev)
        fldhgt = np.transpose(fldhgt_raw, axes=(2, 1, 0))

    with Dataset(rivpar_path, "r") as ds:
        rp_lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        rp_lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)
        if rp_lat.shape != lat.shape or rp_lon.shape != lon.shape or \
                not np.allclose(rp_lat, lat) or not np.allclose(rp_lon, lon):
            raise ValueError(
                "rivpar.nc's lat/lon grid does not match ncdata.nc's -- "
                "these must come from the same build_global_cmf_fixdir.sh run"
            )
        rivhgt = np.ma.filled(ds.variables["rivhgt"][:], 0.0).astype(np.float64).T
        rivwth = np.ma.filled(ds.variables["rivwth"][:], 0.0).astype(np.float64).T

    print(f"Grid: nx={nx}, ny={ny}, num_flood_levels={n_flood_levels}")

    # --- mapdim.txt ---
    with open(out_dir / "mapdim.txt", "w") as f:
        f.write(f"{nx:10d}    !! nXX\n")
        f.write(f"{ny:10d}    !! nYY\n")
        f.write(f"{n_flood_levels:10d}    !! floodplain layer\n")

    # --- nextxy.bin: (nx, ny, 2) int32, 1-based, -9999 missing, -9/-10 mouths ---
    nextxy = np.empty((nx, ny, 2), dtype=np.int32)
    nextxy[:, :, 0] = nextx
    nextxy[:, :, 1] = nexty
    _write_fortran_bin(out_dir / "nextxy.bin", nextxy, "<i4")

    # --- plain (nx, ny) float32 maps ---
    for name, arr in [
        ("rivlen.bin", rivlen),
        ("elevtn.bin", elevtn),
        ("ctmare.bin", ctmare),
        ("uparea.bin", uparea),
        ("nxtdst.bin", nxtdst),
        ("width.bin", width),
        ("rivhgt.bin", rivhgt),
        ("rivwth_gwdlr.bin", rivwth),
    ]:
        _write_fortran_bin(out_dir / name, arr, "<f4")

    # --- lonlat.bin: (nx, ny, 2) float32 ---
    lonlat = np.empty((nx, ny, 2), dtype=np.float32)
    lonlat[:, :, 0] = lonp
    lonlat[:, :, 1] = latp
    _write_fortran_bin(out_dir / "lonlat.bin", lonlat, "<f4")

    # --- fldhgt.bin: (nx, ny, num_flood_levels) float32 ---
    _write_fortran_bin(out_dir / "fldhgt.bin", fldhgt, "<f4")

    # --- reused as-is from the source CMFDIR ---
    src_bifori_gz = source_cmfdir / "bifori.txt.gz"
    with gzip.open(src_bifori_gz, "rb") as fin, open(out_dir / "bifori.txt", "wb") as fout:
        shutil.copyfileobj(fin, fout)
    print(f"Wrote {out_dir / 'bifori.txt'} (gunzipped from {src_bifori_gz})")

    src_grdc = source_cmfdir / "GRDC_alloc.txt"
    if src_grdc.exists():
        shutil.copy(src_grdc, out_dir / "GRDC_alloc.txt")
        print(f"Copied {out_dir / 'GRDC_alloc.txt'}")

    print(f"Wrote MERIT-map .bin directory: {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ncdata", type=Path, required=True)
    parser.add_argument("--rivpar", type=Path, required=True)
    parser.add_argument("--source-cmfdir", type=Path, required=True,
                         help="Original CMFDIR (e.g. "
                              ".../static_network_nc_v2.1/glb_15min) for "
                              "bifori.txt.gz/GRDC_alloc.txt, reused as-is")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    convert(args.ncdata, args.rivpar, args.source_cmfdir, args.out_dir)


if __name__ == "__main__":
    main()
