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
Irati). Full list not yet saved to a repo file — currently only a
`/tmp` scratch table; see step 2 below.

### Step status (§3 of the artifact)

| # | Step | Status | Note |
|---|---|---|---|
| 1 | Naturalised routing of the control run | **partial** | Fortran `LECMF1WAY` coupled run (job 37620761) *was* run for all 37 years, but `/perm/pad/liaise_cmf_1988_2024/output/` was mostly cleaned up afterward — as of 2026-09-16 only 1988–2008 (21 years) of `o_totout.nc` remain on disk, growing slowly (was 7 years two sessions ago). The complete 37-year eclandpy→CaMa-Flood-GPU series exists (`eclandpy_bridge/cmfgpu_out_gpu_repro/`) but carries the documented −21% runoff bias — usable per the artifact's own "shortcut for a first look" (§1 table), not for the final parameters. |
| 2 | Allocate the dams on the map | **done, not yet saved to repo** | 45 dams matched by nearest-cell lookup against `ncdata.nc`'s `basin` field (see above) — a pure-Python re-derivation of the artifact's approach, no Fortran allocator run needed since `GRanD_allocated.csv` ships pre-allocated. Next: write this to a committed script + a small reference CSV (`cama_flood/data/ebro_dam_allocation.csv`, Git LFS-sized-fine-as-plain-text) so it's not re-derived from scratch each session. |
| 3 | Estimate parameters (p01 mean/max, p02 Gumbel Q100) | **in progress** | Next concrete task: extract annual max discharge per dam cell from `o_totout.nc` (Fortran, whatever years exist — 21 currently) and separately from the eclandpy/GPU 37-year series, fit Gumbel via L-moments per dam, compare the two Q100 estimates. Sample size caveat: manual recommends ≥30 years; Fortran naturalised series doesn't have that yet. |
| 4 | Wire `&NDAMOUT` into `namelist/input_cmf` | not started | Ten-line namelist change, see artifact §3.4 for the exact block. |
| 5 | First dammed run, 1988–2024 | not started | Blocked on step 3 (`dam_param.csv`) and step 4. |
| 6 | Score against regulated/natural gauge split | not started | `cama_flood/skill_benchmark_control.py` (already generalised to any `--obs` file) can score this once the dammed run exists — pass the naturalised run as the null model. |

### Open blockers worth flagging early
- **GRSAD download** (surface-area series for normal volume, p03): TDL Dataverse API returns 403 from the HPC; needs a browser/desktop fetch or the 37%-of-capacity fallback (itself a calibration target, so not blocking).
- **`/perm` cleanup risk**: the Fortran naturalised `o_totout.nc` has already been partially cleaned up once mid-plan. If more years are needed for a solid ≥30-year Gumbel fit, either re-run the missing years or checkpoint the annual-max time series to a small committed file as soon as they're extracted, so a future cleanup can't erase the derived product.

## Completed this session (folded into CLAUDE.md, kept here only as a pointer)
- CAMELS-Spain gauge extraction (46 stations) + non-comparative control skill dashboard, deployed to `sites.ecmwf.int/pad/liaise/gauges/`. See CLAUDE.md and `cama_flood/extract_liaise_grdc_observations.py`/`skill_benchmark_control.py`/`build_control_dashboard.py`.
