---
name: liaise-run
description: Reproduce a multi-year LIAISE/Ebro ecLand run end to end - build and pin an executable, stage forcing and ancillaries, submit the 37-year control or CaMa-Flood-coupled chain, and check the right log lines. Use when asked to run, rerun or reproduce ecLand over the LIAISE domain, to build or pin an ecLand executable, or to resume a run that failed partway.
---

# Reproducing a LIAISE ecLand run

Measured costs on hpc2020 (`qos=nf`, 4 threads, 32 GB), so you can budget:
build ~3 min, 37-year control ~1h20, 37-year coupled ~1h35, single year ~3 min.

## Order of work

Never skip step 3. A run launched against an unverified executable can burn two
hours and produce silently wrong physics — that has happened on this repo twice.

### 1. Inputs

```bash
module load git/2.53.0              # system git has NO LFS filter
init_clim/get_init_clim.sh          # surfclim + soilinit from Git LFS -> init_clim/work/
ls forcing/WFDE5_CRU_GPCC_ecland | wc -l    # expect 37 (1988-2024)
```

Without the git module every LFS file looks modified, and `git add -A` would
commit real binaries over the pointers. `git lfs ls-files | wc -l` gives 16.

If forcing is missing, copy it rather than re-downloading (the CDS path is
queue-bound and takes hours):

```bash
cp /perm/pad/liaise-ecland/forcing/WFDE5_CRU_GPCC_ecland/*.nc forcing/WFDE5_CRU_GPCC_ecland/
```

1.9 GB. Prefer a copy over a symlink for a long run — a symlink leaves you
exposed to someone else's directory changing mid-run.

### 2. Executable

Needs an `ecland` checkout carrying the `LECMF1WAY` runoff-coupling loop-bound
fix. Verify, don't assume — 4 hits is fixed, `NLALO` there is not:

```bash
grep -c "DO IST = 1, NPOI, NPROMA" src/surf/offline/driver/cnt41s.F90   # want 4
```

Commit choice matters more than it looks:

- **`origin/develop` tip — default choice.** Has the fix *and* the netCDF
  write-behind/chunking speedup (`c0526a1`), ~1.6x faster I/O.
- `55f3d24` — provenance-matched to upstream's reference numbers, but predates
  the speedup (~3m50s/year vs ~2m59s).
- `main` HEAD — avoid: carries an *ungated* frozen-soil macropore change that
  moves `runoff_mm`.
- Do **not** cherry-pick `c0526a1` onto an older commit: it sits on top of the
  `LEFIRE` commits and drags `LWRFIRE` code into a tree that has none.

Build with the bundle's own arch file, which does `module purge` first:

```bash
cd <ecland-checkout>
PATH=<ecbundle>/bin:$PATH ecbundle-create
sbatch --qos=nf --cpus-per-task=16 --mem=48G --time=03:00:00 --wrap \
  "PATH=<ecbundle>/bin:\$PATH ecbundle-build \
   --arch=\$PWD/source/arch/ecmwf/hpc2020/intel/2023.2.0/hpcx-openmpi/2.9.0 \
   --build-dir=\$PWD/build --threads=16"
```

### 3. Pin it, and prove the pin — do not skip

`ecland-master-dp`'s RPATH is `$ORIGIN/../lib64`, so the layout is load-bearing:

```
run/<pin>/bin/ecland-master-dp   ->  finds run/<pin>/lib64/     CORRECT
run/<pin>/ecland-master-dp       ->  finds run/lib64/           WRONG, silently
```

The flat layout doesn't error — it runs *another pin's* libraries. Mismatched
argument lists then shift arrays into garbage; diagnosing that once cost a day
and produced a wrong conclusion about the physics.

```bash
PIN=run/bin_<tag>; mkdir -p $PIN/bin $PIN/lib64
cp <build>/bin/ecland-master-dp $PIN/bin/
cp <build>/lib64/*.so $PIN/lib64/
ldd $PWD/$PIN/bin/ecland-master-dp | grep libecland_surf   # MUST resolve inside $PIN/lib64
ldd $PWD/$PIN/bin/ecland-master-dp | grep "not found"      # MUST print nothing
```

A correct pin is immune to ambient modules: its RPATH beats `LD_LIBRARY_PATH`,
so a job loading a different `netcdf4`/`intel` still runs the build-time
libraries. `run/bin_*/` is gitignored.

### 4. Smoke-test one year before committing hours

```bash
mkdir -p $SCRATCH/liaise_test/forcing_1988
ln -sf $PWD/forcing/WFDE5_CRU_GPCC_ecland/WFDE5_CRU_GPCC_1988_ecland.nc $SCRATCH/liaise_test/forcing_1988/
source <ecland>/source/arch/ecmwf/hpc2020/intel/2023.2.0/hpcx-openmpi/2.9.0/env.sh
ROOT=$PWD ECLAND_EXE=$PWD/run/bin_<tag>/bin/ecland-master-dp \
  NAMELIST=$PWD/namelist/input RUN_ROOT=$SCRATCH/liaise_test \
  FORCING_DIR=$SCRATCH/liaise_test/forcing_1988 run/run_liaise_ecland.sh
```

Success: `ecLand finished with status 0`, 12 `o_*.nc`, `time=8784` (366x24).

### 5. Submit the full chain

`sbatch`, never the login node, for anything longer than one year. Override the
log paths: upstream hardcodes them into `/perm/pad/...` and `sbatch` **fails
outright** when that isn't writable.

```bash
EXE=$PWD/run/bin_<tag>/bin/ecland-master-dp
sbatch --job-name=liaise_ctl --time=05:00:00 \
  --output=$PWD/run/logs/liaise_ctl_%j.out --error=$PWD/run/logs/liaise_ctl_%j.err \
  --export=ALL,ROOT=$PWD,ECLAND_EXE=$EXE,NAMELIST=$PWD/namelist/input,RUN_ROOT=$PERM/liaise_ctl_1988_2024 \
  run/run_liaise_ecland.slurm
```

Coupled: `NAMELIST=$PWD/namelist/input_cmf1way`, `--time=08:00:00`. Nothing else
changes — CaMa-Flood is compiled *into* `ecland-master-dp`, so there is no
second executable to launch; the script stages `cama_flood/data/` and patches
`namelist/input_cmf` per year.

Never hand-edit dates or `NSTOP`; the script patches them per year.
`NSTOP = days_in_year * 86400 / TSTEP` relies on the prepared forcing's extra
endpoint at 00 UTC on 1 January of the following year — don't remove it.

### 6. Watch the right lines

```bash
L=run/logs/liaise_ctl_<jobid>.out
grep -c "finished with status 0" $L                 # expect 37
grep "Initial state" $L | head -3
grep -icE "error|abort|forrtl|PROGRAM STOP" $L      # expect 0
```

The chain is working when year 1 says `Initial state: .../soilinit` and **every
later year** says
`Initial state (restart chain): .../restart_<y>1231.nc -> soilinit`.
If later years still print a plain `Initial state:`, the chain is broken — stop
and read the `liaise-verify` skill before spending more time.

Coupled runs also print `Configured CaMa-Flood namelist for year <y> (...,
IFRQ_INP=<n>h)`; `IFRQ_INP` must track `TCOUPFREQ`, not `TSTEP`.

### 7. Verify before believing

Always finish with the **`liaise-verify`** skill. A run that completes with
status 0 can still be invalid: the restart chain used to fail silently, with no
error message anywhere.

## Resuming a failed run

`START_YEAR`/`END_YEAR` restrict the annual loop. Pair them with
`INITIAL_RESTART` (and `INITIAL_RESTART_CMF` when coupled) pointing at the last
completed year's restart, or the resumed segment cold-starts and breaks the
chain for every year after it.

## Traps that have already cost time here

- **A shared `ecland/build/` can be rebuilt under a running job.** That killed a
  37-year run at year 1992 mid-flight when someone rebuilt the binary. Step 3
  exists for this.
- **Output is ~1 GB/year** (~70 GB for 37 years, more when coupled). Check space.
- **`$SCRATCH` is faster but is pruned automatically**; pull results back with
  `run/scratch_mirror.sh pull`.
- **Interactive runs need the arch `env.sh` sourced.** The SLURM wrapper loads
  its own modules and deliberately does *not* use `srun`: a job step doesn't
  reliably inherit the module environment on this cluster, so `$ECLAND_EXE`
  fails to find `libmpi*.so`.
- **Dashboard and `sitesctl` scripts need `module load python3/3.11.10-01`**;
  the default `python3` is 3.6 and can't parse their annotations.
