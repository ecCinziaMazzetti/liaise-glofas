---
name: liaise-ecland-verify
description: Validate a finished LIAISE ecLand run - prove the annual restart chain really engaged, extract domain-mean diagnostics, compare against a reference, and sanity-check CaMa-Flood discharge. Use after any multi-year run completes, when a run's numbers look wrong or disagree with someone else's, or when asked whether a run is valid or restart-chained.
---

# Validating a finished LIAISE run

**A run that finishes with status 0 can still be invalid.** The failure that
matters here is silent: the annual restart chain can fail to engage, so every
year cold-starts from `soilinit` with no error message, no warning, and no
obvious signature in the output. Always run step 1.

## 1. Prove the restart chain engaged

```bash
module load python3/3.11.10-01
python3 run/verify_restart_chain.py --run-root $PERM/liaise_ctl_1988_2024
```

Exit status 0 means chained, 1 means cold-starting, so this can gate a pipeline.
Pass `--run-root` twice to compare two runs side by side.

**Do not diagnose this from the namelist.** The signature is counter-intuitive
and inverting it is easy — it produced a confidently wrong conclusion here,
including a recommendation to raise a non-existent bug with a colleague:

| work-dir signature | meaning |
|---|---|
| `LNF=.TRUE.`, no `restart_in.nc` | **FIXED** — previous restart linked *as* `soilinit` |
| `LNF= .FALSE.`, `restart_in.nc` staged | **BROKEN** — driver never reads it |

Root cause (upstream `4f0ad4e`): the offline driver only calls `RDRES`, which
reads `restartin.nc`, when `NSTART /= 0`, and the run script always starts each
year at `NSTART=0`.

The state tests are unambiguous because they compare a field with itself:

| check | cold-starting | chained |
|---|---|---|
| 1 Jan soil moisture, year A vs year B | ~5 (all Januarys alike) | ~410 |
| 31 Dec -> 1 Jan, one hour apart | ~270 (jumps) | ~0.04 |

If a run is cold-starting, it is not usable as a multi-year run. Rename it
`*_NOCHAIN_invalid` (upstream's convention) so it can't be used by accident, and
rerun with a script containing `4f0ad4e`.

## 2. Extract diagnostics

Takes ~10 min for 37 years — it reads every hourly field. Run it in the
background.

```bash
OUTPUT_ROOT=$PERM/liaise_ctl_1988_2024/output START_YEAR=1988 END_YEAR=2024 \
  DIAGNOSTICS_JSON=$PERM/liaise_diagnostics/control.json \
  python3 run/extract_control_diagnostics.py
```

Sanity band for this domain: precipitation 640-975 mm/yr, a wet-autumn/dry-summer
cycle, T2m rising ~11.9 -> ~13.5 °C across 1988-2024 (~+0.34 °C/decade).

`Rainf`/`Snowf`/`Qs`/`Qsb`/`Evap` in `o_wat.nc` are **rates** (kg m⁻² s⁻¹), not
accumulated depths per output step, despite `LACCUMW`/`LRESET`. Multiply by the
output interval (3600 s) before summing to an annual depth — forgetting this
gives ~0 mm/year for every year, which is how it was first caught.

## 3. Compare against a reference

```bash
python3 run/compare_diagnostics.py --a mine.json --b reference.json --show-mtime
```

- **Precipitation must agree to 0.00%** when both runs share the forcing. It is
  the control: it cannot depend on initial state, so if it differs, the runs
  differ in forcing or grid, not in model state, and nothing else in the
  comparison means what you think.
- **Runoff and root-zone moisture are the sensitive fields.** A restart-chain
  difference shows up there: measured 22.5% in runoff and 8.8% in root-zone
  moisture between a cold-started and a chained 37-year run.

**Always use `--show-mtime` when quoting a result.** A reference JSON on a shared
filesystem can be regenerated under you. That happened here:
`/perm/pad/liaise_discharge_compare/control_run_diagnostics.json` held
cold-start values on 2026-09-13 and post-fix values by 2026-09-17, so the same
comparison gave opposite verdicts on consecutive days. Record the mtime with any
number you report.

## 4. CaMa-Flood discharge, for a coupled run

```bash
python3 - <<'PY'
import netCDF4 as nc, numpy as np
a = nc.Dataset("<RUN_ROOT>/output/1988/o_totout.nc")["totout"][:]
a = np.ma.masked_greater(np.ma.masked_invalid(np.ma.filled(a, np.nan)), 1e19)
v = a.compressed()
print("active cells :", int((~a.mask).any(axis=0).sum()), "(expect 1405 at glb_15min)")
print("finite       : %.1f%%" % (100 * v.size / a.size))
print("neg < 0      : %.3f%%" % (100 * (v < 0).sum() / v.size))
print("neg < -0.01  : %.3f%%" % (100 * (v < -0.01).sum() / v.size))
print("worst / peak / mean: %.1f / %.1f / %.2f m3/s" % (v.min(), v.max(), v.mean()))
PY
```

Expected for the committed `glb_15min` weights: **1405 active cells**, 100%
finite, peak ~7000 m³/s, domain mean ~48 m³/s.

**Negative discharge needs a stated tolerance or it is meaningless.** The rate is
dominated by near-zero noise and swings with the cutoff:

| cutoff | rate (1988, chained) |
|---|---|
| `< 0` | 0.352% |
| `< -0.01` | 0.075% |
| `< -1` | ~0.014% |

Quote it as e.g. "0.075% of 6-hourly values below −0.01 m³/s", never as a bare
percentage. Upstream's `CLAUDE.md` quotes 0.13% without a tolerance, which looks
like a discrepancy against 0.352% and is not one.

By magnitude the negatives concentrate at the **Rhône delta** (5.38 °E, 43.38 °N,
worst ~−5100 m³/s) — real bifurcation hydraulics, not a boundary artefact. By
*count* they are mostly the Balearics and Valencia coast at −0.0 to −0.6 m³/s,
i.e. rounding noise in small isolated coastal catchments.

If active cells come out far below 1405 (e.g. ~11), suspect `mpireg.nc`: a
single-process run needs a **single-region** map, and a naive clip of the global
decomposition silently drops most of the domain rather than erroring. Check with
`np.unique` — it must contain only `1`.

## 5. Score against real gauges

```bash
python3 cama_flood/skill_benchmark_chains.py \
  --fortran-tmpl "$PERM/liaise_cmf_1988_2024/output/{y}/o_totout.nc" \
  --years 1988-2014 --out $PERM/liaise_diagnostics/skill.json
```

Reference values for a correctly chained run, 133 station-years at the 7 GRDC
gauges: median KGE **−0.208**, r **0.393**, PBIAS **−52.3%**.

- Mostly negative KGE is expected, not a defect: these are 102–9637 km² headwater
  catchments resolved on a 0.25° network whose cells rival the basins in size.
- **`RIO GUADALOPE, CASPE` is excluded from aggregates.** It is dam-regulated
  with near-zero flow for long stretches, so variance-based metrics explode —
  its NSE reaches ~10¹⁶ and its KGE is `nan`. That is a metric artefact, not
  skill information. Two runs can look wildly different purely because of this
  gauge; exclude it before concluding anything.
- A cold-started chain scores PBIAS ~−37.9% and r ~0.359. If you see those,
  check step 1 — the chain is probably broken.
