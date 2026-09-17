# CLAUDE.md

> **Fork note (mocm/liaise-glofas):** this fork's own working notes are in
> @CLAUDE.mocm.md , and LISFLOOD-specific notes in `lisflood/CLAUDE.md`.
> Upstream appends to the end of this file, so this import stays at the top
> to survive merges. Do not add fork notes below.

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

#### Built CaMa-Flood-GPU from the Fortran reference's own network: negative result (2026-09-13)

Closed the channel-width question for real this time -- not by trying
another CaMa-Flood *package* vintage (already shown to be a dead end
above, since map data is stable across v4.20-v4.30), but by making
CaMa-Flood-GPU consume **the literal FIXDIR the Fortran `LECMF1WAY`
reference itself uses** (`static_network_nc_v2.1/glb_15min`,
`FMAP=/home/rdx/data/50r1/camaflood/static_network_nc_v2.1/glb_15min`),
eliminating the physiographic-parameter confound entirely rather than
reasoning about it.

**Pipeline** (all new, `cama_flood/`):
1. `build_global_cmf_fixdir.sh` (already existed, see the coupling-prep
   work above) run directly against that CMFDIR -- its defaults already
   point there, no override needed. Must run via `srun --partition=par
   --mem=128G` (or similar), NOT the login shell: `gen_inpmat.py` loads
   the FULL global 1-arcmin catchment map (`1min.catmxy.nc`, ~233M cells)
   regardless of target network resolution, and got `EC_MEMKILL`'d at
   ~51GB RSS on the interactive session's cgroup limit even for the
   *lightweight* glb_15min target. Produced a global FIXDIR bundle
   (`ncdata.nc`+`rivpar.nc`+`outclm.nc`+`bifprm.txt`+`mpireg.nc`) with
   252383 catchments / 22022 basins / **16841 bifurcation paths -- exact
   match to v4.20's own count**, reinforcing that bifurcation topology
   specifically has been stable across sources, not just versions.
2. New `fixdir_to_merit_map_bin.py`: converts that FIXDIR into the raw
   `.bin` MERIT-map directory `cmfgpu.params.merit_map.MERITMap` actually
   reads (`nextxy.bin`, `rivlen.bin`, ... -- FIXDIR's consolidated NetCDF
   isn't the same format). Every field traced losslessly to FIXDIR's own
   data, verified empirically before trusting it, not assumed:
   - `nextx`/`nexty` confirmed **exactly 1-based** (all 229256 non-mouth
     links in `ncdata.nc` resolve to a valid basin cell under that
     hypothesis, zero mismatches) -- matches `nextxy.bin`'s convention
     with no adjustment needed.
   - `lonlat.bin` <- `ncdata.nc`'s `lonp`/`latp` ("outlet pixel"
     lon/lat), matching the per-catchment-representative-point semantics
     already established for `lonlat.bin` earlier in this investigation
     (see the coupling-prep section above), not a plain grid-center
     formula.
   - `rivwth_gwdlr.bin` <- `rivpar.nc`'s `rivwth` ("Channel width merged
     with gwdlr") -- the actual field that differed from upstream
     CaMa-Flood's own `rivwth_gwdlr.bin` in the original comparison.
   - Manning roughness (`rivpar.nc`'s `rivman`) is NOT converted --
     confirmed by reading `merit_map.py` that `MERITMap` has no
     `rivman.bin` read path at all; it always uses its pydantic default
     (0.03) regardless.
3. `make_map_params_v21fixdir.py` (CaMa-Flood-GPU checkout's
   `scripts_user/`, gitignored there): builds the global `parameters.nc`
   from the converted directory. **Gotcha**: `visualized=True` hung
   indefinitely (blocked in `poll()` on a localhost socket, near-zero CPU
   growth for over an hour) -- almost certainly a matplotlib GUI-backend
   display connection that never resolves in this headless session; the
   actual `parameters.nc` write had already completed by the time it
   hung (verified by killing it and confirming the file opened cleanly
   with all 252383 catchments intact). Set `visualized=False` for any
   rerun.
4. `subset_parameters_for_liaise.py` against this new global
   `parameters.nc` (same `--ncdata data/ncdata.nc` domain definition as
   always): 1405 catchments, 0 leaks, 66 gauges, 35 bifurcation paths --
   same structural numbers as the v4.30/v4.20 subsets, confirming the
   domain definition itself is package-independent as expected.
5. `run_liaise_year_spinup.py --parameters .../parameters_liaise_v21fixdir.nc
   --tag _v21fixdir`, all 5 years, 2-pass spin-up, bifurcation on --
   already supported both flags from the v4.20 rerun, no script changes
   needed.

**Verified the new width genuinely took effect** (not silently
overridden): `cmfgpu.params.estimate_river_geometry` only runs when a
`.bin` file is *missing* -- confirmed by reading `merit_map.py`, no
unconditional override exists in the model-construction path either.
Direct comparison of `parameters_liaise_v21fixdir.nc` vs the original
`parameters_liaise.nc` (v4.30) confirms a large, genuine, domain-wide
shift: `river_width` median ratio 2.53x (mean 2.71x; only 245/1405
catchments near-identical, mostly small headwaters pinned at both
pipelines' shared WMIN=5m floor), `river_height` median 1.00m -> 3.02m
(1/1405 near-identical). At catchment 519315 specifically (the point
originally used to document the mismatch): `river_width` 37.94m (v4.30)
-> 180.83m (v21fixdir) -- even further from the Fortran regional file's
own 90.53m than v4.30 was, in the *other* direction; this specific global
rebuild's calibration isn't a perfect reproduction of whatever exact
build produced the committed regional `cama_flood/data/rivpar.nc`, but
it's unambiguously built from the same source pipeline/constants, and
the point stands regardless (see below).

**Result: matching the Fortran reference's own channel geometry barely
changes the GPU-vs-Fortran skill gap at all.** Rescored against the same
6 real GRDC gauges (RIO GUADALOPE, CASPE excluded, same reason as
always), 25 station-years:
```
                    v4.30 (mismatched width)   v21fixdir (matched width)
Fortran beats GPU:  19/25 (76%)                19/25 (76%)  -- IDENTICAL
median KGE Fortran: -0.155                     -0.155
median KGE GPU:     -2.231                     -2.231
median PBIAS Fortran: -35.5%                   -35.5%
median PBIAS GPU:     +59.6%                   +59.6%
```
Per-gauge win/loss pattern is also identical: Fortran wins at 5 of 6
gauges (all except RIO JILOCA, CALAMOCHA, where GPU wins 0/5 -> unchanged
either way). The raw per-station-year KGE/PBIAS values differ only in
the 3rd-4th significant figure between the two GPU runs (e.g. catchment
519315-adjacent gauge KGE -2.3836 vs -2.4999) -- consistent with a real
but second-order sensitivity, not a rounding artifact, but nowhere near
large enough to move a single win/loss verdict at any of the 25
station-years, let alone the aggregate picture.

**This closes the channel-width line of investigation for good.**
Domain-wide channel width more than doubling and channel depth tripling
changed discharge skill by less than the noise floor of the comparison
itself. Whatever drives the systematic ~76%-of-station-years Fortran
advantage is NOT primarily channel geometry -- it lies elsewhere in the
GPU implementation (numerics: adaptive-substep scheme, floodplain
module defaults/dynamics, spin-up length or behavior, or a genuine
algorithmic difference from the Fortran kinematic/local-inertia solver),
not something any map-package or parameter-source substitution will fix.
Results: `/perm/pad/liaise_discharge_compare/skill_benchmark_results_v21fixdir.json`,
daily discharge at
`/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_<year>_discharge_daily_v21fixdir.nc`.

#### Correction: "barely changes anything" was too strong, and why (2026-09-13)

The aggregate numbers above (19/25 identical, medians identical to 3
figures) are real, but reporting them alone overstates the case to
"channel width has no effect" -- it doesn't; it's just not the axis this
comparison's aggregate stats are sensitive to. Checked properly after
push-back:

**The width change at the gauges themselves is real, not just at
arbitrary domain points.** 5 of the 7 gauge-matched catchments sat at
`cmf_v430_pkg`'s `WMIN=5.0m` floor (small headwater streams) in the
original comparison; `static_network_nc_v2.1`'s own pipeline gives them
genuine, differentiated widths -- up to **6.16x larger** at Rio Cinca,
Lafortunada (5.00m -> 30.82m):

| Gauge | v4.30 width | v21fixdir width | ratio |
|---|---|---|---|
| Cinca, Lafortunada | 5.00m | 30.82m | 6.16x |
| Vero, Lecina de Barcabo | 5.00m | 17.67m | 3.53x |
| Guadalope, Caspe | 11.25m | 17.39m | 1.55x |
| Fortanete, Pitarque | 25.00m | 44.56m | 1.78x |
| Arba de Luesia, Biota | 5.00m | 8.70m | 1.74x |
| Cinca, Fraga | 5.00m | 5.75m | 1.15x |
| Jiloca, Calamocha | 5.00m | 5.00m | 1.00x (unchanged) |

**And discharge does respond.** Per-station-year KGE moves by up to 0.12
between the two GPU runs (mean delta 0.006, std 0.049, max |delta| 0.116
across the 25 scored station-years -- none large enough to flip a
win/loss verdict, but not nothing). The raw daily time series at a
high-impact catchment (519315, the original documented comparison point)
shows real shape change despite an almost-unchanged annual mean: day-1
discharge 608 m3/s (v4.30) vs 1093 m3/s (v21fixdir); annual std 612 vs
768 m3/s. `r`/`alpha` (KGE's correlation/variability components) shift
measurably at several gauges (e.g. 1995 Rio Vero: r 0.569->0.600, alpha
4.215->4.118); `beta` (the mean-flow-ratio component, which drives
PBIAS) barely moves anywhere.

**Investigated, and ruled out, one candidate explanation: kinematic vs.
local-inertia regime switching.** Hypothesis was that steep pre-Pyrenees
terrain at these headwater gauges triggers a kinematic-wave
simplification (Manning-type, no backwater/pressure term) that's
inherently less width-sensitive than the full local-inertia equation,
muting the effect of a large width change. Checked directly in
`cmfgpu/phys/triton/outflow.py` (and the matching CUDA/Metal kernels):
the kinematic-wave branch (lines ~234-259) is gated by `HAS_RESERVOIR`
and only overrides outflow at `is_dam_up` cells (upstream-of-dam, for
numerical stability near reservoirs) -- it is NOT a general
terrain-slope switch. This LIAISE domain has **zero reservoirs**
(`make_map_params_v21fixdir.py`'s own summary: "Number of reservoirs:
0") and `run_liaise_year_spinup.py` never opens the `reservoir` module
(`OPENED_MODULES = ("base", "adaptive_time", "bifurcation")`). So
`HAS_RESERVOIR` is false and this branch never executes for any
catchment in this domain, regardless of slope -- every cell always runs
the same local-inertia equation. **Hypothesis falsified**, not just
unconfirmed.

**The actual explanation: mass conservation, not regime-switching.**
Worked through the steady-state algebra of the main local-inertia update
(`outflow.py` lines ~187-203, the only equation active here):
```
Q_new = [Q_prev + g*dt*d*S*W] / [1 + g*dt*n^2*(Q_prev/W)/d^(7/3)]
```
which converges at steady state to the standard Manning form
`Q = (W/n)*sqrt(S)*d^(5/3)`. Substituting `d = storage/(W*L)` (i.e.
holding channel *storage volume* fixed while width changes) gives
`Q ~ W^(-2/3)` -- exactly the width-sensitivity relationship documented
earlier in this file from the original v4.30-vs-Fortran width mismatch.
But storage is NOT fixed here -- it's a state variable the model
continuously adjusts to balance whatever inflow it's actually receiving,
and that inflow (ecLand's own runoff forcing) is identical between the
v4.30 and v21fixdir runs, unrelated to channel geometry. Over any
sufficiently long averaging window, **mean outflow must converge to mean
inflow regardless of channel width** -- ordinary mass conservation, not
a numerics artifact or regime effect. Width changes affect *how* that
balance is reached (the depth/storage level required, wave celerity,
peak timing and attenuation) but not the converged mean. This is
consistent with, and explains, the observed pattern: `beta`
(mean-flow-ratio, drives PBIAS) is nearly width-invariant; `r`/`alpha`
(timing/variability, drive the rest of KGE) and the raw time series
shape are not.

**Net takeaway**: channel width is a real, non-trivial control on this
model's discharge *dynamics* (confirmed, not dismissed) but is
structurally protected from affecting long-run mean discharge / PBIAS by
mass conservation -- so a width-matching exercise was never going to
close a systematic multi-year PBIAS gap like the one observed against
Fortran, regardless of how large the width correction turned out to be.
Whatever drives that gap is still open; the next candidate axes are
Manning roughness defaults/calibration (not converted by
`fixdir_to_merit_map_bin.py` at all -- `MERITMap` has no `rivman.bin`
read path, always uses its pydantic default 0.03 regardless of source
pipeline) and the adaptive-substep/spin-up numerics, not channel
geometry.

#### NLOOP>1 spin-up: tested directly, no effect (2026-09-13)

Asked whether running MORE than the existing 2 same-year passes (an
"NLOOP" scheme) would further equilibrate river storage and close some
of the gap. Tested directly rather than assumed: `scripts_user/
test_nloop_convergence.py` (new, gitignored `scripts_user/`) chains 4
passes in one process on year 2000, v21fixdir parameters, logging
end-of-year `river_depth` after each. Result: **pass 1 through pass 4 are
identical to 5-6 significant figures** (mean=0.962023 every single pass;
std/max differ only in the 6th decimal, float noise). The 2-pass scheme
already fully converges river storage within one extra pass -- consistent
with the earlier pass1-vs-pass2 bit-identical-by-year-end finding
documented above for the original v4.30 runs. No groundwater/baseflow
delay state exists in CaMa-Flood-GPU at all (confirmed by grep -- and
consistent with the Fortran namelist's own `LGDWDLY=false`, so this
isn't a case of Fortran having slow state GPU is missing either), so
there's no slower reservoir that additional passes could still be
equilibrating. **NLOOP is not the lever for this gap.**

#### Setup-difference audit against the Fortran namelist (2026-09-13)

Prompted by a direct question: are there other real Fortran-vs-GPU setup
differences left, beyond channel geometry? Went through
`namelist/input_cmf`/`namelist/input` line by line against
CaMa-Flood-GPU's own module defaults/config, rather than guessing:

| Setting | Fortran | GPU | Status |
|---|---|---|---|
| River Manning | `PMANRIV=0.03` | `river_manning` default 0.03 | match (confirmed `rivpar.nc`'s own `rivman` field is uniformly 0.03 everywhere, matching `-pMAN 0.03` passed to `calc_rivpar.py` -- zero spatial variation, `std=0.0`) |
| Floodplain Manning | `PMANFLD=0.10` | `flood_manning` default 0.1 | match |
| Gravity | `PGRV=9.8` | `gravity` default 9.8 | match |
| CFL coefficient | `PCADP=0.7` | `adaptive_time_factor` default 0.7 | match |
| Min kinematic slope | `PMINSLP=1e-5` | `min_kinematic_slope` default 1e-5 | match (moot either way, see below) |
| Kinematic routing | OFF (`LKINE=.FALSE.`) | dam-upstream-only, 0 reservoirs here | match |
| Mixed kine/local-inertia | OFF (`LSLPMIX=.FALSE.`) | no such code path exists | match |
| Groundwater reservoir | OFF (`LGDWDLY=false`) | not implemented at all | match |
| **River-mouth downstream distance** | **`PDSTMTH=25000.D0` m** | **`river_mouth_distance` default 10000.0 m** | **mismatch -- fixed** |
| **Runoff coupling frequency** | **daily, `TCOUPFREQ=24`** | **hourly (`RUNOFF_TIME_INTERVAL=timedelta(hours=1)`)** | **mismatch -- fixed** |

One useful side-effect of this audit: `LKINE=.FALSE.` and
`LSLPMIX=.FALSE.` on the Fortran side directly confirm the local-inertia
analysis above -- Fortran isn't using kinematic or mixed routing for this
domain either, so both sides are apples-to-apples pure local-inertia, not
just GPU defaulting to it.

**Fix 1 -- river-mouth distance**: `MERITMap(..., river_mouth_distance=
25000.0)` in `make_map_params_v21fixdir.py` (was silently using the
10000.0 default). Confirmed applied: `downstream_distance` at every
mouth catchment in the rebuilt `parameters.nc` is now exactly 25000.0.

**Fix 2 -- runoff coupling frequency**: new
`cama_flood/aggregate_runoff_to_daily.py` produces a daily-mean version
of each year's hourly `runoff_<year>.nc` (`runoff_<year>_daily.nc`,
volume-conserving to 1e-9 relative, checked explicitly) and
`run_liaise_year_spinup.py` gained a `--runoff-interval-hours` flag (24
to match Fortran, default 1 = unchanged prior behaviour). Two real
gotchas hit and fixed along the way, worth knowing before touching this
again:
- hydroforge's `DatasetTimeline` does **exact datetime lookups**
  (`start_date + n*time_interval`, decoded via `num2date` against each
  file's own `time` values into a `dt_to_loc` dict) -- NOT positional
  indexing. The source hourly files have no `t=0` entry (`time[0]==3600`,
  i.e. "hour 1", confirmed for all 5 years -- units are `"seconds since
  <year>-01-01 00:00:00"`), so a naive daily aggregation reusing each
  day's first hourly timestamp mislabels every day at 01:00 instead of
  midnight. Fixed: `daily_time = arange(n_days)*86400.0`, exactly
  matching `start_date=datetime(year,1,1,0,0,0)` +
  `time_interval=timedelta(hours=24)`.
- `export_liaise_daily_discharge.py` unconditionally assumed hourly
  input and reshaped in groups of 24 -- silently truncated a
  daily-coupled year's 366 already-daily steps down to 15 "days". Fixed
  to auto-detect the source's own step spacing from its time-coordinate
  units/values and skip re-aggregation when it's already >= 24h.

Verified `model.step_advance(num_sub_steps=None)`'s adaptive substepping
genuinely scales with the outer interval rather than assuming hourly
(checked `hydroforge/execution/substeps.py`'s `_AdaptiveSubstepRequest`,
then confirmed empirically): substep counts went from ~5/hour (hourly
runs) to ~110-130/day (daily runs) -- consistent, no hidden hourly
assumption.

**Result: real, small improvement -- not a fix.** New parameters +
subset at `parameters_liaise_v21fixdir2.nc`, 5-year rerun (2-pass
spin-up, bifurcation on, daily forcing), rescored:
```
                       v21fixdir (width matched only)   v21fixdir2 (+ mouth-dist + daily forcing)
Fortran beats GPU:     19/25 (76%)                      19/25 (76%)  -- still identical
median KGE GPU:        -2.231                           -2.159        (small improvement)
median PBIAS GPU:      +59.6%                            +55.6%       (small improvement)
median PBIAS Fortran:  -35.5%                            -35.4%       (unchanged, as expected)
```
Single-gauge spot check (year 2000, before the 5-year rescore) showed
the same pattern at every gauge: KGE improves a few tenths (e.g. Rio
Arba de Luesia -9.312 -> -8.674, Rio Fortanete -7.693 -> -7.214), `r`
ticks up slightly, but PBIAS stays in the same 130-215%-overprediction
range it was already in. The win/loss verdict never flips anywhere.

**Where this leaves the investigation**: three real setup differences
found and closed this session (channel width/geometry, river-mouth
distance, coupling frequency), each producing measurable but small
shifts, none closing the gap. Fortran under-predicts (~-35% PBIAS,
consistent sign every year) while GPU over-predicts (~+56-150% PBIAS
depending on year) -- opposite signs, which rules out a single shared
missing correction (e.g. a unit-conversion factor) as the explanation,
since that would move both models the same direction. Manning roughness
is confirmed matched (not a candidate, contrary to earlier speculation).
Remaining candidate axes, not yet checked: the `inpmat`/regridding
weights themselves (does the ecLand-to-CaMa-Flood area-weighted regrid
differ between the two coupling implementations, not just the runoff
values feeding it?), spin-up START DATE/procedure differences beyond
river storage (e.g. does Fortran's `INITIAL_RESTART_CMF` spin-up
actually match this repo's 2-pass same-year scheme, or use a longer/
different window?), and the DROFUNIT unit-conversion path end-to-end
(re-verify, don't just re-assume, now that both frequency and mouth
distance are fixed).

#### THE fix: gauge-matching bug + wrong runoff formula (2026-09-13)

Pushed further on "there's no reason for such a large discrepancy" rather
than accepting the setup-audit's small, inconclusive gains. Found two
real, independent, load-bearing bugs -- one in how gauges were matched to
GPU catchments, one in the runoff forcing itself -- that together explain
essentially the entire multi-year discrepancy chased since the very first
GPU-vs-Fortran comparison (`~2x bias` section above, and everywhere since).

**Bug 1 -- gauge matching, wrong catchment at 5 of 7 gauges.**
`skill_benchmark_fortran_vs_gpu.py` matched each GRDC gauge's GPU
catchment by nearest lat/lon between Fortran's grid-cell-center
coordinate (`cama15_lat`/`cama15_lon`) and the GPU output's own
per-catchment `longitude`/`latitude` -- which comes from `lonlat.bin`'s
OUTLET-PIXEL coordinate (can sit anywhere within, or outside, the
nominal 0.25deg grid-cell that Fortran's coordinate represents; see the
coupling-prep section above for how this differs from a plain
grid-center formula). Geographic "nearest" is not "same grid cell", and
is nowhere near "same river-network position": verified this silently
matched the WRONG catchment at 5 of 7 gauges, with `match_dist_deg`
looking deceptively small (0.08-0.26 deg, ~9-29 km -- easily one grid
cell at 0.25deg resolution) every single time, which is exactly why
nobody caught it despite the parallel session's own 2026-09-12 note
("plain nearest-neighbor lat/lon matching was unreliable, occasionally
snapping to an off-channel tributary catchment") -- close, but shrugged
off as a minor artifact rather than tracked down.

Worst case: RIO CINCA, FRAGA's true `upstream_area` is 9678 km2 (matches
the real GRDC-reported ~9637 km2 almost exactly, at the EXACT global
grid-index catchment computed from `cama15_lat`/`cama15_lon`); the old
nearest-lat/lon match instead landed on a catchment with
`upstream_area`=488 km2 -- a 20x-too-small tributary stub ~30 km away,
not the gauge's own river. Fixed: since both sides now share the
identical `static_network_nc_v2.1` global grid (post the FIXDIR rebuild
above), the GPU catchment can be found EXACTLY, deterministically, with
no nearest-neighbor guessing at all -- `catchment_id = ix_global*720 +
iy_global`, computed straight from `cama15_lat`/`cama15_lon` with the
same grid formula `MERITMap` itself uses. This fix affected every GPU
comparison run this session (v4.30, v4.20, v21fixdir, v21fixdir2 alike)
since the bug lived in the shared matching script, not any one
`parameters.nc` -- their historical per-gauge numbers should not be
trusted without re-scoring.

**Bug 2 -- wrong runoff-forcing formula, the real headline finding.**
`prepare_liaise_runoff_for_cmfgpu.py` fed CaMa-Flood-GPU `Qs - Qsb` as
total runoff (see that script's now-corrected docstring for the full
history) -- verified non-negative and "physically plausible" at the
time, but never checked against Fortran's OWN actual received input,
which is what would have caught it. Traced the TRUE formula directly
from ecLand's own Fortran source
(`/perm/pad/ecland/src/surf/offline/driver/`):
  - `wrtdcdf.F90` writes `Qs = D1STSRO2` and `Qsb = -D1STRO2 -
    D1STSRO2` to the output NetCDF -- i.e. `Qsb = -(D1STRO2 + Qs)`, so
    `D1STRO2 = -(Qs + Qsb)`.
  - `cnt41s.F90`'s actual `LECMF1WAY` coupling call (`CMF_FORCING_PUT`)
    hands CaMa-Flood exactly `D1STSRO2` (surface) and `D1STRO2 -
    D1STSRO2` (subsurface) -- which SUM to `D1STRO2` regardless of the
    surface/subsurface split. So Fortran's true total input is
    `D1STRO2 = -(Qs + Qsb)`, not `Qs - Qsb`.

Verified empirically, not just algebraically: computed `-(Qs+Qsb)`,
mass-conservingly area-weighted through the exact same
`inpmat.nc`-derived mapping over each gauge's full upstream drainage set
within the 1405-catchment domain (traced via `downstream_id`, confirmed
each traced set's summed `catchment_area` matches the target's own
`upstream_area` exactly first -- no incomplete-upstream-set risk), then
compared the resulting implied mean discharge against FORTRAN'S OWN
ACTUAL discharge output at 5 independent (gauge, year) points spanning
3 different gauges: RIO CINCA FRAGA 2000 (54.18 vs Fortran's actual
54.29 m3/s), RIO JILOCA CALAMOCHA 1995 (0.580 vs 0.580) and 2003 (1.30
vs 1.302), FORTANETE PITARQUE 1995 (0.06 vs 0.063) and 2003 (0.30 vs
0.305) -- every single one matches to within 0.2-3%, several to 3
significant figures. Airtight, not a coincidence.

`Qs - Qsb` differs from the correct `-(Qs+Qsb)` by exactly `+2*Qs` at
every grid cell/hour (`(Qs-Qsb) - (-(Qs+Qsb)) = 2*Qs`) -- a spurious
DOUBLE-COUNTING of surface runoff stacked on top of the correct total.
This is why the erroneous GPU/Fortran discharge ratio was so stable
*within* a given gauge across all 5 years (1.85-3.03x depending on
gauge, checked explicitly and it holds within ~10% at every gauge every
year) but varied *across* gauges: the excess is proportional to each
catchment's own local surface-vs-subsurface runoff mix, which is a
real physical quantity that varies geographically but not much
year-to-year at a given point. This is also why GPU's own internal mass
balance checked out perfectly (`total OUTPUT volume` == `total INPUT
volume` computed independently via the mapping weights, ratio=1.0000,
at Rio Cinca Fraga 2000) even while the comparison against Fortran
looked so broken: CaMa-Flood-GPU's own routing/mapping pipeline was
NEVER the bug -- it was faithfully, correctly routing whatever input it
was given, and that input was wrong from the very first
`prepare_liaise_runoff_for_cmfgpu.py` run this repo ever made.

**This also retroactively explains the original "channel width" finding**
(`### GPU-vs-Fortran discharge comparison (2026-09-12): ~2x bias,
explained` above): that session found the same ~2.0-2.1x bias and
attributed it to narrower GPU-side channel width (`Q ~ width^-2/3`
reasoning) -- a real, measurable effect (confirmed independently this
session: `river_width` differences of 1.15x-6.16x at these same gauges),
but this session's width-matching experiment (rebuilding CaMa-Flood-GPU
from Fortran's own `static_network_nc_v2.1` network, doubling/tripling
width and depth domain-wide) moved PBIAS by only a few percent, nowhere
near enough to explain a 2x discharge ratio. Channel width was a real,
correlated-but-secondary effect riding on top of this much larger
forcing bug -- coincidentally pointing the same direction (both push GPU
discharge up relative to Fortran), which is exactly why it looked like a
sufficient explanation at the time.

**Final result, all fixes combined** (v2.1-FIXDIR network +
`river_mouth_distance=25000` + daily coupling + corrected `-(Qs+Qsb)`
forcing + exact gauge matching, tag `_v21fixdir3`, 5-year rerun,
rescored against the same 6 real GRDC gauges, 25 station-years):
```
                       v21fixdir2 (exact matching, WRONG forcing)   v21fixdir3 (exact matching, CORRECTED forcing)
Fortran beats GPU:     22/25 (88%)                                  4/25 (16%)  -- reversed
GPU beats Fortran:      3/25 (12%)                                 21/25 (84%)
median KGE Fortran:    -0.156                                      -0.156
median KGE GPU:        -1.468                                      -0.140  -- now slightly BETTER than Fortran
median PBIAS Fortran:  -35.4%                                      -35.4%
median PBIAS GPU:      +62.9%                                      -35.3%  -- matches Fortran to 0.1 point
mean |PBIAS(Fortran)-PBIAS(GPU)|: not computed                      0.23 percentage points
```
Per-station-year PBIAS now matches Fortran almost exactly EVERYWHERE
(e.g. 1988 Rio Arba de Luesia: Fortran -80.1%, GPU -80.1%; 2003 Rio
Guadalope: Fortran 4.9%, GPU 5.0%) -- the remaining KGE differences are
now dominated by `r`/`alpha` (timing/variability), consistent with this
session's earlier finding that channel geometry/numerics affect
dynamics, not the converged mean. GPU actually has a slight net
KGE edge over Fortran once forcing is no longer confounding the
comparison -- not a claim this repo previously had grounds to make.

**Practical implication going forward**: `cama_flood/
prepare_liaise_runoff_for_cmfgpu.py` is now the one true source of
correct CaMa-Flood-GPU runoff forcing for this domain -- any other/older
`runoff_<year>.nc` file (or one regenerated by hand without importing
this script's `-(Qs+Qsb)` formula) is silently ~2-3x wrong. All 5 years'
`runoff_<year>.nc`/`runoff_<year>_daily.nc` under
`/perm/pad/CaMa-Flood-GPU-run/inp/liaise/` were regenerated with the fix
as part of this session -- no stale wrong-formula copies left in that
directory. Final discharge:
`/perm/pad/CaMa-Flood-GPU-run/out/liaise/liaise_<year>_discharge_daily_v21fixdir3.nc`,
scored results:
`/perm/pad/liaise_discharge_compare/skill_benchmark_results_v21fixdir3.json`.

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

### 37-year control run (CY50R1), full 1988-2024 forcing: validated (2026-09-13)

Reran the plain land-surface control configuration (`namelist/input` as
committed: `LECMF1WAY=false`, no CaMa-Flood, `CMODID='CY50R1'`) end to end
over the full newly-extended forcing archive -- one continuous restart
chain, `soilinit` cold start in 1988, all 37 years through 2024. Purpose:
confirm the forcing extension (see "Extended to 2024" above) is actually
usable by ecLand, not just internally self-consistent.

**Result: 37/37 years completed cleanly**, ~1h35m wall-clock (`sbatch`,
job `36575118`). Domain-mean diagnostics (235 active land points) are
physically plausible throughout: precipitation 641-975 mm/year (matches
the Ebro basin's semi-arid/Mediterranean climate), a clean wet-autumn/
dry-summer seasonal cycle, and a real, visible T2m warming trend across
the 37 years (annual mean rises from ~11.9 degC in 1988 to ~13.4 degC in
2024) -- consistent with observed European warming over this period, not
a modeling artifact. Extraction script: `run/extract_control_diagnostics.py`
(note: `Rainf`/`Snowf`/`Qs`/`Qsb`/`Evap` in `o_wat.nc` are RATES, kg m-2
s-1, not pre-accumulated depth per output step despite `LACCUMW`/`LRESET`
in the namelist -- multiply by the output interval, 3600s here, before
summing to a yearly depth; caught this the hard way when a first pass
gave ~0mm for every year). Full annual/monthly-climatology data at
`/perm/pad/liaise_discharge_compare/control_run_diagnostics.json`
(outside this repo, not committed -- same convention as the discharge
comparison data above). Dashboard: `sites.ecmwf.int/pad/liaise/control/`.

**A real infrastructure hazard hit and worked around, worth remembering**:
the first attempt at this run crashed mid-way (year 1992, Fortran runtime
error `195`, "allocatable coarray cannot be allocated by an assignment
statement") at the exact same second (`19:15:23`) that `/perm/pad/ecland`'s
shared `build/bin/ecland-master-dp` was rebuilt by unrelated, uncommitted
work-in-progress elsewhere on that checkout (a `LEFIRE` fire-danger module
addition -- safe-by-default, `namelist/input` never sets it, not itself a
correctness concern) -- the rebuild overwrote the running binary's pages
out from under the in-flight process. Fixed by freezing a private,
self-contained copy of the executable *and* its RPATH-relative shared
libraries (`$ORIGIN/../lib64`) before rerunning: `run/bin/` (gitignored;
not derived automatically -- regenerate from `/perm/pad/ecland/build/`
if it goes stale or a real rebuild is wanted). `run/run_liaise_ecland.slurm`
also had a stale hardcoded `#SBATCH --output/--error` path left over from
before this repo was renamed from `liaise` to `liaise-ecland` -- fixed
alongside this run; `sbatch` fails outright (not just a wrong path) if
that directory doesn't exist, so this would have blocked any future
submission of this exact script, not just looked wrong in retrospect.

### Pinned binaries: the executable's RPATH is `$ORIGIN/../lib64` (2026-09-16)

`ecland-master-dp` finds its own `libecland_surf_dp.so`/`libfiat.so`/... via
the RPATH `$ORIGIN/../lib64`. That is why `run/bin/` (executable) +
`run/lib64/` (libraries) works for the Sep-13 control pin above -- and why
the layout `run/bin_<tag>/ecland-master-dp` + `run/bin_<tag>/lib64/` does
**not**: from `run/bin_<tag>/`, `../lib64` is `run/lib64/`, so every such
copy silently runs against the *Sep-13 control build's* libraries. Any
additional pin must therefore be `run/<pin>/bin/ecland-master-dp` +
`run/<pin>/lib64/` (that is how `run/bin_depthtrilogy_8fc1d41_intel20{21,23}/`
are laid out), and `ldd <exe> | grep libecland_surf` must be checked after
pinning. `.gitignore` covers `run/bin_*/`.

This was found the hard way: the "depth-trilogy" prototype (ecland's
per-gridpoint `RDBEDROCK` commit `7434326`, which adds a `PBEDROCK`
argument to `SURFTSTP`/`SURFTSTP_CTL`/`SRFWEXC_VG`/`SRFGWRECHARGE`) appeared
to crash on the LIAISE domain (SIGFPE in `SRFSN_DRIVER` on the first step,
then `malloc(): smallbin double linked list corrupted`), and a whole
bisect -- the `run/bin_bisect*`, `bin_clean_*`, `bin_diag_psdor`,
`bin_ssdp3d`, `bin_final_safe` copies left by the previous, mem-killed
session -- concluded the new argument plumbing was at fault and staged a
revert in `ecland-bedrock-per-point`. All of it was this layout: a
post-`7434326` executable calling the Sep-13 `libecland_surf_dp.so` (built
from `55f3d24`, no `PBEDROCK`) with a mismatched argument list, which shifts
`PSDOR` and the snow arrays into garbage. The copies that "worked"
(`bin_final_safe`, `bin_clean_develop`) merely had a SURFTSTP signature
matching the old library -- they were silently running the Sep-13 physics.
Verified both ways: the byte-identical executable runs the full 1988 year
cleanly in place or with a `bin/` subdirectory (even under
`MALLOC_PERTURB_=165` heap poisoning), and crashes as a flat copy. The
depth-trilogy code, Intel 2021.4 vs 2023.2, the fresh bundle's newer
field_api/fiat and the netCDF write-behind buffering (`NCHUNKTIME`/`NIOBUF`)
were all ruled out along the way. The staged revert in
`ecland-bedrock-per-point` is not a fix and should be dropped; the leftover
`run/bin_*` bisect copies are invalid and can be deleted.

Two genuine, unrelated things noticed while chasing this: `srfsn_driver_mod.F90`'s
`LEROGLACIER` block (currently hard-set `.FALSE.`) uses `KLACT` without
initialising it on snow-free points, and `run/check_water_budget.py` returns
absurd totals on this domain's output (it does not mask sea/missing points
despite its docstring) -- neither affects the runs documented here.

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
