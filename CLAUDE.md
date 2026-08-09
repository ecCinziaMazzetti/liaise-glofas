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
- logs
- Python caches

Respect `.gitignore`.

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
