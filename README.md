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

2. Prepare annual forcing files:
   ```bash
   cd forcing
   python3 prepare_liaise_forcing_ecland.py \
    --input-dir WFDE5_CRU_GPCC \
    --output-dir WFDE5_CRU_GPCC_ecland \
    --start-year 1988 \
    --end-year 2014 \
    --repeat-last-for-final-year
   ```

Each annual file uses:
hours since 1988-01-01 00:00:00

and contains an additional endpoint at 00 UTC on 1 January of the
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
     prepare_liaise_forcing_ecland.py
     prepare_liaise_forcing_ecland.sh

   init_clim/
     clim.sh
     init_clim.py
     init_clim.sh

   namelist/
     create_liaise_namelist.sh
     input

   run/
     postprocess_liaise_ecland.sh
     run_liaise_ecland.sh
     run_liaise_ecland.slurm
   ```

Large forcing datasets, generated ancillary files, outputs, logs, work
directories, and restart files are intentionally excluded from Git.

