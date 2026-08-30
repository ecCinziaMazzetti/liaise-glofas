# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What this repo is

`liaise-ecland` contains scripts and configuration for preparing forcing,
ancillary fields, namelists, and ecLand runs over the LIAISE domain.

The repository contains workflow code and configuration, not the large forcing
or model-output datasets themselves.

## Repository layout

forcing/
  Download and preprocess forcing datasets.

init_clim/
  Generate ecLand `surfclim` and `soilinit` ancillary files.

namelist/
  Generate the ecLand offline namelist.

run/
  Run ecLand annually, manage restarts, and post-process outputs.

cama_flood/
  Derive the ecLand <-> CaMa-Flood interpolation weights and river-network
  fix files for the LIAISE domain.

## Data policy

Do not commit large generated or downloaded data.

In particular, do not add:
- NetCDF forcing files
- GRIB files
- `forcing/WFDE5_CRU_GPCC/`
- `forcing/WFDE5_CRU_GPCC_ecland/`
- `init_clim/work/`
- `init_clim/output/`
- `run/work/`
- `run/output/`
- `run/restart/`
- `cama_flood/work/`
- logs
- Python caches

Respect `.gitignore`.

The exception is `init_clim/data/soilinit`, `init_clim/data/surfclim`, and
the files under `cama_flood/data/`, which are validated reference files
tracked via Git LFS (see `.gitattributes`). These are small, LIAISE-specific
*derived* outputs, distinct from the much larger upstream/global datasets
they are built from (the ECMWF `climate.v021` archive, and the global
CaMa-Flood static network data -- see `cama_flood/derive_cmf_weights.sh`),
which must never be committed. They are also distinct from the gitignored
`init_clim/work/`, `init_clim/output/`, and `cama_flood/work/` directories,
which hold regenerated, run-specific copies.

## Forcing workflows

### 0.5-degree forcing

`forcing/get_liaise_forcing_05.sh`

Downloads WFDE5-CRU-GPCC annual forcing for 1988-2014.

### Kilometre-scale forcing

`forcing/get_liaise_forcing_km.sh`

Downloads the LIAISE forcing products:
- ETHZ_Avg
- IPSL_Alt
- IPSL_Avg

These are approximately 3 km resolution.

### ecLand forcing preparation

`forcing/prepare_liaise_forcing_ecland.py`

Annual forcing files are rebased to:

    hours since 1988-01-01 00:00:00

Each yearly file includes one additional endpoint timestep at
00 UTC on 1 January of the following year.

For the final year, when no following-year forcing exists, the final forcing
record is duplicated and assigned the next hourly timestamp.

Do not remove this endpoint logic: ecLand needs it to reach the full-year
integration endpoint cleanly.

## Ancillary fields

`init_clim/` creates:
- `surfclim`
- `soilinit`

The output grid must match the forcing grid.

The current workflow also repairs/initializes the multilayer snow state where
needed.

### Pre-generated ancillary files

`init_clim/get_init_clim.sh`

Validated `surfclim`/`soilinit` files are stored under `init_clim/data/` via
Git LFS, so they can be installed into `init_clim/work/` without regenerating
them from MARS. This is the supported path when running outside ECMWF (for
example on macOS), where MARS access is unavailable.

Run `git lfs pull` before invoking the script if the files under
`init_clim/data/` have not yet been fetched.

## CaMa-Flood coupling

`cama_flood/derive_cmf_weights.sh`

Derives the interpolation weights (`inpmat.nc`) mapping the LIAISE ecLand
runoff grid onto the CaMa-Flood river network, plus the clipped river-network
fix files CaMa-Flood needs (`ncdata.nc`, `rivclim.nc`, `rivpar.nc`,
`outclm.nc`, `mpireg.nc`, `bifprm.txt`, `diminfo.txt`). Output lands in
`cama_flood/work/` for review; the validated, committed reference copies
live in `cama_flood/data/` (Git LFS).

This script adapts (rather than calls directly) the `ecland` repo's own
`tools/create_forcing/scripts/prepare_basin_ini.bash` / `gen_inpmat.py`,
because that upstream tool assumes the ecLand grid being coupled is a
*subset of the global reduced-Gaussian IFS grid* (the normal case: cut a
regional CaMa-Flood domain out of a global run). LIAISE's ecLand grid is an
independently-built regular 0.5-degree lat/lon grid, not a subset of any
global grid, so the global-Gaussian-grid clipping step (`sel_region.py
-inpmat`, which produces `cdo_clip_htessel.txt`) does not apply and is
skipped -- LIAISE's `surfclim`/`soilinit` are already regional and used
directly.

### Domain: extend crossing basins, not a fixed halo

`EXTEND_CROSSING_BASINS=true` (the default) passes `sel_region.py -e`, so
any river basin crossing the requested LIAISE box is kept in full rather
than dropped -- `sel_region.py`'s default otherwise drops a crossing basin
*entirely*, not just the part outside the box. This grows the actual
derived domain well beyond LIAISE's own bounds (currently the box roughly
spans Iberia to the Alps, ~-9 to 8.5 lon / 37 to 48.5 lat, versus LIAISE's
own -5.75/5.25/39.25/46.75), because this location sits where both the
Ebro and Rhone basins cross a small regional box.

This was tested against two alternatives, both rejected -- **a fixed halo
around the LIAISE box does not work**, and gets *worse*, not better, as
the halo grows:

| Domain | Active cells | Finite output | Negative-discharge rate | Worst negative |
|---|---|---|---|---|
| No halo, no `-e` (original) | 522 | 11 (2%) | -- | -- |
| 0.5 deg halo, no `-e` | 577 | 577 (100%) | 0.33% | -7091 m3/s |
| 2 deg halo, no `-e` | 965 | 965 (100%) | 0.48% | -6582 m3/s |
| **Full extension (`-e`)** | **1405** | **1405 (100%)** | **0.13%** | -5205 m3/s |

CaMa-Flood's local-inertia solver (`LADPSTP`/`LFLDOUT`/`LPTHOUT`) allows
backward flow, which is physically real near estuaries and confluences but
becomes a numerical artifact wherever a hard domain edge cuts through one.
A fixed halo of any size tested still truncates basins mid-stream, so it
just relocates that artifact to wherever the edge happens to land (the
0.5 deg halo cut the Garonne/Dordogne estuary; the 2 deg halo moved the
worst case to the Biscay coast/Loire estuary). Full extension is the only
tested option that lets basins reach their real outlets, and its residual
0.13% negative rate concentrates at the Rhone's own delta bifurcation
channels -- genuine hydraulics, not a boundary artifact. If a future
change wants to keep the domain smaller, it needs a fundamentally
different approach (e.g. a real open-boundary condition at the truncation
point), not a bigger fixed buffer -- re-run the comparison above before
trusting a smaller domain.

`gen_inpmat.py`'s Cython extension needs a source patch for `-e` to work
at all -- see "Two ecland-side source patches" below.

### `mpireg.nc`: flattened to a single region, not clipped

`$FIXDIR/mpireg.nc` is the *global* multi-process MPI decomposition map
(16+ regions across the clipped window). CaMa-Flood (`NPROC_CMF=1` here)
only computes cells tagged region 1; naively clipping the global file (as
the first version of this script did) silently carries over the other
regions' cells, which then never get computed -- confirmed as the actual
cause of an apparently fragmented, disconnected-looking river network
(only ~10-11 of 522 "active" cells producing output), which first looked
like a basin-clipping problem but wasn't. `derive_cmf_weights.sh` clips
`mpireg.nc` for its grid shape, then sets every valid cell to region 1 via
an inline Python step -- not a plain `cdo`/`ncks` clip.

### Running at other resolutions: `build_global_cmf_fixdir.sh`

`derive_cmf_weights.sh` needs a `FIXDIR` -- a global CaMa-Flood fix bundle
(`ncdata.nc`, `rivpar.nc`, `outclm.nc`, `bifprm.txt`, `mpireg.nc`) at the
chosen `CMF_RES` -- to clip. Historically the only one available was a
colleague's personal, non-permanent work area, staged at `glb_15min` only.

`cama_flood/build_global_cmf_fixdir.sh` builds that bundle at any of
`glb_15min`/`glb_06min`/`glb_03min`/`glb_01min` directly from data already
in the shared, permanent `CMFDIR`, so `derive_cmf_weights.sh` can be
pointed at it (`FIXDIR=<its OUTDIR> CMF_RES=<same>`) without depending on
that colleague's directory at all. It is a from-scratch port of ECMWF's
own operational `create_init_clim_cmf.ksh` (E. Dutra 2019, found under
`/ec/vol/ifs/rd/pad/ja8f/include/`) -- only the resolution-independent,
regional-LIAISE-relevant steps are kept (river-network params, discharge
climatology, bifurcation, MPI region, mixed kinematic/local-inertia mask);
the global *atmospheric*-grid `inpmat.nc` that script also builds (an
IFS-climatology-grid product) is not ported, since `derive_cmf_weights.sh`
derives LIAISE's own `inpmat.nc` separately.

Three companion Python tools that script depends on
(`calc_outclm.py`/`calc_rivpar.py`/`gen_mask_mixKinIner.py`) are vendored,
unmodified except one dtype fix, into `cama_flood/vendor/` (from the same
colleague's include directory -- otherwise-unavailable ECMWF operational
tooling, not something to reimplement). `calc_outclm.py` needed one local
fix: it called our patched `cython_ext`'s `remap()` with `float32` input,
but that function expects `float64` -- see the comment in the vendored
copy.

Both this script and `derive_cmf_weights.sh` rebuild the `create_forcing`
Cython extension automatically if missing or stale, so the `-e`/`continue`
patch above is always in effect.

Run it as a proper `sbatch` job, not on the interactive login node: the
global 1-arcmin catchment map (`1min.catmxy.nc`, 233M points) it loads
briefly pushes memory usage high enough (for a few seconds, mid-run) to
trigger what looks like a login-node memory watchdog -- repeated,
inconsistent `SIGKILL`s were observed there regardless of launch method
(plain `&`, `nohup`+`disown`, `run_in_background`), even though total
system memory headroom was never actually exhausted (`free -h`). Under
`sbatch --mem=48G` the whole build completes in under two minutes at every
resolution tried so far. (Also true of `derive_cmf_weights.sh` itself for
the same reason -- submit it the same way.)

**Validated so far**: `glb_06min` (0.1 deg), built, derived (see "Domain"
above -- 179x118 clipped grid, 8573 active river cells, exactly 2.5x
`glb_15min`'s 73x49/1405, matching the resolution ratio), and run for 1988
alone with `LPROD=.FALSE.` (all ecLand `o_*.nc` output off, since only the
CaMa-Flood coupling was of interest) and CaMa-Flood's own `IFRQ_OUT=24`:
6m50s wall-clock, all 8573 active cells produced finite discharge (100%,
matching `glb_15min`'s clean result), non-physical-negative-discharge rate
0.20-0.21% (comparable to `glb_15min`'s 0.13%) but far smaller in
magnitude (worst case -0.5 m3/s vs. `glb_15min`'s -5205 m3/s at the Rhone
delta), and discharge magnitudes were physically plausible (up to ~1089
m3/s on major rivers). `glb_01min` has not yet been tried -- expect roughly
another 4x increase in in-domain 1-arcmin pixel count over `glb_03min`
below, so budget more memory/time headroom accordingly and confirm the
case-table `NMAX`/`NMAXI`/`NMAXRC`/`NMAXIRC` entries still hold before
trusting the result.

`glb_03min` (0.05 deg) is also validated, same method: global build 8m16s
(`--mem=64G`; peak 5.76GB), regional derive 358x234/34137 active cells
(4x `glb_06min`'s 179x118/8573, matching the resolution ratio again), 1988
run 25m25s (`--mem=16G` was enough; needed `--time` above `sbatch`'s
default 30 min headroom is thin -- gave it 30 min and it finished with
~5 min to spare). All 34137 active cells produced finite discharge (100%),
non-physical-negative-discharge rate 0.11-0.14% (closer to `glb_15min`'s
0.13% than `glb_06min`'s own 0.20-0.21%), worst-case magnitude -2.9 to
-3.0 m3/s, and peak discharge on major rivers (~1090 m3/s) matched
`glb_06min`'s (~1089 m3/s) closely -- a good cross-resolution consistency
check.

`glb_01min` (1 arcmin, the native resolution of the underlying catchment
data) needed real fixes, not just a bigger time budget:

- **Global build**: `rivseq`/`i1seq` inside `calc_outclm.py` (via
  `cython_ext.calc_1d_seq_rivseq`) each took ~2h45m against the full
  55.8M-point global river network -- a ~59x slowdown over `glb_03min`'s
  167s for what's only a ~9x bigger network, i.e. this step is
  worse-than-linear at this scale. Total global build: 5h39m under
  `--mem=128G` (peak 34.7GB) and `--time=20:00:00`.
- **Regional derive**: failed outright the first time -- `EC_MEMKILL`
  (ECMWF's cgroup memory watchdog; it applies to `sbatch` jobs too, not
  just the interactive login node) even under `--mem=128G`. Root cause: a
  real bug, now fixed -- see the `NMAX`/`derive_cmf_weights.sh` note
  right above the resolution case table. The wildcard default (`NMAX=100`)
  silently sized an allocation off the *global* `FIXDIR` grid
  (10800x21600 at this resolution), not the clipped regional one, trying
  to allocate a ~186GB array before doing any real work. Fixed by adding
  an explicit `glb_01min) NMAX=10` case (observed max actually needed:
  4) -- any future finer-resolution case must size `NMAX` the same way,
  not fall through to the wildcard. After the fix: 9m58s, grid
  1067x697/306420 active cells (~9x `glb_03min`, matching the resolution
  ratio).
- **Single-year run**: also needed far more than the `sbatch` default --
  an 8-hour attempt got killed by the time limit only 53% of the way
  through 1988 (reached day 195 of 366), extrapolating to ~15h for the
  full year (a ~36x slowdown over `glb_03min`'s 25 minutes, from ~9x more
  active cells compounding with a much smaller CaMa-Flood adaptive
  substep at this grid spacing -- `NT=83` substeps per hourly coupling
  step, vs. far fewer at coarser resolutions). Resubmitted at
  `--time=20:00:00`; not yet complete as of this note -- update this
  section (or move this bullet up to a validated one) once it finishes
  and the discharge output has been checked the same way as the other
  three resolutions.

### Two ecland-side source patches required

Both are in the **`ecland` repo**, not this one -- a fresh `ecland`
checkout will not have them; re-apply before deriving weights or running
with `LECMF1WAY` on. (Committed there alongside this repo's changes; see
that repo's own history for the exact diffs.)

1. **`src/surf/offline/driver/cnt41s.F90`** -- a real memory-safety bug,
   independent of the domain-extension work above, required for *any*
   valid LIAISE CaMa-Flood run. The four `DO IST = 1, NLALO, NPROMA`
   loops in the `LECMF1WAY` runoff-coupling blocks (and their paired
   `IEND = MIN(IST+NPROMA-1,NLALO)`) iterate `NLALO` (full grid point
   count), but every array they touch (`ZBUFFOAUX`, `D1STSRO2` via
   `GDIAUX1S`, `VFCLAKE`/`VFITM` via `GPD`) is allocated/blocked from
   `NPOI` (active land points only; `NBLOCKS` computed from `NPOI` in
   `rdcoor.F90`). Fix: `NLALO` -> `NPOI` in both the loop bound and the
   `IEND` line, all four occurrences. Confirmed via the debug build
   (`ecland/build-debug/bin/ecland-master-dp`, built with bounds
   checking): before the fix, default `NPROMA=120` gave a clean crash
   (`Subscript #3 of ZBUFFOAUX has value 3 which is greater than the
   upper bound of 2`); a since-abandoned `NPROMA=400` workaround
   (documented in an earlier version of this file -- do not use it, it
   is wrong) avoided the block-count overrun but silently overran
   `ZBUFFOAUX`'s *first* dimension instead (368 > `NPOI`=235) in the
   non-bounds-checked release binary, i.e. silent heap corruption, not a
   fix. After the real fix, the default `NPROMA=120` runs clean with no
   workaround needed.
2. **`tools/create_forcing/scripts/osm_pyutils/cython_ext.pyx`** --
   `gen_inpmat_inp2riv_hres_reg` aborted (`raise ValueError`) on any
   1-arcmin pixel whose mapped index fell outside the `-igrid` (ecLand)
   reference grid. That's expected and harmless once basins are kept
   whole via `-e` above (a river cell's basin now routinely extends far
   beyond ecLand's own small grid, and such pixels simply have no local
   runoff to contribute) but crashed `gen_inpmat.py` outright. Fix:
   `raise ValueError(...)` -> `continue` (skip the pixel) at both bounds
   checks in `gen_inpmat_inp2riv_hres_reg`. Strictly additive -- every
   in-bounds pixel's contribution, and therefore every weight already
   validated before this change, is unchanged; verified via the
   area-conservation diagnostic (`<1e-13%` error on mapped cells, both
   before and after).

Also requires two further upstream data sources, referenced by path
(never committed):
- `CMFDIR` (default `/home/rdx/data/50r1/camaflood/static_network_nc_v2.1`):
  shared ECMWF 1-arcmin CaMa-Flood catchment maps, per resolution.
- `FIXDIR` (default a colleague's ECMWF work-area path -- not guaranteed
  permanent, override if it disappears): the matching global river-network
  fix files (`ncdata.nc`, `bifprm.txt`, `rivpar.nc`, `outclm.nc`,
  `mpireg.nc`).

`derive_cmf_weights.sh` builds the `create_forcing` Cython extension
automatically if missing *or stale* (older than `cython_ext.pyx`), so a
pre-patch `.so` is never silently reused.

### Running with CaMa-Flood coupled in

`namelist/input_cmf`

The CaMa-Flood namelist template, staged and patched per year by
`run/run_liaise_ecland.sh` alongside the ecLand namelist whenever
`LECMF1WAY` is on in `namelist/input`. CaMa-Flood is not a separate
executable: `ecland-master` calls into it in-process (see
`src/surf/offline/driver/cnt01s.F90` in the `ecland` repo), so the wiring
is entirely about staging its input files and namelist correctly, not
about launching anything extra.

Field naming and behaviour here were cross-checked against a real ECMWF
production run (`rd_jaan`'s coupled `surface_model` job) and verified by
actually running `ecland-master-dp` end to end (full 1988-2014 with hourly
coupling, see "Domain" and "Two ecland-side source patches" above), not
just the `ecland` repo's generic template -- notably:
- `IFRQ_INP`/`DROFUNIT`/`DT` (CaMa-Flood) all track ecLand's own
  `TCOUPFREQ` (coupling frequency, hours) -- *not* `TSTEP`. CaMa-Flood
  substeps adaptively (`LADPSTP=.TRUE.`) within each `DT`, but `DT` is
  not a free-standing nominal ceiling: CaMa-Flood requires its internal
  `DTIN` (= `IFRQ_INP*3600`) to be an exact multiple of `DT`
  ("`DTIN should be multiple of DT`", a hard startup check). Setting
  `DT == DTIN` (i.e. `TCOUPFREQ*3600`, same value as `DROFUNIT`) always
  satisfies that; `run_liaise_ecland.sh` derives all three from
  `TCOUPFREQ` each year rather than hold them as static values that
  could drift out of sync or violate this constraint (confirmed the hard
  way: a static `DT=86400` aborts as soon as `IFRQ_INP*3600 < 86400`,
  e.g. `TCOUPFREQ=1`).
- `CMPIREGNC` (MPI region map, `mpireg.nc`) is required in `&NMAP` even
  for a single-process run -- omitting it makes `RIVMAP_INIT` try to
  literally open a file named `"NONE"` and abort (`PROGRAM STOP!`). It
  must be a *single-region* map for a single-process run, not a plain
  clip of the global decomposition -- see "`mpireg.nc`: flattened to a
  single region" above; getting this wrong doesn't crash, it silently
  drops most of the domain's output.
- The observed restart-output filename convention is
  `restart<EYEAR><EMON><EDAY><EHOUR>.nc` (e.g. `restart2025092300.nc`),
  reconstructed from the (patched) CaMa-Flood namelist's own `NSIMTIME`
  end-date fields via the `nml_value` helper. Don't extract these fields
  with a plain `awk '{print $1}' | cut -d=` (as the upstream
  `ecland_run_model.sh` reference does) -- it silently breaks once a
  patched line has a space after `=`, which this repo's `sed_inplace`
  patches always do.
- `CRESTSTO` is kept as the fixed name `restartin_cmf.nc`; the script
  symlinks/copies the previous year's saved CaMa-Flood restart to that
  name, the same way it already does for ecLand's own restart via
  `RESTART_IN_NAME`.
- `-cinv` (1-way only, dummy inverse weights) in
  `derive_cmf_weights.sh` is deliberate, matching `LECMF2LAKEC=0` /
  `LECMF1WAY` (1-way) in `namelist/create_liaise_namelist.sh` -- 2-way
  coupling would need the weights regenerated with `COMPUTE_INV=true`.
- Neither driver script uses `srun` to launch `$ECLAND_EXE`, even when
  `srun` is available: invoking it as a job step from inside an
  already-running shell (interactive `run_liaise_ecland.sh`) or from
  inside the sbatch job itself (`run_liaise_ecland.slurm`) does not
  reliably inherit the shell's module-loaded environment on this
  cluster -- observed concretely as the step landing on its allocated
  node without `hpcx-openmpi`'s `LD_LIBRARY_PATH`, so `$ECLAND_EXE`
  fails to find `libmpi*.so` even with `srun --export=ALL`. Both scripts
  run the executable directly instead.

#### Validated so far: one year, not yet the full multi-year loop

With both `ecland`-side patches applied and the extended-domain,
single-region `cama_flood/data/` above, the default `NPROMA=120` (no
workaround needed -- see the `cnt41s.F90` patch note) ran **1988 alone**
(366 days, hourly coupling, `TCOUPFREQ=1`) cleanly: all 1405 active river
cells produced discharge (previously 11), both ecLand and CaMa-Flood
restarts were written, and the residual non-physical-negative-discharge
rate was 0.13% (see "Domain" above) -- concentrated at the Rhone delta's
bifurcation channels, a real hydraulic feature there, not a
domain-boundary artifact.

The only *multi-year* (1988-2014) run completed so far predates all three
fixes above (fragmented 522-cell domain, the `cnt41s.F90` bug, and the
since-abandoned `NPROMA=400` workaround that silently corrupted memory) --
**that run's output is invalid and must not be used or treated as a
baseline.** A full 1988-2014 run has not yet been redone against the
fixed setup; do that (and update this note with the result) before
relying on more than a single validated year.

## ecLand execution

`run/run_liaise_ecland.sh`
`run/run_liaise_ecland.slurm`

The annual workflow:
1. starts from `soilinit` for the first year;
2. runs one calendar year;
3. writes a restart;
4. uses that restart as input for the next year.

For a year with model timestep `TSTEP`:

    NSTOP = days_in_year * 86400 / TSTEP

This is intentional because the prepared forcing includes the extra endpoint
at next-year 01-01 00 UTC.

## Coding guidelines

- Preserve scientific logic unless explicitly asked to change it.
- Prefer small, auditable changes.
- Keep Bash scripts compatible with ECMWF Linux.
- Use `set -euo pipefail` in new Bash scripts.
- Add clear comments for non-obvious scientific or temporal logic.
- Keep paths configurable through environment variables where practical.
- Do not hard-code local generated data into Git.
- Validate year ranges, filenames, and required files before long runs.
- Do not change ecLand variable names or restart conventions without checking
  the model expectations first.
