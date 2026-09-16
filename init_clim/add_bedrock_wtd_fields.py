#!/usr/bin/env python3
"""Derive LIAISE-domain depth-to-bedrock and water-table-depth fields.

Produces two NEW ancillary files -- init_clim/data/surfclim_depthtrilogy
(surfclim + RDBEDROCK) and init_clim/data/soilinit_depthtrilogy (soilinit + WTD)
-- rather than modifying the committed surfclim/soilinit in place, because those
two files are what the existing 37-year control run (and other developers sharing
this repo) already depend on; this experiment must not change their output.

Sources:
  - Bedrock depth: Shangguan et al. (2017) BDTICM, global 250m GeoTIFF, absolute
    depth to bedrock in cm. Hosted at ISRIC (former SoilGrids archive). This is
    the same dataset ecLand's own develop-branch source comments reference for
    a future per-gridpoint RDBEDROCK (yos_soil.F90).
  - Water-table depth: Fan, Miguez-Macho, Jobbagy, Jackson & Otero-Casal (2017,
    PNAS) global equilibrium water-table depth, ~30 arcsec, EURASIA tile.
    Confirmed as the exact dataset ecLand's rdsupr.F90 comment cites
    ("Fan et al. 2017 water-table depth, which reaches 257m at CN-Din...").
    Hosted on USC-Santiago GFNL's THREDDS server (co-author Miguez-Macho's group).

The BDTICM GeoTIFF is 8.5GB global and this environment's GDAL build cannot open
it via /vsicurl/ (confirmed: vsicurl fails to open ANY remote URL here, not just
this one -- likely a network-sandboxing quirk specific to GDAL's own libcurl
handle, since plain curl/urllib range requests to the same host work fine). It is
not tiled (RowsPerStrip=1, DEFLATE-compressed per row), so this script fetches
only the contiguous byte range spanning the LIAISE-box rows (~640MB, not the full
8.5GB) via a single HTTP range request, then decompresses each row's DEFLATE
stream individually with zlib.
"""
from __future__ import annotations

import shutil
import sys
import urllib.request
import zlib
from pathlib import Path

import numpy as np
import tifffile
import fsspec
from netCDF4 import Dataset

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SURFCLIM_SRC = DATA_DIR / "surfclim"
SOILINIT_SRC = DATA_DIR / "soilinit"
SURFCLIM_OUT = DATA_DIR / "surfclim_depthtrilogy"
SOILINIT_OUT = DATA_DIR / "soilinit_depthtrilogy"

BDTICM_URL = "https://files.isric.org/soilgrids/former/2017-03-10/data/BDTICM_M_250m_ll.tif"
WTD_URL = "http://thredds-gfnl.usc.es/thredds/fileServer/GLOBALWTDFTP/annualmeans/EURASIA_WTD_annualmean.nc"

DEFAULT_CACHE = Path("/perm/pad/depth_trilogy_source_data")
SCRATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CACHE

# Pad half a target grid cell (0.25 deg) around the LIAISE box so every target
# cell's true footprint is covered by source pixels, not just its center.
BOX_LON = (-6.0, 5.5)
BOX_LAT = (39.0, 47.0)

# RGWTD_MIN/RDBEDROCK-no-data clamp bounds SRFGWRECHARGE_MOD already enforces at
# read time (rdsupr.F90) -- applied here too so the committed file is
# self-consistent even before any read-time clamp.
WTD_MIN, WTD_MAX = 0.5, 100.0
# RZBEDROCK_MIN floor in srfwexc_vg_mod.F90; no fixed ceiling in the model, but
# BDTICM itself saturates around this depth for "no bedrock found" pixels.
BEDROCK_MIN = 1.0


def target_grid():
    with Dataset(SOILINIT_SRC) as ds:
        lat = np.asarray(ds.variables["lat"][:])
        lon = np.asarray(ds.variables["lon"][:])
    return lat, lon


def cell_edges(centers):
    step = float(np.median(np.diff(centers)))
    return np.concatenate([centers - step / 2.0, [centers[-1] + step / 2.0]])


def block_mean_to_grid(src_lat, src_lon, src_val, valid, lat_centers, lon_centers):
    """Average all valid source pixels whose center falls in each target cell."""
    lat_edges = cell_edges(lat_centers)
    lon_edges = cell_edges(lon_centers)
    out = np.full((len(lat_centers), len(lon_centers)), np.nan, dtype="f8")
    counts = np.zeros_like(out, dtype="i8")
    row_idx = np.digitize(src_lat, lat_edges) - 1
    col_idx = np.digitize(src_lon, lon_edges) - 1
    for i in range(len(lat_centers)):
        rmask = (row_idx == i)
        if not rmask.any():
            continue
        for j in range(len(lon_centers)):
            cmask = (col_idx == j)
            sel = valid[np.ix_(rmask, cmask)] if valid.ndim == 2 else None
            block = src_val[np.ix_(rmask, cmask)]
            if valid.ndim == 2:
                block = block[sel]
            v = block[np.isfinite(block)]
            if v.size:
                out[i, j] = float(np.mean(v))
                counts[i, j] = v.size
    return out, counts


def fetch_bedrock_grid(lat_centers, lon_centers) -> np.ndarray:
    print(f"[bedrock] reading BDTICM header from {BDTICM_URL}")
    with fsspec.open(BDTICM_URL, "rb") as f:
        tif = tifffile.TiffFile(f)
        page = tif.pages[0]
        width, length = page.imagewidth, page.imagelength
        tiepoint = page.tags["ModelTiepointTag"].value
        scale = page.tags["ModelPixelScaleTag"].value
        offs = np.asarray(page.dataoffsets)
        counts = np.asarray(page.databytecounts)
    x0, y0 = tiepoint[3], tiepoint[4]
    dx, dy = scale[0], scale[1]

    def lon_to_col(lon):
        return int(np.floor((lon - x0) / dx))

    def lat_to_row(lat):
        return int(np.floor((y0 - lat) / dy))

    col_min = max(0, lon_to_col(BOX_LON[0]))
    col_max = min(width, lon_to_col(BOX_LON[1]) + 1)
    row_min = max(0, lat_to_row(BOX_LAT[1]))
    row_max = min(length, lat_to_row(BOX_LAT[0]) + 1)
    print(f"[bedrock] source window rows {row_min}:{row_max} cols {col_min}:{col_max}")

    byte_start = int(offs[row_min])
    byte_end = int(offs[row_max - 1] + counts[row_max - 1])
    nbytes = byte_end - byte_start
    print(f"[bedrock] fetching {nbytes/1e6:.1f} MB byte range [{byte_start}:{byte_end}) ...")

    cache = SCRATCH / f"bdticm_liaise_band_rows{row_min}-{row_max}.bin"
    if not cache.exists() or cache.stat().st_size != nbytes:
        print(f"[bedrock] no cached slice at {cache}, fetching from source")
        req = urllib.request.Request(
            BDTICM_URL, headers={"Range": f"bytes={byte_start}-{byte_end - 1}"}
        )
        with urllib.request.urlopen(req, timeout=900) as resp, open(cache, "wb") as out:
            shutil.copyfileobj(resp, out)
    else:
        print(f"[bedrock] reusing cached slice at {cache}")
    blob = cache.read_bytes()
    assert len(blob) == nbytes, f"expected {nbytes} bytes, got {len(blob)}"

    nrows = row_max - row_min
    ncols = col_max - col_min
    data = np.empty((nrows, ncols), dtype="i4")
    pos = 0
    for i, r in enumerate(range(row_min, row_max)):
        cnt = int(counts[r])
        chunk = blob[pos:pos + cnt]
        pos += cnt
        row = np.frombuffer(zlib.decompress(chunk), dtype="<i4")
        data[i, :] = row[col_min:col_max]
    assert pos == nbytes

    src_lat = y0 - (np.arange(row_min, row_max) + 0.5) * dy
    src_lon = x0 + (np.arange(col_min, col_max) + 0.5) * dx
    nodata = -32768
    valid = data != nodata
    data_m = np.where(valid, data / 100.0, np.nan)  # cm -> m

    out, n = block_mean_to_grid(src_lat, src_lon, data_m, valid, lat_centers, lon_centers)
    print(f"[bedrock] target cells with no valid source pixel: {int(np.sum(~np.isfinite(out)))}/{out.size}")
    return out


def fetch_wtd_grid(lat_centers, lon_centers) -> np.ndarray:
    cache = SCRATCH / "EURASIA_WTD_annualmean.nc"
    if not cache.exists():
        print(f"[wtd] no cached tile at {cache}, downloading {WTD_URL}")
        urllib.request.urlretrieve(WTD_URL, cache)
    else:
        print(f"[wtd] reusing cached tile at {cache}")
    with Dataset(cache) as ds:
        lat = np.asarray(ds.variables["lat"][:])
        lon = np.asarray(ds.variables["lon"][:])
        lat_edges = cell_edges(lat_centers)
        lon_edges = cell_edges(lon_centers)
        i0, i1 = np.searchsorted(lat, [lat_edges[0], lat_edges[-1]])
        j0, j1 = np.searchsorted(lon, [lon_edges[0], lon_edges[-1]])
        i0, i1 = max(0, i0 - 1), min(len(lat), i1 + 1)
        j0, j1 = max(0, j0 - 1), min(len(lon), j1 + 1)
        print(f"[wtd] source window rows {i0}:{i1} cols {j0}:{j1}")
        # Read raw int16 with auto scale/mask OFF: this file's scale_factor/
        # add_offset decode to a NEGATIVE-down quantity (verified empirically --
        # e.g. raw==32767, the encoding's near-max, decodes to ~0.0m; the
        # domain's shallowest, near-river/wetland cells; raw near the low end
        # decodes to large negative numbers). True depth-below-surface (positive
        # down, matching this dataset's own "water table depth"/"m" description
        # and the 0-500m dynamic range implied by the encoding) is the NEGATION
        # of the decoded value. raw==-32768 is a separate true nodata sentinel
        # (decodes to ~-1000m, well outside the ~0-500m physical range) --
        # treated as invalid on top of the `mask` variable, not relied on alone.
        ds.set_auto_maskandscale(False)
        wtd_var = ds.variables["WTD"]
        raw = np.asarray(wtd_var[0, i0:i1, j0:j1]).astype("f8")
        scale = float(wtd_var.scale_factor)
        offset = float(wtd_var.add_offset)
        wtd = -(raw * scale + offset)
        mask = np.asarray(ds.variables["mask"][i0:i1, j0:j1])
        valid = (raw > -32768) & (mask > 0)
        src_lat = lat[i0:i1]
        src_lon = lon[j0:j1]

    out, n = block_mean_to_grid(src_lat, src_lon, wtd, valid, lat_centers, lon_centers)
    print(f"[wtd] target cells with no valid source pixel: {int(np.sum(~np.isfinite(out)))}/{out.size}")
    return out


def write_surfclim_with_bedrock(bedrock_grid: np.ndarray):
    SURFCLIM_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SURFCLIM_SRC, SURFCLIM_OUT)
    with Dataset(SURFCLIM_OUT, "a") as ds:
        dims = ds.variables["sotype"].dimensions  # ('lat','lon') on this regular-grid file
        grid = bedrock_grid
        fallback = np.nanmean(grid)
        n_fallback = int(np.sum(~np.isfinite(grid)))
        grid = np.where(np.isfinite(grid), grid, fallback)
        grid = np.maximum(grid, BEDROCK_MIN)
        if "RDBEDROCK" in ds.variables:
            var = ds.variables["RDBEDROCK"]
        else:
            var = ds.createVariable("RDBEDROCK", "f8", dims, zlib=True, complevel=6)
        var.long_name = "Depth to bedrock"
        var.units = "m"
        var.source = "Shangguan et al. (2017) BDTICM, block-averaged to LIAISE grid"
        var.comment = f"{n_fallback} of {grid.size} cells had no valid source pixel; filled with domain mean {fallback:.2f} m"
        var[:] = grid
        print(f"[bedrock] wrote RDBEDROCK: min={grid.min():.2f} mean={grid.mean():.2f} max={grid.max():.2f} m "
              f"({n_fallback} cells filled with domain mean)")


def write_soilinit_with_wtd(wtd_grid: np.ndarray):
    SOILINIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOILINIT_SRC, SOILINIT_OUT)
    with Dataset(SOILINIT_OUT, "a") as ds:
        dims = ds.variables["AvgSurfT"].dimensions  # ('lat','lon') on this regular-grid file
        grid = wtd_grid
        fallback = np.nanmean(grid) if np.any(np.isfinite(grid)) else WTD_MAX
        n_fallback = int(np.sum(~np.isfinite(grid)))
        grid = np.where(np.isfinite(grid), grid, fallback)
        grid = np.clip(grid, WTD_MIN, WTD_MAX)
        if "WTD" in ds.variables:
            var = ds.variables["WTD"]
        else:
            var = ds.createVariable("WTD", "f8", dims, zlib=True, complevel=6)
        var.long_name = "Water table depth"
        var.units = "m"
        var.source = "Fan et al. (2017, PNAS) equilibrium water-table depth, block-averaged to LIAISE grid"
        var.comment = (f"Clipped to [{WTD_MIN},{WTD_MAX}] m to match SRFGWRECHARGE_MOD's own clamp bounds "
                        f"(rdsupr.F90); {n_fallback} of {grid.size} cells had no valid source pixel, "
                        f"filled with domain mean {fallback:.2f} m before clipping")
        var[:] = grid
        print(f"[wtd] wrote WTD: min={grid.min():.2f} mean={grid.mean():.2f} max={grid.max():.2f} m "
              f"({n_fallback} cells filled with domain mean before clipping)")


def main():
    if not SURFCLIM_SRC.exists() or not SOILINIT_SRC.exists():
        raise SystemExit(f"Missing {SURFCLIM_SRC} or {SOILINIT_SRC} -- run `git lfs pull` first.")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    lat_centers, lon_centers = target_grid()
    print(f"[grid] {len(lat_centers)}x{len(lon_centers)} LIAISE grid, "
          f"lat {lat_centers[0]}..{lat_centers[-1]}, lon {lon_centers[0]}..{lon_centers[-1]}")

    bedrock_grid = fetch_bedrock_grid(lat_centers, lon_centers)
    write_surfclim_with_bedrock(bedrock_grid)

    wtd_grid = fetch_wtd_grid(lat_centers, lon_centers)
    write_soilinit_with_wtd(wtd_grid)

    print(f"\nWrote {SURFCLIM_OUT} and {SOILINIT_OUT}")
    print("Original surfclim/soilinit left untouched -- the existing control run is unaffected.")


if __name__ == "__main__":
    main()
