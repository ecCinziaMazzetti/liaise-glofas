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
  fix files for the LIAISE domain, plus real river-gauge (GRDC) discharge
  observations for validating against it.

landbench/
  Real point (flux-tower) observations in the LIAISE region, pulled from
  the sibling `ifs-landbench` repository's FLUXNET Shuttle run.

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

The exception is `init_clim/data/soilinit`, `init_clim/data/surfclim`, the
files under `cama_flood/data/`, and `landbench/data/`, which are validated
reference/observation files tracked via Git LFS (see `.gitattributes`).
These are small, LIAISE-specific *derived* or *filtered* outputs, distinct
from the much larger upstream/global datasets they are built from (the
ECMWF `climate.v021` archive, the global CaMa-Flood static network data --
see `cama_flood/derive_cmf_weights.sh` -- and the `ifs-riverbench`/
`ifs-landbench` observation archives), which must never be committed. They
are also distinct from the gitignored `init_clim/work/`, `init_clim/output/`,
and `cama_flood/work/` directories,
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

#### Extended to 2024 (2026-09-13)

The archive now covers **1988-2024** (previously 1988-2014). The CDS
dataset behind `get_liaise_forcing_05_cds.sh`
(`derived-near-surface-meteorological-variables`, WFDE5-CRU-GPCC) itself
only covers "1979 to 2024" per its own catalog page as of this date --
2025 is not available yet and won't be until CRU/GPCC's own gauge-based
products catch up (WFDE5 bias-corrects ERA5 against them, so it inherits
their lag by design, not a limitation of this pipeline).

Ran as: `START_YEAR=2015 END_YEAR=2024 forcing/get_liaise_forcing_05_cds.sh`,
then `prepare_liaise_forcing_ecland.py --start-year 1988 --end-year 2024
--repeat-last-for-final-year --overwrite` over the FULL range (not just the
new years) -- necessary because 2014 was previously the archive's final
year and had a duplicated endpoint; re-running the full range gives it a
real one from 2015, and moves the duplicated-endpoint treatment to 2024
(now the actual final year, verified in the run log: "endpoint: duplicated
final timestep because next-year forcing was unavailable" appears only for
2024, every other year got "endpoint: appended first timestep from
<next-year>.nc").

Real bug found and fixed while extending: `get_liaise_forcing_05_cds.py`'s
main output variable was created with no compression at all (missing
`zlib=True, complevel=4, shuffle=True`, which `get_liaise_forcing_05.sh`'s
IPSL-mirror path does use) -- roughly doubled file size for no benefit
(confirmed: an uncompressed year was ~107MB vs ~56MB for an equivalent
compressed one). Fixed for future runs; not worth re-downloading the
already-fetched 2015-2024 raw data just to recompress (the fix only
affects new invocations of this script, and the absolute size difference
here is trivial against available storage) -- if it matters later,
`nccopy -d4 -s` on the existing files would fix it without re-downloading.

**Each CDS request downloads a global 0.5deg file (the 7-variable "cru"
request alone is ~12GB) and clips to the LIAISE region during assembly** --
so the transient raw download is much larger than the final per-year
output (~56-107MB), and per-request CDS queue time (the real bottleneck,
not local I/O or transfer -- observed 1-25 minutes per request, highly
variable) dominates wall-clock time far more than data volume does. A
transient `502 Bad Gateway` mid-download is normal CDS flakiness;
`cdsapi`'s own retry logic (up to 500 attempts) handles it without
intervention.

`forcing/scratch_mirror.sh` (new, same push/pull-only-what-you-need
pattern as `run/scratch_mirror.sh` and the sibling `plumber2-ecland`
repo's `scripts/scratch_mirror.sh` -- see either for the measured
PERM-vs-SCRATCH throughput numbers): pushes raw forcing + the prep script
to `$SCRATCH` for `prepare_liaise_forcing_ecland.py`'s pass (genuinely
I/O-heavy across the full multi-decade range, unlike the CDS download
itself, which gains nothing from `$SCRATCH` since it's queue-bound), pulls
back only the finished `forcing/WFDE5_CRU_GPCC_ecland/`.

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
  `--time=20:00:00` and got much further -- CaMa-Flood itself completed
  the entire year cleanly (reached 1988-12-31, wrote its own annual
  restart) -- but ecLand then died with SIGBUS (exit 135) at 12h13m
  elapsed, with no application-level error/traceback anywhere in the log.
  That signature (abrupt OS-level kill, no diagnostic, deep in very large
  I/O -- the daily CaMa-Flood output files are ~1GB each at this
  resolution) points to a one-off NFS/filesystem glitch during the final
  restart write, not a reproducible bug in the code or namelist (`/perm`
  itself had 159TB free at the time, so not a quota/disk-full issue).
  **Not retried** -- given the cost (12h+ per attempt) versus the marginal
  value over the already-validated glb_15min/06min/03min results, this
  was deliberately left unresolved rather than spending another ~12h on
  a plausibly-transient failure. The build and regional-derive steps
  above are still fully validated and usable; only the single-year
  discharge/water-balance check remains undone at this resolution. If
  revisiting, retry the run as-is first (same weights, same namelists,
  under `cama_flood/work_01min/` and the `liaise_cmf_test/` test harness)
  before assuming a real bug.

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
  `derive_cmf_weights.sh` is deliberate, matching `NCMF2LAKEC=0` (default,
  1-way) in `namelist/create_liaise_namelist.sh` -- 2-way coupling needs
  the weights regenerated with `COMPUTE_INV=true`. Note `NCMF2LAKEC` is an
  *integer* namelist parameter (matches the Fortran name in `ecland`'s
  `YOEPHY` exactly) and, like every other `N`-prefixed integer in
  `create_liaise_namelist.sh` (`NCSS`, `NCWS`, `NDLEVEL`, ...), is set via
  an identically-named env var -- `NCMF2LAKEC=2`, not `LECMF2LAKEC=2`. The
  `LE`-prefixed alias convention used elsewhere in that script only
  applies to *logical* flags (`LECMF1WAY` among them); don't extend it to
  this one -- a same-session attempt to "fix" a perceived naming mismatch
  here by aliasing `NCMF2LAKEC` to `LECMF2LAKEC` was itself wrong and was
  reverted (see git history, `d5480bc`).
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

#### 2-way coupling (`NCMF2LAKEC=2` / `LWEVAP=true`): does it increase evaporation?

Yes, validated at `glb_15min`, single year 1988, `LECMF1WAY=true` (always
required to turn coupling on at all -- see the `NCMF2LAKEC` bullet above)
with `NCMF2LAKEC=2` ("add" mode: CaMa-Flood's floodplain fraction is
added to ecLand's own lake-tile cover, `VFCLAKEF`, over land points --
`cnt41s.F90`) and CaMa-Flood's own `LWEVAP=true` (extracts evaporation
from its floodplain storage, `namelist/input_cmf`). Requires weights
re-derived with `COMPUTE_INV=true` (real inverse mapping; the committed
`cama_flood/data/` only has dummy 1-way weights).

Two independent, distinguishable increases, against a 1-way/`LWEVAP=false`
control run generated the same way:
- ecLand's own open-water evaporation (`EWater` in `o_eva.nc`, needs
  `LPROD=.TRUE.` -- the default -- since this test cares about ecLand's
  own output, unlike the resolution-scaling tests above) rose ~19.5%
  domain/year mean. The other evap components (`ECanop`, `TVeg`, `ESoil`,
  `SubSnow`) barely moved (<0.06%), so this is a clean, isolated signal
  from the added lake fraction, not noise.
- CaMa-Flood's own floodplain evaporation (`o_wevap.nc`) goes from
  *zero time records written at all* under `LWEVAP=false` (the variable
  exists in the namelist but nothing is extracted) to a fully populated
  366-day field under `LWEVAP=true` (domain mean 0.0023 m3/s, peak 10.7
  m3/s across active cells) -- a wholly separate loss term that doesn't
  exist in 1-way mode.

Total domain evap barely shifts (+0.08%) because open water is a small
tile fraction here -- the effect is real but localized to lake/floodplain
cells, not a domain-wide signal.

### CaMa-Flood-GPU coupling prep: `cama_flood/inpmat_to_cmfgpu_npz.py`

Separate from the Fortran `ecland`/`LECMF1WAY` coupling documented above,
there's an independent effort (2026-09) to couple CaMa-Flood to
`ecLandPy` (`/perm/pad/eclandpy`, a from-scratch Python port), using
**CaMa-Flood-GPU** (`/etc/ecmwf/nfs/dh2_perm_a/pad/CaMa-Flood-GPU`, upstream
`Kshy0/CaMa-Flood-GPU` -- not a repo we own, so its own toolchain/run notes
live in this session's Claude memory rather than a CLAUDE.md there) instead
of the Fortran model. That model is a from-scratch PyTorch/Triton/CUDA
reimplementation with its own runoff-mapping format: a CSR sparse `.npz`
(schema `hydroforge.spatial_mapping.v2`), not `inpmat.nc`.

`cama_flood/inpmat_to_cmfgpu_npz.py` bridges the two: it re-encodes this
repo's already-validated `inpmat.nc` weights into that `.npz` format,
rather than re-deriving the interpolation from scratch against
CaMa-Flood-GPU's own map package.
```
python3 inpmat_to_cmfgpu_npz.py \
    --inpmat data/inpmat.nc --ncdata data/ncdata.nc \
    --out runoff_mapping_liaise.npz \
    --out-inverse runoff_mapping_liaise_inverse.npz
```
- **Forward** (ecLand grid -> CaMa-Flood catchment): recovers each target
  cell's *global* CaMa-Flood grid index (`catchment_id = ix*ny+iy`, matching
  `cmfgpu.params.merit_map.MERITMap`) by inverting `inpmat.nc`'s own
  regular-grid lat/lon cell-center coordinates, rather than depending on
  `derive_cmf_weights.sh`'s ephemeral `work/clip_cama_ix0_iy0.txt` offset.
  Validated: 1026/1026 LIAISE catchments' re-derived area matched
  `ncdata.nc`'s own `ctmare` at 0.000% difference.
- **Inverse** (`--out-inverse`, for a future 2-way path): `inpmat.nc`'s own
  `inpaI/inpxI/inpyI` are dummy-filled here (same root cause as the
  `COMPUTE_INV=true` requirement noted above -- this repo's committed
  `cama_flood/data/` only has 1-way weights). Rather than re-run the full
  `CMFDIR`/`FIXDIR` pipeline, the script computes the exact same result a
  real `-cinv` run would: reading `gen_inpmatI_reg` in `cython_ext.pyx`
  confirms the real inverse is *only* a transpose of the forward
  `(inpx, inpy, inpa)` link table (duplicate-summed), so transposing the
  already-built forward CSR matrix reproduces it exactly, with no extra
  1-arcmin data needed. Verified: `forward - inverse.T` is exactly zero,
  and total linked area is conserved exactly across both directions.
  Caveat (inherent to the data, not this script): a source cell's summed
  `coverage` can exceed its own physical area, because the forward map's
  `fix_area()` rescales each *target* catchment's area independently to
  match `ctmare` -- not constrained to keep any shared source cell's total
  under its true area. The real `-cinv` output would show the same
  property, since it transposes these same post-correction arrays.
  Documented in the script's own `metadata_json` (`coverage_caveat`) so it
  travels with the file.
- No 2-way-coupling consumer exists yet in `cmfgpu` (checked by grepping
  its source for "inverse"/"reverse"/"2-way" on 2026-09-12) -- the inverse
  `.npz`'s schema (`cmfgpu_liaise.spatial_mapping.inverse.v1`) is this
  script's own proposal, not an established Hydroforge convention.

### First CaMa-Flood-GPU run on the LIAISE domain: validated, 2026-09-12

Ran CaMa-Flood-GPU end-to-end on LIAISE for year 2000, driven by ecLand's
own runoff -- not just the weight conversion above, an actual regional
simulation. Three real correctness issues were caught and fixed along the
way; read these before trusting or extending this pipeline.

**The pipeline** (all in `cama_flood/`, paired with a driver script kept in
the CaMa-Flood-GPU checkout's own gitignored `scripts_user/` --
`run_liaise_2000.py` there, not committed here):
1. `subset_parameters_for_liaise.py`: slices CaMa-Flood-GPU's GLOBAL
   `parameters.nc` (built once via its own `make_map_params.py` against the
   official `cmf_v430_pkg` map package, glb_15min) down to a self-contained
   LIAISE regional network.
2. `inpmat_to_cmfgpu_npz.py --ncdata ...`: the runoff mapping (now extended
   to the full domain -- see below).
3. `prepare_liaise_runoff_for_cmfgpu.py`: `Qs - Qsb` from
   `run/output/2000/o_wat.nc` into a single-variable NetCDF.
4. `run_liaise_2000.py` (CaMa-Flood-GPU checkout): drives the model,
   `base` + `adaptive_time` modules only (bifurcation dropped for this
   first pass -- see `subset_parameters_for_liaise.py`'s docstring).
5. `export_liaise_daily_discharge.py`: hourly -> daily discharge, keyed by
   `catchment_id`/`longitude`/`latitude`, for comparison against a Fortran
   reference (e.g. `o_totout.nc`).

**Issue 1 -- domain size: 1026 vs 1405 catchments.** `MappingTable._local()`
(Hydroforge) hard-errors unless every catchment the model loads is present
in the mapping's `target_ids`. The model needs the FULL `ncdata.nc`
`ctmare > 0` footprint (1405 catchments -- matches the "1405 active river
cells" figure documented above for this exact domain), but `inpmat.nc`
itself only links the 1026 cells with a direct ecLand-grid overlap; the
other 379 are real routing-only cells (inside the extended domain, outside
the ecLand grid's exact box). Fixed in `inpmat_to_cmfgpu_npz.py`: when
`--ncdata` is given, it now extends `target_ids` to the full active
footprint with all-zero rows for the 379 (correct -- they truly get zero
local runoff). Verified: downstream connectivity of the full 1405-cell set
closes with **zero leaks** against the global network (every catchment's
`downstream_id` is either a self-referencing mouth or another catchment in
the set) -- confirming 1405, not 1026, is the right self-contained domain.

**Issue 2 -- sign convention bug, caught before it drove the model.**
`Qs` (surface runoff) is a positive outward flux, but `Qsb` (subsurface
runoff) is signed as a NEGATIVE soil-column-loss term in ecland's own
water-budget convention. Naively computing `Qs + Qsb` gives max()==0.0
across the entire year (63.8% of all values negative) -- an unmistakable
tell, caught by checking the preprocessed data's own summary stats before
running anything. `Qs - Qsb` gives min==0.0 exactly (zero negative values,
any cell, any hour, all year) and a domain-mean annual depth of ~230
mm/year -- physically plausible for this Mediterranean-influenced region,
and independent confirmation the fix is right. See
`prepare_liaise_runoff_for_cmfgpu.py`'s docstring.

**Issue 3 -- unit_factor.** The bundled CaMa-Flood-GPU scripts' `e2o_ecmwf`
example uses `unit_factor=86400000` for accumulated-mm/day source data.
`o_wat.nc`'s `Qs`/`Qsb` are already a rate (`kg m-2 s-1`), so the correct
factor is `1000.0` (`NetCDFDataset` DIVIDES by it: kg/m2/s / 1000 = m/s;
the area-multiply to m3/s happens separately via the mapping regrid).
Using `86400000` here would have silently under-forced the model by a
factor of 86400 -- not an error, just quietly wrong output.

**Result**: 8783 hourly steps (one hour short of the full year --
`o_wat.nc`'s last record is a shared year-boundary endpoint that would
otherwise need a `runoff_2001.nc`; dropped rather than duplicated, see
`run_liaise_2000.py`), ~65s wall clock on 1x A100. Daily discharge: mean
57.3 m3/s, peak 7754 m3/s (plausible for the Rhone-scale rivers this
extended domain includes), 0.57% of hourly values negative -- same order
of magnitude as the Fortran `LECMF1WAY` reference's 0.13% (see "Validated
so far" above), plausibly higher here specifically because bifurcation
(which stabilizes flow near the Rhone delta) isn't open in this pass.

**Not yet done** (as of writing the above): no bifurcation module (would
need path-endpoint filtering added to `subset_parameters_for_liaise.py`,
mirroring its gauge filtering); no direct numeric comparison against a real
Fortran `LECMF1WAY` discharge output. Both addressed next -- see below.

### GPU-vs-Fortran discharge comparison (2026-09-12): ~2x bias, explained

A parallel session ran the Fortran `LECMF1WAY` reference for the same year
(2000) and compared discharge at 7 points along the Ebro main-stem against
the GPU run above (matched by each side's own local discharge maxima,
within 0.3 deg -- plain nearest-neighbor lat/lon matching was unreliable,
occasionally snapping to an off-channel tributary catchment).

**Result**: strong temporal agreement (correlation 0.67-0.96 at all 7
points -- both models see the same storm-driven flow events, correctly
timed) but a systematic **~2.0-2.1x GPU-over-Fortran discharge bias** at 5
of 7 points (the other 2, closely spaced, ~1.2x -- both snapped to the same
coarse Fortran cell, likely a matching-resolution artifact rather than a
separate effect). Basin delineation itself checks out on both sides
(`upstream_area` at the Ebro-mouth catchment: 84,737 km2, matching the real
Ebro basin almost exactly).

**Root cause, confirmed quantitatively, not just plausible**: channel
width. `river_width` in the GPU's `parameters_liaise.nc` (from
`cmf_v430_pkg`'s `rivwth_gwdlr.bin`) runs systematically narrower than the
Fortran side's `rivwth` (`cama_flood/data/rivpar.nc`, built from the older
`CMFDIR=static_network_nc_v2.1`). Checking `cmfgpu`'s own routing kernel
(`cmfgpu/phys/triton/outflow.py`): `Q = width * depth *
(1/manning)*sqrt(slope)*depth^(2/3)`, and storage ~= width*length*depth, so
**at fixed storage, Q is proportional to width^(-2/3)** -- narrower
channel, higher discharge, by construction of the physics, not a bug. At
catchment 519315: Fortran `rivwth`=90.53m vs GPU `river_width`=37.94m
(ratio 2.39x) predicts a discharge ratio of 2.39^(2/3) = 1.79x; the
measured ratio there is 2.12x -- same direction, right order of magnitude.

**It's not a simple "wrong file" fix, though.** Checked three width
sources across all 7 points, not just the two `rivwth_gwdlr.bin` vs
`rivwth` values that first flagged this: `cmf_v430_pkg`'s raw
`width.bin` (unprocessed satellite width) and its own `rivwth.bin`
(power-law-only estimate), against the Fortran side's `rivwth` (final,
satellite-fused) AND `rivwth_par` (power-law-only, pre-fusion). None of the
GPU-side width fields consistently matches the Fortran side's -- at one
point raw `width.bin` matches Fortran `rivwth` almost exactly (256.76 vs
256.76), at others it's wildly different (100.30 vs 210.68). Even the
power-law-ONLY estimates differ by ~5x between packages (Fortran
`rivwth_par` ~181m vs the v4.30 package's own `rivwth.bin` ~24-38m at
these points) -- so the whole channel-geometry parameterization pipeline
differs between the `static_network_nc_v2.1` FIXDIR and the `cmf_v430_pkg`
test package, not just which satellite-width file got picked. There's no
one-file swap that would reconcile them.

**Conclusion**: real, expected uncertainty between CaMa-Flood map-package
vintages (channel width is one of the least-constrained global CaMa-Flood
parameters) -- not a bug in either the Fortran or GPU implementation, and
not something to "fix" by tweaking either pipeline's code. A width-neutral
comparison would need both runs built from the SAME map-package vintage,
which isn't a config flag -- it means regenerating one side's parameters
from the other's source data (e.g. running `subset_parameters_for_liaise.py`
against a `parameters.nc` built from the `static_network_nc_v2.1`-era raw
map files instead of `cmf_v430_pkg`, if those are still available; or
reprocessing the Fortran `rivpar.nc` from `cmf_v430_pkg`'s inputs).
Full comparison data (7-point time series, correlations, ratios) is at
`/perm/pad/liaise_discharge_compare/fortran_vs_gpu_comparison_v2.json` and
a plot at `.../fortran_vs_gpu_ebro_2000.png` (both outside this repo, not
committed data).

### CaMa-Flood-GPU river-storage spin-up + 5-year run (2026-09-12)

The single-year GPU runs above (2000) all started `river_storage`/
`river_depth` from zero -- `parameters_liaise.nc`'s `init_state` fields are
zero since it's sliced from a freshly-built `parameters.nc`, with no
restart mechanism used. This is the CaMa-Flood-side counterpart of a gap
the paired Fortran runs also had for ecLand's own land state (fixed there
via `run_liaise_ecland.sh`'s new `INITIAL_RESTART`/`INITIAL_RESTART_CMF`
env vars) -- the driving runoff (`run/output/<year>/o_wat.nc`) comes from
ecLand's own continuous 1988-2014 restart chain so the LAND state feeding
CaMa-Flood-GPU was already realistic, but CaMa-Flood's own river storage
was not.

**Fix, verified to matter**: `scripts_user/run_liaise_year_spinup.py`
(CaMa-Flood-GPU checkout) runs the same year twice in one process --
`model.save_state()` returns a complete `InputProxy` (topology + params +
end-of-run state) fed directly into a second `CaMaFlood` construction, no
restart file needs to be written to disk for this. Checked on 2000: pass 1
vs pass 2 domain-mean discharge diverges sharply early (day 1: 12.7 vs
112.9 m3/s) and converges to bit-for-bit identical by year-end (both
108.01 m3/s in the last week) -- confirms the cold start is a real,
multi-month transient bias, not a rounding difference, and that the model
does reach the same steady dynamics regardless of starting condition.

**Ran all 5 comparison years this way** (1988, 1995, 2000, 2003, 2005 --
same years as the multi-year GRDC skill benchmark below): pass 2's daily
discharge, keyed by `catchment_id`/lon/lat, is at
`/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_<year>_discharge_daily_spunup.nc`
-- use THESE, not the earlier non-spun-up `liaise_<year>_discharge_daily.nc`
files, for any skill/bias comparison against real observations or the
Fortran reference. Domain-mean effect is modest annually (e.g. 2000: 57.3
-> 58.7 m3/s, +2.4%) since it dilutes across 1405 catchments of very
different response times, but will matter much more for the 7 individual
GRDC-gauge comparison points during the first few months of each year --
check that explicitly rather than assuming the modest domain-mean shift
means it doesn't matter per-gauge.

2003 also produced a real, historically-grounded sanity check while
reviewing this: a sharp discharge spike (day 2003-12-03, peak 31,508 m3/s)
at catchment 531544 (4.84E, 43.33N) -- the Rhone delta near Arles/Camargue,
and early December 2003 is the real, well-documented Rhone flood event.
The hydrograph shape (smooth week-long rise and fall, not a runaway or
oscillation) and the adjacent catchment's negative value (531545, matching
the already-documented Rhone-delta bifurcation artifact) both confirm this
is genuine hydraulics being resolved correctly, not a numerical instability
-- worth knowing before anyone sees a ~30x-normal spike in this domain's
output and assumes it's a bug.

#### Bifurcation module enabled to match the Fortran reference (2026-09-12)

All GPU runs above had the `bifurcation` module OFF -- not for a physical
reason, just because `subset_parameters_for_liaise.py` originally dropped
all bifurcation data when clipping the regional domain. The Fortran LIAISE
runs have `LPTHOUT=.TRUE.` (bifurcation on, via this repo's own
`bifprm.txt`), so this was a real config gap between the two comparison
runs, not a capability gap -- `cmfgpu/modules/bifurcation.py` is a working
feature (CUDA/Triton/Metal kernels), not a stub.

Fixed: `subset_parameters_for_liaise.py` now filters bifurcation paths the
same way it already filters gauges -- kept where BOTH
`bifurcation_catchment_id` and `bifurcation_downstream_id` fall inside the
domain. **36 of 17242 global paths survive** into the LIAISE domain.
`run_liaise_year.py`/`run_liaise_year_spinup.py` now open `("base",
"adaptive_time", "bifurcation")`.

**One real bug hit and fixed along the way**: `model.save_state()` (needed
for the 2-pass spin-up) started failing with a NetCDF/HDF "Buffer is
uncompressible" error once bifurcation was added -- a known Blosc
small-buffer edge case, triggered by the new 36-element bifurcation arrays
under Hydroforge's default checkpoint compression (`blosc_zstd`,
`complevel=5`). Fixed by passing `checkpoint_netcdf_options={}` to
`CaMaFlood(...)` (checkpoint files are tiny regardless of compression, so
this has no real downside) -- not a bug in the bifurcation filtering logic
itself, a compression-library edge case exposed by it.

Reran all 5 years (2-pass spin-up, bifurcation on) -- daily discharge at
`/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_<year>_discharge_daily_spunup_bif.nc`
(use these, not the earlier `..._spunup.nc` files without bifurcation, for
any comparison meant to isolate the channel-width difference from
bifurcation on/off as a config variable). Domain-mean discharge and
negative-rate both shifted modestly and inconsistently by year (e.g. 2000's
worst negative improved, 260-352 -> 107 m3/s; 2003's worsened slightly,
1675 -> 1924 m3/s, during the real Rhone-flood event) -- not investigated
further here, since isolating the net effect on GRDC skill (the actual
question) is the next step, not a magnitude judgment on bifurcation alone
from the domain-mean numbers.

#### Tried v4.20 to close the channel-width gap: negative result (2026-09-13)

After the bifurcation rescoring left channel-width vintage
(`static_network_nc_v2.1` vs `cmf_v430_pkg`) as the sole remaining
explanation for Fortran's real-gauge advantage, the obvious next question
was whether running CaMa-Flood-GPU against `cmf_v420_pkg` -- the vintage
`static_network_nc_v2.1` is understood to actually correspond to --
would close it. Obtained `cmf_v420_pkg_20240430.tar.gz` (the official
site, `global-hydrodynamics.github.io/CaMa-Flood/`, still lists this exact
filename as "the main package" even though a newer v4.30 also exists in
the same Dropbox folder -- likely doc prose lagging a newer file being
added, not v4.20 being withdrawn). Rebuilt the whole chain against it
(`make_map_params_v420.py` -> `subset_parameters_for_liaise.py` ->
existing `runoff_mapping_liaise.npz`, reused unchanged since it depends
only on the glb_15min grid definition, not map-package content -- verified
by exact `target_ids` set equality) -- all 5 years, same 2-pass spin-up,
bifurcation on.

**Result: no difference at all.** `river_width` (`rivwth_gwdlr.bin`) is
**byte-identical** between `cmf_v420_pkg_20240430` and `cmf_v430_pkg_20260312`
-- confirmed by direct file diff/md5sum, not just spot-checking a few
catchments (also checked: raw satellite `width.bin` and even `nextxy.bin`,
the whole river network topology -- also byte-identical). Consequently the
v4.20-driven discharge output matches the v4.30 one to 3+ decimal places
at every GRDC gauge and at the original Ebro-mainstem comparison points.
Makes sense in hindsight: v4.30's own changelog entry is just "levee
parameter map: sample data and script prepared" -- nothing about revising
the base river network/width maps, so the underlying MERIT Hydro-derived
map dataset apparently hasn't changed since at least 2024-04.

**This reframes the whole channel-width finding**: it was never a
"CaMa-Flood-GPU package vintage" issue -- it's a genuine difference
between two independent width-generation PIPELINES that happen to be
paired with different package labels: ECMWF's own `static_network_nc_v2.1`
FIXDIR, built via `calc_rivpar.py`'s power-law-plus-satellite-fusion with
ECMWF's own calibration constants (`WC=10, WP=0.5, WO=0, WMIN=5`, per
`build_global_cmf_fixdir.sh`), versus upstream CaMa-Flood's own bundled
`rivwth_gwdlr.bin` (built by the Yamazaki lab via a separate method,
apparently stable across at least v4.20-v4.30). No CaMa-Flood-GPU package
download will touch this -- closing it for real would mean re-deriving one
side's width using the OTHER side's actual generation pipeline (e.g.
rerunning `calc_rivpar.py` against `cmf_v430_pkg`'s satellite width input,
or vice versa), not swapping which map package is used. Treating this as
the final word on "try a different CaMa-Flood vintage" -- the width
discrepancy stays a documented, unresolved cross-pipeline difference
rather than something either side's tooling can close by itself.

The v4.20-driven outputs are at
`/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_<year>_discharge_daily_v420.nc`
for completeness/reproducibility, but add no new information over the
v4.30 ones given the above.

### Real gauge observations: `cama_flood/extract_liaise_grdc_observations.py`

A third, independent validation arm alongside the Fortran-vs-GPU comparison
above: real river-gauge discharge, not just model-vs-model.

Source data (both "internal ECMWF assets" per `ifs-riverbench`'s own
README, at `/perm/pad/flood_cases/Stations/` on this filesystem -- not
redistributed by that repo or this one; only this script's small filtered
output is committed):
- The station metadata CSV (`allstations_v1.3.csv`), which conveniently
  carries each station's pre-computed CaMa-Flood glb_15min lookup cell
  (`Cama15lon`/`Cama15lat`/`Cama15area`) -- no fuzzy nearest-neighbor
  matching needed against `cama_flood/data/*.nc`.
- The Qobs archive (`Qobs_24_1980-2025_withcaravan.zarr`/`.nc`), daily
  discharge per station, keyed by `statid` (matches the CSV's `Id`).

**GRDC-only, basin-filtered, not just a lat/lon box.** Kept only stations
with `Source=="Caravan"` and `Provid` starting `GRDC_` -- the same
public-domain (Global Runoff Data Centre, via the GRDC-Caravan extension of
Caravan) filter `ifs-riverbench`'s own `prepare_public_bundle.py` uses to
decide what's safe to redistribute (see that repo's `2026-09-11` commit).
A naive Ebro-region bounding box is NOT enough on its own: several GRDC
stations that fall inside one are actually on entirely separate river
systems (Tagus, Turia, Jucar, Llobregat, Ter, Bidasoa all have gauges
nearby). The script instead matches each station's `Cama15lat`/`Cama15lon`
cell against `ncdata.nc`'s own `basin` field and keeps only stations
CaMa-Flood's own glb_15min network considers connected to the same basin as
the Ebro-mouth cell used in the discharge comparison above. A few real-world
Ebro tributaries with small catchments (under ~200 km2) don't survive this
filter -- glb_15min's coarse river-network delineation doesn't always
resolve them as connected to the main network; a genuine CaMa-Flood
resolution limitation, not a bug in the filter.

**Result**: 7 gauges survive, 1988-2014 daily discharge, saved to
`cama_flood/data/liaise_grdc_observations.nc` (Git LFS, 360KB): Cinca at
Fraga (9637 km2, mean 64 / max 1036 m3/s), Guadalope at Caspe (3780 km2,
mean 1.3 / max 319 -- low baseflow is real, this one's regulated), Jiloca
at Calamocha (1489 km2, mean 1.7 / max 17 -- also real, a karstic losing
stream), Cinca at Lafortunada (449 km2, mean 13 / max 133), Fortanete (274
km2, mean 1.5 / max 23), Arba de Luesia at Biota (142 km2, mean 0.4 / max
14), Vero at Lecina de Barcabo (102 km2, mean 1.1 / max 44) -- all
physically plausible for these specific, mostly semi-arid/karstic Iberian
tributaries.

One real bug caught while writing this script, worth remembering:
netCDF4's fixed-width `S1` char-array dtype silently garbles text if you
assign it a list of raw byte-integers (e.g. from `list(some_bytes_object)`)
-- each int gets cast through `str()` and truncated to one character
(byte 82 -> `"82"` -> `"8"`), corrupting every name with no error raised.
Fixed by using netCDF4's variable-length string type (`createVariable(...,
str, ...)`) instead, which needs no manual byte-padding at all.

### 5-year discharge skill benchmark: Fortran vs CaMa-Flood-GPU vs GRDC (2026-09-12)

`cama_flood/skill_benchmark_fortran_vs_gpu.py`

Answers the question the earlier model-vs-model comparison couldn't: not
just "do the two CaMa-Flood versions agree with each other" but "which one
is actually closer to reality." Scores both against the 7 real GRDC gauges
(`cama_flood/data/liaise_grdc_observations.nc`) for 5 years spanning the
observed flow range at those gauges -- 1988 (wettest), 2003 (2nd-wettest),
2000 (near-normal), 1995 (dry), 2005 (driest), chosen from the GRDC data's
own annual flow index, not assumed.

**Both sides needed a river-storage spin-up fix first**, caught by the user
asking about ecLand's own `NLOOP` spin-up convention (a real, documented
option in `ecland_run_experiment.sh`/`ecland_run_model.sh`, re-running a
period multiple times and chaining the restart so land and river state
equilibrate before the scored pass): every earlier single-pass Fortran run
in this file (including the original 2000 comparison) cold-started BOTH
ecLand's soil state and CaMa-Flood's river storage from scratch each year --
an asymmetric handicap versus the GPU side, whose driving runoff
(`run/output/<year>/o_wat.nc`) already came from ecLand's own continuous
1988-2014 restart chain (land state pre-spun-up), while CaMa-Flood-GPU's
own river storage was separately found to have the identical cold-start gap
(see "CaMa-Flood-GPU river-storage spin-up" above). Both now fixed with a
2-pass same-year spin-up: Fortran via `run_liaise_ecland.sh`'s new
`INITIAL_RESTART`/`INITIAL_RESTART_CMF` env vars (small, additive -- lets a
single-year run seed its starting restart instead of always cold-starting
from `soilinit`; land starts from the already-spun-up
`run/output/<year>/restart_in.nc` where available, 1988 excepted since it's
the first year of that chain), GPU via CaMa-Flood-GPU's own
`save_state()`/reconstruction (see that section). Verified this matters:
GPU's spin-up shifted 2000's domain-mean discharge from 57.3 to 58.7 m3/s
and, more importantly, fixed a multi-month cold-start transient concentrated
in exactly the early-year period the gauge comparison is sensitive to.

**Result** (KGE, correlation, PBIAS; `RIO GUADALOPE, CASPE` excluded from
these aggregates -- see below): **Fortran beats GPU on KGE in 19 of 25
station-years (76%)**, median KGE -0.155 (Fortran) vs -2.231 (GPU).
Correlation is similar between the two (median r 0.34 vs 0.41 -- GPU is not
worse at capturing *timing*), so the skill gap is a magnitude-bias story,
and the bias runs in OPPOSITE, consistent directions: Fortran
under-predicts almost everywhere (23/25 station-years negative PBIAS,
median -36%), GPU over-predicts more often than not (16/25 positive,
median +60%). This lines up exactly with the channel-width finding from the
single-year Ebro-mainstem comparison (`static_network_nc_v2.1`'s wider
channels vs `cmf_v430_pkg`'s narrower ones, `Q ~ width^-2/3` at fixed
storage) -- here it shows up as a real, measurable skill cost for the
narrower-channel (GPU) version at real gauges, not just a number the two
models disagree on.

Both models still struggle in an absolute sense at most of these gauges
(mostly negative KGE/NSE, i.e. neither beats a simple mean-flow benchmark)
-- expected, not a defect: these are small headwater/tributary catchments
(102-9637 km2, all but one under 4000 km2) being resolved by a 0.25deg
global river network whose grid cells are themselves comparable in size to
several of these basins. `RIO CINCA, FRAGA` (9637 km2, much closer to a
grid-cell-scale catchment) has the best skill on both sides, consistent
with this being a genuine resolution/scale-mismatch limitation rather than
a bug.

**`RIO GUADALOPE, CASPE` excluded from the aggregates above, not from the
raw results**: a heavily regulated river (dam/irrigation controlled), real
discharge is near-zero for long stretches in several of these years, which
sends KGE/NSE to astronomical negative values (variance-based metrics
divide by near-zero) -- a metric artifact, not a meaningful skill signal at
this specific gauge. Left in `skill_benchmark_results.json` for anyone who
wants it, just excluded from the printed medians.

Full per-station-year results at
`/perm/pad/liaise_discharge_compare/skill_benchmark_results.json` and a
summary plot at `.../skill_benchmark.png` (both outside this repo, not
committed data -- same convention as the earlier single-year comparison).

**Bifurcation, rechecked, changes nothing at these 7 gauges.** Once the
GPU side's bifurcation config gap was closed (see "Bifurcation module
enabled to match the Fortran reference" above), rescored with
`skill_benchmark_fortran_vs_gpu.py --gpu-suffix _bif`: the numbers above
are unchanged to 3 decimal places. Checked this wasn't a script bug by
diffing the two GPU discharge files directly at each of the 7 matched
catchments: bifurcation-on/off differs by ~1e-5 to 3e-4 m3/s at every one
of them (float noise) despite changing ~48% of the domain's 1405
catchments substantially elsewhere (max diff 2222 m3/s, near the Rhone
delta and other confluence points) -- none of these 7 Ebro
headwater/midstream tributary gauges are anywhere near one of the domain's
36 bifurcation paths, which is physically sensible (bifurcation is a
localized delta/braided-channel phenomenon). This is a genuine, useful
negative result: it rules bifurcation out as a contributor to the skill
gap, rather than leaving it as an open confound, and leaves the
channel-width/map-package-vintage difference (`static_network_nc_v2.1` vs
`cmf_v430_pkg`) as the sole well-isolated explanation for Fortran's
advantage here.

## Point observations: `landbench/`

`landbench/extract_liaise_landbench_sites.py`

Pulls FLUXNET Shuttle point (flux-tower) observations in the LIAISE region
from the sibling `ifs-landbench` repository (`/perm/pad/ifs-landbench`, 775
sites -- see that repo's own README), the point-observation counterpart to
`cama_flood/extract_liaise_grdc_observations.py`'s river discharge.

**Read the caveats in the script's own docstring before trusting or
extending this** -- unlike the GRDC river-gauge work, there is no
equivalent hard cross-check here:

- **Geographic relevance is unverified.** The river-gauge script could
  confirm relevance against CaMa-Flood's own basin topology (a checkable
  fact); point sites have no equivalent structure, only a bounding box
  (same LIAISE-region box as the discharge comparison: lat 40.5-43,
  lon -0.75-2.0). The 3 candidates this finds (`ES-LBr`/La Bertolina,
  `ES-PRt`/Pla de Riart, both woody savanna; `ES-VDA`/Vall d'Alinya,
  grassland) are all Pre-Pyrenees (~42.1N), north of LIAISE's core
  irrigated-agriculture supersite (Ivars d'Urgell / Els Plans de Sio,
  ~41.6-41.7N per published campaign descriptions), and none are irrigated
  cropland. They may be legitimate LIAISE contrast sites (the campaign
  studies irrigation-driven land-atmosphere heterogeneity against
  surrounding rainfed/natural vegetation) or simply nearby-but-unrelated
  FLUXNET towers -- confirm against an actual LIAISE site list before
  treating either as an official campaign observation.
- **Only `ES-VDA` has materialized data** (forcing, `surfclim`/`surfinit`,
  flux, and soil moisture/temperature, all copied to `landbench/data/ES-VDA/`,
  Git LFS, ~5.8MB total). `ES-LBr`/`ES-PRt` are metadata-only in
  `ifs-landbench` -- building them needs the FLUXNET Shuttle CLI, network
  access, and (for physiography) an ECMWF account; not attempted here.
- **No overlap with the main domain runs' forcing period.** `ES-VDA`'s data
  is 2023-2024 (soil: 2022-2024); the LIAISE ecLand domain runs documented
  above use 1988-2014 WFDE5-CRU-GPCC. Comparing this site means a separate,
  standalone point run using its own bundled `surfclim`/`surfinit`/forcing
  -- not extractable from the existing domain output.

**Not yet done**: no ecLand point run at `ES-VDA` has actually been made or
scored against its flux/soil observations -- this is the input bundle only.

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
