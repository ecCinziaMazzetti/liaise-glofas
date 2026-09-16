![LIAISE ecLand](docs/liaise-ecland-banner.png)

# liaise-ecland

Scripts and configuration to run [ecLand](https://www.ecmwf.int/en/research/modelling-systems/land-surface) — ECMWF's land-surface model — over the LIAISE domain (the Ebro basin, north-east Spain, 0.5°, 235 land points) for 1988–2024, optionally coupled to the CaMa-Flood river-routing model, and to score the routed discharge against real river gauges.

To learn more about the LIAISE field campaign see the [LIAISE data portal](https://liaise.aeris-data.fr/); the meteorological forcing is WFDE5-CRU-GPCC (Cucchi et al., 2020, https://doi.org/10.5194/essd-12-2097-2020), 0.5°, hourly, via the [LIAISE forcing wiki](https://gitlab.in2p3.fr/ipsl/lmd/intro/liaise-forcing/-/wikis/home) mirror (1988–2014) and the [Copernicus Climate Data Store](https://cds.climate.copernicus.eu/) (2015–2024).

## Requirements

- An ecLand executable, built separately — see [ECMWF ecLand](https://github.com/ecmwf-ifs/ecland). CaMa-Flood is compiled *into* `ecland-master-dp` (`src/surf/cmflood/`), so no second executable is needed for the coupled run.
- ECMWF HPC modules: `prgenv/intel`, `intel/2021.4`, `hpcx-openmpi/2.9`, `netcdf4/4.9.1`, `python3` (the SLURM wrapper loads them itself).
- Python packages: `numpy`, `netCDF4`; `cdsapi` only to download 2015–2024 forcing from the CDS.
- Git LFS, for the validated ancillary files, the CaMa-Flood river-network files and the gauge observations.
- MARS access only if you want to *regenerate* the ancillary fields (`init_clim/clim.sh`); the committed ones cover the normal case, so the workflow also runs outside ECMWF (e.g. macOS) once you have forcing and an executable.

## Quick start

Five steps take you from a clone to a 37-year run and a checked output. Each step says what to expect when it worked. All paths are relative to the repository root.

### 1. Clone with LFS

```bash
git lfs install
git clone git@github.com:gpbalsamo/liaise-ecland.git
cd liaise-ecland
git lfs pull
```

*Expect:* real NetCDF files (not pointer stubs) in `init_clim/data/` (`surfclim`, `soilinit`), `cama_flood/data/` (7 files) and `landbench/data/ES-VDA/` (5 files):

```bash
git lfs ls-files | wc -l    # 14
```

### 2. Install the ancillary fields

```bash
init_clim/get_init_clim.sh
```

*Expect:* `init_clim/work/surfclim` and `init_clim/work/soilinit` — the validated, MARS-derived static fields (soil type, vegetation, orography, …) and initial state on the 23×16 LIAISE grid. Regenerating them from MARS instead (`init_clim/clim.sh` then `init_clim/init_clim.sh`) is only needed if the grid or the climate archive changes.

### 3. Get the forcing

Two sources, one layout. Both write raw yearly files `forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_<year>.nc`:

```bash
cd forcing
./get_liaise_forcing_05.sh                              # 1988–2014 from the IPSL mirror
START_YEAR=2015 END_YEAR=2024 ./get_liaise_forcing_05_cds.sh   # 2015–2024 from the CDS (needs ~/.cdsapirc)
```

Then rebase every year onto ecLand's time axis (`hours since 1988-01-01 00:00:00`) and append the endpoint at 00 UTC 1 January of the following year that ecLand needs to close each year — always over the **full** range, so the last year gets a real endpoint from its successor and only the final year has a duplicated one:

```bash
python3 prepare_liaise_forcing_ecland.py --input-dir WFDE5_CRU_GPCC --output-dir WFDE5_CRU_GPCC_ecland \
    --start-year 1988 --end-year 2024 --repeat-last-for-final-year
cd ..
```

*Expect:* 37 files `forcing/WFDE5_CRU_GPCC_ecland/WFDE5_CRU_GPCC_<year>_ecland.nc` (~60–110 MB each):

```bash
ls forcing/WFDE5_CRU_GPCC_ecland | wc -l    # 37
```

Each CDS request downloads a global file (up to ~12 GB) and clips it on assembly; queue time dominates, transient `502`s are retried automatically. `forcing/scratch_mirror.sh` runs the preparation on `$SCRATCH` and pulls back only the finished `WFDE5_CRU_GPCC_ecland/`. Inside ECMWF the prepared archive is already on `/perm/pad/liaise-ecland/forcing/` and on `sites.ecmwf.int/pad/liaise/forcing/`.

### 4. Choose a namelist

Two namelists are committed and ready to use:

- `namelist/input` — the **control**: land surface only, CY50R1 physics, `LECMF1WAY=false`.
- `namelist/input_cmf1way` — the same, **coupled to CaMa-Flood** (`LECMF1WAY=true`, hourly coupling `TCOUPFREQ=1`); its CaMa-Flood side is `namelist/input_cmf`.

`namelist/create_liaise_namelist.sh` regenerates `namelist/input` from environment variables (every logical `LE*` flag and integer `N*` parameter of the ecLand namelist can be set that way, e.g. `LECMF1WAY=true ./create_liaise_namelist.sh`). The run script patches dates, `NSTOP` and restart flags per year, so never edit those by hand.

### 5. Run ecLand

Submit the whole 1988→2024 chain as one SLURM job. Every input is an environment variable with a sensible default; the four you will typically set are the executable, the namelist, and where to write:

```bash
cd run
sbatch --job-name=liaise_ctl --time=04:00:00 \
  --export=ALL,ROOT=$PERM/liaise-ecland,ECLAND_EXE=/path/to/ecland/build/bin/ecland-master-dp,\
NAMELIST=$PERM/liaise-ecland/namelist/input,RUN_ROOT=$PERM/liaise_ctl_1988_2024 \
  run_liaise_ecland.slurm
```

*Expect:* `Submitted batch job <id>`, then `run/logs/liaise_ecland_<id>.out` printing `Running LIAISE ecLand year 1988`, `ecLand finished with status 0`, … one year at a time, and under `RUN_ROOT`: `output/<year>/o_*.nc` (hourly land diagnostics), `restart/<year>/restart_<year>1231.nc`, `logs/ecland_<year>.log`. The 37-year control takes ~1 h 35 min (~2.5 min/year, `qos=nf`, 4 threads, 32 GB); the coupled run ~2.7 min/year.

The same script runs interactively (`run/run_liaise_ecland.sh`, same variables) for a test; to run a single year, point `FORCING_DIR` at a directory holding just that year's file. Other useful variables: `SURFCLIM_SOURCE`/`SOILINIT_SOURCE` (default `init_clim/work/…`), `INITIAL_RESTART`/`INITIAL_RESTART_CMF` (seed the first year from an existing restart instead of a cold start), `OMP_NUM_THREADS` (default 4).

### 6. Check the output

```bash
python3 run/extract_control_diagnostics.py    # domain-mean water balance, T2m, seasonal cycle -> JSON
```

*Expect:* precipitation of 640–975 mm/yr, a wet-autumn/dry-summer cycle and a slow T2m warming over 1988–2024 (see `CLAUDE.md`, "37-year control run"). `run/check_water_budget.py` and `run/check_energy_budget.py` (imported from plumber2-ecland) close the raw budgets per year; note they do not yet mask sea points on this domain's output. Note that `Rainf`, `Snowf`, `Qs`, `Qsb`, `Evap` in `o_wat.nc` are rates (kg m⁻² s⁻¹): multiply by the 3600 s output interval before summing.

## Running coupled to CaMa-Flood

```bash
cd run
sbatch --job-name=liaise_cmf --time=08:00:00 \
  --export=ALL,ROOT=$PERM/liaise-ecland,ECLAND_EXE=/path/to/ecland-master-dp,\
NAMELIST=$PERM/liaise-ecland/namelist/input_cmf1way,RUN_ROOT=$PERM/liaise_cmf_1988_2024 \
  run_liaise_ecland.slurm
```

The run script sees `LECMF1WAY=true`, stages the river-network files from `cama_flood/data/` (`inpmat.nc`, `rivpar.nc`, `rivclim.nc`, `mpireg.nc`, `bifprm.txt`, `diminfo.txt` — Git LFS, validated), patches `namelist/input_cmf` per year and chains CaMa-Flood's own restart alongside ecLand's.

*Expect, in addition to the land output:* `output/<year>/o_totout.nc` (routed discharge on the 73×49 CaMa-Flood grid, 6-hourly, 1405 active river cells, 1e20 fill elsewhere), `o_rivsto.nc`, `o_fldsto.nc`, `o_fldfrc.nc`, `log_CaMa.txt`, and `restart/<year>/restart_cmf_<year>1231.nc`. The domain is deliberately larger than LIAISE (Iberia to the Alps): CaMa-Flood keeps every basin that crosses the box whole, so the Ebro and Rhône reach their real outlets — see `CLAUDE.md`, "Domain: extend crossing basins".

The river-network files were derived once with `cama_flood/derive_cmf_weights.sh` (needs ECMWF's shared CaMa-Flood static data and two small `ecland`-side patches documented in `CLAUDE.md`); reuse the committed ones unless the grid changes.

## Running on `$SCRATCH`

Lustre is ~10× faster than `$PERM` for the hourly output. Mirror inputs and code, run from the mirror, pull back only results:

```bash
run/scratch_mirror.sh push
ROOT=$SCRATCH/liaise-ecland ECLAND_EXE=... run/run_liaise_ecland.sh   # or sbatch, with the same variables
run/scratch_mirror.sh pull        # status: show both sides; -n: dry run
```

Deletions are never propagated, so a pull cannot lose a result. `$SCRATCH` is pruned automatically — anything not pulled back is eventually lost.

## Pinning an executable

A shared `ecland/build/` can be rebuilt under a running job (it happened; see `CLAUDE.md`). To freeze one, copy the executable **and** its libraries in the layout its RPATH expects — `ecland-master-dp` looks for `libecland_surf_dp.so` etc. at `$ORIGIN/../lib64`:

```bash
mkdir -p run/<pin>/bin run/<pin>/lib64
cp /path/to/ecland/build/bin/ecland-master-dp run/<pin>/bin/
cp /path/to/ecland/build/lib64/lib{ecland_surf_dp,ecland_cmflood_dp,parkind_dp,field_api_dp,fiat,eccodes,eccodes_f90,eccodes_memfs}.so run/<pin>/lib64/
ldd run/<pin>/bin/ecland-master-dp | grep libecland_surf    # must point into run/<pin>/lib64/
```

`run/bin/` + `run/lib64/` is the same layout one level up. A flat `run/<pin>/ecland-master-dp` next to its own `lib64/` silently picks up `run/lib64/` instead — a mismatch that once cost a day of debugging. `run/bin*`, `run/lib64*`, `run/output*` are gitignored.

## Scoring discharge against real gauges

`cama_flood/data/liaise_grdc_observations.nc` holds daily discharge 1988–2014 at the 7 GRDC gauges that CaMa-Flood's own network connects to the Ebro (Cinca at Fraga and Lafortunada, Guadalope at Caspe — regulated —, Jiloca, Vero, Arba de Luesia, Fortanete), each with its exact CaMa-Flood grid cell (`cama15_ix/iy`), extracted by `cama_flood/extract_liaise_grdc_observations.py` from ECMWF's internal station archive.

`cama_flood/data/liaise_river_observations_grdc_camels.nc` extends that to 53 gauges by adding CAMELS-Spain (`--providers GRDC camelses`) — the merged Qobs archive turned out to carry CAMELS-Spain station IDs with no populated discharge, so non-GRDC providers fall back to the raw per-station Caravan archive (`--caravan-timeseries-dir`), converting its mm/d convention to m3/s via each station's catchment area. CAMELS-Spain carries its own licence, separate from GRDC's public-domain status — see the script's docstring before redistributing this file.

```bash
python3 cama_flood/skill_benchmark_chains.py --years 1988-2014      # coupled chain vs eclandpy->CaMa-Flood-GPU chain vs GRDC
python3 cama_flood/build_chain_dashboard.py --results <json> --out index.html

# Non-comparative: score the Fortran control chain alone against every gauge (GRDC + CAMELS-Spain)
python3 cama_flood/skill_benchmark_control.py --obs data/liaise_river_observations_grdc_camels.nc \
    --fortran-tmpl /perm/pad/liaise_cmf_1988_2024/output/{y}/o_totout.nc \
    --reuse-fortran-rows <skill_benchmark_chains.json> --out <results.json>
python3 cama_flood/build_control_dashboard.py --obs data/liaise_river_observations_grdc_camels.nc \
    --results <results.json> --ncdata data/ncdata.nc --out index.html
```

*Expect:* one JSON row per (year, gauge, model) with KGE, r, α, β, NSE, PBIAS, and a self-contained HTML page. `skill_benchmark_fortran_vs_gpu.py` is the original five-year (1988/1995/2000/2003/2005, 2-pass spin-up) benchmark; its findings — including two bugs it took to make the GPU port agree with Fortran to 0.2 % — are written up in `CLAUDE.md`.

## Beyond the Fortran chain

- `cama_flood/*cmfgpu*`, `inpmat_to_cmfgpu_npz.py`, `subset_parameters_for_liaise.py`, `prepare_liaise_runoff_for_cmfgpu.py`: drive [CaMa-Flood-GPU](https://github.com/Kshy0/CaMa-Flood-GPU) (Kang, Yin & Yamazaki 2026, https://doi.org/10.5194/gmd-19-5623-2026) on the same LIAISE network with ecLand's runoff — ~1 min per year on one A100.
- `eclandpy_bridge/`: the all-Python chain, eclandpy (a from-scratch Python/GT4Py port of ecLand) → CaMa-Flood-GPU over the 37 years, with its own README and dashboard.
- `landbench/`: FLUXNET-Shuttle point observations in the LIAISE region (one materialised site, `ES-VDA`), for future point runs.
- `docs/`: banner, report and slides on the eclandpy chain.

ECMWF-internal dashboards: `sites.ecmwf.int/pad/liaise/control/` (37-year control), `…/GPU_check/` (Fortran vs GPU vs GRDC), `…/eclandpy/` (eclandpy chain), `…/chains/` (Fortran vs eclandpy→GPU chains, every gauged year), `…/gauges/` (Fortran control alone, KGE/NSE/r/PBIAS map over 47 GRDC+CAMELS-Spain gauges).

## Namelists

- `namelist/input` — ecLand CY50R1 control, land only. Generated by `create_liaise_namelist.sh`; committed so a clone runs without regenerating it.
- `namelist/input_cmf1way` — control + `LECMF1WAY=true`, `TCOUPFREQ=1`.
- `namelist/input_cmf` — CaMa-Flood namelist template (bifurcation on, reservoirs off, 6-hourly `totout`/`rivsto`/`fldsto`/`fldfrc`/`gwsto`/`wevap`); dates, coupling frequency and restart flags are patched per year by the run script.
- `namelist/input_depthtrilogy` — prototype: the ecLand `develop` "depth trilogy" switches (`LEUNIFORMROOT`, `LEBEDROCKLIM`, `LEGWRECHARGE`) on, with per-gridpoint bedrock depth and water-table depth from `init_clim/add_bedrock_wtd_fields.py` (`init_clim/data/*_depthtrilogy`). Needs an executable built from that branch.

## Repository layout

```
liaise-ecland/
├── forcing/                 # Download + preparation scripts; WFDE5_CRU_GPCC*/ data — not in git
├── init_clim/               # Ancillary-field generation; data/{surfclim,soilinit} (Git LFS); work/ — not in git
├── namelist/                # ecLand and CaMa-Flood namelists
├── run/                     # Run scripts, budget/diagnostic checks; output*, restart*, work*, logs*, bin* — not in git
├── cama_flood/              # River-network derivation, GRDC gauges, GPU bridge, discharge benchmark; data/ (Git LFS)
├── eclandpy_bridge/         # eclandpy -> CaMa-Flood-GPU chain (own README)
├── landbench/               # Point observations in the LIAISE region; data/ (Git LFS)
├── docs/                    # Banner, report, slides
└── CLAUDE.md                # The working notes: every decision, validation and bug, dated
```

Key scripts. Shell scripts resolve the repository from their own location; Python scripts default to paths relative to the working directory, so run them from the repository root.

| Script | Does |
|---|---|
| `init_clim/get_init_clim.sh` | Install the validated `surfclim`/`soilinit` from Git LFS into `init_clim/work/` |
| `init_clim/clim.sh`, `init_clim.sh`, `init_clim.py` | Regenerate them from MARS/ERA5 (ECMWF only) |
| `forcing/get_liaise_forcing_05.sh` | 1988–2014 WFDE5-CRU-GPCC from the IPSL mirror |
| `forcing/get_liaise_forcing_05_cds.sh` | 2015–2024 from the CDS, assembled into the same layout |
| `forcing/prepare_liaise_forcing_ecland.py` | Rebase onto ecLand's time axis, add the year endpoint |
| `forcing/get_liaise_forcing_km.sh` | The ~3 km LIAISE campaign forcing products (ETHZ/IPSL) |
| `namelist/create_liaise_namelist.sh` | Generate `namelist/input` from environment variables |
| `run/run_liaise_ecland.sh` / `.slurm` | Run 1988→2024 year by year, restart-chained; coupled when `LECMF1WAY` is on |
| `run/scratch_mirror.sh` | `push` / `pull` / `status` between `$PERM` and `$SCRATCH` |
| `run/extract_control_diagnostics.py` | Domain-mean diagnostics of a finished run |
| `run/check_water_budget.py`, `check_energy_budget.py` | Raw-output budget closure (from plumber2-ecland) |
| `cama_flood/derive_cmf_weights.sh` | Derive `inpmat.nc` and the clipped river-network files |
| `cama_flood/build_global_cmf_fixdir.sh` | Build the global CaMa-Flood fix bundle at any resolution |
| `cama_flood/extract_liaise_grdc_observations.py` | GRDC (+ optionally CAMELS-Spain) gauges connected to the Ebro on the CaMa-Flood network |
| `cama_flood/skill_benchmark_chains.py`, `skill_benchmark_fortran_vs_gpu.py` | Score discharge, Fortran chain vs eclandpy→GPU chain, against the gauges |
| `cama_flood/skill_benchmark_control.py` | Score the Fortran control chain alone (no second model) against every gauge |
| `cama_flood/build_chain_dashboard.py`, `build_control_dashboard.py` | Self-contained skill pages from the benchmark JSONs |

## License

Copyright 2025– ECMWF. Licensed under the [Apache Licence Version 2.0](http://www.apache.org/licenses/LICENSE-2.0).
