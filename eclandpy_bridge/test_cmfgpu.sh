#!/bin/bash
set -eu
module load gcc/11.2.0
module load cuda/12.6
export CC=$(which gcc)
export CXX=$(which g++)
cd /perm/pad/CaMa-Flood-GPU
python3 scripts_user/run_eclandpy_liaise_chained.py --year-start 1988 --year-end 1989
