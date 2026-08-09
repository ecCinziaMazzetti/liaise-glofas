# LIAISE ecLand workflow

Scripts and configuration for preparing and running ecLand over the LIAISE
domain using WFDE5-CRU-GPCC forcing.

## Workflow

1. Prepare ecLand ancillary fields:

   ```bash
   cd init_clim
   ./clim.sh
   ./init_clim.sh
   ```

   This requires MARS access. Outside ECMWF (for example on macOS), install
   the pre-generated, validated `surfclim`/`soilinit` files instead. They are
   tracked via Git LFS under `init_clim/data/`:

   ```bash
   git lfs pull
   cd init_clim
   ./get_init_clim.sh
   ```

2. Download and process annual forcing files:
   ```bash
   cd forcing
   ./get_liaise_forcing_05.sh
  
   python3 prepare_liaise_forcing_ecland.py \
    --input-dir WFDE5_CRU_GPCC \
    --output-dir WFDE5_CRU_GPCC_ecland \
    --start-year 1988 \
    --end-year 2014 \
    --repeat-last-for-final-year
   ```

Each annual file uses as time reference:
hours since 1988-01-01 00:00:00
and it contains an additional endpoint at 00 UTC on 1 January of the
following year. For the final year, the final forcing record is repeated.

3. Generate the ecLand namelist:

   ```bash
   cd namelist
   ./create_liaise_namelist.sh
   ```

4. Run ecLand interactively:

   ```bash
   cd run
   ./run_liaise_ecland.sh
   ```

5. Run ecLand through Slurm:

This is alternative to 4. in case of an HPC setup
   ```bash
   cd run
   sbatch run_liaise_ecland.slurm
   ```

## Repository content
   ```bash
   forcing/
     get_liaise_forcing_05.sh 
     get_liaise_forcing_km.sh
     prepare_liaise_forcing_ecland.py
     prepare_liaise_forcing_ecland.sh

   init_clim/
     clim.sh
     init_clim.py
     init_clim.sh
     get_init_clim.sh
     data/
       soilinit
       surfclim

   namelist/
     create_liaise_namelist.sh
     input

   run/
     postprocess_liaise_ecland.sh
     run_liaise_ecland.sh
     run_liaise_ecland.slurm
   ```

Large forcing datasets, generated ancillary files, outputs, logs, work
directories, and restart files are intentionally excluded from Git. The
exception is `init_clim/data/soilinit` and `init_clim/data/surfclim`, which
are tracked via Git LFS as validated reference ancillary files.

