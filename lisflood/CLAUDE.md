# lisflood/ — LISFLOOD (GloFAS) application on the LIAISE/Ebro domain

Directory-scoped working notes. Claude Code picks this file up when working in
this subtree, so it never conflicts with the upstream root `CLAUDE.md` — that is
the point of putting them here rather than appending to it. Fork-wide notes
(remotes, pins, reproduction results, upstream defects) are in `../CLAUDE.mocm.md`.

## What this directory is for

LISFLOOD — the hydrological/routing model behind
[GloFAS](https://global-flood.emergency.copernicus.eu/) — applied to the same
LIAISE/Ebro domain this repository already runs ecLand over. It is the
counterpart of `../cama_flood/`, which does the equivalent job for CaMa-Flood:
take ecLand's runoff and route it, then score the resulting discharge against
the same real gauges.

Nothing here yet beyond this file. Started 2026-09-17.

## Ground rules inherited from the fork layout

- **Everything LISFLOOD goes under this directory** (or into new files with new
  names elsewhere, e.g. `../run/run_liaise_lisflood.sh`). Do not edit
  `../cama_flood/`, `../run/run_liaise_ecland.sh`, `../README.md` or the root
  `../CLAUDE.md` to accommodate LISFLOOD — that is what makes upstream merges
  conflict-free. See `../CLAUDE.mocm.md`.
- **Reuse rather than re-derive.** The ecLand half of this repository (forcing,
  `init_clim/`, `namelist/`, `run/`) is shared with upstream and already
  validated; LISFLOOD replaces only the routing stage. In particular the
  observations and scoring machinery are model-agnostic and should be reused:
  `../cama_flood/data/liaise_grdc_observations.nc` (7 GRDC gauges connected to
  the Ebro on CaMa-Flood's own network, 1988-2014 daily) and the metric
  functions in `../cama_flood/skill_benchmark_chains.py`.

## Things already established that LISFLOOD work will need

- **The runoff formula is `-(Qs + Qsb)`**, from `run/output/<year>/o_wat.nc`.
  This is not obvious and getting it wrong is the single most expensive mistake
  recorded in this repository's history: `Qs` is a positive outward flux while
  `Qsb` is signed as a negative soil-column loss, so the intuitive `Qs + Qsb`
  gives ~zero and `Qs - Qsb` double-counts surface runoff (a ~2-3x forcing
  error that took multiple sessions to find). Upstream traced the true formula
  to ecLand's own source: `wrtdcdf.F90` writes `Qsb = -(D1STRO2 + Qs)`, and
  `cnt41s.F90`'s `LECMF1WAY` coupling passes CaMa-Flood a surface/subsurface
  pair summing to `D1STRO2 = -(Qs + Qsb)`. Drive LISFLOOD with the same
  quantity, and sanity-check it the way upstream did: a domain-mean annual
  depth around 230 mm/yr, and exactly zero negative values.
- **`Rainf`/`Snowf`/`Qs`/`Qsb`/`Evap` in `o_wat.nc` are rates** (kg m⁻² s⁻¹),
  not accumulated depths per output step, despite `LACCUMW`/`LRESET` in the
  namelist. Multiply by the output interval (3600 s) before summing to an
  annual depth.
- **Use my own runs, not `/perm/pad`'s current on-disk output**, which is not
  restart-chained — see `../CLAUDE.mocm.md`. Correctly chained ecLand runoff
  for 1988-2024 is at `/perm/mocm/liaise_ctl_1988_2024/output/<year>/o_wat.nc`
  (land-only control) and `/perm/mocm/liaise_cmf_1988_2024/` (coupled; its land
  output is bit-identical to the control, so either serves as LISFLOOD forcing).
- **The ecLand grid is a regular 0.5° lat/lon 23x16 box, 235 active land
  points** — deliberately *not* a subset of a global reduced-Gaussian grid.
  That assumption broke upstream's CaMa-Flood weight tooling and needed a
  documented workaround; expect LISFLOOD's own grid/mapping tooling to make the
  same assumption and check it before trusting any interpolation weights.
- **Domain extent is a real decision, not a detail.** CaMa-Flood's weights here
  keep every basin that crosses the LIAISE box *whole* (roughly Iberia to the
  Alps), because clipping mid-basin produces boundary artefacts that get worse,
  not better, as a fixed halo grows. If LISFLOOD is set up on a smaller domain,
  read the comparison table in the root `CLAUDE.md` ("Domain: extend crossing
  basins, not a fixed halo") before assuming a box around the Ebro is enough.

## Open questions to settle first

- Which LISFLOOD distribution/version, and is a suitable static map set (river
  network, gradients, land use, soil, `chanbw`/`chanlength`) available for the
  Ebro at a resolution compatible with 0.5° ecLand runoff — or does it need
  deriving, as CaMa-Flood's `inpmat.nc` did?
- Does LISFLOOD run offline from prepared runoff here, or is the intent to
  couple it in-process the way CaMa-Flood is compiled into `ecland-master-dp`?
  The former is far simpler and matches the CaMa-Flood-GPU precedent in
  `../eclandpy_bridge/`.
- Spin-up: CaMa-Flood needed river storage equilibrating (a 2-pass same-year
  scheme sufficed; more passes changed nothing). LISFLOOD additionally carries
  groundwater storage, which typically needs far longer — decide the spin-up
  length deliberately rather than inheriting the 2-pass convention.
