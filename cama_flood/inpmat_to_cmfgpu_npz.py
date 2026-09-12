#!/usr/bin/env python3
"""Convert a CaMa-Flood `inpmat.nc` interpolation-weights file into the
runoff-mapping `.npz` format CaMa-Flood-GPU's Hydroforge dataset classes
consume directly (`DailyBinDataset`/`NetCDFDataset`.build_local_mapping()).

Why this exists
----------------
`derive_cmf_weights.sh` (this directory) already computes the ecLand-grid ->
CaMa-Flood-river-network interpolation weights for the LIAISE domain, via
ECMWF's own `gen_inpmat.py` (see that script's header for how `inpmat.nc` is
built and what `inpa`/`inpx`/`inpy`/`nlev` mean). CaMa-Flood-GPU is a
from-scratch reimplementation with its own runoff-mapping format -- a CSR
sparse matrix stored as a flat `.npz` (schema `hydroforge.spatial_mapping.v2`,
produced normally by `DailyBinDataset.generate_mapping_table()` from a raw
1-arcmin catchment map). Rather than redo that expensive hi-res aggregation,
this script losslessly re-encodes the *already validated* `inpmat.nc` weights
into that same `.npz` shape, so CaMa-Flood-GPU can be driven with the exact
interpolation this repo's Fortran/LECMF1WAY coupling path uses.

Conventions this script relies on (verified against a real LIAISE
inpmat.nc + a full glb_15min CaMa-Flood-GPU map/ package on 2026-09-12):

  * `inpmat.nc`'s `(lat, lon)` dims are the CaMa-Flood river-network TARGET
    grid, clipped from the global CaMa-Flood grid (e.g. glb_15min: 1440x720,
    0.25 deg, west edge -180, north edge 90). `inpx`/`inpy` at each
    (lat,lon,lev) give the SOURCE-grid (e.g. ecLand) cell that link covers,
    as **1-based** indices into `(latin, lonin)`; `inpa` is that link's
    overlap area in m2 (already area-corrected upstream by gen_inpmat.py's
    `fix_area()`, so per-target-cell sums reproduce the river network's own
    catchment area). `nlev` is the valid-link count per target cell; unused
    (lev, lat, lon) slots are filled with `_FillValue` (-9999 / -9999.0).

  * CaMa-Flood-GPU's `catchment_id` is `ix_global * global_ny + iy_global`
    on that same global grid (`cmfgpu.params.merit_map.MERITMap`,
    `np.ravel_multi_index((catchment_x, catchment_y), (nx, ny))`). Since
    `inpmat.nc`'s `lat`/`lon` are literal regular-grid cell-center degree
    values on that identical lattice (not a per-catchment representative
    point -- that's `lonlat.bin`'s job, which is NOT used here), each
    target cell's global (ix, iy) is recovered by inverting the grid
    formula and verifying the round trip, rather than depending on
    `derive_cmf_weights.sh`'s ephemeral `work/clip_cama_ix0_iy0.txt` offset
    file (which isn't a committed artifact and needn't be regenerated).

  * The output `.npz`'s `coord_lon`/`coord_lat` describe the SOURCE grid
    (`lonin`/`latin` -- for the LIAISE case, this is ecLand's own 0.5 deg
    grid), matching what a real Hydroforge-generated mapping table stores;
    `matrix_shape[1]` is that source grid's full flattened size
    (`len(latin) * len(lonin)`), not just the cells actually referenced.

  * When `--ncdata` is given, `target_ids` is extended (with all-zero rows)
    to cover ncdata.nc's FULL `ctmare > 0` domain, not just the cells
    `inpmat.nc` itself links (`nlev > 0`). Found this the hard way running
    CaMa-Flood-GPU on the LIAISE domain (2026-09-12): Hydroforge's
    `MappingTable._local()` hard-errors if a loaded model's catchment set
    isn't a subset of the mapping's `target_ids`, and a real regional
    domain (`subset_parameters_for_liaise.py`'s "extend crossing basins"
    footprint) includes routing-only cells with no ecLand-grid overlap --
    379 of LIAISE's 1405 active cells, verified. Those get an all-zero row
    (zero local runoff), which is physically correct, not a workaround.

Usage
-----
    python3 inpmat_to_cmfgpu_npz.py \\
        --inpmat data/inpmat.nc \\
        --out runoff_mapping_liaise.npz \\
        --out-inverse runoff_mapping_liaise_inverse.npz

`--out-inverse` additionally writes the catchment -> source-grid inverse
mapping, in preparation for 2-way coupling (e.g. scattering flooded
fraction/area back onto the land-surface grid). This is NOT read from
`inpmat.nc`'s own `inpaI/inpxI/inpyI` fields -- those are dummy-filled here
since `derive_cmf_weights.sh` defaults to `COMPUTE_INV=false` (1-way
coupling only). Instead it's derived directly from the forward mapping this
script already computes, by the same transpose `gen_inpmat.py`'s own real
`-cinv` path would apply (see `_write_inverse`'s docstring) -- so it's
exact, not an approximation, and needs no extra CMFDIR/FIXDIR/1-arcmin data.

Override the global grid only if targeting a different CaMa-Flood
resolution than glb_15min (0.25 deg, -180/90 origin) -- see `--global-nx`
etc. below, and cross-check `mapdim.txt`/`diminfo*.txt` in the CaMa-Flood-GPU
map package you're pairing this with.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from scipy import sparse


def _invert_grid_index(
    values: np.ndarray,
    *,
    origin: float,
    cell_size: float,
    increasing: bool,
    tolerance: float,
    label: str,
) -> np.ndarray:
    """Recover integer grid indices from regular-grid cell-center coordinates.

    ``increasing=True``: value = origin + cell_size * (index + 0.5)  (e.g. lon,
    origin = west edge). ``increasing=False``: value = origin - cell_size *
    (index + 0.5)  (e.g. lat, origin = north edge). Raises if any input value
    isn't within ``tolerance`` degrees of its nearest cell center, since that
    would mean the assumed global-grid parameters (edges/resolution) don't
    actually match the grid `inpmat.nc` was built on.
    """

    if increasing:
        raw_index = (values - origin) / cell_size - 0.5
    else:
        raw_index = (origin - values) / cell_size - 0.5
    index = np.round(raw_index).astype(np.int64)

    if increasing:
        reconstructed = origin + cell_size * (index + 0.5)
    else:
        reconstructed = origin - cell_size * (index + 0.5)
    residual = np.abs(reconstructed - values)
    bad = residual > tolerance
    if np.any(bad):
        bad_i = np.nonzero(bad)[0][:5]
        raise ValueError(
            f"{label}: {int(bad.sum())} coordinate(s) do not align to the "
            f"assumed global grid (origin={origin}, cell_size={cell_size}); "
            f"largest residual sample(s) (value, nearest-index, "
            f"reconstructed): "
            + ", ".join(
                f"({values[i]:.6f}, {index[i]}, {reconstructed[i]:.6f})"
                for i in bad_i
            )
            + ". Check --global-nx/--global-ny/--west/--north/--dlon/--dlat "
            "against the CaMa-Flood map package's mapdim.txt/diminfo*.txt."
        )
    return index


def _recover_ncdata_active_ids(
    ncdata_path: Path,
    *,
    global_ny: int,
    west: float,
    north: float,
    dlon: float,
    dlat: float,
    tolerance: float,
) -> np.ndarray:
    """Recover global catchment ids for every ncdata.nc cell with ctmare > 0."""

    with Dataset(ncdata_path, "r") as ds:
        ctmare = np.asarray(ds.variables["ctmare"][:].filled(0.0))
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)

    ix = _invert_grid_index(
        lon, origin=west, cell_size=dlon, increasing=True,
        tolerance=tolerance, label="ncdata.nc lon",
    )
    iy = _invert_grid_index(
        lat, origin=north, cell_size=dlat, increasing=False,
        tolerance=tolerance, label="ncdata.nc lat",
    )
    ix_grid, iy_grid = np.meshgrid(ix, iy)
    cid_grid = ix_grid * global_ny + iy_grid
    return np.unique(cid_grid[ctmare > 0].astype(np.int64))


def _extend_to_full_ncdata_domain(
    csr: sparse.csr_matrix,
    target_ids: np.ndarray,
    ncdata_path: Path,
    *,
    global_nx: int,
    global_ny: int,
    west: float,
    north: float,
    dlon: float,
    dlat: float,
    tolerance: float,
) -> tuple[sparse.csr_matrix, np.ndarray, int]:
    """Add zero-weight rows for ncdata.nc cells with no direct grid overlap.

    `inpmat.nc` only records a link for target cells `gen_inpmat.py` found
    at least one source-grid overlap for (`nlev > 0`). But CaMa-Flood-GPU
    needs every catchment it will ever load (e.g. via
    `subset_parameters_for_liaise.py`, which keeps ncdata.nc's FULL
    `ctmare > 0` domain -- see that script's docstring for why: extended
    "crossing basin" domains include real routing-only cells with no ecLand
    overlap) to be present in `MappingTable.target_ids`, or
    `MappingTable._local()` raises. Those cells legitimately get zero local
    runoff -- an all-zero row is the correct representation, not a
    workaround.
    """

    active_ids = _recover_ncdata_active_ids(
        ncdata_path, global_ny=global_ny, west=west, north=north,
        dlon=dlon, dlat=dlat, tolerance=tolerance,
    )
    existing = set(int(x) for x in target_ids)
    missing = np.array(
        sorted(int(x) for x in active_ids if int(x) not in existing),
        dtype=np.int64,
    )
    if missing.size == 0:
        return csr, target_ids, 0

    extra_rows = sparse.csr_matrix(
        (missing.size, csr.shape[1]), dtype=csr.dtype,
    )
    combined_ids = np.concatenate([target_ids, missing])
    combined_csr = sparse.vstack([csr, extra_rows]).tocsr()
    order = np.argsort(combined_ids)
    return combined_csr[order], combined_ids[order], int(missing.size)


def convert(
    inpmat_path: Path,
    out_path: Path,
    *,
    global_nx: int,
    global_ny: int,
    west: float,
    north: float,
    dlon: float,
    dlat: float,
    tolerance: float,
    ncdata_path: Path | None,
    out_inverse_path: Path | None,
) -> None:
    with Dataset(inpmat_path, "r") as ds:
        target_lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        target_lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)
        source_lat = np.asarray(ds.variables["latin"][:], dtype=np.float64)
        source_lon = np.asarray(ds.variables["lonin"][:], dtype=np.float64)

        inpa = ds.variables["inpa"][:]  # (lev, lat, lon), masked
        inpx = ds.variables["inpx"][:]  # 1-based source lon index
        inpy = ds.variables["inpy"][:]  # 1-based source lat index
        nlev = np.asarray(ds.variables["nlev"][:].filled(0), dtype=np.int64)

    n_target_lat, n_target_lon = target_lat.size, target_lon.size
    n_source_lat, n_source_lon = source_lat.size, source_lon.size
    n_lev = inpa.shape[0]

    print(f"inpmat.nc: target grid {n_target_lat}x{n_target_lon} (lat,lon), "
          f"source grid {n_source_lat}x{n_source_lon} (lat,lon), "
          f"up to {n_lev} links/cell")

    global_ix = _invert_grid_index(
        target_lon, origin=west, cell_size=dlon, increasing=True,
        tolerance=tolerance, label="target lon",
    )
    global_iy = _invert_grid_index(
        target_lat, origin=north, cell_size=dlat, increasing=False,
        tolerance=tolerance, label="target lat",
    )
    ix_out_of_bounds = (global_ix < 0) | (global_ix >= global_nx)
    iy_out_of_bounds = (global_iy < 0) | (global_iy >= global_ny)
    if np.any(ix_out_of_bounds) or np.any(iy_out_of_bounds):
        raise ValueError(
            f"{int(ix_out_of_bounds.sum())} target lon / "
            f"{int(iy_out_of_bounds.sum())} target lat coordinate(s) fall "
            f"outside the assumed global grid ({global_nx}x{global_ny}); "
            "check --global-nx/--global-ny."
        )

    # Fill values: -9999 (int) for inpx/inpy, -9999.0 (float) for inpa --
    # gen_inpmat.py's gen_output() fills unused (lev, lat, lon) slots with
    # `zmiss` regardless of nlev, so masking on inpa/inpx validity alone
    # (rather than trusting nlev's count) is the direct, self-checking way
    # to find real links; zero-area links are dropped too since they don't
    # contribute to the interpolation.
    inpa_filled = inpa.filled(0.0).astype(np.float64)
    valid = (~np.ma.getmaskarray(inpa)) & (inpa_filled > 0.0)
    inpx_filled = np.ma.filled(inpx, -9999)
    inpy_filled = np.ma.filled(inpy, -9999)
    valid &= (inpx_filled >= 1) & (inpx_filled <= n_source_lon)
    valid &= (inpy_filled >= 1) & (inpy_filled <= n_source_lat)

    lev_idx, lat_idx, lon_idx = np.nonzero(valid)
    n_links = lev_idx.size
    print(f"Found {n_links} valid (target, source) links across "
          f"{np.count_nonzero(nlev > 0)} target cells")

    target_catchment_id = global_ix[lon_idx] * global_ny + global_iy[lat_idx]
    source_ix0 = inpx_filled[lev_idx, lat_idx, lon_idx].astype(np.int64) - 1
    source_iy0 = inpy_filled[lev_idx, lat_idx, lon_idx].astype(np.int64) - 1
    source_flat = source_iy0 * n_source_lon + source_ix0  # C order, lat-major
    weights = inpa_filled[lev_idx, lat_idx, lon_idx]

    target_ids, row_of_link = np.unique(target_catchment_id, return_inverse=True)
    n_targets = target_ids.size

    coo = sparse.coo_matrix(
        (weights, (row_of_link, source_flat)),
        shape=(n_targets, n_source_lat * n_source_lon),
        dtype=np.float64,
    )
    csr = coo.tocsr()
    csr.sum_duplicates()

    n_zero_overlap_added = 0
    if ncdata_path is not None:
        csr, target_ids, n_zero_overlap_added = _extend_to_full_ncdata_domain(
            csr, target_ids, ncdata_path,
            global_nx=global_nx, global_ny=global_ny,
            west=west, north=north, dlon=dlon, dlat=dlat,
            tolerance=tolerance,
        )
        n_targets = target_ids.size

    coverage = np.asarray(csr.sum(axis=1)).ravel().astype(np.float32)

    metadata = {
        "schema": "hydroforge.spatial_mapping.v2",
        "producer": "inpmat_to_cmfgpu_npz.convert",
        "method": "cama_flood_inpmat",
        "overlap_engine": "gen_inpmat.py (ECMWF osm_pyutils, 1-arcmin catchment aggregation)",
        "normalization": "sum",
        "target_kind": "catchment",
        "source_is_geographic": True,
        "source_order": "C",
        "source_shape": [int(n_source_lat), int(n_source_lon)],
        "source_x_name": "lon",
        "source_y_name": "lat",
        "source_inpmat_file": str(inpmat_path),
        "global_grid": {
            "nx": global_nx, "ny": global_ny,
            "west": west, "north": north, "dlon": dlon, "dlat": dlat,
        },
    }

    np.savez_compressed(
        out_path,
        target_ids=target_ids.astype(np.int64),
        sparse_data=csr.data.astype(np.float32),
        sparse_indices=csr.indices.astype(np.int64),
        sparse_indptr=csr.indptr.astype(np.int64),
        matrix_shape=np.array(csr.shape, dtype=np.int64),
        coord_lon=source_lon.astype(np.float64),
        coord_lat=source_lat.astype(np.float64),
        coverage=coverage,
        metadata_json=json.dumps(metadata),
    )
    extra_note = (
        f" (+{n_zero_overlap_added} zero-overlap ncdata.nc cells added)"
        if n_zero_overlap_added else ""
    )
    print(f"Wrote {out_path} ({n_targets} target catchments{extra_note}, "
          f"{csr.nnz} links, matrix_shape={csr.shape})")

    if ncdata_path is not None:
        _print_area_diagnostics(
            ncdata_path, target_ids, coverage,
            global_ny=global_ny,
            west=west, north=north, dlon=dlon, dlat=dlat,
            tolerance=tolerance,
        )

    if out_inverse_path is not None:
        _write_inverse(
            csr, target_ids, source_lat, source_lon,
            n_source_lat=n_source_lat, n_source_lon=n_source_lon,
            inpmat_path=inpmat_path, forward_out_path=out_path,
            out_path=out_inverse_path,
        )


def _write_inverse(
    forward_csr: sparse.csr_matrix,
    target_ids: np.ndarray,
    source_lat: np.ndarray,
    source_lon: np.ndarray,
    *,
    n_source_lat: int,
    n_source_lon: int,
    inpmat_path: Path,
    forward_out_path: Path,
    out_path: Path,
) -> None:
    """Write the target-catchment -> source-grid inverse mapping.

    This is NOT an independent re-aggregation from 1-arcmin data (that would
    need CMFDIR's 1min.catmxy.nc/1min.grdare.nc, which this converter never
    touches). It's the exact transpose of the forward link table instead --
    confirmed by reading `gen_inpmatI_reg` in ECMWF's own
    `cython_ext.pyx` (the function `gen_inpmat.py`'s real `-cinv` path calls):
    it takes ONLY the forward (inpn, inpx, inpy, inpa) arrays as input and,
    for each forward link (target cell -> source cell, area `inpa`), appends
    the same area to the reverse list at (source cell -> target cell),
    summing areas when a source/target pair repeats. That is precisely a
    sparse-matrix transpose with duplicate-summing, so this function
    reproduces what `derive_cmf_weights.sh COMPUTE_INV=true` would have
    written into `inpmat.nc`'s `inpaI/inpxI/inpyI` (currently dummy-filled
    here, since this repo defaults to `COMPUTE_INV=false` / 1-way coupling),
    without needing that heavier toolchain.

    No schema for this direction exists yet in Hydroforge/CaMa-Flood-GPU
    (grep of the whole cmfgpu source at 2026-09-12 found no inverse/2-way
    mapping consumer) -- so this defines a new, explicit one rather than
    guessing at an established convention. `target_ids` here is the SAME
    array, in the SAME order, as the paired forward `.npz`'s `target_ids`,
    so matrix columns line up 1:1 with the forward matrix's rows.

    Caveat -- `coverage` (summed linked catchment area per source cell) can
    exceed that source cell's own true physical area, sometimes by a large
    margin. This is inherited from the forward map's `fix_area()` step
    (in `gen_inpmat.py`), which rescales each TARGET catchment's linked
    area independently so its row-sum matches CaMa-Flood's own `ctmare`
    (verified earlier as an exact match) -- a correction for a real
    discretization mismatch between the 1-arcmin catchment delineation and
    the coarse river-network's own declared area. That per-target rescaling
    isn't constrained to keep any shared SOURCE cell's total at or below its
    physical area, so summing rescaled links back onto one source cell can
    overshoot it. This is not an artifact of the transpose: the same
    over-100% coverage would appear in `-cinv`'s own real output too, since
    it transposes these same post-`fix_area()` arrays. A consumer computing
    an area-weighted mean per source cell should treat `coverage` as "total
    area attributed by the (corrected) river-network parameterization," not
    as a literal sub-cell area partition.
    """

    inverse_csr = forward_csr.transpose().tocsr()
    inverse_csr.sum_duplicates()

    coverage = np.asarray(inverse_csr.sum(axis=1)).ravel().astype(np.float32)

    metadata = {
        "schema": "cmfgpu_liaise.spatial_mapping.inverse.v1",
        "producer": "inpmat_to_cmfgpu_npz._write_inverse",
        "method": "transpose_of_forward_inpmat",
        "note": (
            "Exact transpose (with duplicate-summing) of the paired forward "
            "mapping, matching what gen_inpmat.py's gen_inpmatI_reg (real "
            "-cinv path) computes from the same forward link table -- not an "
            "independent 1-arcmin re-aggregation."
        ),
        "normalization": "sum",
        "row_kind": "source_grid_cell",
        "column_kind": "catchment",
        "row_order": "C",
        "row_shape": [int(n_source_lat), int(n_source_lon)],
        "row_x_name": "lon",
        "row_y_name": "lat",
        "source_inpmat_file": str(inpmat_path),
        "forward_mapping_file": str(forward_out_path),
        "coverage_caveat": (
            "coverage[j] can exceed source cell j's true physical area -- "
            "inherited from the forward map's per-target fix_area() "
            "rescaling to match ctmare, not a partition of the cell's area. "
            "See _write_inverse's docstring."
        ),
        "usage": (
            "To scatter a per-catchment quantity onto the source grid: "
            "grid_flat = inverse_matrix @ catchment_values[target_ids order]. "
            "This yields an area-weighted SUM per source cell (units: "
            "quantity * m2, if catchment_values is a plain quantity) -- "
            "divide by `coverage` for an area-weighted MEAN over the linked "
            "area, or by the source cell's own full area for a mean over "
            "the whole grid cell (coverage <= full cell area in general)."
        ),
    }

    np.savez_compressed(
        out_path,
        target_ids=target_ids.astype(np.int64),
        sparse_data=inverse_csr.data.astype(np.float32),
        sparse_indices=inverse_csr.indices.astype(np.int64),
        sparse_indptr=inverse_csr.indptr.astype(np.int64),
        matrix_shape=np.array(inverse_csr.shape, dtype=np.int64),
        coord_lon=source_lon.astype(np.float64),
        coord_lat=source_lat.astype(np.float64),
        coverage=coverage,
        metadata_json=json.dumps(metadata),
    )
    print(f"Wrote {out_path} (inverse: {inverse_csr.shape[0]} source cells, "
          f"{inverse_csr.nnz} links, matrix_shape={inverse_csr.shape})")


def _print_area_diagnostics(
    ncdata_path: Path,
    target_ids: np.ndarray,
    coverage: np.ndarray,
    *,
    global_ny: int,
    west: float,
    north: float,
    dlon: float,
    dlat: float,
    tolerance: float,
) -> None:
    """Optional cross-check against ncdata.nc's own catchment area (ctmare).

    Reuses the SAME global-grid origin/resolution as the main conversion --
    ncdata.nc's (lat, lon) dims are a regional clip of the identical global
    lattice inpmat.nc's target grid sits on (both come from the same
    derive_cmf_weights.sh run), so re-deriving a separate "local" origin
    from ncdata.nc's own first coordinate would silently produce different,
    wrong global indices instead of a genuine independent cross-check.
    """

    with Dataset(ncdata_path, "r") as ds:
        if "ctmare" not in ds.variables:
            print(f"(skipping area diagnostics: no 'ctmare' in {ncdata_path})")
            return
        ctmare = np.asarray(ds.variables["ctmare"][:].filled(0.0))
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)

    # ncdata.nc uses the same clipped (lat, lon) grid as inpmat.nc's target
    # dims; ctmare's shape is (lat, lon) in m2 already.
    ny_local, nx_local = ctmare.shape
    if lat.size != ny_local or lon.size != nx_local:
        print("(skipping area diagnostics: unexpected ctmare shape)")
        return

    global_ix = _invert_grid_index(
        lon, origin=west, cell_size=dlon, increasing=True,
        tolerance=tolerance, label="ncdata.nc lon",
    )
    global_iy = _invert_grid_index(
        lat, origin=north, cell_size=dlat, increasing=False,
        tolerance=tolerance, label="ncdata.nc lat",
    )
    ix_grid, iy_grid = np.meshgrid(global_ix, global_iy)
    catchment_id_grid = ix_grid * global_ny + iy_grid

    id_to_ctmare = dict(zip(catchment_id_grid.ravel(), ctmare.ravel()))
    ref_area = np.array(
        [id_to_ctmare.get(cid, np.nan) for cid in target_ids]
    )
    has_ref = np.isfinite(ref_area) & (ref_area > 0)
    if not np.any(has_ref):
        print("(area diagnostics: no matching ctmare entries found)")
        return
    # Rows with zero coverage but real ctmare are legitimate zero-overlap
    # cells added by _extend_to_full_ncdata_domain (real catchments, just no
    # direct ecLand-grid link) -- report them separately rather than let
    # them show up as a spurious -100% "difference" in the area cross-check.
    zero_overlap = has_ref & (coverage == 0)
    checkable = has_ref & (coverage > 0)
    if np.any(checkable):
        pct_diff = (
            100.0 * (coverage[checkable] - ref_area[checkable])
            / ref_area[checkable]
        )
        print(
            "Area cross-check vs ncdata.nc ctmare "
            f"({int(checkable.sum())}/{target_ids.size} catchments with "
            "direct overlap matched): "
            f"mean diff {pct_diff.mean():+.3f}%, "
            f"|diff| p95 {np.percentile(np.abs(pct_diff), 95):.3f}%, "
            f"max |diff| {np.abs(pct_diff).max():.3f}%"
        )
    if np.any(zero_overlap):
        print(
            f"({int(zero_overlap.sum())} additional catchment(s) have real "
            "ctmare but zero direct grid overlap -- legitimate routing-only "
            "cells, not counted in the diff stats above)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inpmat", type=Path, required=True,
                         help="Path to the source inpmat.nc")
    parser.add_argument("--out", type=Path, required=True,
                         help="Output .npz path (CaMa-Flood-GPU runoff mapping)")
    parser.add_argument("--ncdata", type=Path, default=None,
                         help="Optional ncdata.nc for an area cross-check "
                              "diagnostic (not required for the conversion)")
    parser.add_argument("--out-inverse", type=Path, default=None,
                         help="Optional output .npz path for the "
                              "catchment -> source-grid inverse mapping "
                              "(2-way coupling prep; see _write_inverse's "
                              "docstring for the schema and how it's derived)")
    parser.add_argument("--global-nx", type=int, default=1440,
                         help="Global CaMa-Flood grid width (default: glb_15min)")
    parser.add_argument("--global-ny", type=int, default=720,
                         help="Global CaMa-Flood grid height (default: glb_15min)")
    parser.add_argument("--west", type=float, default=-180.0,
                         help="Global grid west edge, degrees (default: -180)")
    parser.add_argument("--north", type=float, default=90.0,
                         help="Global grid north edge, degrees (default: 90)")
    parser.add_argument("--dlon", type=float, default=0.25,
                         help="Global grid longitude cell size, degrees "
                              "(default: 0.25 for glb_15min)")
    parser.add_argument("--dlat", type=float, default=0.25,
                         help="Global grid latitude cell size, degrees "
                              "(default: 0.25 for glb_15min)")
    parser.add_argument("--tolerance", type=float, default=1e-3,
                         help="Max allowed degrees of misalignment when "
                              "recovering global grid indices (default: 1e-3)")
    args = parser.parse_args()

    convert(
        args.inpmat, args.out,
        global_nx=args.global_nx, global_ny=args.global_ny,
        west=args.west, north=args.north, dlon=args.dlon, dlat=args.dlat,
        tolerance=args.tolerance, ncdata_path=args.ncdata,
        out_inverse_path=args.out_inverse,
    )


if __name__ == "__main__":
    main()
