# CLAUDE.mocm.md — mocm's working notes (liaise-glofas fork)

Notes for **this fork** (`mocm/liaise-glofas`, branch `lisflood`), kept separate
from the upstream `CLAUDE.md` on purpose: both sides append dated entries to the
end of that file, so sharing it guarantees merge conflicts. Root `CLAUDE.md`
imports this file from its **top** (upstream appends at the bottom, so a one-line
edit there survives merges). LISFLOOD-specific notes live in
`lisflood/CLAUDE.md`, which is directory-scoped and cannot conflict at all.

## Fork layout and update procedure (2026-09-17)

```
origin    https://github.com/mocm/liaise-glofas.git   (mine; inert until the fork exists)
upstream  https://github.com/gpbalsamo/liaise-ecland.git  (push DISABLED_read_only)
main      tracks upstream/main — NEVER commit here
lisflood  my working branch; `git diff main...lisflood` is exactly my work
```

Pull upstream developments:

```bash
module load git/2.53.0              # system git has no LFS filter, see below
git fetch upstream
git checkout main && git merge --ff-only upstream/main   # refuses if main got polluted
git checkout lisflood && git merge main
```

**Keep changes additive.** Merge pain scales with the number of *shared* files
edited, not with how much is added: a new `lisflood/` tree can grow without ever
conflicting, while three lines in `README.md` conflict on every upstream rewrite.
So: new directories and new filenames for LISFLOOD work; do not rename, move,
delete or reformat upstream files; leave `cama_flood/` in place even when unused
(deleting it conflicts with upstream edits to it).

Upstreamable fixes (generic, not fork-specific) should go to `gpbalsamo/liaise-ecland`
as PRs rather than live here forever — each one accepted is one less permanent
divergence:
- `run/extract_control_diagnostics.py` hardcoded `/perm/pad` for input **and
  output**, so it could not run for any other user (fixed here, see below).
- `run/run_liaise_ecland.slurm` hardcodes `--output`/`--error` into
  `/perm/pad/liaise-ecland/run/logs/`; `sbatch` fails outright for anyone else.
  Override on the command line until upstream takes a fix.
- `run/build_land_control_dashboard.py` is new here and fills a real gap: the
  LAND-surface control dashboard was hand-made and not reproducible from a clone.
  Deliberately renamed away from `build_control_dashboard.py`: upstream added a
  file of that exact name under `cama_flood/` in the same window, but it is a
  river-gauge skill map, a different page entirely -- not a duplicate.

## Environment gotchas on this machine (2026-09-17)

- **`git-lfs` is not in the default PATH**, but it *is* bundled in the git
  modules: `module load git/2.53.0` gives git-lfs 3.7.1. Without it every
  LFS-tracked file shows in `git status`/`git diff --stat` as a spurious
  modification (`Bin 131 -> 777780 bytes`) because the working tree holds real
  content where git expects a pointer — do **not** `git add -A` in that state.
  With LFS loaded the tree is clean and `git lfs ls-files | wc -l` gives **16**
  (upstream README says 14; it predates the two `*_depthtrilogy` ancillaries).
- **The dashboard scripts need Python 3.11+**: `module load python3/3.11.10-01`.
  The default `python3` is 3.6 and dies on `from __future__ import annotations`
  and `X | Y` annotations.
- **ECMWF Sites** publishing is `sitesctl` (`module load sites`), which needs
  `sitesctl auth login --username mocm` and prompts for confirmation unless
  given `--force`. Its `Could not upgrade the CLI binary ... permission denied`
  line is harmless. A silent no-output upload means it failed (usually an
  expired token → HTTP 403); always confirm with `content list --recursive`.
- ecLand's `arch/.../intel/2023.2.0/hpcx-openmpi/2.9.0/env.sh` does `module
  purge` first; source it before an interactive run so the runtime environment
  matches the build.

## Pinned executables (2026-09-17)

Both built from my own clone of `gpbalsamo/ecland` at `/perm/mocm/ecland-gpb`
(own `ecbundle` at `/perm/mocm/ecbundle`, own dependency tree), never copied from
`/perm/pad`. Layout follows upstream's RPATH rule — `$ORIGIN/../lib64`, so
`run/<pin>/bin/` + `run/<pin>/lib64/`, verified each time with
`ldd <exe> | grep libecland_surf`.

| Pin | ecland commit | Use |
|---|---|---|
| `run/bin_55f3d24_intel2023/` | `55f3d24` | provenance-matched to upstream's reference control |
| `run/bin_develop_0f3c579_intel2023/` | `origin/develop` tip | same answers, **1.6x faster I/O** |

`55f3d24` was chosen over `main` HEAD deliberately: upstream's reference
diagnostics come from it, and `main` HEAD carries an *ungated* frozen-soil
macropore-permeability change that would move `runoff_mm`. Note `82356ae` (the
`LECMF1WAY` loop-bound fix) is **not** on `main` — it is on `origin/develop`, and
`55f3d24` is a descendant of it, so both pins carry the fix (verify with
`grep -c "DO IST = 1, NPOI, NPROMA" src/surf/offline/driver/cnt41s.F90` → 4).

**The I/O speedup is `c0526a1`, which is newer than `55f3d24`** — this is why a
`55f3d24` build runs ~3m50s/year against the ~2min/year in upstream's notes;
nothing to do with `$PERM` vs `$SCRATCH` (measured: same cost on both).
Do **not** try to cherry-pick `c0526a1` onto `55f3d24`: it sits on top of the
`LEFIRE` commits and its diff drags `LWRFIRE`/fire-output code into a tree that
has none (two conflicts, plus files that silently absorb `LWRFIRE` references).
Build `origin/develop` instead — `LWRFIRE=.FALSE.` by default and neither
namelist sets it. Verified output-neutral: 1988 control reproduces all five
reference diagnostics exactly, at 2m59s vs 4m42s.

## Reproduction results, and why the first pass had to be redone (2026-09-17)

**Read this before trusting any number in this fork's earlier dashboards or JSONs.**

The first pass reproduced upstream's 37-year control *exactly* -- 184 of 185
field-years identical to
`/perm/pad/liaise_discharge_compare/control_run_diagnostics.json` (the one
exception root-zone moisture in 1995, 0.01 kg/m2, the last decimal of a value
rounded to 2 places), and a coupled run with 1405 active river cells and 100%
finite discharge. Both matched the documented signatures.

**Both were nevertheless invalid as multi-year runs, and so was the reference
JSON they matched**: every year silently cold-started from `soilinit` instead of
continuing the previous year's land state.

Upstream found and fixed this independently in `4f0ad4e` (2026-09-16 18:53),
with the real root cause: the offline driver only calls `RDRES` (which reads
`restartin.nc`) when `NSTART != 0`, and `patch_namelist_for_year` always sets
`NSTART=0`. So the old `restart_in.nc` + `LNF=.FALSE.` path staged a restart the
driver never read, with **no error message**. Every multi-year run made with
these scripts before that commit is affected, including upstream's own
2026-09-13 reference and the 2026-09-13 dashboard built from it.

The fix links the previous year's `restartout.nc` **as** `soilinit`
(`restartout.nc` is a superset: `SoilMoist` in kg m-2 which `RDSUPR` converts,
all `NCSNEC` snow layers, WTD), matching `ecland_run_model.sh`'s own RLOOP
mechanism, and runs normally at `NSTART=0`, `LNF=.TRUE.`.

**Diagnostic trap, recorded because it cost this fork a wrong conclusion.**
`LNF=.TRUE.` with no `restart_in.nc` in the work directory is the **FIXED**
configuration, not the broken one; `LNF= .FALSE.` with a staged `restart_in.nc`
is the **BROKEN** one. Reading those signatures the intuitive way inverts the
verdict, and this fork initially did exactly that -- concluding upstream's runs
were defective and its own correct, when the reverse was true. Do not diagnose
this from the namelist. Test the state directly; these two checks are unambiguous
and unit-free:

| check | cold-starting | correctly chained |
|---|---|---|
| 1 Jan soil moisture, year A vs year B | nearly identical (~5) | genuinely different (~400) |
| 31 Dec -> 1 Jan, one hour apart | discontinuous (~270) | continuous (~0.04) |

Measured on this fork's first-pass control: 4.95 and 269.6 -> cold-starting.
On upstream's post-fix control: 410.5 and 0.037 -> chained.

**The effect is large**, per upstream's own quantification: the fixed chain
lowers Jan-Mar discharge by a factor 1.5-4 and annual means by 15-45%, and
raises peak flows, since real antecedent-moisture memory lets wet spells
compound. It also removes a spurious 1-January runoff pulse traced to one
`soilinit` cell (43.25N, -5.75E, outside the Ebro) sitting above saturation and
dumping ~50 mm at each "start", which CaMa-Flood routed into thousand-m3/s
1-January spikes downstream. That cell still needs capping in `init_clim`.

This also retroactively explains a difference this fork misread as evidence: its
first-pass coupled run scored median PBIAS **-37.9%** against upstream's
**-52.3%**, which is exactly the 15-45% annual-mean shift above. Upstream's is
the valid figure.

Invalid first-pass runs are preserved for reference only, following upstream's
naming: `/perm/mocm/liaise_ctl_1988_2024_NOCHAIN_invalid` and
`/perm/mocm/liaise_cmf_1988_2024_NOCHAIN_invalid`. **Not for use.** The
dashboards published from them at `sites.ecmwf.int/mocm/liaise/` were rebuilt
from the corrected runs; if a page shows cold-start numbers it predates that.

### Chained reruns (2026-09-17, after merging 4f0ad4e)

Both rerun with the fixed script, `develop` pin, into
`/perm/mocm/liaise_ctl_1988_2024` and `/perm/mocm/liaise_cmf_1988_2024`.
Verify each with the two state checks in the table above -- the first year
correctly reports `Initial state: .../soilinit` and every later year must report
`Initial state (restart chain): .../restart_<y>1231.nc -> soilinit`.

### The 0.13% negative-discharge figure needs a tolerance

Upstream `CLAUDE.md` quotes a "0.13% non-physical-negative-discharge rate" for
the 1988 coupled run. Reproducing it gives **0.440%** counting every value below
zero, which looks alarming and is not a defect — the metric is dominated by
near-zero noise and is extremely threshold-sensitive:

| cutoff | rate |
|---|---|
| `< 0` | 0.440% |
| `< -0.001` | 0.209% |
| `< -0.01` | 0.091% |
| `< -1` | 0.014% |

0.13% falls between the -0.001 and -0.01 cutoffs, so the numbers are consistent;
only the epsilon is unstated. Quote it as e.g. "0.09% of 6-hourly values below
-0.01 m³/s" instead.

The spatial pattern supports the documented physical reading *for the magnitude*
but not for the count: the largest contributor by count is 5.38°E, 43.38°N — the
Rhône delta, as documented (worst value -5096 m³/s here vs -5205 upstream) — but
most remaining high-count cells are the Balearics (~2.6-3.4°E, 39.3-39.9°N) and
the Valencia coast, small isolated island/coastal catchments inside the extended
domain, at -0.0 to -0.6 m³/s. Rounding-level noise inflating a count.

### Discharge-dashboard caveat

`sites.ecmwf.int/mocm/liaise/discharge/` headlines a "GPU wins N/133" count that
should not be read as a model comparison. Its Fortran rows are this fork's run
and its GPU rows are upstream's eclandpy -> CaMa-Flood-GPU chain, so the two
sides are only comparable when both were produced from correctly chained ecLand
runoff. A fair comparison needs either upstream's GPU chain re-driven from this
fork's runoff, or an eclandpy run of this fork's own.
