# CaMa-Flood reservoir operation: official methodology vs. what we do

Reference: **"Activating Reservoir Operation in CaMa-Flood"**, Dai Yamazaki and
the CaMa-Flood development team, IIS U-Tokyo, 15 April 2024 — the v4.20
reservoir manual,
[`doc/Manual_ReservoirOperation_v420.docx`](https://github.com/global-hydrodynamics/CaMa-Flood_v4/blob/master/doc/Manual_ReservoirOperation_v420.docx).
Local copy of the package it describes: `/perm/pad/cmf_v420_pkg_20240430/`.

This file exists because the honest answer to "are we following the recommended
methodology?" is **partly**. Below is the official pipeline step by step, what we
actually do at each step, and whether that is a deviation that matters.

---

## The official pipeline

| Step | Official tool | Purpose |
|---|---|---|
| Allocation | `map/src/src_param/allocate_dam.F90`, driven by `t02-alloc_dams.sh`, run **inside each map directory** (`map/glb_15min/src_param/` etc.) | Put each GRanD dam on a CaMa-Flood grid cell. Outputs `GRanD_river.txt` (allocated) and `GRanD_small.txt` (too small for this map) |
| p01 | `script/p01_get_annualmax_mean.py` | Annual mean and max discharge per dam cell, from a **naturalised** run |
| p02 | `script/p02_get_100yrDischarge.py` | Gumbel Q100 from the annual maxima (plotting position + L-moments) |
| p03 | `script/p03_est_fldsto_surfacearea.py` | Normal volume from **GRSAD** surface area (75th percentile) converted via **ReGeom** geometry |
| p04 | `script/p04_complete_damcsv.py` | Merge into `dam_param.csv`: Qf rules, fallbacks, `MINUPAREA` filter, co-located-dam dedup |
| run | `gosh/test6-reservoir_glb15min.sh` | `LDAMOUT=.TRUE.` plus the `&NDAMOUT` options |

The manual also states two design points worth knowing, both of which we had
previously recorded as unexplained observations:

- `CMF_DAMOUT_INIT` **deliberately deactivates bifurcation around reservoir
  cells**, "to avoid instability and un-expected water leakage from reservoir".
  `PLAN.md` previously called this a "documented-nowhere interaction" — it is
  documented, here, and it is intentional.
- `CMF_DAMOUT_CALC` replaces the inflow to a reservoir cell using a
  **kinematic-wave equation** (`UPDATE_INFLOW`) to avoid a "storage buffer
  effect" — an unexpected water-level rise upstream of the dam caused by
  imperfect reservoir topography.

---

## Where we conform, and where we don't

### 1. Allocation — **we do NOT follow the official method**

We reimplemented allocation in `cama_flood/estimate_dam_q100.py` instead of
running `t02-alloc_dams.sh`. The official allocator is available to us — it ships
in the package, already instantiated at `map/glb_15min/src_param/t02-alloc_dams.sh`.

Reading `allocate_dam.F90` directly, the official algorithm is:

- search the **1-min high-resolution `uparea`** (`hires.uparea.bin`), not the
  coarse CaMa grid, over a **±3 pixel window** around the dam's own pixel;
- skip candidates with `upa1m < 0.05 * area0` (reject grossly-too-small cells);
- score by **relative upstream-area error** `err = (upa1m - area0)/area0`, then
  add a **distance penalty**: `err2 = err ± 0.02*dd`, sign following `err`;
- convert to a `rate` that treats over- and under-estimation symmetrically
  (`rate = 1+err2` if positive, `1/(1+err2)` if negative, capped at 1000) and
  take the minimum;
- write rejected/failed cases to `dam_alloc_error.txt` and `GRanD_small.txt`.

Ours (after the 2026-09-17 fix) matches the *family* — area matching rather than
nearest-cell — but differs in three ways:

1. we search the **coarse CaMa grid**, not the 1-min hires grid;
2. we score with `|log(a/area_alloc)|` and **no distance penalty**;
3. we have no `GRanD_small.txt` equivalent, only a reported `uparea_err_pct`.

**Difference 2 is the one that bit us.** Without a distance term, an area-only
search reaches across a watershed divide and picks a hydrologically unrelated
cell — which is exactly the failure that produced a spurious 62-dam and then a
33-dam Ebro list before the current basin-membership-then-area design. The
official algorithm's `0.02*dd` term is precisely the guard against this. If we
keep our own allocator, it should adopt that penalty; better, run the official
one.

> **Upstream bug found while reading this (2026-09-17), worth reporting.**
> `allocate_dam.F90`'s distance term is
> `dd = ( (jy-iy)**2. + (jy-iy)**2. )**0.5`
> — `jy-iy` appears **twice**, so the longitudinal offset `jx-ix` is ignored
> entirely and the latitudinal one is double-counted (`dd = sqrt(2)*|dy|`). It
> should be `( (jx-ix)**2. + (jy-iy)**2. )**0.5`. Effect: east–west displacement
> is free, north–south is penalised ~1.41x too heavily. Mild given the ±3-pixel
> window and the small 0.02 coefficient, but real. Verified in context:
> `ix/iy` are the dam's own pixel indices (lines 276-277), `jx=ix+dx`,
> `jy=iy+dy` (lines 287-288).

**On `lat_alloc`/`lon_alloc`**: the manual explains what these are — GRanD
attributes corrected by allocating on **1-min MERIT Hydro**, which is the
hydrography basemap for CaMa-Flood. They are *conceptually* 1-min-allocated, but
in the shipped CSV they are **rounded to 3 decimal places** (e.g. `-153.029000`),
and 1 arcmin ≈ 0.01667°, so the rounding destroys exact grid alignment. That is
why 0% of the 7320 global dams' coordinates land on a cell centre at any
resolution, and why nearest-cell matching them onto a 0.25° grid is invalid. They
are fine as *search seeds* — which is how both the official allocator and our
fixed version use them — but must never be used as exact grid indices.

### 2. p01 / p02 (mean, max, Q100) — **conform in method, differ in plumbing**

Gumbel via L-moments, already checked line-for-line against
`p02_get_100yrDischarge.py`. We read 37 years of NetCDF `o_totout.nc` rather than
the plain-binary daily `outflwYYYY.bin` the official scripts assume; the manual
asks for "~30 years", so our sample length conforms.

### 3. p03 (normal volume) — **using the manual's own sanctioned fallback**

The official route is GRSAD 75th-percentile surface area → ReGeom geometry →
normal volume. GRSAD is blocked (TDL Dataverse returns 403 from the HPC), so we
use **37% of total capacity**, which the manual explicitly specifies for exactly
this case: "For reservoirs with no GRSAD or ReGeom data, flood control storage is
given as 37% of total storage." This is a documented fallback, not an
improvisation — but it is also one of the named calibration targets, so
`FldVol`/`ConVol` stay provisional. **ReGeom is on Zenodo and may be reachable
even though GRSAD is not — worth trying.**

### 4. p04 (merge) — **conforms, verified against the source**

- Qf = 0.3·Q100, with the `<Qn` bump rule (0.4·Q100, else 1.1·Qn) — matches.
- **Co-located-dam dedup**: we keep the largest by capacity per grid cell. Checked
  against `p04_complete_damcsv.py` lines 88-105 — it does exactly this
  (`maxsto = max(cap_mcm)`, drop the rest), with a secondary tiebreak on
  `fldsto_mcm` when capacities tie, which we do not implement. Our claim to match
  the official rule is correct.
- **`MINUPAREA`**: the official p04 takes it as an argument and filters
  `area_CaMa >= MINUPAREA`. The package's own `s01-calc_damparam.sh` ships with
  `MINUPAREA=0` (with `1000` commented out). Our `--min-uparea-km2` defaults to
  0, so we match the shipped default.

### 5. Namelist — **conforms, with one untested option**

| Option | Ours | Manual |
|---|---|---|
| `LDAMH22` | `.FALSE.` | `.FALSE.` recommended (Funato-Yamazaki; Hanazaki 2022 "had some issues") ✅ |
| `LDAMYBY` | `.TRUE.` | year-by-year activation from the construction year ✅ |
| `LDAMTXT` | `.TRUE.` | optional, and it has already paid for itself diagnostically ✅ |
| `LiVnorm` | `.FALSE.` | default, but **see below** ⚠️ |

**`LiVnorm` is the option to try next for the 1988-05-20 crash.** The manual:

> `LiVnorm`: "Options on how to set initial reservoir storage when reservoir is
> first activated in Year-By-Year option. TRUE: reservoirs are activated with
> Normal Volume as initial storage. FALSE: Reservoirs are activated with zero
> additional storage."

Our crashes involved four dams — Itoiz (2003), Rialb (1999), SanSalvador (2013),
Pajares (1994) — **all with construction years after 1988**, going storage-negative
under `LDAMYBY=.TRUE.` with `LiVnorm=.FALSE.`, i.e. activated with *zero
additional storage*. `LiVnorm=.TRUE.` activates them at Normal Volume instead.
This is a documented, single-flag, manual-sanctioned option aimed squarely at the
initialisation path our crash goes through, and **it has never been tried** — none
of the four configurations logged in `PLAN.md` varied it. Try it before any
further per-dam parameter surgery.

---

## Recommended next steps, in order

1. **Try `LiVnorm=.TRUE.`** — cheapest possible test of the most likely fix, one
   namelist flag.
2. **Add the `0.02*dd` distance penalty** to our own allocator (corrected to use
   both `dx` and `dy`), or switch to running `t02-alloc_dams.sh` per resolution.
   The latter is more faithful but needs the map directory layout
   (`../uparea.bin`, `../<hires>/<hires>.uparea.bin`); `build_global_cmf_fixdir.sh`
   plus `fixdir_to_merit_map_bin.py` can already produce that at 6 and 3 arcmin.
3. **Try ReGeom from Zenodo** to replace the 37% fallback, even if GRSAD stays
   blocked.
4. **Report the `dd` bug** upstream to the CaMa-Flood team.
