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
| 1 | Naturalised routing of the control run | **done, full 37 years, AND on a just-fixed restart chain** | Fortran `LECMF1WAY` coupled run (job 37620761) *was* run for all 37 years, but that run — like every multi-year run made with `run/run_liaise_ecland.{sh,slurm}` before 2026-09-16 — turns out to have **silently cold-started the LAND state every 1 January** (soil moisture/snow reset to `soilinit`, not actually carried over; only CaMa-Flood's own river restart was ever chained). Root cause: the driver only reads a restart when `NSTART /= 0`, and this script always sets `NSTART=0`, so the staged `restart_in.nc` was silently ignored. Found and fixed 2026-09-16 (see CLAUDE.md, "The annual restart chain never carried the land state"); the old run is now `/perm/pad/liaise_cmf_1988_2024_NOCHAIN_invalid` and explicitly marked superseded. **The run this Q100 estimate actually used, job `37653123` (submitted 16:15, i.e. after the 16:05 fix), is the corrected, restart-chain-verified rerun** — confirmed by file mtimes before trusting this. Effect size was not small: fixing the chain lowers Jan–Mar discharge by 1.5–4x and annual means by 15–45% versus the old cold-start run, and *raises* peak flows (proper antecedent-moisture memory lets wet spells compound) — so the Q100 numbers below benefit from the fix, not just the full 37-year sample length. `/perm` cleanup separately meant only 22 of these 37 years were on disk mid-session; both a re-run and the restart fix landed the same day, in the right order — worth re-stating since it would have been easy to conflate "more years appeared" with "nothing else changed." The complete 37-year eclandpy→CaMa-Flood-GPU series also exists (`eclandpy_bridge/cmfgpu_out_gpu_repro/`) but carries the documented −21% runoff bias AND predates this land-restart fix (eclandpy has its own separate state handling, not affected by this specific bug, but not re-verified against it either) — kept only as the cross-check series (§1 table), not the final parameter source.|
| 2 | Allocate the dams on the map | **done** | `cama_flood/estimate_dam_q100.py`'s `load_dams()`: 45 dams matched by nearest-cell lookup against `ncdata.nc`'s `basin` field (see above), no Fortran allocator run needed since `GRanD_allocated.csv` ships pre-allocated. 39 unique grid cells (some dams share a 0.25° cell, e.g. Canelles/SantaAna, Talarn/Terradets — expected at this resolution, both get the same naturalised Q100 from their shared cell). |
| 3 | Estimate parameters (p01 mean/max, p02 Gumbel Q100, p03 volume, p04 merge) | **done, first pass (37%-fallback volume)** | `cama_flood/estimate_dam_q100.py` re-run 2026-09-16 once all 37 years landed (superseding the earlier 22-year interim pass — Q100 moved <7% at every dam between the two, e.g. Mequinenza 5713→5703, Itoiz 630→673). Gumbel-via-L-moments checked line-for-line against `p02_get_100yrDischarge.py`. **Key finding stands**: annual-mean discharge agrees closely between the Fortran and GPU/eclandpy naturalised series at every dam despite the documented −21% runoff bias, but Q100 doesn't — Fortran runs ~1.5–1.8× the GPU estimate everywhere (mean flow is protected by mass conservation, extremes aren't). `cama_flood/build_dam_param_csv.py` then reimplements `p04_complete_damcsv.py`'s exact merge rules (Qf=0.3·Q100 with the <Qn bump rule; FldVol=37%·capacity since GRSAD is still blocked; **one dam per grid cell, keep the largest by capacity** — 6 smaller co-located dams dropped: SantaAna, Urrunaga, Terradets, GonzalezLacasa, Laparan, SanLorenzoMongay) into a runtime-ready `dam_param.csv`, 39 dams, exact 13-column `LDAMYBY=.TRUE.` format `cmf_ctrl_damout_mod.F90` reads. Saved at `/perm/pad/liaise_discharge_compare/dam_param.csv` and staged for a run at `cama_flood/data_dam_firstpass/dam_param.csv` (gitignored — first-pass, not GRSAD-calibrated, deliberately kept out of the validated `cama_flood/data/`). |
| 4 | Wire `&NDAMOUT` into the CaMa namelist | **done** | New `namelist/input_cmf_dam` (copy of `input_cmf` with `LDAMOUT=.TRUE.`, `CVARSOUT` +`daminf,damsto`, and the `&NDAMOUT` block from the artifact's §3.4) — kept as a separate file rather than editing `input_cmf` in place, so the naturalised baseline used everywhere else in this project is untouched. `run/run_liaise_ecland.{sh,slurm}`'s `CMF_STATIC_FILES` array gained a `${CMF_STATIC_FILES_EXTRA:-}` extension point (empty by default, zero behaviour change for existing runs) so `dam_param.csv` can be staged without hardcoding it into every run. |
| 5 | First dammed run, 1988–2024 | **ready, not launched** | Everything needed exists; this just needs an `sbatch` submission (see command below) and hasn't been fired — a multi-hour job on shared infrastructure is worth a final check before submitting rather than launching automatically. |
| 6 | Score against regulated/natural gauge split | not started | `cama_flood/skill_benchmark_control.py` (already generalised to any `--obs` file) can score this once the dammed run exists — pass the naturalised run as the null model. |

### Step 5 launch command (ready, awaiting go-ahead)
```bash
RUN_ROOT=/perm/pad/liaise_cmf_1988_2024_dam \
NAMELIST=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/namelist/input_cmf1way \
CMF_NAMELIST=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/namelist/input_cmf_dam \
CMF_STATIC_DIR=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/cama_flood/data_dam_firstpass \
ECLAND_EXE=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/run/bin/ecland-master-dp_pinned_20260913 \
sbatch run/run_liaise_ecland.slurm
```
Mirrors the naturalised run's own configuration (same pinned binary, same
`input_cmf1way`, 1988 cold start, 37 years restart-chained) with only the
CaMa namelist and static-file source swapped in for the dam module. Expect
~20% runtime overhead over the naturalised run's ~2h (artifact §5), so
budget ~2.5h.

### Open blockers worth flagging early
- **GRSAD download** (surface-area series for normal volume, p03): TDL Dataverse API returns 403 from the HPC; needs a browser/desktop fetch. The 37%-fallback in use now is itself one of the artifact's named calibration targets, so not blocking step 5 — but the first dammed run's `FldVol`/`ConVol` split should be treated as provisional until GRSAD lands.
- **`/perm` cleanup risk, recurring**: the Fortran naturalised `o_totout.nc` has now been cleaned up and re-run once already. The derived Q100 table and `dam_param.csv` are checkpointed at `/perm/pad/liaise_discharge_compare/` precisely so a future cleanup of the raw `o_totout.nc` doesn't erase them — but neither file is in the repo yet (convention: only small *validated* reference data goes in `cama_flood/data/`, and this is the first, fallback-volume pass, not the calibrated version). Reconsider committing once GRSAD-based volumes replace the 37% fallback.

## Completed this session (folded into CLAUDE.md, kept here only as a pointer)
- CAMELS-Spain gauge extraction (46 stations) + non-comparative control skill dashboard, deployed to `sites.ecmwf.int/pad/liaise/gauges/`. See CLAUDE.md and `cama_flood/extract_liaise_grdc_observations.py`/`skill_benchmark_control.py`/`build_control_dashboard.py`.
