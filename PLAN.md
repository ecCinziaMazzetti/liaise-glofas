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
| 5 | First dammed run, 1988–2024 | **blocked: crashes in 1988, real finding, not a config error** | See "Step 5 attempt" below — three submissions, two were this session's own mistakes (wrong `sbatch` invocation, then a missing env var), the third hit a genuine CaMa-Flood dam-module interaction and crashed with SIGFPE ~140 days into 1988. |
| 6 | Score against regulated/natural gauge split | not started | Blocked on step 5. |

### Step 5 attempt, 2026-09-16: submission mistakes, then a real crash

**Submission mistakes (own errors, logged so they aren't repeated)**:
1. First attempt used shell-prefixed env vars (`RUN_ROOT=... sbatch run_liaise_ecland.slurm`) — **this cluster's `sbatch` does not propagate ad-hoc shell env vars this way**; the README already documented the right form (`sbatch --export=ALL,VAR=val,... script`) and this should have been checked first. The job silently ran with every default — plain `namelist/input` (no coupling at all), writing into the default `run/output/`/`run/restart/` (not a scratch path) — and "succeeded" in ~1h55m, overwriting all 37 years of the plain CY50R1 control run's restart chain. Not catastrophic (that control run was already invalidated by the land-restart-chain bug above and needed rerunning anyway) but unintentional and unverified — **the control-run diagnostics documented elsewhere in CLAUDE.md are now stale against what's actually on disk in `run/output/`; re-verify before citing them.**
2. Second attempt fixed the `--export=ALL,...` syntax but dropped `CMF_STATIC_FILES_EXTRA=dam_param.csv` from the list — failed in 12 seconds with a clear `forrtl: file not found ... dam_param.csv`, negligible cost.

**The real finding, third attempt**: with both of the above fixed, the run got into 1988 and crashed after ~140 simulated days (2026-09-16, job 37742075) with `forrtl: error (75): floating point exception` inside `cmf_ctrl_damout_mod_mp_cmf_damout_calc_`, specifically `(DamVol/ConVol)**0.5` (line 384) going through a negative base. Diagnosed exactly via `damtxt-1988.txt` (`LDAMTXT=.TRUE.` paid off): 4 grid cells had gone storage-negative by day 141 (19880520) — **all 4 belong to dams with a construction year after 1988** (Itoiz/2003, Rialb/1999, SanSalvador/2013, Pajares/1994, i.e. `DamStat<=0` this year).

Checked the source directly rather than guessing: `CMF_DAMOUT_CALC` does correctly `CYCLE` past `DamStat<=0` dams — the reservoir release rule genuinely never runs for them, so this is **not** a Qf/Qn calibration problem on these 4. But `CMF_DAMOUT_INIT` marks `I1DAM(ISEQ)=1` and `I2MASK(ISEQ,1)=2` (excluded from the adaptive timestep) **unconditionally for every allocated dam cell**, and the `LPTHOUT` bifurcation-stop loop also checks `I1DAM(...)>0` unconditionally — both regardless of `DamStat`/`LDAMYBY`. So a not-yet-built dam cell still loses its adaptive substep and its bifurcation path the moment it's *allocated*, years before its release rule activates. That's a real, documented-nowhere interaction: at these 4 specific cells, removing those stabilising mechanisms was enough to blow up plain river-routing mass balance, independent of any parameter choice in `dam_param.csv`.

**Diagnostic run, `LDAMYBY=.FALSE.` (all 39 dams active from 1988), 2026-09-16, job 37751981**: does **not** cleanly confirm the not-yet-built-cell hypothesis above. It crashed with the identical SIGFPE signature, on the **exact same date, 19880520**, after the identical 564 written `damtxt-1988.txt` records — but this time **no dam ever went storage-negative** (checked every record, not just the last one). Two things follow: (1) the coincidence of both runs dying on the same calendar date points to a specific forcing event around 1988-05-20 as the trigger, not specifically the `LDAMYBY`/inactive-cell mechanism — that mechanism may still be a real, separate issue (the confluence-proximity finding below stands on its own), but this test doesn't isolate it as *the* cause of either crash; (2) a different, more concrete culprit surfaced instead — see below. `namelist/input_cmf_dam_test_ldambyfalse` is a throwaway diagnostic namelist, kept for the record but not part of the real pipeline.

**Root cause, now confirmed and quantified — Flix specifically, uniquely among all 39 dams**:

Checked `CALC_ADPSTP` (`cmf_ctrl_physics_mod.F90`, the exact CFL-based adaptive-timestep calculation, in the same call stack as the crash): it explicitly excludes any cell with `I2MASK>0` — i.e. every allocated dam/dam-upstream cell — from the `DT_MIN` computation that sets the model's global adaptive timestep. So the timestep used everywhere, including at dam cells, is chosen ignoring how fast a dam cell's *own* storage is actually changing.

Computed `AdjVol`/`EmeVol`/`Qa` from `CMF_DAMOUT_INIT`'s own formulas (`EmeVol=ConVol+0.95*FldVol`, `AdjVol=ConVol+0.1*FldVol`, `Qa=(Qn+Qf)/2`) for all 39 dams and compared each one's storage-response band width against how much volume moves through it in a single hourly coupling step (`IFRQ_INP=1h`) at its own flood discharge `Qf`. **Flix is the only dam that fails this check, and by a wide margin**: its case-2 band (`AdjVol-ConVol`) is 0.422 MCM, but one hour at `Qf`=1544.9 m3/s moves 5.56 MCM through it — a **13.2x overshoot in a single non-substepped hour**. The next-highest dam, Irabia, overshoots only 2.7x, and its turnover time at mean flow (121 hours) is nowhere near as fast as Flix's (7.2 hours). Caspe2 and LaLoteta — flagged earlier from the raw inflow-spike magnitude alone — do **not** actually meet this properly-normalized criterion (overshoot 0.2x and 0.9x respectively) once turnover time is accounted for; that was a false lead from not normalizing by capacity. Ribarroja (130 MCM) and Mequinenza (966 MCM), immediately upstream on the same hydropower cascade, are both comfortably fine (0.8x and 0.1x).

**In plain terms**: Flix is a genuine run-of-river afterbay (matches the artifact's own description of the cascade), but the reservoir module's storage-ratio release formulas assume seasonal-scale storage, and the model's adaptive-timestep mechanism structurally cannot see that Flix needs a much finer step than the rest of the domain — so at flood inflow, a single coupling-interval step blows straight through its entire operating range and produces a negative or otherwise invalid ratio argument feeding a fractional power (`**0.5`, `**3.0`, `**0.1`), triggering the SIGFPE. This is a real gap in the upstream CaMa-Flood reservoir module (worth reporting to Yamazaki/the ecland maintainers, independent of this project), not something fixable by better-calibrating `dam_param.csv`.

**Recommendation**: drop Flix from `dam_param.csv` for the first working run. Its cell simply reverts to normal (undammed) routing — full adaptive timestep and bifurcation restored there — since `I1DAM`/`I2MASK` are only set for cells that appear in the file at all. Ribarroja and Mequinenza, immediately upstream on the same cascade, are unaffected and keep their own reservoir operation; only the very last, smallest link in that specific cascade is excluded. Not yet implemented — awaiting confirmation before regenerating `dam_param.csv` and resubmitting.

The original not-yet-built-cell/confluence finding (3 of 4 flagged cells sit at or within a few steps of a major confluence; none sit directly on a bifurcation path per `bifprm.txt`) remains a real, separate observation, but given the diagnostic run crashed identically without it being the active mechanism, it's likely a second, independent manifestation of the same root cause (small/fast-changing storage at a cell excluded from `CALC_ADPSTP`'s adaptive-timestep consideration) rather than a distinct confluence-specific bug — worth keeping in mind if further dams surface this same failure mode later in the 37-year run, past 1988.

### Step 5 launch command (superseded — do not reuse until the crash above is resolved)
```bash
sbatch --job-name=liaise_cmf_dam --time=08:00:00 \
  --export=ALL,RUN_ROOT=/perm/pad/liaise_cmf_1988_2024_dam,NAMELIST=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/namelist/input_cmf1way,CMF_NAMELIST=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/namelist/input_cmf_dam,CMF_STATIC_DIR=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/cama_flood/data_dam_firstpass,CMF_STATIC_FILES_EXTRA=dam_param.csv,ECLAND_EXE=/etc/ecmwf/nfs/dh2_perm_a/pad/liaise-ecland/run/bin/ecland-master-dp_pinned_20260913 \
  run/run_liaise_ecland.slurm
```
This is the *correct submission form* (note: `--export=ALL,...` as flags, not
shell-prefixed vars) — keep this form for any future submission on this
cluster — but do not re-run until one of the candidate fixes above is chosen,
since it will crash the same way otherwise.

### Open blockers worth flagging early
- **GRSAD download** (surface-area series for normal volume, p03): TDL Dataverse API returns 403 from the HPC; needs a browser/desktop fetch. The 37%-fallback in use now is itself one of the artifact's named calibration targets, so not blocking step 5 — but the first dammed run's `FldVol`/`ConVol` split should be treated as provisional until GRSAD lands.
- **`/perm` cleanup risk, recurring**: the Fortran naturalised `o_totout.nc` has now been cleaned up and re-run once already. The derived Q100 table and `dam_param.csv` are checkpointed at `/perm/pad/liaise_discharge_compare/` precisely so a future cleanup of the raw `o_totout.nc` doesn't erase them — but neither file is in the repo yet (convention: only small *validated* reference data goes in `cama_flood/data/`, and this is the first, fallback-volume pass, not the calibrated version). Reconsider committing once GRSAD-based volumes replace the 37% fallback.

## Completed this session (folded into CLAUDE.md, kept here only as a pointer)
- CAMELS-Spain gauge extraction (46 stations) + non-comparative control skill dashboard, deployed to `sites.ecmwf.int/pad/liaise/gauges/`. See CLAUDE.md and `cama_flood/extract_liaise_grdc_observations.py`/`skill_benchmark_control.py`/`build_control_dashboard.py`.
