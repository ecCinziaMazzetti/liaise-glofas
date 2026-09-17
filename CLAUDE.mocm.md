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
- `run/build_control_dashboard.py` is new here and fills a real gap: the control
  dashboard was previously hand-made and not reproducible from a clone.

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

## Reproduction results (2026-09-17)

Both runs use my own pins, my own copy of the forcing
(`forcing/WFDE5_CRU_GPCC_ecland/`, 37 files, 1.9 GB, copied from
`/perm/pad/liaise-ecland/forcing/` so no pad dependency remains at run time) and
the Git-LFS ancillaries.

- **37-year control** (`namelist/input`, `RUN_ROOT=/perm/mocm/liaise_ctl_1988_2024`):
  37/37 years, 2h34m41s. Against
  `/perm/pad/liaise_discharge_compare/control_run_diagnostics.json`:
  **184 of 185 field-years exactly identical**, the one exception being
  root-zone moisture in 1995 differing by 0.01 kg/m² (the last decimal of a
  value rounded to 2 places). Precipitation 641-975 mm/yr and T2m 11.91 -> 13.45 °C
  both match the documented signatures. T2m trend **+0.34 °C/decade**.
- **37-year coupled** (`namelist/input_cmf1way`,
  `RUN_ROOT=/perm/mocm/liaise_cmf_1988_2024`): 37/37 years, 2h01m40s, 70 GB,
  all 37 `o_totout.nc`, both restart chains reaching 2024. 1988 discharge has
  **1405 active river cells** and 100% finite output, matching the documented
  domain exactly. Scored over 1988-2014 (133 station-years, 7 GRDC gauges,
  `RIO GUADALOPE, CASPE` excluded): median KGE **-0.233**, r **0.359**,
  PBIAS **-37.9%** — close to the documented -35.4%.
- The coupled run's land output is **bit-identical to my own control** in every
  year 1988-2014, which is the correct behaviour for 1-way coupling: CaMa-Flood
  must not feed back into the land unless `NCMF2LAKEC=2`.

Diagnostics JSONs: `/perm/mocm/liaise_diagnostics/`. Dashboards:
`sites.ecmwf.int/mocm/liaise/` (control) and `.../discharge/` (skill).

### Upstream's on-disk runs are NOT restart-chained — do not score against them

Upstream **re-ran both** the control and the coupled chain on **2026-09-16**
(control 19:49-21:41, coupled 16:18-18:12), overwriting the 2026-09-13 output,
with the land restart chain broken: `LNF=.TRUE.` in **every** year 1988-2024 and
no `restart_in.nc` staged in any work directory. The land restarts were written
each year and never read back. So each year cold-starts from `soilinit` and has
no soil-moisture memory.

Consequences, all verified:
- `/perm/pad/liaise-ecland/run/output/` no longer reproduces
  `control_run_diagnostics.json`, which it is supposed to have produced:
  1989 runoff -102.5 mm vs the JSON's -169.3 mm, 2000 -199.9 vs -212.3.
  Precipitation matches exactly in both years, as it must — it is forcing-driven
  and cannot depend on initial state. That contrast is the diagnostic signature.
- `/perm/pad/liaise_cmf_1988_2024/` has the same defect, giving median PBIAS
  **-52.3%** against my correctly-chained **-37.9%**.
- Upstream's coupled run matches upstream's *current* control exactly (both
  cold-start), which is why the defect is invisible if the two are only compared
  with each other. 1988 agrees with a chained run too, since the first year
  cold-starts either way; divergence starts in 1989.
- The **2026-09-13 reference JSON is still correct** and is what my control
  reproduces. Compare against the JSON, never against the current on-disk output.

The tell is formatting: upstream's line is the untouched template
(`LNF=.TRUE.` with its trailing comment) whereas `sed_inplace` leaves
`LNF= .FALSE.` with a tell-tale space — so the patch never fired there.
Likeliest cause is an older copy of `run_liaise_ecland.sh` or an overriding
environment variable; not established. **Not yet reported upstream.**

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

`sites.ecmwf.int/mocm/liaise/discharge/` headlines "GPU wins 80/133", which
overstates the GPU chain. Its Fortran rows are my restart-chained run, but its
GPU rows are upstream's eclandpy -> CaMa-Flood-GPU chain, driven by runoff from
an ecLand run with the cold-start defect above. The two sides are therefore not
forced by equivalent land states. A fair comparison needs either upstream's GPU
chain re-driven from my runoff, or my own eclandpy run.
