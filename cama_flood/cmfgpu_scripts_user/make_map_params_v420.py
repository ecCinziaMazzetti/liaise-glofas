# LICENSE HEADER MANAGED BY add-license-header
# Copyright (c) 2025 Shengyu Kang (Wuhan University)
# Licensed under the Apache License, Version 2.0
# http://www.apache.org/licenses/LICENSE-2.0
#

"""
Generate model parameters from the v4.20 CaMa-Flood map package
(cmf_v420_pkg_20240430), kept separate from make_map_params.py's v4.30
package so both can be built and compared -- see liaise-ecland/CLAUDE.md
("channel-width vintage" discussion) for why this matters.
"""


from cmfgpu.params import MERITMap


def main():
    print("=== Generating Map Parameters (v4.20) ===")

    # --- Configuration Start ---
    map_resolution = "glb_15min"
    map_dir = f"/perm/pad/cmf_v420_pkg_20240430/map/{map_resolution}"
    out_dir = f"/perm/pad/CaMa-Flood-GPU-run/inp/{map_resolution}_v420"

    # Optional files
    bifori_file = f"{map_dir}/bifori.txt"
    gauge_file = f"{map_dir}/GRDC_alloc.txt"

    # Settings
    target_gpus = 1
    visualized = True
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
    )
    merit_map.build_input()


if __name__ == "__main__":
    main()
