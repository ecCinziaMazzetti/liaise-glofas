# PLAN.md

Living state for work in progress. Unlike `CLAUDE.md` (narrative log of what was
tried and found, append-only), this file tracks the *current* plan and its
status, and gets edited/reordered as work completes — so a new session can
pick up mid-task without re-deriving where things stand. When a plan finishes
or is abandoned, fold a one-line summary into `CLAUDE.md` and delete its
section here.

## Active: Reservoir operation on the Ebro (CaMa-Flood v4.20 dam module)

Full feasibility writeup: [Ebro Reservoir Operation](https://claude.ai/artifact/V5ZZxE3K4jFS6tsds5JiP3)
(artifact, 2026-09-16) — read it before touching this section, this is just
the status tracker for its 6-step activation pipeline (§3) plus calibration
(§4).

**Reservoirs**: 45 GRanD dams drain to the Ebro inside our 73×49 domain,
7.77 km³ total capacity (confirmed 2026-09-16 by filtering
`/perm/pad/cmf_v420_pkg_20240430/map/data/GRanD_allocated.csv`'s
`lat_alloc`/`lon_alloc` — already snapped to the global glb_15min grid, no
need to recompile/rerun `allocate_dam.F90` — by nearest-cell match against
our own `cama_flood/data/ncdata.nc` `basin` field, basin id 4). Matches the
artifact's figure exactly. Biggest: Mequinenza (1534 MCM, Ebro mainstem,
ix=39/iy=30), Canelles (688 MCM, Noguera Ribagorzana), Itoiz (586 MCM,
Irati). Allocation + Q100 now produced by `cama_flood/estimate_dam_q100.py`
(committed); full per-dam table at
`/perm/pad/liaise_discharge_compare/ebro_dam_q100.csv` (not committed —
regenerate from the script, same convention as the other discharge-compare
outputs).

### Step status (§3 of the artifact)

| # | Step | Status | Note |
|---|---|---|---|
| 1 | Naturalised routing of the control run | **partial** | Fortran `LECMF1WAY` coupled run (job 37620761) *was* run for all 37 years, but `/perm/pad/liaise_cmf_1988_2024/output/` was mostly cleaned up afterward — as of 2026-09-16 (this check) 1988–2009 (22 years) of `o_totout.nc` remain on disk, growing slowly across sessions (was 7, then 21). The complete 37-year eclandpy→CaMa-Flood-GPU series exists (`eclandpy_bridge/cmfgpu_out_gpu_repro/`) but carries the documented −21% runoff bias — usable per the artifact's own "shortcut for a first look" (§1 table), not for the final parameters. |
| 2 | Allocate the dams on the map | **done** | `cama_flood/estimate_dam_q100.py`'s `load_dams()`: 45 dams matched by nearest-cell lookup against `ncdata.nc`'s `basin` field (see above), no Fortran allocator run needed since `GRanD_allocated.csv` ships pre-allocated. 39 unique grid cells (some dams share a 0.25° cell, e.g. Canelles/SantaAna, Talarn/Terradets — expected at this resolution, both get the same naturalised Q100 from their shared cell). |
| 3 | Estimate parameters (p01 mean/max, p02 Gumbel Q100) | **p01+p02 done, first pass** | `cama_flood/estimate_dam_q100.py` run 2026-09-16 against both series. Gumbel-via-L-moments implementation checked line-for-line against the actual CaMa-Flood package script (`map/src/src_dam/script/p02_get_100yrDischarge.py`) — same PWM formula, same result method, not just "a" Gumbel fit. **Key finding**: annual-mean discharge agrees closely between the two naturalised series at every dam (e.g. Mequinenza 280.7 vs 281.6 m³/s, Fortran 22yr vs GPU 37yr) despite the documented −21% domain-mean runoff bias on the GPU/eclandpy side — but **Q100 does not**: Fortran's Gumbel-fit Q100 runs systematically ~1.5–1.8× the GPU-series estimate at nearly every dam (Mequinenza 5713 vs 3382 m³/s; Canelles 3938 vs 2244; Itoiz 630 vs 360). Consistent with the earlier channel-width/routing-dynamics finding (mean flow is protected by mass conservation, peak/extreme statistics are not) — reinforces that the GPU/eclandpy series is not a safe substitute for Q100, only for a rough first look. **p03/p04 (normal volume, merged dam_param.csv) not started** — needs GRSAD/ReGeom (see blocker below) or the 37%-of-capacity fallback. |
| 4 | Wire `&NDAMOUT` into `namelist/input_cmf` | not started | Ten-line namelist change, see artifact §3.4 for the exact block. |
| 5 | First dammed run, 1988–2024 | not started | Blocked on step 3 (`dam_param.csv`) and step 4. |
| 6 | Score against regulated/natural gauge split | not started | `cama_flood/skill_benchmark_control.py` (already generalised to any `--obs` file) can score this once the dammed run exists — pass the naturalised run as the null model. |

### Open blockers worth flagging early
- **Fortran naturalised sample size**: only 22 years on disk vs the manual's ≥30-year recommendation for the Gumbel fit — a 100-year return period fit from 22 years is a real extrapolation (T/n ≈ 4.5×), not disqualifying but worth stating alongside any Q100 number used downstream. Re-running the missing 2009–2024 years (or waiting for whatever is slowly restoring them) would close this before the numbers go into `dam_param.csv` for real.
- **GRSAD download** (surface-area series for normal volume, p03): TDL Dataverse API returns 403 from the HPC; needs a browser/desktop fetch or the 37%-of-capacity fallback (itself a calibration target, so not blocking).
- **`/perm` cleanup risk**: the Fortran naturalised `o_totout.nc` has already been partially cleaned up once mid-plan. The derived Q100 table is now checkpointed at `/perm/pad/liaise_discharge_compare/ebro_dam_q100.csv` precisely so a future cleanup of the raw `o_totout.nc` doesn't erase this derived product — but that CSV itself is also outside the repo and outside Git LFS's scope (convention: only small *validated* reference data goes in `cama_flood/data/`, and this Q100 table isn't validated/final yet). Reconsider once p03/p04 finish and the number is meant to persist long-term.

## Completed this session (folded into CLAUDE.md, kept here only as a pointer)
- CAMELS-Spain gauge extraction (46 stations) + non-comparative control skill dashboard, deployed to `sites.ecmwf.int/pad/liaise/gauges/`. See CLAUDE.md and `cama_flood/extract_liaise_grdc_observations.py`/`skill_benchmark_control.py`/`build_control_dashboard.py`.
