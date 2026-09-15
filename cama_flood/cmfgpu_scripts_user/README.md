# CaMa-Flood-GPU driver scripts, archived

Verbatim copies of the personal driver scripts that ran the CaMa-Flood-GPU work documented
in `../../CLAUDE.md` ("CaMa-Flood-GPU coupling prep" onward). They lived — and by
CaMa-Flood-GPU's own convention must run from — that checkout's `scripts_user/`, which its
`.gitignore` excludes (`scripts_*/`), so until 2026-09-15 they existed in one place with no
version control. `/perm/pad/CaMa-Flood-GPU/scripts_user/<name>.py` are now symlinks to these
files; edit them here.

| file | what it ran |
|---|---|
| `run_liaise_2000.py` | first LIAISE run, 2000, base + adaptive_time (no bifurcation) |
| `run_liaise_year.py` | any single year, hourly runoff, bifurcation on |
| `run_liaise_year_spinup.py` | the 2-pass same-year river-storage spin-up; `--parameters`/`--tag`/`--runoff-interval-hours` for the map-package and coupling-frequency investigations |
| `make_map_params_v420.py`, `make_map_params_v21fixdir.py` | global `parameters.nc` from the v4.20 package and from the Fortran reference's own FIXDIR (both negative results on channel width) |
| `test_nloop_convergence.py` | substep convergence check |
| `run_eclandpy_liaise_chained.py` | first eclandpy-driven multi-year chain (2026-09-14) |
| `make_map_params.py`, `make_runoff_map.py`, `run_daily_bin.py` | upstream templates with local path edits |

**Superseded for new work** by `eclandpy.cmfgpu` (eclandpy repo): `chain` generalises
`run_liaise_year_spinup.py`/`run_eclandpy_liaise_chained.py` (paths as arguments,
`--spinup-passes`, `--runoff-interval-hours`), and `runoff`/`mapping`/`subset`/`discharge`/
`daily_runoff` are the packaged forms of `../prepare_liaise_runoff_for_cmfgpu.py`,
`../inpmat_to_cmfgpu_npz.py`, `../subset_parameters_for_liaise.py`,
`../export_liaise_daily_discharge.py`, `../aggregate_runoff_to_daily.py`. The LIAISE
pipeline (`../../eclandpy_bridge/submit_cmfgpu_eclandpy_chain.sh`) calls the package.
These originals stay so every number in `CLAUDE.md` remains reproducible as it was produced.
