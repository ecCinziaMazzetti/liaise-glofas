#!/usr/bin/env python3
"""Pull FLUXNET Shuttle point-observation sites in the LIAISE region from ifs-landbench.

Companion to cama_flood/extract_liaise_grdc_observations.py -- that script
wires in real river discharge for the LIAISE domain; this one wires in real
point (flux-tower) observations, from the sibling ifs-landbench repository
(/perm/pad/ifs-landbench, run over 775 FLUXNET Shuttle sites, see its own
README) rather than the fixed 170-site PLUMBER2 set.

IMPORTANT CAVEATS -- read before trusting or extending this, unlike the
river-gauge script this one has no equivalent "basin" cross-check:

  - Geographic relevance is NOT verified against LIAISE's actual field
    campaign, only against a geographic box. Site coordinates alone put all
    matched sites in the Pre-Pyrenees (~42.1N), north of LIAISE's core
    irrigated-agriculture supersite (Ivars d'Urgell / Els Plans de Sio,
    ~41.6-41.7N per published campaign descriptions), and the matched
    vegetation types here are savanna/grassland, not irrigated cropland.
    They may be legitimate LIAISE contrast sites (the campaign studies
    irrigation-driven land-atmosphere heterogeneity against surrounding
    rainfed/natural vegetation) or may simply be nearby-but-unrelated
    FLUXNET towers -- this script cannot tell the difference, only a person
    with the actual LIAISE site list can. Confirm before treating any site
    pulled in here as an official LIAISE observation.
  - The river-gauge script could verify relevance via CaMa-Flood's own
    basin topology (a hard, checkable fact). There is no equivalent
    structure for point sites -- a bounding box is the only filter
    available here.
  - Materialized site-years do NOT overlap the main LIAISE ecLand domain
    runs' 1988-2014 WFDE5-CRU-GPCC forcing period (sites are recent,
    typically 2020s). Comparing a site here against the existing domain
    runs is not possible; it would need a separate, standalone ecLand
    point run using the site's own forcing/clim (also bundled here).

What this script does: filters ifs-landbench's reference/site_metadata_merged.csv
to a LIAISE-region box, reports every candidate, and for whichever ones
already have materialized inputs in ifs-landbench's shuttle-all775-era5
group (forcing/clim/flux/soil), copies that site's five files
(met_insituHT_*, surfclim_*, surfinit_*, *_FLUXNET2015_Flux.nc, soil_*) into
landbench/data/<SiteCode>/. Candidates without materialized data are only
reported, not built -- doing so needs the FLUXNET Shuttle CLI, network
access, and (for physiography) an ECMWF account; see ifs-landbench's own
README ("Building the inputs from scratch").

Usage
-----
    python3 extract_liaise_landbench_sites.py \\
        --landbench-root /perm/pad/ifs-landbench \\
        --group shuttle-all775-era5 \\
        --out-dir data
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


def get_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--landbench-root", required=True, type=Path, help="ifs-landbench checkout")
    p.add_argument("--group", default="shuttle-all775-era5", help="ifs-landbench --experiment-name / data group")
    p.add_argument("--lon-window", nargs=2, type=float, default=[-0.75, 2.0], metavar=("WEST", "EAST"),
                    help="LIAISE-region box -- same default as cama_flood's discharge-comparison work")
    p.add_argument("--lat-window", nargs=2, type=float, default=[40.5, 43.0], metavar=("SOUTH", "NORTH"))
    p.add_argument("--out-dir", required=True, type=Path, help="destination for per-site file bundles")
    return p.parse_args()


def find_candidate_sites(opts: argparse.Namespace) -> list[dict]:
    csv_path = opts.landbench_root / "reference" / "site_metadata_merged.csv"
    lonW, lonE = opts.lon_window
    latS, latN = opts.lat_window
    sites = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            try:
                lat, lon = float(row["SiteLatitude"]), float(row["SiteLongitude"])
            except (ValueError, KeyError):
                continue
            if lonW <= lon <= lonE and latS <= lat <= latN:
                sites.append(row)
    return sites


def find_materialized_files(landbench_root: Path, group: str, site_code: str) -> dict[str, Path] | None:
    """Locate a site's 5 input/obs files if all are present; else None."""

    patterns = {
        "forcing": landbench_root / "forcing" / group,
        "surfclim": landbench_root / "clim" / group,
        "surfinit": landbench_root / "clim" / group,
        "flux": landbench_root / "flux" / group,
        "soil": landbench_root / "soil" / group,
    }
    found: dict[str, Path] = {}
    for kind, directory in patterns.items():
        if not directory.is_dir():
            return None
        if kind == "forcing":
            matches = [f for f in directory.glob(f"met_insituHT_{site_code}_*")]
        elif kind == "surfclim":
            matches = [f for f in directory.glob(f"surfclim_{site_code}_*")]
        elif kind == "surfinit":
            matches = [f for f in directory.glob(f"surfinit_{site_code}_*")]
        elif kind == "flux":
            matches = [f for f in directory.glob(f"{site_code}_*_FLUXNET2015_Flux.nc")]
        elif kind == "soil":
            matches = [f for f in directory.glob(f"soil_{site_code}_*")]
        if not matches:
            return None
        found[kind] = matches[0]
    return found


def main() -> None:
    opts = get_args()
    sites = find_candidate_sites(opts)
    print(f"Candidate sites in the LIAISE-region box: {len(sites)}")

    materialized = []
    for s in sites:
        code = s["SiteCode"]
        files = find_materialized_files(opts.landbench_root, opts.group, code)
        status = "MATERIALIZED" if files else "metadata only, not built"
        print(f"  {code:12s} {s['Fullname'][:30]:30s} lat={s['SiteLatitude']:>9} lon={s['SiteLongitude']:>9} "
              f"IGBP={s['IGBP_vegetation_short']:5s} -- {status}")
        if files:
            materialized.append((s, files))

    if not materialized:
        print("\nNo candidate site has materialized data in this group; nothing copied.")
        return

    for s, files in materialized:
        code = s["SiteCode"]
        dest = opts.out_dir / code
        dest.mkdir(parents=True, exist_ok=True)
        for kind, src in files.items():
            shutil.copy2(src, dest / src.name)
        print(f"\nCopied {code} ({len(files)} files) to {dest}")


if __name__ == "__main__":
    main()
