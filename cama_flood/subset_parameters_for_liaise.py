#!/usr/bin/env python3
"""Subset a global CaMa-Flood-GPU `parameters.nc` down to the LIAISE domain.

Why this exists
----------------
`cmfgpu.data.mapping.table.MappingTable._local()` (in Hydroforge) requires
every catchment loaded into a `CaMaFlood` model to already be present in the
runoff-mapping `.npz`'s `target_ids` -- it hard-errors otherwise. So driving
CaMa-Flood-GPU with LIAISE-region ecLand runoff (`inpmat_to_cmfgpu_npz.py`'s
output) needs the MODEL itself loaded with only the LIAISE catchments, not
the full global network filtered at the mapping layer. This script builds
that regional `parameters.nc` by slicing the global one CaMa-Flood-GPU's own
`MERITMap` produces (`make_map_params.py`), rather than re-deriving it from
raw MERIT/CaMa-Flood map files (which this repo's `cama_flood/data/` isn't
even in the right format for -- see `CLAUDE.md`).

Domain definition
------------------
The kept catchment set is `ncdata.nc`'s own full active-cell footprint
(`ctmare > 0`), recovered as GLOBAL catchment ids via the same grid-cell
inversion `inpmat_to_cmfgpu_npz.py` uses -- NOT just the subset with a
direct ecLand-grid overlap link (`inpmat.nc`'s own ~1026 target cells).
Verified on 2026-09-12: this gives exactly **1405** catchments, matching
`CLAUDE.md`'s own documented figure for this domain ("all 1405 active river
cells produced discharge"), and downstream connectivity closes with **zero
leaks** against the global network (every kept catchment's `downstream_id`
either self-references, a mouth, or points to another kept catchment) --
confirming this is the right, already-validated domain, not an
approximation. The ~379 catchments outside `inpmat.nc`'s own footprint are
real routing-only cells (they fall outside the ecLand grid's exact box but
are still part of the extended domain) -- they correctly receive zero local
runoff forcing, same as they would in the Fortran `LECMF1WAY` run.

What gets simplified (deliberate, for a first regional test)
--------------------------------------------------------------
- `catchment_id`/`downstream_id` keep their ORIGINAL GLOBAL values (verified
  self-closing above -- no renumbering needed, and this is what lets
  `nextxy`-derived indices stay meaningful).
- `catchment_basin_id` is collapsed to a single basin (0) and `basin_sizes`/
  `num_basins` follow -- correct and sufficient for a single-GPU run, where
  `catchment_basin_id` only matters for multi-GPU load-balancing.
- Bifurcation arrays are dropped entirely (`bifurcation_path` dim -> 0):
  this script's paired driver run doesn't open the `bifurcation` module, so
  they're unused; filtering them (path endpoints both inside the subset)
  is real extra work with no payoff for this first pass. Add it back (mirror
  the gauge-filtering logic below) if/when a run opens that module.
- `gauge_*` arrays ARE filtered (kept where `gauge_catchment_id` falls in
  the subset) -- cheap, and useful for comparing simulated discharge against
  real GRDC stations later, even though the model itself never reads them.
- `nx`/`ny` (the GLOBAL grid dims, 1440x720 for glb_15min) are kept
  UNCHANGED -- `catchment_id = ix*ny+iy` depends on them; changing them
  would silently corrupt every id.

Usage
-----
    python3 subset_parameters_for_liaise.py \\
        --parameters /perm/pad/CaMa-Flood-GPU-run/inp/glb_15min/parameters.nc \\
        --ncdata data/ncdata.nc \\
        --out /perm/pad/CaMa-Flood-GPU-run/inp/liaise/parameters_liaise.nc
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def _recover_active_global_ids(
    ncdata_path: Path, *, west: float, north: float, dlon: float, dlat: float,
    global_ny: int, tolerance: float,
) -> np.ndarray:
    with Dataset(ncdata_path, "r") as ds:
        ctmare = np.asarray(ds.variables["ctmare"][:].filled(0.0))
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)

    ix = np.round((lon - west) / dlon - 0.5).astype(np.int64)
    iy = np.round((north - lat) / dlat - 0.5).astype(np.int64)
    recon_lon = west + dlon * (ix + 0.5)
    recon_lat = north - dlat * (iy + 0.5)
    if np.abs(recon_lon - lon).max() > tolerance or np.abs(recon_lat - lat).max() > tolerance:
        raise ValueError(
            "ncdata.nc coordinates do not align to the assumed global grid "
            f"(west={west}, north={north}, dlon={dlon}, dlat={dlat}); check "
            "--global-* flags against the parameters.nc's own nx/ny/origin."
        )

    ix_grid, iy_grid = np.meshgrid(ix, iy)
    cid_grid = ix_grid * global_ny + iy_grid
    return np.unique(cid_grid[ctmare > 0].astype(np.int64))


def _check_closure(
    keep_ids: np.ndarray, catchment_id: np.ndarray, downstream_id: np.ndarray,
) -> None:
    id_to_idx = {int(c): i for i, c in enumerate(catchment_id)}
    keep_set = set(int(c) for c in keep_ids)
    missing = [c for c in keep_set if c not in id_to_idx]
    if missing:
        raise ValueError(
            f"{len(missing)} catchment id(s) from ncdata.nc are not present "
            f"in the global parameters.nc; examples={missing[:5]}. The "
            "global grid assumptions (--global-nx/ny/west/north/dlon/dlat) "
            "likely don't match this parameters.nc -- check its nx/ny."
        )
    leaks = []
    for c in keep_set:
        d = int(downstream_id[id_to_idx[c]])
        if d != c and d not in keep_set:
            leaks.append((c, d))
    if leaks:
        raise ValueError(
            f"{len(leaks)} catchment(s) flow downstream out of the kept "
            f"domain (not a self-referencing mouth): {leaks[:10]}. The "
            "domain isn't self-contained -- either extend the kept set to "
            "include those downstream targets (recursively), or this "
            "isn't a safe subset to run standalone."
        )


# Per-variable handling for the global parameters.nc's known schema
# (cmfgpu.params.merit_map.MERITMap's own output convention).
_CATCHMENT_DIM_VARS = [
    "catchment_x", "catchment_y", "catchment_mainstem_basin_id",
    "upstream_area", "river_mouth_id", "catchment_id", "downstream_id",
    "river_length", "catchment_elevation", "catchment_area",
    "downstream_distance", "longitude", "latitude", "satellite_width",
    "river_width", "river_height", "river_storage", "river_depth",
]
_CATCHMENT_FLOODLEVEL_VARS = ["flood_depth_table"]
_GAUGE_DIM_VARS = [
    "gauge_catchment_id", "gauge_station_id", "gauge_reported_area_km2",
    "gauge_allocated_area_km2", "gauge_alloc_error",
]
_SCALAR_PASSTHROUGH = ["nx", "ny"]


def subset(
    parameters_path: Path,
    ncdata_path: Path,
    out_path: Path,
    *,
    global_nx: int,
    global_ny: int,
    west: float,
    north: float,
    dlon: float,
    dlat: float,
    tolerance: float,
) -> None:
    src = Dataset(parameters_path, "r")
    try:
        src_nx = int(src.variables["nx"][...])
        src_ny = int(src.variables["ny"][...])
        if src_nx != global_nx or src_ny != global_ny:
            raise ValueError(
                f"parameters.nc's own nx/ny ({src_nx}x{src_ny}) does not "
                f"match --global-nx/--global-ny ({global_nx}x{global_ny})"
            )

        keep_ids = _recover_active_global_ids(
            ncdata_path, west=west, north=north, dlon=dlon, dlat=dlat,
            global_ny=global_ny, tolerance=tolerance,
        )
        print(f"ncdata.nc active-cell domain: {keep_ids.size} catchments")

        catchment_id = np.asarray(src.variables["catchment_id"][:], dtype=np.int64)
        downstream_id = np.asarray(src.variables["downstream_id"][:], dtype=np.int64)
        _check_closure(keep_ids, catchment_id, downstream_id)
        print("Downstream connectivity closes within the domain (0 leaks).")

        id_to_idx = {int(c): i for i, c in enumerate(catchment_id)}
        keep_idx = np.array(
            sorted(id_to_idx[int(c)] for c in keep_ids), dtype=np.int64,
        )
        n_keep = keep_idx.size

        gauge_cid = np.asarray(src.variables["gauge_catchment_id"][:], dtype=np.int64)
        keep_set = set(int(c) for c in keep_ids)
        gauge_keep_idx = np.array(
            [i for i, c in enumerate(gauge_cid) if int(c) in keep_set],
            dtype=np.int64,
        )
        print(f"Gauges within domain: {gauge_keep_idx.size} "
              f"(of {gauge_cid.size} global)")

        with Dataset(out_path, "w", format="NETCDF4") as dst:
            dst.createDimension("catchment", n_keep)
            dst.createDimension("basin", 1)
            dst.createDimension("flood_level", src.dimensions["flood_level"].size)
            dst.createDimension("bifurcation_path", 0)
            dst.createDimension("bifurcation_level", src.dimensions["bifurcation_level"].size)
            dst.createDimension("gauge", gauge_keep_idx.size)
            dst.createDimension("saved_points", n_keep)

            for name in _SCALAR_PASSTHROUGH:
                var = dst.createVariable(name, src.variables[name].dtype, ())
                var[...] = src.variables[name][...]

            num_basins = dst.createVariable("num_basins", "i8", ())
            num_basins[...] = 1

            for name in _CATCHMENT_DIM_VARS:
                srcvar = src.variables[name]
                dvar = dst.createVariable(name, srcvar.dtype, ("catchment",))
                dvar[:] = np.asarray(srcvar[:])[keep_idx]
                for attr in srcvar.ncattrs():
                    dvar.setncattr(attr, srcvar.getncattr(attr))

            for name in _CATCHMENT_FLOODLEVEL_VARS:
                srcvar = src.variables[name]
                dvar = dst.createVariable(
                    name, srcvar.dtype, ("catchment", "flood_level"),
                )
                dvar[:, :] = np.asarray(srcvar[:])[keep_idx, :]
                for attr in srcvar.ncattrs():
                    dvar.setncattr(attr, srcvar.getncattr(attr))

            basin_sizes = dst.createVariable("basin_sizes", "i8", ("basin",))
            basin_sizes[:] = np.array([n_keep], dtype=np.int64)

            catchment_basin_id = dst.createVariable(
                "catchment_basin_id", "i8", ("catchment",),
            )
            catchment_basin_id[:] = np.zeros(n_keep, dtype=np.int64)

            output_catchment_id = dst.createVariable(
                "output_catchment_id", "i8", ("saved_points",),
            )
            output_catchment_id[:] = catchment_id[keep_idx]

            for name in _GAUGE_DIM_VARS:
                srcvar = src.variables[name]
                dvar = dst.createVariable(name, srcvar.dtype, ("gauge",))
                dvar[:] = np.asarray(srcvar[:])[gauge_keep_idx]
                for attr in srcvar.ncattrs():
                    dvar.setncattr(attr, srcvar.getncattr(attr))

            for name in [
                "bifurcation_catchment_x", "bifurcation_downstream_x",
                "bifurcation_catchment_y", "bifurcation_downstream_y",
                "bifurcation_path_id", "bifurcation_catchment_id",
                "bifurcation_downstream_id", "bifurcation_manning",
                "bifurcation_width", "bifurcation_length",
                "bifurcation_elevation",
            ]:
                if name not in src.variables:
                    continue
                srcvar = src.variables[name]
                dims = tuple(
                    "bifurcation_path" if d == "bifurcation_path" else d
                    for d in srcvar.dimensions
                )
                dst.createVariable(name, srcvar.dtype, dims)

        print(f"Wrote {out_path}: {n_keep} catchments, 1 basin, "
              f"{gauge_keep_idx.size} gauges, 0 bifurcation paths")
    finally:
        src.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path, required=True,
                         help="Global CaMa-Flood-GPU parameters.nc")
    parser.add_argument("--ncdata", type=Path, required=True,
                         help="LIAISE cama_flood/data/ncdata.nc (defines the "
                              "kept domain via ctmare > 0)")
    parser.add_argument("--out", type=Path, required=True,
                         help="Output regional parameters.nc path")
    parser.add_argument("--global-nx", type=int, default=1440)
    parser.add_argument("--global-ny", type=int, default=720)
    parser.add_argument("--west", type=float, default=-180.0)
    parser.add_argument("--north", type=float, default=90.0)
    parser.add_argument("--dlon", type=float, default=0.25)
    parser.add_argument("--dlat", type=float, default=0.25)
    parser.add_argument("--tolerance", type=float, default=1e-3)
    args = parser.parse_args()

    subset(
        args.parameters, args.ncdata, args.out,
        global_nx=args.global_nx, global_ny=args.global_ny,
        west=args.west, north=args.north, dlon=args.dlon, dlat=args.dlat,
        tolerance=args.tolerance,
    )


if __name__ == "__main__":
    main()
