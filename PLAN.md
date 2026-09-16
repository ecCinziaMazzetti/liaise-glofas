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
| 1 | Naturalised routing of the control run | **done, full 37 years** | Fortran `LECMF1WAY` coupled run (job 37620761) *was* run for all 37 years; `/perm/pad/liaise_cmf_1988_2024/output/` was then partially cleaned up (freed disk space after the two-chains benchmark had consumed it), dropping to as few as 7 years on disk at one point this session. **Re-run to completion 2026-09-16** (job 37653123, ~2h, status 0) — all 37 years (1988-2024) of `o_totout.nc` confirmed back on disk. This was a data-retention issue, not a spin-up problem — the run itself never needed re-spinning-up (single 1988 cold start, restart-chained throughout); NLOOP-style repeat-forcing was considered and correctly ruled out, since looping the same 37 years would replicate the same 37 annual maxima rather than add independent flood years. The complete 37-year eclandpy→CaMa-Flood-GPU series also exists (`eclandpy_bridge/cmfgpu_out_gpu_repro/`) but carries the documented −21% runoff bias — kept only as the cross-check series (§1 table), not the final parameter source. |
| 2 | Allocate the dams on the map | **done** | `cama_flood/estimate_dam_q100.py`'s `load_dams()`: 45 dams matched by nearest-cell lookup against `ncdata.nc`'s `basin` field (see above), no Fortran allocator run needed since `GRanD_allocated.csv` ships pre-allocated. 39 unique grid cells (some dams share a 0.25° cell, e.g. Canelles/SantaAna, Talarn/Terradets — expected at this resolution, both get the same naturalised Q100 from their shared cell). |
| 3 | Estimate parameters (p01 mean/max, p02 Gumbel Q100) | **p01+p02 done on the full 37-year record** | `cama_flood/estimate_dam_q100.py` re-run 2026-09-16 once all 37 years landed (superseding the earlier 22-year interim pass — Q100 moved <7% at every dam between the two, e.g. Mequinenza 5713→5703, Itoiz 630→673, so the interim numbers were already close, but the full record is what's saved now). Gumbel-via-L-moments implementation checked line-for-line against the actual CaMa-Flood package script (`map/src/src_dam/script/p02_get_100yrDischarge.py`) — same PWM formula, same result method, not just "a" Gumbel fit. **Key finding stands**: annual-mean discharge agrees closely between the two naturalised series at every dam (e.g. Mequinenza 274.0 vs 281.6 m³/s) despite the documented −21% domain-mean runoff bias on the GPU/eclandpy side — but **Q100 does not**: Fortran's Gumbel-fit Q100 runs systematically ~1.5–1.8× the GPU-series estimate at nearly every dam (Mequinenza 5703 vs 3382 m³/s; Canelles 3790 vs 2244; Itoiz 673 vs 360). Consistent with the earlier channel-width/routing-dynamics finding (mean flow is protected by mass conservation, peak/extreme statistics are not) — confirms the GPU/eclandpy series is not a safe substitute for Q100, only for a rough first look. **p03/p04 (normal volume, merged dam_param.csv) not started** — needs GRSAD/ReGeom (see blocker below) or the 37%-of-capacity fallback. |
| 4 | Wire `&NDAMOUT` into `namelist/input_cmf` | not started | Ten-line namelist change, see artifact §3.4 for the exact block. |
| 5 | First dammed run, 1988–2024 | not started | Blocked on step 3 (`dam_param.csv`) and step 4. |
| 6 | Score against regulated/natural gauge split | not started | `cama_flood/skill_benchmark_control.py` (already generalised to any `--obs` file) can score this once the dammed run exists — pass the naturalised run as the null model. |

### Open blockers worth flagging early
- **GRSAD download** (surface-area series for normal volume, p03): TDL Dataverse API returns 403 from the HPC; needs a browser/desktop fetch or the 37%-of-capacity fallback (itself a calibration target, so not blocking).
- **`/perm` cleanup risk, recurring**: the Fortran naturalised `o_totout.nc` has now been cleaned up and re-run once already. The derived Q100 table is checkpointed at `/perm/pad/liaise_discharge_compare/ebro_dam_q100.csv` (full 37-year version as of 2026-09-16) precisely so a future cleanup of the raw `o_totout.nc` doesn't erase this derived product — but that CSV itself is outside the repo and outside Git LFS's scope (convention: only small *validated* reference data goes in `cama_flood/data/`, and this Q100 table isn't the final calibrated `dam_param.csv` yet). Reconsider committing it once p03/p04 finish.

## Completed this session (folded into CLAUDE.md, kept here only as a pointer)
- CAMELS-Spain gauge extraction (46 stations) + non-comparative control skill dashboard, deployed to `sites.ecmwf.int/pad/liaise/gauges/`. See CLAUDE.md and `cama_flood/extract_liaise_grdc_observations.py`/`skill_benchmark_control.py`/`build_control_dashboard.py`.
