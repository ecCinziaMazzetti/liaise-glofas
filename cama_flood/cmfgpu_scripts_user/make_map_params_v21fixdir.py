# LICENSE HEADER MANAGED BY add-license-header
# Copyright (c) 2025 Shengyu Kang (Wuhan University)
# Licensed under the Apache License, Version 2.0
# http://www.apache.org/licenses/LICENSE-2.0
#

"""
Generate model parameters from ECMWF's own static_network_nc_v2.1 FIXDIR
(the exact data the Fortran LIAISE/LECMF1WAY reference run uses), converted
via fixdir_to_merit_map_bin.py -- for a true apples-to-apples comparison
with no physiographic-parameter difference from the Fortran side. See
liaise-ecland/CLAUDE.md ("Building CaMa-Flood-GPU from the Fortran
reference's own v2.1 network") for the full rationale.
"""


from cmfgpu.params import MERITMap


def main():
    print("=== Generating Map Parameters (ECMWF static_network_nc_v2.1 FIXDIR) ===")

    # --- Configuration Start ---
    map_resolution = "glb_15min"
    map_dir = f"/perm/pad/cmf_v21_fixdir_map/{map_resolution}"
    out_dir = f"/perm/pad/CaMa-Flood-GPU-run/inp/{map_resolution}_v21fixdir"

    # Optional files
    bifori_file = f"{map_dir}/bifori.txt"
    gauge_file = f"{map_dir}/GRDC_alloc.txt"

    # Settings
    target_gpus = 1
    # False: visualized=True hung indefinitely in this headless session
    # (matplotlib basin_map.png save blocked in poll() on a localhost
    # socket, likely a GUI-backend display connection that never
    # resolves) -- the actual parameters.nc write had already completed
    # by the time it hung, confirmed by killing it and validating the
    # file opened cleanly with all 252383 catchments intact.
    visualized = False
    # Fortran namelist/input_cmf: PDSTMTH = 25000.D0 (downstream distance
    # at river mouth). MERITMap's own default (10000.0) doesn't match --
    # closing this setup gap per the CLAUDE.md audit (2026-09-13).
    river_mouth_distance = 25000.0
    # --- Configuration End ---

    merit_map = MERITMap(
        map_dir=map_dir,
        out_dir=out_dir,
        bifori_file=bifori_file,  # Set to None if not available
        gauge_file=gauge_file,  # Set to None if not available
        visualized=visualized,
        bif_levels_to_keep=5,
        target_gpus=target_gpus,
        out_file="parameters.nc",
        river_mouth_distance=river_mouth_distance,
    )
    merit_map.build_input()


if __name__ == "__main__":
    main()
